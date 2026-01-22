import os
import yaml
import argparse
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from .controller import LumaController

app = FastAPI()
controller = None
config_file_path = None  # To store the selected config path

class MotorCommand(BaseModel):
    speed: float  # 0-100

class LedCommand(BaseModel):
    brightness: float # 0-100

@app.on_event("startup")
def load_hardware():
    global controller, config_file_path
    
    # If config_file_path wasn't set by the CLI (running via uvicorn directly), check env var
    if config_file_path is None:
        config_file_path = os.getenv("LUMASTIR_CONFIG", "configs/3led_3motor.yaml")

    try:
        # Handle relative paths if running from different directories
        if not os.path.isabs(config_file_path) and not os.path.exists(config_file_path):
             # Try looking relative to the package root or current working dir
             pass

        with open(config_file_path) as f:
            config = yaml.safe_load(f)
            
        controller = LumaController(
            led_pins=config.get("led_pins", []),
            motor_channels=config.get("motor_channels", [])
        )
        print(f"Loaded configuration from {config_file_path}")
        print(f"  LED Pins (Indices 0-{len(controller.led_pins)-1}): {controller.led_pins}")
        print(f"  Motor Channels (Indices 0-{len(controller.motor_channels)-1}): {controller.motor_channels}")
        
    except Exception as e:
        print(f"Failed to load configuration from {config_file_path}: {e}")
        # In production, you might want to fail hard here, 
        # but for now we'll log it. FastAPI will still start.
        raise e

@app.on_event("shutdown")
def shutdown_hardware():
    if controller:
        controller.cleanup()

@app.get("/")
def read_root():
    return {
        "status": "online", 
        "service": "lumastir",
        "config": config_file_path,
        "config_data": {
            "led_pins": controller.led_pins if controller else [],
            "motor_channels": controller.motor_channels if controller else []
        }
    }

@app.post("/motor/{index}/speed")
async def set_motor(index: int, cmd: MotorCommand):
    if not controller:
         raise HTTPException(status_code=503, detail="Hardware not initialized")
    
    success, real_channel = controller.set_motor_by_index(index, cmd.speed)
    
    if not success:
        raise HTTPException(
            status_code=400, 
            detail=f"Invalid motor index {index}. Max index is {len(controller.motor_channels)-1}."
        )
        
    return {"status": "ok", "index": index, "hardware_channel": real_channel, "speed": cmd.speed}

@app.post("/led/{index}/brightness")
async def set_led(index: int, cmd: LedCommand):
    if not controller:
         raise HTTPException(status_code=503, detail="Hardware not initialized")

    success, real_pin = controller.set_led_by_index(index, cmd.brightness)

    if not success:
         raise HTTPException(
            status_code=400, 
            detail=f"Invalid LED index {index}. Max index is {len(controller.led_pins)-1}."
        )

    return {"status": "ok", "index": index, "hardware_pin": real_pin, "brightness": cmd.brightness}

def start():
    """Entry point for the application script"""
    import uvicorn
    global config_file_path

    parser = argparse.ArgumentParser(description="Lumastir Hardware Controller Server")
    parser.add_argument(
        "--config", 
        type=str, 
        help="Path to the hardware configuration YAML file",
        default=os.getenv("LUMASTIR_CONFIG", "configs/3led_3motor.yaml")
    )
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind to")
    
    args = parser.parse_args()
    config_file_path = args.config

    print(f"Starting Lumastir Server with config: {config_file_path}")
    
    # Host 0.0.0.0 allows external access (e.g. via Tailscale)
    uvicorn.run(app, host=args.host, port=args.port)
