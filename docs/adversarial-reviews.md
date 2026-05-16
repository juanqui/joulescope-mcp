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
