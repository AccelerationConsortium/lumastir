# Lumastir repository instructions

Lumastir owns hardware access, command validation, deadlines, claims, and its
HTTP contract. The dashboard/SDK lives in the separate `ac-organic-lab` repo.
Read `src/lumastir/agent-guide.md` and `docs/dashboard-integration.md` before
changing control semantics. Where available, follow the lab's binding
`ac-organic-lab/docs/AGENTIC_LAB_DESIGN.md` Part I and `docs/STATUS_SPEC.md`.

- Use `uv`; install development tools with `uv sync --extra dev`.
- Tests are hardware-free: `uv run pytest`; lint: `uv run ruff check src tests`.
- Run local API checks with `lumastir-server --simulate`. Never run the demo,
  import/initialize real drivers, or send live commands as a software test.
- Only explicitly authorized hardware operations or approved lab workflows may
  energize outputs. Do not bypass interlocks, claim refusals, or the SDK.
- Preserve validation at both API and backend boundaries. A timer must be owned
  by the device process, not only an HTTP caller.
- Never label commanded PWM as measured RPM or physical activity. A failed write
  means output is unknown. Never silently retry an ambiguous timed action with
  a new request ID.
- Keep one hardware owner and keep stop available during faults. Cleanup must
  attempt every resource even when an earlier operation fails.
- Keep addresses, credentials, and deployment-specific paths in local config;
  never put experiment records in git. Experimental evidence belongs in BitacoraDB.
- Changing the local repo does not deploy the Pi. Report what was tested, what
  was deployed, and what remains pending separately. Do not change shared lab
  contracts or another repo's access configuration without its required approval.
