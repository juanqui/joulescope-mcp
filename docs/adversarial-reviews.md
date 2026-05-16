# Adversarial Review Log

This log records the five consecutive adversarial review passes requested for the initial implementation. Each pass identified a concrete weakness, then the repository was changed before moving to the next pass.

## Review 1: Hardware Contention

Finding: MCP clients can issue overlapping tool calls. The first implementation opened a fresh driver connection per call but did not serialize access inside the process. The same JS220 can fail to open when another call is already using it.

Improvement: `Js220Service` now uses an in-process reentrant lock and `_driver_session()` context manager around all driver operations.

Evidence:

- `src/joulescope_mcp/service.py`
- Manual hardware checks reproduced contention when operations were run in parallel and succeeded when run sequentially.

## Review 2: File Recording Safety

Finding: `record_jls` wrote files but was annotated as a read-only tool and would overwrite an existing output path through the driver recorder.

Improvement: `record_jls` is now annotated as write/destructive-capable, accepts `overwrite`, and rejects existing paths unless `overwrite=true`.

Evidence:

- `src/joulescope_mcp/server.py`
- `src/joulescope_mcp/service.py`
- `tests/test_service.py::test_record_jls_rejects_existing_path_without_overwrite`

## Review 3: Agent-Usable Timing

Finding: Measurement samples exposed device-relative `start_s` and `end_s`, but agents comparing optimization runs benefit from run-relative interval times. The response also omitted a concise actual interval field.

Improvement: `measure_energy` now returns `actual_interval_s`; each sample includes `relative_start_s` and `relative_end_s`.

Evidence:

- `src/joulescope_mcp/service.py`
- `tests/test_service.py::test_measure_energy_returns_totals_and_interval_samples`

## Review 4: Repeatable Hardware Verification

Finding: Hardware verification commands were present in documentation, but there was no repo-native script that emits concise JSON for future rechecks.

Improvement: Added `scripts/hardware_smoke.py` and `docs/testing.md`.

Evidence:

- `scripts/hardware_smoke.py`
- `docs/testing.md`
- `README.md`

## Review 5: Completion Evidence

Finding: The review requirement itself could be lost in terminal history, making future maintainers unable to tell what was challenged or improved.

Improvement: Added this review log as a committed artifact and referenced the testing/design docs from the README.

Evidence:

- `docs/adversarial-reviews.md`
- `README.md`

## README Installation Review 1: Stale Local-Venv Flow

Finding: The README still centered local `.venv` commands even though the requested installation path was `uvx` and client-managed stdio server startup.

Improvement: Reworked the top-level install flow around `uvx`, Git-based `uvx --from`, and local `uv --directory ... run joulescope-mcp` configurations.

Evidence:

- `README.md`

## README Installation Review 2: Invalid Driver Check Command

Finding: The troubleshooting section attempted to run `python -m pyjoulescope_driver` through `uvx --from joulescope-mcp`, which is not the right shape for a tool runner command.

Improvement: Replaced it with `uvx --from pyjoulescope-driver pyjoulescope_driver scan` and verified the installed package exposes `pyjoulescope_driver`.

Evidence:

- `README.md`
- `uvx --from . pyjoulescope_driver --help`

## README Installation Review 3: Missing Source Traceability

Finding: The README provided client snippets but did not show the reader what client documentation and MCP examples were used to choose each config shape.

Improvement: Added a client reference matrix with at least two references per client, plus popular MCP setup examples reviewed.

Evidence:

- `README.md`

## README Installation Review 4: Git Replacement Ambiguity

Finding: The per-client sections show the PyPI command, but pre-PyPI users could easily miss how to split the GitHub install command into `command` and `args`.

Improvement: Added GitHub and local checkout replacement blocks that can be dropped into any `mcpServers` or `servers` entry.

Evidence:

- `README.md`

## README Installation Review 5: Hardware Contention Risk

Finding: Installing the same JS220 server into several desktop clients can cause multiple always-on MCP server processes to compete for one USB device.

Improvement: Added a client configuration warning to configure only one always-on client per physical JS220.

Evidence:

- `README.md`
