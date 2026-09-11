# Dashboard and lab-skills integration

The existing `ac-organic-lab` dashboard uses two separate inventories:

- `api/app/ssh_console.py::SSH_HOSTS` controls the human-admin SSH terminal list.
  The dashboard service user's SSH config resolves aliases and selects keys.
  Host-key checking stays strict. Adding an entry does not authorize a new key
  on the Pi or make the device controllable through lab-skills.
- `equipment.yaml` registers equipment status endpoints; its existing generic
  HTTP adapter can read Lumastir's new `/status` without a device-specific
  transport adapter. This release advertises STATUS_SPEC `1.1`, `kind: other`.
  It deliberately omits v1.2 physical activity because no motion feedback exists.

Installation-specific addresses and SSH configuration remain outside commits.
Before changing the dashboard or global SSH config, follow that repository's
exact-path approval requirements. Do not bypass missing SSH host trust with
`StrictHostKeyChecking=no` or trust an unverified `ssh-keyscan` result.

## Read-only equipment registration template

After upgrading the Pi and verifying `/status`, merge this into the dashboard's
local/reviewed registry using the installation's approved address convention:

```yaml
- id: lumastir
  name: Lumastir
  kind: other
  adapter: http
  protocol: "1.1"
  base_url: http://<pi-tailnet-address>:8000
  status_path: /status
  enabled: true
  documentation:
    - { label: Swagger UI, path: /docs, kind: swagger }
    - { label: OpenAPI JSON, path: /openapi.json, kind: openapi }
    - { label: Agent guide, path: /agent-guide, kind: markdown }
```

Ensure `equipment_id` in the Pi configuration matches the registry ID. Register
`/openapi.json` and `/agent-guide` in the registry's documentation endpoints if
exposing them through the dashboard proxy. Do not register the old 0.1 `/` as a
STATUS_SPEC envelope: it is incompatible.

With the `lumastir` ID in the `complexation` section of `platforms.yaml`, the
dashboard's `/api/catalog` lists these documents under Complexation Platform.
The API Reference page discovers the links from that catalog. Browser URLs are:

- `/api/equipment/lumastir/documentation/docs`
- `/api/equipment/lumastir/documentation/openapi.json`
- `/api/equipment/lumastir/documentation/agent-guide`

The existing documentation proxy permits only registered GET paths. Its Swagger
view disables command submission; documentation access does not grant control.
Verify each proxied document after restarting the dashboard. Until the SDK
catalog integration is reviewed, retain `enabled: false` and a maintenance
reason stating that SDK controls are not registered. Status reads and documentation
remain available in that mode, but `Lab.get("lumastir")` refuses hardware control.

## SDK control registration still requires review

The existing catalog dispatches by **equipment kind**, not equipment ID.
Registering Lumastir commands under the generic `other` kind would incorrectly
advertise them on unrelated services. Do not do that. A reviewed dashboard/SDK
change must either introduce a dedicated Lumastir kind in the shared contract,
or add per-equipment skill selection. The shared contract is binding and is not
changed by this device repo.

The device action vocabulary and bodies for that integration are:

| Skill name | Endpoint | Body model in `lumastir.models` |
|---|---|---|
| `lumastir.motor.set` | `/control/motor/set` | `MotorSet` |
| `lumastir.motor.run` | `/control/motor/run` | `RunCommand` |
| `lumastir.led.set` | `/control/led/set` | `LedSet` |
| `lumastir.stop` | `/control/stop` | empty |

Use the SDK's existing `ClaimManager`; its owner/session/TTL request and token
headers match this server. The approved execution layer must acquire the claim,
resolve current output indices, supply the current server `instance_id`, retain
one `request_id` across retries, and wait for that run's terminal state while
maintaining heartbeats. Do not mark a plan step complete when `/motor/run` merely
acknowledges starting. Claim release stops all outputs and may cancel an unfinished
run. Stop remains a human safety-floor action, not an agent-proposable workaround.

`allowed_actions` advertises device capability/preconditions, not a verified
caller identity. Hardware faults omit start/set capabilities; an active timed run
omits conflicting motor commands. The HTTP layer rechecks the conditions. The
SDK layer must preserve approved plans, claims, preconditions, and truthful
BitacoraDB records. Installing these device changes does not grant unattended
agent hardware control.
