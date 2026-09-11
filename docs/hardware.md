# Hardware and commissioning

A default three-vial unit uses BCM GPIO 17/18/27 for LEDs and PCA9685 channels
0/4/8 for motors. A list index is configuration order, not a physical vial label.
Confirm wiring, motor power circuitry, supply polarity, and stir-bar presence
before an authorized physical test. Use appropriate motor drivers, flyback
protection, current limits, and LED current limiting for the actual assembly.
No current, RPM, temperature, stir-bar, or illumination sensors are present in
this software; safe operating limits require bench characterization.

The PCA9685 driver exposes 16-bit duty-cycle values to Python while the chip's
PWM resolution is 12 bits. 50% means half-duty PWM at the configured frequency,
not half the maximum stirring speed. Starting thresholds and stirring behavior
vary with the motor, vial, stir bar, and liquid. Do not infer successful mixing
from an HTTP response.

Run one backend owner. The hardware lock must live on the same filesystem path
for the server, demo, and any direct Python process. Never delete or replace a
lock file while a process holds it. Changing its path creates a different lock
and defeats mutual exclusion. Unrelated programs that do not honor the lock
remain outside its protection.

Startup and graceful shutdown attempt zero output. If a write fails, stop-all
continues with every other output and returns an error. Failed output state is
unknown; the software cannot establish a physical stop. Timers are checked every
50 ms, so scheduling/bus latency may delay a command. A hung synchronous I2C call
can block the supervisor and HTTP commands. A process kill, kernel hang, or powered
PCA9685 surviving a Pi restart can retain output. A software timer is insufficient
for experiments requiring a guaranteed independent cutoff.

For deployment:

1. Install the wheel or checkout with the `hardware` extra on the Pi; install
   development/test dependencies only on a development machine.
2. Record the selected wiring config and validate it before starting. If changing
   physical addresses, update mappings and reverify vial identity.
3. Customize `deploy/lumastir.service` with absolute paths and a Tailnet bind.
   Do not expose the unauthenticated API to the public network. Set exact allowed
   origins with `LUMASTIR_CORS_ORIGINS` only if browser-direct access is needed.
4. Before a restart, coordinate active claims/runs and confirm output state. Do
   not assume restarting the service establishes whether an earlier action happened.
5. Read `/health`, `/status`, `/v1/devices`, and `/agent-guide`; check version,
   simulation flag, mapping, and faults. Run a separately authorized short bench
   test, confirm physical stirring, and verify stopping at the end.

The test suite uses simulated and mocked hardware only. It cannot validate
current limits, physical wiring, mixing, motor inertia, GPIO timing, or cutoff
behavior during power failure.
