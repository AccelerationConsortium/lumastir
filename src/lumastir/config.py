"""Validate the complete wiring map before allocating hardware resources."""

from pathlib import Path
from typing import List, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator


class HardwareConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    led_pins: List[StrictInt] = Field(default_factory=lambda: [17, 18, 27])
    motor_channels: List[StrictInt] = Field(default_factory=lambda: [0, 4, 8])
    device_type: str = "3-vial-motor"
    equipment_id: str = Field(default="lumastir", pattern=r"^[a-z][a-z0-9_]*$")
    equipment_name: str = "Lumastir"
    max_power: float = Field(default=100, gt=0, le=100, allow_inf_nan=False)
    max_run_seconds: float = Field(default=600, gt=0, le=86400, allow_inf_nan=False)

    @field_validator("led_pins", "motor_channels")
    @classmethod
    def valid_mapping(cls, values, info):
        if len(values) != len(set(values)):
            raise ValueError("duplicate pins/channels are not allowed")
        maximum = 27 if info.field_name == "led_pins" else 15
        if any(value < 0 or value > maximum for value in values):
            raise ValueError(f"indices must be between 0 and {maximum}")
        if info.field_name == "led_pins" and {2, 3}.intersection(values):
            raise ValueError("GPIO 2 and 3 are reserved for the PCA9685 I2C bus")
        return values


def load_config(path: Optional[str] = None) -> HardwareConfig:
    if path is None:
        return HardwareConfig()
    with Path(path).expanduser().open(encoding="utf-8") as stream:
        data = yaml.safe_load(stream)
    if not isinstance(data, dict):
        raise ValueError("configuration must be a YAML mapping")
    if "led_pins" not in data or "motor_channels" not in data:
        raise ValueError("configuration must specify led_pins and motor_channels")
    return HardwareConfig.model_validate(data)
