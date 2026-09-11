"""Serialized control, expiring claims, and server-owned run deadlines."""

import logging
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from . import __version__
from .controller import checked_index, percent
from .models import (
    ClaimResponse,
    Devices,
    ErrorInfo,
    Output,
    RunResponse,
    SetResponse,
    Status,
)

LOG = logging.getLogger(__name__)


def utcnow():
    return datetime.now(timezone.utc)


class ControlError(Exception):
    def __init__(self, status, code, message):
        self.status = status
        self.code = code
        super().__init__(message)


class ControlService:
    def __init__(self, config, backend, *, clock=time.monotonic):
        self.config = config
        self.backend = backend
        self.clock = clock
        self.started = clock()
        self.instance_id = uuid4()
        self.lock = threading.RLock()
        self.closed = False
        self.claim = None
        self.jobs = {}
        self.active = None
        self.last_error = None
        self.pending_stop = False
        self.retry_at = 0
        self.values = {
            "motor": [0.0] * len(config.motor_channels),
            "led": [0.0] * len(config.led_pins),
        }
        self.updated = {
            kind: [utcnow()] * len(values) for kind, values in self.values.items()
        }
        self._exit = threading.Event()
        self._thread = None

    def start(self):
        self._thread = threading.Thread(
            target=self._watch, name="lumastir-deadlines", daemon=True
        )
        self._thread.start()

    def _watch(self):
        while not self._exit.wait(0.05):
            try:
                self.tick()
            except Exception:
                LOG.exception("deadline supervisor failed")
                with self.lock:
                    self._fault(
                        "supervisor_failed", "deadline supervisor failed; stop required"
                    )
                    self.pending_stop = True

    def _fault(self, code, message):
        self.last_error = ErrorInfo(code=code, message=message, timestamp=utcnow())
        LOG.error("%s: %s", code, message)

    def _claim_response(self):
        return ClaimResponse(
            claim_token=self.claim["token"],
            heartbeat_interval_s=self.claim["ttl"] / 3,
            expires_at=utcnow()
            + timedelta(seconds=max(0, self.claim["deadline"] - self.clock())),
        )

    def acquire(self, command):
        with self.lock:
            self._expire()
            if self.closed:
                raise ControlError(503, "shutting_down", "controller is shutting down")
            if self.claim:
                if (self.claim["session_id"], self.claim["owner"]) != (
                    command.session_id,
                    command.owner,
                ):
                    raise ControlError(
                        409, "claimed", "device is claimed by another session"
                    )
                # Acquisition retry does not extend the lease. Heartbeats do.
                return self._claim_response()
            self.claim = dict(
                token=secrets.token_urlsafe(32),
                owner=command.owner,
                session_id=command.session_id,
                ttl=command.ttl_s,
                deadline=self.clock() + command.ttl_s,
            )
            return self._claim_response()

    def _expire(self):
        if self.claim and self.clock() >= self.claim["deadline"]:
            self.claim = None
            self._stop_all("claim_expired", clear_fault=False)

    def _require_claim(self, token):
        self._expire()
        if self.closed:
            raise ControlError(503, "shutting_down", "controller is shutting down")
        if (
            not self.claim
            or not token
            or not secrets.compare_digest(token, self.claim["token"])
        ):
            raise ControlError(
                423, "claim_required", "a live X-Claim-Token is required"
            )

    def heartbeat(self, token):
        with self.lock:
            self._require_claim(token)
            self.claim["deadline"] = self.clock() + self.claim["ttl"]
            return self._claim_response()

    def release(self, token):
        with self.lock:
            if self.claim is None:
                return
            self._require_claim(token)
            self._stop_all("claim_released")
            self.claim = None

    def _validate(self, kind, index, value):
        mapping = (
            self.config.motor_channels if kind == "motor" else self.config.led_pins
        )
        try:
            checked_index(index, mapping)
            value = percent(value)
        except ValueError as exc:
            raise ControlError(422, "invalid_output", str(exc)) from exc
        if value > self.config.max_power:
            raise ControlError(422, "power_limit", "value exceeds configured max_power")
        return value

    def _write(self, kind, index, value):
        method = (
            self.backend.set_motor_by_index
            if kind == "motor"
            else self.backend.set_led_by_index
        )
        try:
            _, address = method(index, value)
        except Exception as exc:
            self.values[kind][index] = None
            self.updated[kind][index] = utcnow()
            self.pending_stop = True
            self._fault("hardware_write_failed", f"{kind} {index}: {exc}")
            raise ControlError(
                503,
                "hardware_write_failed",
                f"{kind} {index} write failed; physical state unknown",
            ) from exc
        self.values[kind][index] = value
        self.updated[kind][index] = utcnow()
        LOG.info("output kind=%s index=%s commanded_percent=%s", kind, index, value)
        return SetResponse(index=index, value=value, hardware_address=address)

    def set_output(self, kind, index, value, token):
        with self.lock:
            self._require_claim(token)
            value = self._validate(kind, index, value)
            if value and self.last_error:
                raise ControlError(
                    412,
                    "fault_active",
                    "stop all outputs successfully before starting again",
                )
            if kind == "motor" and self.active and value:
                raise ControlError(
                    409,
                    "run_active",
                    "a timed run is active; stop it before changing motor power",
                )
            result = self._write(kind, index, value)
            if (
                kind == "motor"
                and self.active
                and self.jobs[self.active]["response"].index == index
                and value == 0
            ):
                self._finish("cancelled", "motor_set_to_zero")
            return result

    def run(self, command, token):
        with self.lock:
            self._require_claim(token)
            if command.instance_id != self.instance_id:
                raise ControlError(
                    409,
                    "instance_changed",
                    "server restarted; reconcile state before creating a new request",
                )
            key = str(command.request_id)
            payload = command.model_dump(mode="json")
            if key in self.jobs:
                old = self.jobs[key]
                if (
                    old["payload"] != payload
                    or old["session_id"] != self.claim["session_id"]
                ):
                    raise ControlError(
                        409,
                        "request_id_conflict",
                        "request_id already belongs to a different command or session",
                    )
                return old["response"].model_copy()
            self._validate("motor", command.index, command.speed)
            if command.duration_s > self.config.max_run_seconds:
                raise ControlError(
                    422, "duration_limit", "duration exceeds configured max_run_seconds"
                )
            if self.last_error:
                raise ControlError(
                    412,
                    "fault_active",
                    "stop all outputs successfully before starting again",
                )
            if self.active or any(value != 0 for value in self.values["motor"]):
                raise ControlError(
                    409,
                    "motor_active",
                    "stop existing motor outputs before starting a timed run",
                )
            if len(self.jobs) >= 1000:
                raise ControlError(
                    409,
                    "run_capacity",
                    "run ledger full; stop and restart service before further runs",
                )
            response = RunResponse(
                **{
                    k: payload[k]
                    for k in (
                        "request_id",
                        "instance_id",
                        "index",
                        "speed",
                        "duration_s",
                    )
                },
                state="running",
                started_at=utcnow(),
            )
            self.jobs[key] = dict(
                payload=payload,
                response=response,
                session_id=self.claim["session_id"],
                deadline=self.clock() + command.duration_s,
            )
            self.active = key
            try:
                self._write("motor", command.index, command.speed)
            except ControlError:
                self._finish("failed", "start_write_failed")
                raise
            LOG.info(
                "run started request_id=%s index=%s duration_s=%s",
                key,
                command.index,
                command.duration_s,
            )
            return response.model_copy()

    def get_run(self, request_id):
        with self.lock:
            job = self.jobs.get(str(request_id))
            if job is None:
                raise ControlError(
                    404, "run_not_found", "run not found in this server instance"
                )
            return job["response"].model_copy()

    def _finish(self, state, reason):
        if self.active:
            response = self.jobs[self.active]["response"]
            response.state = state
            response.reason = reason
            response.stopped_at = utcnow() if state != "failed" else None
            LOG.info(
                "run ended request_id=%s state=%s reason=%s", self.active, state, reason
            )
            self.active = None

    def _stop_all(self, reason, clear_fault=True):
        errors = []
        for kind, values in self.values.items():
            for index in range(len(values)):
                try:
                    self._write(kind, index, 0)
                except ControlError as exc:
                    errors.append(str(exc))
        self._finish("failed" if errors else "cancelled", reason)
        self.pending_stop = bool(errors)
        if errors:
            self.retry_at = self.clock() + 1
            self._fault("stop_failed", "; ".join(errors))
            raise ControlError(
                503,
                "stop_failed",
                "some outputs could not be stopped; physical state unknown",
            )
        if clear_fault:
            self.last_error = None

    def stop_all(self):
        with self.lock:
            self._stop_all("stop_requested")

    def tick(self):
        with self.lock:
            try:
                self._expire()
                if self.active:
                    job = self.jobs[self.active]
                    if self.clock() >= job["deadline"]:
                        self._write("motor", job["response"].index, 0)
                        self._finish("completed", "duration_elapsed")
                if self.pending_stop and self.clock() >= self.retry_at:
                    self._stop_all("fault_stop", clear_fault=False)
            except ControlError:
                if self.active:
                    self._finish("failed", "stop_write_failed")
                self.pending_stop = True
                self.retry_at = self.clock() + 1

    def devices(self):
        with self.lock:

            def outputs(kind, mapping):
                return [
                    Output(
                        id=f"{kind}_{address}",
                        index=i,
                        hardware_address=address,
                        commanded_percent=self.values[kind][i],
                        updated_at=self.updated[kind][i],
                    )
                    for i, address in enumerate(mapping)
                ]

            return Devices(
                instance_id=self.instance_id,
                equipment_id=self.config.equipment_id,
                simulated=self.backend.simulated,
                motors=outputs("motor", self.config.motor_channels),
                leds=outputs("led", self.config.led_pins),
                max_power=self.config.max_power,
                max_run_seconds=self.config.max_run_seconds,
            )

    def status(self):
        with self.lock:
            moving = any(value is None or value > 0 for value in self.values["motor"])
            state = (
                "error"
                if self.last_error
                else "dry_run"
                if self.backend.simulated
                else "busy"
                if moving
                else "ready"
            )
            actions = ["lumastir.stop"]
            if not self.last_error:
                actions += ["lumastir.led.set"]
                if not self.active:
                    actions += ["lumastir.motor.set"]
                if not moving and not self.active:
                    actions += ["lumastir.motor.run"]
            claim = None
            if self.claim:
                claim = dict(
                    owner=self.claim["owner"],
                    session_id=self.claim["session_id"],
                    expires_at=self._claim_response().expires_at.isoformat(),
                )
            return Status(
                equipment_id=self.config.equipment_id,
                equipment_name=self.config.equipment_name,
                equipment_version=__version__,
                equipment_status=state,
                message="Commanded PWM only; no motion or light-output feedback.",
                required_actions=["lumastir.stop"] if self.last_error else [],
                device_time=utcnow(),
                uptime_seconds=self.clock() - self.started,
                allowed_actions=actions,
                last_error=self.last_error,
                details=dict(
                    **self.devices().model_dump(mode="json"),
                    claimed_by=claim,
                    active_run=self.active,
                    hardware_feedback=False,
                ),
            )

    def close(self):
        self._exit.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
        with self.lock:
            self.closed = True
            try:
                self._stop_all("shutdown")
            finally:
                self.backend.cleanup()
