import time
import argparse
import os
import yaml
from .controller import LumaController

def run_demo(controller):
    """Run a demonstration sequence on the connected hardware."""
    print("Starting LED Blink Test...")
    # Demonstration of three LEDs
    for i in range(0, 2):
        for pin in controller.led_pins:
            print(f"  Blinking LED on GPIO {pin}")
            controller.blink_led(pin)

    print("\nStarting Motor Sequence...")
    # Demonstration of motors with LED on
    # We iterate up to the number of available motor channels
    for i, channel in enumerate(controller.motor_channels):
        # If we have a corresponding LED for this motor index, use it
        led_pin = controller.led_pins[i] if i < len(controller.led_pins) else None
        
        print(f"  Testing Channel {channel} (Vial {i})...")
        
        if led_pin:
            controller.set_led_brightness(led_pin, 100)
            
        time.sleep(0.5)
        controller.set_motor_speed(channel, 100)
        time.sleep(3)
        controller.set_motor_speed(channel, 0)
        
        if led_pin:
            controller.set_led_brightness(led_pin, 0)
            
        time.sleep(0.5)
        print(f"  Finished demo on channel {channel}.")

    print("\nDemo Complete.")

def main():
    parser = argparse.ArgumentParser(description="Lumastir Hardware Demo")
    parser.add_argument(
        "--config", 
        type=str, 
        help="Path to the hardware configuration YAML file",
        default=os.getenv("LUMASTIR_CONFIG", "configs/3led_3motor.yaml")
    )
    args = parser.parse_args()

    # Load Config
    try:
        with open(args.config) as f:
            config = yaml.safe_load(f)
    except FileNotFoundError:
        print(f"Error: Config file not found at {args.config}")
        return

    print(f"Loading configuration from {args.config}...")
    
    # Initialize Controller
    try:
        controller = LumaController(
            led_pins=config.get("led_pins", []),
            motor_channels=config.get("motor_channels", [])
        )
    except Exception as e:
        print(f"Failed to initialize hardware: {e}")
        return

    try:
        run_demo(controller)
    except KeyboardInterrupt:
        print("\nInterrupted! Stopping hardware...")
    finally:
        controller.cleanup()

if __name__ == "__main__":
    main()
