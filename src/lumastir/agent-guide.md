# Lumastir agent control guide (API 0.2, STATUS_SPEC 1.1)

This guide describes the new implementation. A running Pi still reporting
version 0.1 has not been upgraded. Read `/status`, `/v1/devices`, and
`/openapi.json` before acting; do not infer support from this repository alone.

## Endpoint reference

All paths are relative to the device API base URL. Control bodies are JSON.
The OpenAPI document is the authoritative machine-readable request/response schema.

| Method | Path | Purpose | Claim token |
|---|---|---|---|
| GET | `/` | Service identity and wiring configuration | No |
| GET | `/health` | Process liveness | No |
| GET | `/status` | Dashboard STATUS_SPEC envelope | No |
| GET | `/v1/devices` | Output mapping, limits, setpoints, instance ID | No |
| GET | `/v1/runs/{request_id}` | Timed-run outcome | No |
| GET | `/agent-guide` | This operating guide | No |
| GET | `/openapi.json` | Typed API contract | No |
| GET | `/docs` | Interactive API reference | No |
| POST | `/control/claim` | Acquire a lease using owner, session_id, ttl_s | No |
| POST | `/control/heartbeat` | Renew lease; no body | Yes |
| POST | `/control/release` | Stop all outputs and release lease; no body | Yes |
| POST | `/control/motor/set` | Set index and speed (0–100% PWM) | Yes |
| POST | `/control/motor/run` | Start a bounded, deduplicated timed run | Yes |
| POST | `/control/led/set` | Set index and brightness (0–100% PWM) | Yes |
| POST | `/control/stop` | Stop every motor and LED; no body | No |

To stop one motor while keeping LEDs on, set that motor's speed to zero within
the existing claim. Do not release the claim or call stop-all if you intend to
keep lights on. Continue heartbeats for as long as any output must remain on.
There is no separately named backlight endpoint; identify the actual LED output
through wiring verification before assigning that label.

## Measurement and mapping

Lumastir drives LEDs and stirring motors through PWM. `speed` and `brightness`
are percentages, not RPM or calibrated light intensity. There is no tachometer,
stir-bar detector, optical feedback, or physical emergency-stop sensor.
A successful response confirms a driver write, not physical stirring.
`commanded_percent: null` means the most recent write failed and output is uncertain.
`equipment_status` reports the controller's known faults and commanded motor use.
The primary operation is stirring; measured physical `activity` is unavailable,
so this release advertises STATUS_SPEC 1.1 and does not invent a v1.2 activity value.

`GET /v1/devices` returns the server `instance_id`, simulation mode, output
indices, stable IDs based on hardware addresses, configured limits, and last
successful setpoints. With the built-in 3-vial mapping, motor index 0 is channel
0, index 1 is channel 4, and index 2 is channel 8. Do not assume physical vial
placement from an index: confirm wiring and a stir bar with the operator.
Stable IDs survive list reordering; resolve the current index before commands.

## Authorized control sequence

For lab automation, use the lab-skills SDK, approved plans, claims and
preconditions required by the lab contract. An HTTP surface alone does not make
this device a registered SDK skill. See `docs/dashboard-integration.md` in the
repository for the remaining deployment/catalog steps. Do not use SSH as a way
to bypass device controls or claims. The CLI/API examples below are protocol
reference for explicitly authorized commissioning and simulator tests.

1. Read `/status` and `/v1/devices`. Check `simulated`, `last_error`, mappings,
   power/duration limits, and `allowed_actions`. Physically reconcile unknown state.
2. `POST /control/claim` with an owner, a unique session ID, and `ttl_s` (5–120,
   default 30). Store the returned `claim_token` privately. Claims are cooperative
   ownership, not authentication; restrict the network with Tailnet ACLs.
3. Send the token as `X-Claim-Token` on every set/run/heartbeat/release request.
   Heartbeat more frequently than `heartbeat_interval_s`. Expiry and release turn
   off **both motors and LEDs**, including outputs set earlier in the same claim.
4. To run the first configured motor at 50% for 20 seconds, send
   `POST /control/motor/run` with:

   ```json
   {
     "index": 0,
     "speed": 50,
     "duration_s": 20,
     "request_id": "<new UUID retained by the caller>",
     "instance_id": "<UUID returned by /v1/devices>"
   }
   ```

   The server starts its own monotonic deadline and returns immediately. Only
   one timed run may be active, and existing motor outputs must first be off.
   A claim expiring first cancels the run early. Maintain the claim while waiting.
5. Poll `GET /v1/runs/{request_id}` until `completed`, `cancelled`, or `failed`.
   `completed` means the timer elapsed and the zero-PWM write succeeded;
   `stopped_at` timestamps that write, not a sensor-confirmed physical stop.
6. `POST /control/release` stops every output and relinquishes the claim.
   For immediate all-output stopping use `POST /control/stop`, which needs no
   claim and remains available during faults. It does not release another
   client's claim. Stop is not a physical emergency-stop circuit.

Other controls:

- `/control/motor/set`: `{"index": 0, "speed": 50}`; persists until changed,
  stopped, released, or lease expiry. Prefer a timed run for experiments.
- `/control/led/set`: `{"index": 0, "brightness": 100}`; same lease rules.
- `/control/heartbeat`: refresh lease using the token; empty body.
- Legacy `/motor/{index}/speed` and `/led/{index}/brightness` remain but now
  enforce the same claims and limits. Unclaimed legacy clients receive 423.

## Retries, faults and process restarts

Persist the request ID and exact body **before** sending a timed run. If the
response is lost, inspect that ID; retry only the identical body and ID against
the same server instance and claim session. A retry returns the existing run and
never resets its deadline, including when that run already failed or finished.
A reused ID with a different body/session returns 409. Setpoint calls are absolute,
but a delayed retry after a later command can overwrite that later setting;
serialize callers within one claim.

The ledger is in memory, bounded to 1,000 runs per process, and is not an
experimental record store. It is never evicted while the process lives. A full
ledger refuses new runs; stop and restart the service when operationally safe.
Every process gets a new `instance_id`; an old timed request is refused after a
restart. Reconcile physical state before issuing a new ID. Never automatically
replay a run after a 404 or process change. Store experiment records in BitacoraDB,
not git or this in-memory ledger.

Errors use `{"error": {"code": "...", ...}}`. HTTP 422 means invalid input or
configured limits; 409 means an ownership/run/ID conflict; 423 means missing or
expired claim; 412 means a known fault blocks starting; 503 means a write/stop
failure or shutdown. Refusals are not permission to adjust parameters and retry.
`last_error` codes: `hardware_write_failed`, `stop_failed`, `supervisor_failed`.
Failed stop writes make output unknown, attempt other outputs, and trigger
one-second best-effort retries. A successful automatic stop retains the fault
for reconciliation. Explicit stop-all clears it only if **every** write succeeds.

Timers and leases are software supervision, not hard real-time guarantees. A
blocked bus call, killed process, OS hang, or lost power defeats software cleanup;
a PCA9685 may retain output while powered. Use a hardware output-disable/watchdog
or independently switched motor power where a stop guarantee is required.
Startup initializes outputs off; shutdown attempts every output and resource.
Run exactly one hardware worker and never use auto-reload with connected hardware.

## Access and documentation

The server binds loopback by default. For deployment, bind the Pi's Tailnet
interface explicitly and configure Tailnet ACLs. There is no per-user HTTP
identity verification in this device API. Claim owner strings are caller labels,
not verified identities. The dashboard's human admin SSH gate is separate.
`LUMASTIR_CORS_ORIGINS` accepts comma-separated exact dashboard origins if needed;
CORS is not authentication. `/docs` and `/openapi.json` are generated from typed
models, including request bounds and response schemas.
