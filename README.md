# Lumastir

Raspberry Pi LED and stirring-motor control using GPIO PWM and a PCA9685.
Version 0.2 adds server-timed runs, exclusive expiring claims, output discovery,
fault reporting, stop-all, and hardware-free simulation.

**PWM percentage is not measured RPM.** Lumastir has no motion or optical
feedback. Acknowledgements confirm commands accepted by the driver.

## Install and test without hardware

```bash
git clone https://github.com/AccelerationConsortium/lumastir.git
cd lumastir
uv sync --extra dev
uv run lumastir-server --simulate
# Another terminal:
uv run lumastir-cli devices
uv run lumastir-cli run 0 50 20 --owner commissioning
uv run lumastir-cli status
uv run lumastir-cli stop
uv run pytest
uv run ruff check src tests
```

The `run` command claims the device, starts one server-timed operation,
heartbeats while waiting, and releases afterward. Release also turns off LEDs.
The CLI defaults to localhost; set `LUMASTIR_URL` or use `--host` before the
subcommand. It imports no Pi drivers. CLI error details go to stderr and failures
return a nonzero exit code. Do not repeat a failed timed command blindly: its
request ID is printed before starting, and `run-status <request_id>` inspects it.

## Hardware installation

On the Raspberry Pi, enable I2C, install the hardware extras, and use a service
account with GPIO/I2C access:

```bash
uv sync --extra hardware
uv run lumastir-server --config configs/3led_3motor.yaml
```

The default bind is `127.0.0.1`. For remote access, pass `--host <pi-tailnet-ip>`
and restrict access through Tailnet ACLs. Default configuration is built in and
works from an installed wheel outside the repository; an explicit `--config`
(or `LUMASTIR_CONFIG`) path must exist. There is no fallback from a bad path.

Default mappings:

| Output indices | LED GPIO (BCM) | Motor PCA9685 channels |
|---|---|---|
| 0, 1, 2 | 17, 18, 27 | 0, 4, 8 |

The six-motor file is `configs/3led_6motor.yaml`, with motor channels
`[0, 4, 8, 3, 7, 11]`. Physically verify which channel drives each vial.

Configuration requires both mapping lists; duplicates, non-integers, invalid
channels, and LED use of I2C GPIO 2/3 are rejected before hardware setup.
Optional `max_power` (default 100) and `max_run_seconds` (default 600) constrain
control. Optional `equipment_id` and `equipment_name` identify an installation.
GPIO LED PWM is 100 Hz; PCA9685 motor PWM is 500 Hz. Do not power motors directly
from a GPIO or PCA9685 signal output; use the appropriate driver/power stage.

## Control and agent documentation

- [Agent control guide](src/lumastir/agent-guide.md), also served as `/agent-guide`.
- [Hardware and deployment](docs/hardware.md).
- [Dashboard/SDK integration](docs/dashboard-integration.md).
- Live `/docs` and `/openapi.json`: typed API reference.
- `AGENTS.md`: repository instructions for coding agents.

| Action | Endpoint |
|---|---|
| Discover mappings, setpoints, limits, server instance | `GET /v1/devices` |
| Controller state and faults (STATUS_SPEC 1.1) | `GET /status` |
| Acquire / maintain / release exclusive claim | `POST /control/claim`, `/control/heartbeat`, `/control/release` |
| Set motor PWM / LED brightness | `POST /control/motor/set`, `/control/led/set` |
| Start timed motor run / inspect its result | `POST /control/motor/run`, `GET /v1/runs/{request_id}` |
| Stop every motor and LED | `POST /control/stop` |

All set/run operations require a live `X-Claim-Token`. Claims expire after 30
seconds by default and must be heartbeated. Expiry/release stops all outputs.
Stop-all needs no claim. Claims coordinate clients; they are not authentication.

For sustained setpoints, use `lumastir-cli claim --owner <label>` and pass the
returned token via `LUMASTIR_CLAIM_TOKEN` to `motor`, `led`, `heartbeat`, and
`release`. Keep that token private. For timed work prefer `lumastir-cli run`.

### Upgrade from 0.1

Legacy motor and LED paths remain but now enforce limits and claims. Existing
unclaimed clients will receive 423. Hardware dependencies moved to the `hardware`
extra. The bind default changed from all interfaces to loopback. Version 0.2
must be installed on the Pi before new controls are available; editing a clone
on the dashboard server does not update the Pi.

## Systemd

Edit [deploy/lumastir.service](deploy/lumastir.service) with the actual account,
absolute installation/config paths, and Tailnet bind address. The template uses
`/opt/lumastir`, not `%h` (which does not follow `User=` in a system service).
Install dependencies before starting; the service runs the installed venv entry
point and never downloads packages during a restart.

```bash
sudo cp deploy/lumastir.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now lumastir
```

One process owns hardware through `/run/lock/lumastir.lock`; both demo and server
use it. An optional `LUMASTIR_LOCK_FILE` override must be identical for every
hardware process. Never run multiple workers or `--reload` against hardware.
The demo explicitly energizes outputs and must only run as an authorized bench
check with the server stopped. It uses the same validated configuration and lock.

Software timers cannot guarantee stopping after an OS/process/bus failure.
Where required, provide hardware output disable, a watchdog, or independent power
cutoff. The server retries failed stops and reports uncertain output honestly.

## License

[MIT](LICENSE)
