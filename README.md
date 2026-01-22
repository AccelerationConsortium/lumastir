# Lumastir

A flexible, server-based hardware controller for Raspberry Pi + PCA9685 setups. Designed for biological experiments requiring precise LED and motor/fan control.

## Overview

Lumastir runs as a lightweight HTTP API server on your Raspberry Pi. It allows external orchestration software (or any device on your network) to control hardware via simple REST API calls.

It is built with:
- **FastAPI** for the web server
- **RPi.GPIO** for LED control
- **Adafruit CircuitPython PCA9685** for PWM motor/fan control

## Hardware Setup

Lumastir is designed for:
- **Raspberry Pi** (Zero 2W)
- **PCA9685 PWM Driver** (connected via I2C)
- **Standard LEDs** (connected via GPIO)

### Default Configuration
- **LEDs:** GPIO Pins 17, 18, 27
- **Motors:** PCA9685 Channels 0, 3, 6 (for 3-vial setup)

*Note: Hardware mapping is fully configurable via YAML files.*

## Installation

We recommend using `uv` for fast, reliable Python package management.

1.  **Install `uv`:**
    ```bash
    curl -LsSf https://astral.sh/uv/install.sh | sh
    source $HOME/.cargo/env
    ```

2.  **Clone the repository:**
    ```bash
    git clone https://github.com/yourusername/lumastir.git
    cd lumastir
    ```

3.  **Run the server:**
    ```bash
    # Run with default config (3 motors)
    uv run lumastir-server

    # Run with a custom config via flag
    uv run lumastir-server --config configs/3led_6fan.yaml

    # Run with custom host/port
    uv run lumastir-server --port 8080 --host 0.0.0.0
    ```

## Hardware Demo

To verify your hardware setup without running the full server, you can run the demo script. This will cycle through all LEDs and Motors defined in your configuration.

```bash
# Run demo with default config
uv run lumastir-demo

# Run demo with custom config
uv run lumastir-demo --config configs/3led_6fan.yaml
```

## CLI Usage

You can control the device directly from the command line (e.g., via SSH) using the `lumastir-cli` tool.

```bash
# Get server status
uv run lumastir-cli status

# Set Motor (channel 0 to 50% speed)
uv run lumastir-cli motor 0 50

# Set LED (GPIO 17 to 100% brightness)
uv run lumastir-cli led 17 100

# Specify a different host
uv run lumastir-cli --host http://<other-pi-ip>:8000 status
```

## Usage (API)

Once the server is running, you can control it via HTTP requests. The interactive API documentation is available at: `http://<raspberry-pi-ip>:8000/docs`

### Common Endpoints

**1. Set Motor Speed**
`POST /motor/{channel}/speed`
```json
{
  "speed": 50.0
}
```
*`channel` must be one of the valid channels defined in your configuration.*

**2. Set LED Brightness**
`POST /led/{pin}/brightness`
```json
{
  "brightness": 100.0
}
```

**3. Check Status**
`GET /`
Returns `{"status": "online", "service": "lumastir"}`.

## Configuration

Lumastir supports multiple hardware configurations via YAML files in the `configs/` directory.

### Creating a Custom Config
Create a new file in `configs/my_custom_setup.yaml`:

```yaml
led_pins: [17, 18, 27]
motor_channels: [0, 1, 2, 3] # Example: 4 motors
device_type: "custom-4-motor"
```

Then launch the server with:
```bash
uv run lumastir-server --config configs/my_custom_setup.yaml
```

## Deployment (Systemd)

To have Lumastir start automatically on boot:

1.  Edit `deploy/lumastir.service` to match your path and desired config flag.
    ```ini
    ExecStart=/home/pi/.cargo/bin/uv run lumastir-server --config /home/pi/lumastir/configs/3led_6fan.yaml
    ```
2.  Install the service:
    ```bash
    sudo cp deploy/lumastir.service /etc/systemd/system/
    sudo systemctl enable lumastir
    sudo systemctl start lumastir
    ```

## License
[MIT License](LICENSE)
