"""Failure injection only: these tests never import real GPIO/I2C drivers."""

import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest

from lumastir.controller import LumaController


@pytest.fixture
def drivers(monkeypatch, tmp_path):
    monkeypatch.setenv("LUMASTIR_LOCK_FILE", str(tmp_path / "hardware.lock"))
    gpio = ModuleType("RPi.GPIO")
    gpio.BCM, gpio.OUT, gpio.LOW = 11, 0, 0
    gpio.setmode = Mock()
    gpio.setup = Mock()
    gpio.cleanup = Mock()
    pwms = []

    def make_pwm(*args):
        pwm = Mock()
        pwms.append(pwm)
        return pwm

    gpio.PWM = Mock(side_effect=make_pwm)
    rpi = ModuleType("RPi")
    rpi.GPIO = gpio
    board = ModuleType("board")
    board.SCL, board.SDA = "scl", "sda"
    busio = ModuleType("busio")
    bus = Mock()
    busio.I2C = Mock(return_value=bus)
    pca_module = ModuleType("adafruit_pca9685")
    pca = Mock()
    pca.channels = [SimpleNamespace(duty_cycle=0) for _ in range(16)]
    pca_module.PCA9685 = Mock(return_value=pca)
    for name, module in {
        "RPi": rpi,
        "RPi.GPIO": gpio,
        "board": board,
        "busio": busio,
        "adafruit_pca9685": pca_module,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)
    return SimpleNamespace(
        gpio=gpio, pwms=pwms, bus=bus, pca=pca, pca_module=pca_module
    )


def test_partial_initialization_rolls_back_gpio_bus_and_lock(drivers):
    drivers.pca_module.PCA9685.side_effect = OSError("no PCA9685")
    with pytest.raises(OSError, match="no PCA9685"):
        LumaController([17, 18, 27], [0, 4, 8])
    assert len(drivers.pwms) == 3
    assert all(pwm.stop.call_count == 1 for pwm in drivers.pwms)
    drivers.gpio.cleanup.assert_called_once()
    drivers.bus.deinit.assert_called_once()
    drivers.pca_module.PCA9685.side_effect = None
    # A second constructor proves the first released its flock.
    controller = LumaController([17], [0])
    controller.cleanup()


def test_cleanup_continues_after_motor_and_pwm_failures(drivers, monkeypatch):
    controller = LumaController([17, 18], [0, 4])
    monkeypatch.setattr(
        controller, "stop_all_motors", Mock(side_effect=OSError("bus stop failed"))
    )
    drivers.pwms[0].stop.side_effect = OSError("PWM stop failed")
    with pytest.raises(RuntimeError, match="cleanup failed"):
        controller.cleanup()
    drivers.pwms[1].stop.assert_called_once()
    drivers.gpio.cleanup.assert_called_once()
    drivers.pca.deinit.assert_called_once()
    drivers.bus.deinit.assert_called_once()
    controller.cleanup()  # Repeated cleanup is safe even after failures.
    replacement = LumaController([17], [0])
    replacement.cleanup()


def test_second_hardware_owner_is_refused_without_disturbing_first(drivers):
    first = LumaController([17], [0])
    try:
        first.set_motor_by_index(0, 50)
        with pytest.raises(RuntimeError, match="hardware lock"):
            LumaController([17], [0])
        assert drivers.pca.channels[0].duty_cycle == 32768
        assert drivers.gpio.cleanup.call_count == 0
    finally:
        first.cleanup()


def test_backend_rejects_invalid_values_before_driver_access(drivers):
    controller = LumaController([17], [0])
    try:
        with pytest.raises(ValueError):
            controller.set_motor_by_index(0, 150)
        with pytest.raises(ValueError):
            controller.set_led_by_index(-1, 50)
        assert drivers.pca.channels[0].duty_cycle == 0
        drivers.pwms[0].ChangeDutyCycle.assert_not_called()
    finally:
        controller.cleanup()
