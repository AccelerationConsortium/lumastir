"""Public, typed control contract. Percentages are PWM setpoints, not RPM."""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MotorCommand(Command):
    speed: float = Field(
        ge=0,
        le=100,
        allow_inf_nan=False,
        strict=True,
        description="PWM duty percentage; not measured RPM",
    )


class LedCommand(Command):
    brightness: float = Field(
        ge=0,
        le=100,
        allow_inf_nan=False,
        strict=True,
        description="PWM duty percentage; not measured light output",
    )


class MotorSet(MotorCommand):
    index: int = Field(ge=0, strict=True)


class LedSet(LedCommand):
    index: int = Field(ge=0, strict=True)


class RunCommand(MotorSet):
    speed: float = Field(gt=0, le=100, allow_inf_nan=False, strict=True)
    duration_s: float = Field(gt=0, le=86400, allow_inf_nan=False, strict=True)
    request_id: UUID = Field(
        description="Unique operation ID; reuse this ID for retries of the same operation"
    )
    instance_id: UUID = Field(
        description="Server instance_id from /v1/devices; prevents replay across restarts"
    )


class ClaimRequest(Command):
    owner: str = Field(min_length=1, max_length=128)
    session_id: str = Field(min_length=1, max_length=128)
    ttl_s: float = Field(default=30, ge=5, le=120, allow_inf_nan=False, strict=True)


class ClaimResponse(BaseModel):
    claim_token: str
    heartbeat_interval_s: float
    expires_at: datetime


class Ack(BaseModel):
    status: Literal["ok"] = "ok"


class Probe(BaseModel):
    status: Literal["online"] = "online"
    service: Literal["lumastir"] = "lumastir"
    equipment_id: str
    equipment_name: str
    protocol_version: Literal["1.1"] = "1.1"
    config_data: Dict[str, List[int]]


class Health(BaseModel):
    status: Literal["healthy"] = "healthy"


class LegacyMotorResponse(Ack):
    index: int
    hardware_channel: int
    speed: float


class LegacyLedResponse(Ack):
    index: int
    hardware_pin: int
    brightness: float


class SetResponse(Ack):
    index: int
    value: float
    hardware_address: int
    measurement: Literal["commanded_pwm"] = "commanded_pwm"


class RunResponse(BaseModel):
    request_id: UUID
    instance_id: UUID
    index: int
    speed: float
    duration_s: float
    state: Literal["running", "completed", "cancelled", "failed"]
    started_at: datetime
    stopped_at: Optional[datetime] = None
    reason: Optional[str] = None


class Output(BaseModel):
    id: str
    index: int
    hardware_address: int
    commanded_percent: Optional[float]
    updated_at: datetime


class Devices(BaseModel):
    instance_id: UUID
    equipment_id: str
    simulated: bool
    motors: List[Output]
    leds: List[Output]
    max_power: float
    max_run_seconds: float
    feedback: Literal["none"] = "none"


class ErrorInfo(BaseModel):
    code: Literal["hardware_write_failed", "stop_failed", "supervisor_failed"]
    message: str
    severity: Literal["error"] = "error"
    timestamp: datetime


class ErrorResponse(BaseModel):
    error: Dict[str, Any]


class Status(BaseModel):
    protocol_version: Literal["1.1"] = "1.1"
    equipment_id: str
    equipment_name: str
    equipment_kind: Literal["other"] = "other"
    equipment_version: str
    equipment_status: Literal["ready", "busy", "dry_run", "error"]
    message: str
    required_actions: List[str] = Field(default_factory=list)
    device_time: datetime
    uptime_seconds: float
    components: Dict[str, Any] = Field(default_factory=dict)
    metrics: Dict[str, Any] = Field(default_factory=dict)
    last_error: Optional[ErrorInfo] = None
    allowed_actions: List[str]
    details: Dict[str, Any]
