"""Hardware backends. All callers must serialize access to a backend."""

import math
import os
import time

from .config import HardwareConfig


def percent(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("percentage must be numeric")
    if not math.isfinite(value) or not 0 <= value <= 100:
        raise ValueError("percentage must be finite and between 0 and 100")
    return float(value)


def checked_index(index, values):
    if type(index) is not int or not 0 <= index < len(values):
        raise ValueError("invalid output index")
    return values[index]


class SimulatedController:
    simulated = True

    def __init__(self, led_pins, motor_channels):
        config = HardwareConfig(led_pins=led_pins, motor_channels=motor_channels)
        self.led_pins = config.led_pins
        self.motor_channels = config.motor_channels
        self.led_values = [0.0] * len(led_pins)
        self.motor_values = [0.0] * len(motor_channels)

    def set_led_by_index(self, index, brightness):
        pin = checked_index(index, self.led_pins)
        self.led_values[index] = percent(brightness)
        return True, pin

    def set_motor_by_index(self, index, speed):
        channel = checked_index(index, self.motor_channels)
        self.motor_values[index] = percent(speed)
        return True, channel

    def cleanup(self):
        self.led_values[:] = [0.0] * len(self.led_pins)
        self.motor_values[:] = [0.0] * len(self.motor_channels)


class LumaController:
    simulated = False

    def __init__(self, led_pins, motor_channels):
        config = HardwareConfig(led_pins=led_pins, motor_channels=motor_channels)
        self.led_pins = config.led_pins
        self.motor_channels = config.motor_channels
        self.pwm_leds = {}
        self.pca = self.i2c = self.gpio = None
        self._lock_file = None
        self._gpio_pins = []
        try:
            import fcntl

            path = os.getenv("LUMASTIR_LOCK_FILE", "/run/lock/lumastir.lock")
            self._lock_file = open(path, "a")
            fcntl.flock(self._lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except Exception:
            if self._lock_file is not None:
                self._lock_file.close()
                self._lock_file = None
            raise RuntimeError(
                "cannot acquire Lumastir hardware lock; check ownership and other processes"
            )
        try:
            import board
            import busio
            import RPi.GPIO as GPIO
            from adafruit_pca9685 import PCA9685

            self.gpio = GPIO
            GPIO.setmode(GPIO.BCM)
            for pin in self.led_pins:
                self._gpio_pins.append(pin)
                GPIO.setup(pin, GPIO.OUT, initial=GPIO.LOW)
                pwm = GPIO.PWM(pin, 100)
                self.pwm_leds[pin] = pwm
                pwm.start(0)
            self.i2c = busio.I2C(board.SCL, board.SDA)
            self.pca = PCA9685(self.i2c)
            self.pca.frequency = 500
            self.stop_all_motors()
        except BaseException:
            try:
                self.cleanup()
            except Exception:
                import logging

                logging.getLogger(__name__).exception(
                    "partial initialization cleanup failed"
                )
            raise

    def set_led_by_index(self, index, brightness):
        pin = checked_index(index, self.led_pins)
        self.pwm_leds[pin].ChangeDutyCycle(percent(brightness))
        return True, pin

    def set_motor_by_index(self, index, speed):
        channel = checked_index(index, self.motor_channels)
        # CircuitPython's duty-cycle API is 16-bit; the PCA9685 hardware is 12-bit.
        self.pca.channels[channel].duty_cycle = round(percent(speed) * 65535 / 100)
        return True, channel

    def set_led_brightness(self, led_pin, brightness):
        return self.set_led_by_index(self.led_pins.index(led_pin), brightness)

    def set_motor_speed(self, channel, speed):
        return self.set_motor_by_index(self.motor_channels.index(channel), speed)

    def blink_led(self, led_pin, duration=0.5, brightness=100):
        if not math.isfinite(duration) or duration < 0:
            raise ValueError("duration must be finite and nonnegative")
        try:
            self.set_led_brightness(led_pin, brightness)
            time.sleep(duration)
        finally:
            self.set_led_brightness(led_pin, 0)

    def stop_all_motors(self):
        errors = []
        for index in range(len(self.motor_channels)):
            try:
                self.set_motor_by_index(index, 0)
            except Exception as exc:
                errors.append(str(exc))
        if errors:
            raise RuntimeError("motor stop failed: " + "; ".join(errors))

    def cleanup(self):
        errors = []

        def attempt(action):
            try:
                action()
            except Exception as exc:
                errors.append(str(exc))

        if self.pca is not None:
            attempt(self.stop_all_motors)
        for pwm in self.pwm_leds.values():
            attempt(pwm.stop)
        self.pwm_leds.clear()
        if self.gpio is not None and self._gpio_pins:
            attempt(lambda: self.gpio.cleanup(self._gpio_pins))
            self._gpio_pins.clear()
        if self.pca is not None:
            attempt(self.pca.deinit)
            self.pca = None
        if self.i2c is not None:
            attempt(self.i2c.deinit)
            self.i2c = None
        if self._lock_file is not None:
            attempt(self._lock_file.close)
            self._lock_file = None
        if errors:
            raise RuntimeError("cleanup failed: " + "; ".join(errors))
