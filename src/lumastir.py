import time
import board
import busio
import RPi.GPIO as GPIO
from adafruit_pca9685 import PCA9685

# Configuration
LED_PINS = [17, 18, 27]  # GPIO pins of 3.3V LED
MOTOR_CHANNELS = [4, 8, 12]  # PCA9685 has 16 12-bit-channels


class LumaController:
    def __init__(self, led_pins, motor_channels):
        # LED Setup (GPIO)
        self.led_pins = led_pins
        GPIO.setmode(GPIO.BCM)
        self.pwm_leds = {}

        for led_pin in led_pins:
            GPIO.setup(led_pin, GPIO.OUT)
            self.pwm_leds[led_pin] = GPIO.PWM(led_pin, 100)  # 100 Hz frequency
            self.pwm_leds[led_pin].start(0)

        # Motor Setup (PCA9685)
        self.i2c = busio.I2C(board.SCL, board.SDA)
        self.pca = PCA9685(self.i2c)
        self.pca.frequency = 500  # 500 Hz for motors
        self.motor_channels = motor_channels

        # Initialize motors to off
        self.stop_all_motors()

    def set_led_brightness(self, led_pin, brightness):
        """Control LED brightness (0-100%)"""
        if led_pin in self.pwm_leds:
            self.pwm_leds[led_pin].ChangeDutyCycle(brightness)

    def set_motor_speed(self, channel, speed):
        """Control motor speed (0-100%)"""
        if channel in self.motor_channels:
            duty_cycle = round(speed * 65535 / 100)  # Convert % to 12-bit value
            self.pca.channels[channel].duty_cycle = duty_cycle

    def blink_led(self, led_pin, duration=0.5):
        """Simple blink function for LEDs"""
        self.set_led_brightness(led_pin, 100)
        time.sleep(duration)
        self.set_led_brightness(led_pin, 0)

    def stop_all_motors(self):
        """Stop all connected motors"""
        for channel in self.motor_channels:
            self.pca.channels[channel].duty_cycle = 0

    def cleanup(self):
        """Clean up resources"""
        self.stop_all_motors()
        for led_pin in self.pwm_leds:
            self.pwm_leds[led_pin].stop()
        GPIO.cleanup()
        self.pca.deinit()


if __name__ == "__main__":
    try:
        controller = LumaController(LED_PINS, MOTOR_CHANNELS)

        # Demonstration of three LEDs
        print("Starting blinking test!")
        for i in range(0, 2):
            for pin in LED_PINS:
                controller.blink_led(pin)

        # Demonstration of motors with LED on
        for vial_loc in [0, 1, 2]:
            controller.set_led_brightness(LED_PINS[vial_loc], 100)
            time.sleep(0.5)
            controller.set_motor_speed(MOTOR_CHANNELS[vial_loc], 100)
            time.sleep(10)
            controller.set_motor_speed(MOTOR_CHANNELS[vial_loc], 0)
            controller.set_led_brightness(LED_PINS[vial_loc],0)
            time.sleep(0.5)
            print(f"Finished demo on vial location {vial_loc}.")
            controller.stop_all_motors()

    except KeyboardInterrupt:
        controller.cleanup()
        print("Interrupted!")

    finally:
        controller.cleanup()
