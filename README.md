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
    # You may need to restart your terminal or run:
    # source $HOME/.local/bin/env  (if it exists)
    # OR ensure ~/.local/bin is in your PATH
    ```

2.  **Clone the repository:**

    ```bash
    # Make a "~/Projects" folder and enter it
    cd ~
    mkdir Projects
    cd Projects
    
    # clone this repo
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

# Set Motor (Index 0 to 50% speed)
# Index 0 maps to the first channel in your config (e.g., Channel 4)
uv run lumastir-cli motor 0 50

# Set LED (Index 0 to 100% brightness)
# Index 0 maps to the first pin in your config (e.g., GPIO 17)
uv run lumastir-cli led 0 100

# Specify a different host
uv run lumastir-cli --host http://<other-pi-ip>:8000 status
```

## Usage (API)

Once the server is running, you can control it via HTTP requests. The interactive API documentation is available at: `http://<raspberry-pi-ip>:8000/docs`

### Common Endpoints

**1. Set Motor Speed**
`POST /motor/{index}/speed`
```json
{
  "speed": 50.0
}
```
*`index` corresponds to the list index in your configuration (0 for first motor, 1 for second...).*

**2. Set LED Brightness**
`POST /led/{index}/brightness`
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

1.  Edit `deploy/lumastir.service`.
    *   Change `User=pi` to your username.
    *   Ensure the `Environment` config path matches your desired setup.
    *   *Note: `%h` in the service file automatically resolves to your home directory.*

2.  Install the service:
    Go to the project folder and
    ```bash
    sudo cp deploy/lumastir.service /etc/systemd/system/
    sudo systemctl enable lumastir
    sudo systemctl start lumastir
    ```

## License
[MIT License](LICENSE)
