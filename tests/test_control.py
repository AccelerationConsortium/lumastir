import math
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from lumastir.config import HardwareConfig, load_config
from lumastir.controller import SimulatedController, percent
from lumastir.models import ClaimRequest, RunCommand
from lumastir.server import create_app
from lumastir.service import ControlError, ControlService


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


@pytest.fixture
def service():
    clock = Clock()
    config = HardwareConfig()
    backend = SimulatedController(config.led_pins, config.motor_channels)
    service = ControlService(config, backend, clock=clock)
    service.test_clock = clock
    yield service
    service.close()


def claim(service, session="test", ttl=30):
    return service.acquire(
        ClaimRequest(owner="test-operator", session_id=session, ttl_s=ttl)
    ).claim_token


def run_command(service, **kw):
    values = dict(
        index=0,
        speed=50,
        duration_s=20,
        request_id=uuid4(),
        instance_id=service.instance_id,
    )
    values.update(kw)
    return RunCommand(**values)


@pytest.mark.parametrize("value", [-1, 101, math.nan, math.inf, -math.inf, True, "50"])
def test_controller_rejects_invalid_percentages(value):
    with pytest.raises(ValueError):
        percent(value)


@pytest.mark.parametrize(
    "mapping",
    [
        {"led_pins": [17, 17]},
        {"motor_channels": [0, 16]},
        {"motor_channels": [-1]},
        {"led_pins": [2]},
        {"led_pins": [True]},
        {"motor_channels": ["0"]},
        {"motor_channels": [1.1]},
        {"misspelled": 1},
    ],
)
def test_configuration_rejects_unsafe_or_ambiguous_mappings(mapping):
    with pytest.raises(ValidationError):
        HardwareConfig(**mapping)


def test_installed_defaults_do_not_depend_on_cwd(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert load_config().motor_channels == [0, 4, 8]
    invalid = tmp_path / "config.yaml"
    invalid.write_text("led_pins: [17]\n")
    with pytest.raises(ValueError):
        load_config(str(invalid))


def test_timed_run_stops_without_any_further_client_call(service):
    token = claim(service)
    command = run_command(service)
    service.run(command, token)
    assert service.backend.motor_values == [50, 0, 0]
    service.test_clock.now = 19.99
    service.tick()
    assert service.backend.motor_values[0] == 50
    service.test_clock.now = 20
    service.tick()
    assert service.backend.motor_values == [0, 0, 0]
    assert service.get_run(command.request_id).state == "completed"


def test_real_supervisor_stops_a_run_after_client_disconnect():
    cfg = HardwareConfig()
    backend = SimulatedController(cfg.led_pins, cfg.motor_channels)
    service = ControlService(cfg, backend)
    service.start()
    try:
        command = run_command(service, duration_s=0.1)
        service.run(command, claim(service))
        deadline = time.monotonic() + 2
        while (
            service.get_run(command.request_id).state == "running"
            and time.monotonic() < deadline
        ):
            time.sleep(0.02)
        assert service.get_run(command.request_id).state == "completed"
        assert backend.motor_values[0] == 0
    finally:
        service.close()


def test_expired_claim_stops_leds_and_motor(service):
    token = claim(service, ttl=5)
    service.set_output("led", 0, 100, token)
    command = run_command(service)
    service.run(command, token)
    service.test_clock.now = 5
    service.tick()
    assert service.backend.motor_values == [0, 0, 0]
    assert service.backend.led_values == [0, 0, 0]
    assert service.get_run(command.request_id).reason == "claim_expired"
    with pytest.raises(ControlError) as exc:
        service.heartbeat(token)
    assert exc.value.status == 423


def test_claim_conflicts_and_heartbeat(service):
    token = claim(service, ttl=5)
    with pytest.raises(ControlError) as exc:
        claim(service, session="other")
    assert exc.value.status == 409
    assert claim(service) == token
    service.test_clock.now = 4
    service.heartbeat(token)
    service.test_clock.now = 6
    service.tick()
    assert service.claim is not None
    with pytest.raises(ControlError):
        service.set_output("led", 0, 100, "wrong-token")
    assert service.backend.led_values == [0, 0, 0]


def test_run_retries_are_idempotent_even_concurrently_and_after_completion(service):
    token = claim(service)
    command = run_command(service)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: service.run(command, token), range(8)))
    assert len(service.jobs) == 1
    assert len({str(result.request_id) for result in results}) == 1
    service.test_clock.now = 20
    service.tick()
    assert service.run(command, token).state == "completed"
    assert service.backend.motor_values[0] == 0
    with pytest.raises(ControlError) as exc:
        service.run(command.model_copy(update={"speed": 60}), token)
    assert exc.value.code == "request_id_conflict"


def test_old_instance_and_overlapping_runs_are_refused(service):
    token = claim(service)
    with pytest.raises(ControlError) as exc:
        service.run(run_command(service, instance_id=uuid4()), token)
    assert exc.value.code == "instance_changed"
    service.run(run_command(service), token)
    with pytest.raises(ControlError):
        service.run(run_command(service, index=1), token)
    with pytest.raises(ControlError):
        service.set_output("motor", 0, 75, token)
    assert "lumastir.motor.run" not in service.status().allowed_actions
    service.set_output("motor", 0, 0, token)
    assert service.active is None


def test_stop_all_is_claim_independent_and_release_stops_outputs(service):
    token = claim(service)
    service.set_output("motor", 0, 50, token)
    service.set_output("led", 2, 100, token)
    service.stop_all()
    assert service.backend.motor_values == [0, 0, 0]
    assert service.backend.led_values == [0, 0, 0]
    service.set_output("led", 1, 80, token)
    service.release(token)
    assert service.claim is None
    assert service.backend.led_values == [0, 0, 0]


def test_stop_failure_does_not_skip_remaining_outputs_and_remains_visible(
    service, monkeypatch
):
    token = claim(service)
    service.run(run_command(service), token)
    service.set_output("led", 0, 100, token)
    original = service.backend.set_motor_by_index
    attempted = []

    def failing(index, speed):
        attempted.append(index)
        if index == 0:
            raise OSError("simulated bus failure")
        return original(index, speed)

    monkeypatch.setattr(service.backend, "set_motor_by_index", failing)
    with pytest.raises(ControlError) as exc:
        service.stop_all()
    assert exc.value.code == "stop_failed"
    assert attempted == [0, 1, 2]
    assert service.backend.led_values == [0, 0, 0]
    assert service.devices().motors[0].commanded_percent is None
    assert service.status().equipment_status == "error"
    assert service.status().allowed_actions == ["lumastir.stop"]
    monkeypatch.setattr(service.backend, "set_motor_by_index", original)
    service.test_clock.now += 1
    service.tick()
    assert service.backend.motor_values[0] == 0
    assert service.last_error is not None  # Operator must reconcile via explicit stop.
    service.stop_all()
    assert service.last_error is None


def test_failed_start_request_cannot_reexecute_on_retry(service, monkeypatch):
    token = claim(service)
    command = run_command(service)
    original = service.backend.set_motor_by_index
    with monkeypatch.context() as context:
        context.setattr(
            service.backend,
            "set_motor_by_index",
            lambda *a: (_ for _ in ()).throw(OSError("bus")),
        )
        with pytest.raises(ControlError):
            service.run(command, token)
    service.stop_all()
    assert service.run(command, token).state == "failed"
    assert service.backend.motor_values[0] == 0
    assert service.backend.set_motor_by_index == original


def test_status_reads_have_no_hardware_side_effects(service):
    token = claim(service, ttl=5)
    service.set_output("led", 0, 50, token)
    service.test_clock.now = 6
    before = service.backend.led_values.copy()
    service.status()
    service.devices()
    assert service.backend.led_values == before
    service.tick()
    assert service.backend.led_values == [0, 0, 0]


@pytest.fixture
def client():
    with TestClient(create_app(config=HardwareConfig(), simulate=True)) as client:
        yield client


def api_claim(client):
    response = client.post(
        "/control/claim", json={"owner": "test-operator", "session_id": "test"}
    )
    assert response.status_code == 200
    return {"X-Claim-Token": response.json()["claim_token"]}


@pytest.mark.parametrize(
    "body",
    [
        '{"speed":-1}',
        '{"speed":101}',
        '{"speed":true}',
        '{"speed":"50"}',
        '{"speed":NaN}',
        '{"speed":Infinity}',
        '{"speed":50,"typo":1}',
    ],
)
def test_invalid_http_inputs_do_not_touch_hardware(client, body):
    response = client.post(
        "/motor/0/speed",
        content=body,
        headers={**api_claim(client), "Content-Type": "application/json"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"
    assert client.get("/v1/devices").json()["motors"][0]["commanded_percent"] == 0


def test_api_contract_and_no_token_in_status(client):
    headers = api_claim(client)
    assert (
        client.post("/control/motor/set", json={"index": 0, "speed": 50}).status_code
        == 423
    )
    response = client.post(
        "/control/motor/set", headers=headers, json={"index": 0, "speed": 50}
    )
    assert response.json()["value"] == 50
    assert headers["X-Claim-Token"] not in client.get("/status").text
    assert client.get("/status").json()["equipment_status"] == "dry_run"
    assert client.post("/control/stop").status_code == 200
    assert client.get("/agent-guide").status_code == 200
    schema = client.get("/openapi.json").json()
    assert (
        schema["components"]["schemas"]["MotorSet"]["properties"]["speed"]["maximum"]
        == 100
    )
    assert schema["paths"]["/control/motor/run"]["post"]["operationId"] == "run_motor"


def test_api_duration_limits_and_invalid_indices(client):
    headers = api_claim(client)
    instance = client.get("/v1/devices").json()["instance_id"]
    response = client.post(
        "/control/motor/run",
        headers=headers,
        json={
            "index": 0,
            "speed": 50,
            "duration_s": 601,
            "request_id": str(uuid4()),
            "instance_id": instance,
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "duration_limit"
    assert (
        client.post(
            "/led/99/brightness", headers=headers, json={"brightness": 50}
        ).status_code
        == 422
    )
