import argparse
import os
import time

from .config import load_config
from .controller import LumaController


def run_demo(controller, power=50, duration=3):
    """Run a demonstration sequence on the connected hardware."""
    print("Starting LED Blink Test...")
    # Demonstration of three LEDs
    for i in range(2):
        for pin in controller.led_pins:
            print(f"  Blinking LED on GPIO {pin}")
            controller.blink_led(pin, brightness=power)

    print("\nStarting Motor Sequence...")
    # Demonstration of motors with LED on
    # We iterate up to the number of available motor channels
    for i, channel in enumerate(controller.motor_channels):
        # If we have a corresponding LED for this motor index, use it
        led_pin = controller.led_pins[i] if i < len(controller.led_pins) else None

        print(f"  Testing Channel {channel} (Vial {i})...")

        if led_pin is not None:
            controller.set_led_brightness(led_pin, power)

        time.sleep(0.5)
        controller.set_motor_speed(channel, power)
        time.sleep(duration)
        controller.set_motor_speed(channel, 0)

        if led_pin is not None:
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
        default=os.getenv("LUMASTIR_CONFIG"),
    )
    args = parser.parse_args()

    # Load Config
    try:
        config = load_config(args.config)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Configuration error: {exc}\n")

    print(f"Loading configuration from {args.config}...")

    # Initialize Controller
    try:
        controller = LumaController(
            led_pins=config.led_pins,
            motor_channels=config.motor_channels,
        )
    except Exception as e:
        parser.exit(1, f"Failed to initialize hardware: {e}\n")

    try:
        run_demo(
            controller,
            power=min(50, config.max_power),
            duration=min(3, config.max_run_seconds),
        )
    except KeyboardInterrupt:
        print("\nInterrupted! Stopping hardware...")
    finally:
        controller.cleanup()


if __name__ == "__main__":
    main()
