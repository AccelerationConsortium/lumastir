"""FastAPI presentation over serialized, independently supervised hardware control."""

import argparse
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional
from uuid import UUID

from fastapi import FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse

from . import __version__
from .config import load_config
from .controller import LumaController, SimulatedController
from .models import (
    Ack,
    ClaimRequest,
    ClaimResponse,
    Devices,
    ErrorResponse,
    Health,
    LedCommand,
    LedSet,
    LegacyLedResponse,
    LegacyMotorResponse,
    MotorCommand,
    MotorSet,
    Probe,
    RunCommand,
    RunResponse,
    SetResponse,
    Status,
)
from .service import ControlError, ControlService


def create_app(*, config=None, simulate=None, backend_factory=None):
    @asynccontextmanager
    async def lifespan(app):
        selected = (
            config if config is not None else load_config(os.getenv("LUMASTIR_CONFIG"))
        )
        simulated = (
            simulate
            if simulate is not None
            else os.getenv("LUMASTIR_SIMULATE", "0") == "1"
        )
        factory = backend_factory or (
            SimulatedController if simulated else LumaController
        )
        backend = factory(selected.led_pins, selected.motor_channels)
        service = ControlService(selected, backend)
        app.state.service = service
        try:
            service.start()
            yield
        finally:
            service.close()

    app = FastAPI(
        title="Lumastir control API",
        version=__version__,
        lifespan=lifespan,
        description=(
            "LED and motor PWM control. Read /agent-guide and /v1/devices before control. "
            "Mutations require a live claim except stop-all. Acknowledgements confirm driver "
            "writes, not physical motion. Network access must be restricted by Tailnet ACLs."
        ),
        responses={
            code: {"model": ErrorResponse} for code in (409, 412, 422, 423, 503)
        },
    )
    origins = [
        value.strip()
        for value in os.getenv("LUMASTIR_CORS_ORIGINS", "").split(",")
        if value.strip()
    ]
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type", "X-Claim-Token"],
        )

    @app.exception_handler(ControlError)
    async def control_error(request, exc):
        return JSONResponse(
            status_code=exc.status,
            content={"error": {"code": exc.code, "message": str(exc)}},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # Never echo untrusted NaN/Infinity or claim-token input into JSON/errors.
        errors = [
            {
                "location": list(error["loc"]),
                "message": error["msg"],
                "type": error["type"],
            }
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "invalid_request", "details": errors}},
        )

    def service(request: Request):
        return request.app.state.service

    @app.get("/", response_model=Probe, operation_id="probe", tags=["discovery"])
    def root(request: Request):
        cfg = service(request).config
        return {
            "status": "online",
            "service": "lumastir",
            "equipment_id": cfg.equipment_id,
            "equipment_name": cfg.equipment_name,
            "protocol_version": "1.1",
            "config_data": {
                "led_pins": cfg.led_pins,
                "motor_channels": cfg.motor_channels,
            },
        }

    @app.get(
        "/health", response_model=Health, operation_id="health", tags=["discovery"]
    )
    def health():
        """Process liveness only; /status reports known hardware faults."""
        return {"status": "healthy"}

    @app.get(
        "/status", response_model=Status, operation_id="get_status", tags=["discovery"]
    )
    def status(request: Request):
        """Side-effect-free STATUS_SPEC 1.1 envelope; no physical feedback is available."""
        return service(request).status()

    @app.get(
        "/v1/devices",
        response_model=Devices,
        operation_id="list_outputs",
        tags=["discovery"],
    )
    def devices(request: Request):
        """Discover output indices, GPIO/PCA addresses, commanded PWM, and configured limits.

        Resolve indices before each session. These are configuration positions,
        not verified physical vial labels. Save instance_id before timed runs.
        """
        return service(request).devices()

    @app.get(
        "/agent-guide",
        response_class=PlainTextResponse,
        operation_id="read_agent_guide",
        tags=["discovery"],
    )
    def guide():
        """Read the agent operating guide, including claims, retries, and stop semantics."""
        return Path(__file__).with_name("agent-guide.md").read_text(encoding="utf-8")

    @app.post(
        "/control/claim",
        response_model=ClaimResponse,
        operation_id="acquire_claim",
        tags=["claims"],
    )
    def claim(cmd: ClaimRequest, request: Request):
        """Acquire exclusive control. Repeat owner/session returns the same live claim."""
        return service(request).acquire(cmd)

    @app.post(
        "/control/heartbeat",
        response_model=ClaimResponse,
        operation_id="heartbeat_claim",
        tags=["claims"],
    )
    def heartbeat(
        request: Request, x_claim_token: Optional[str] = Header(default=None)
    ):
        """Refresh the current lease; send X-Claim-Token and no request body.

        Heartbeat before heartbeat_interval_s elapses, including while waiting
        for a timed run. Lease expiry stops both motors and LEDs.
        """
        return service(request).heartbeat(x_claim_token)

    @app.post(
        "/control/release",
        response_model=Ack,
        operation_id="release_claim",
        tags=["claims"],
    )
    def release(request: Request, x_claim_token: Optional[str] = Header(default=None)):
        """Stop every output, then release the claim. Failure leaves a fault visible."""
        service(request).release(x_claim_token)
        return Ack()

    @app.post(
        "/control/motor/set",
        response_model=SetResponse,
        operation_id="set_motor",
        tags=["control"],
    )
    def motor(
        cmd: MotorSet,
        request: Request,
        x_claim_token: Optional[str] = Header(default=None),
    ):
        """Set motor PWM until changed, claim expiry/release, stop-all, or shutdown."""
        return service(request).set_output("motor", cmd.index, cmd.speed, x_claim_token)

    @app.post(
        "/control/led/set",
        response_model=SetResponse,
        operation_id="set_led",
        tags=["control"],
    )
    def led(
        cmd: LedSet,
        request: Request,
        x_claim_token: Optional[str] = Header(default=None),
    ):
        """Set absolute LED PWM percentage; zero turns off this LED only.

        Requires X-Claim-Token. The setpoint lasts until changed, claim expiry
        or release, stop-all, or shutdown. No calibrated light measurement exists.
        """
        return service(request).set_output(
            "led", cmd.index, cmd.brightness, x_claim_token
        )

    @app.post(
        "/control/motor/run",
        response_model=RunResponse,
        operation_id="run_motor",
        tags=["control"],
    )
    def run(
        cmd: RunCommand,
        request: Request,
        x_claim_token: Optional[str] = Header(default=None),
    ):
        """Start one server-timed run. Retrying identical request_id/body never restarts it."""
        return service(request).run(cmd, x_claim_token)

    @app.get(
        "/v1/runs/{request_id}",
        response_model=RunResponse,
        operation_id="get_run",
        tags=["discovery"],
    )
    def get_run(request_id: UUID, request: Request):
        """Read a timed run without changing it. Acknowledged start is not completion.

        Completed means the deadline elapsed and the zero-PWM write succeeded.
        A 404 may indicate a process restart; never automatically replay with a new ID.
        """
        return service(request).get_run(request_id)

    @app.post(
        "/control/stop", response_model=Ack, operation_id="stop_all", tags=["control"]
    )
    def stop(request: Request):
        """Stop all motors AND LEDs; no claim required. Clears faults only if every write succeeds."""
        service(request).stop_all()
        return Ack()

    @app.post(
        "/motor/{index}/speed",
        response_model=LegacyMotorResponse,
        deprecated=True,
        operation_id="legacy_set_motor",
        tags=["legacy"],
    )
    def legacy_motor(
        index: int,
        cmd: MotorCommand,
        request: Request,
        x_claim_token: Optional[str] = Header(default=None),
    ):
        """Compatibility route. Now requires the same claim and validation as /control/motor/set."""
        result = service(request).set_output("motor", index, cmd.speed, x_claim_token)
        return {
            "status": "ok",
            "index": index,
            "hardware_channel": result.hardware_address,
            "speed": result.value,
        }

    @app.post(
        "/led/{index}/brightness",
        response_model=LegacyLedResponse,
        deprecated=True,
        operation_id="legacy_set_led",
        tags=["legacy"],
    )
    def legacy_led(
        index: int,
        cmd: LedCommand,
        request: Request,
        x_claim_token: Optional[str] = Header(default=None),
    ):
        result = service(request).set_output(
            "led", index, cmd.brightness, x_claim_token
        )
        return {
            "status": "ok",
            "index": index,
            "hardware_pin": result.hardware_address,
            "brightness": result.value,
        }

    return app


app = create_app()


def start():
    import uvicorn

    parser = argparse.ArgumentParser(description="Lumastir Hardware Controller Server")
    parser.add_argument("--config", default=os.getenv("LUMASTIR_CONFIG"))
    parser.add_argument(
        "--simulate", action="store_true", default=os.getenv("LUMASTIR_SIMULATE") == "1"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(
        create_app(config=load_config(args.config), simulate=args.simulate),
        host=args.host,
        port=args.port,
    )
