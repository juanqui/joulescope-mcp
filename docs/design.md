# JouleScope JS220 MCP Design

## Goals

This server is designed for agents that need reliable physical power measurements while iterating on embedded firmware, software, or hardware settings. The MCP interface prioritizes tools that produce structured, directly comparable measurements rather than raw streams that an agent must interpret manually.

The design also exposes driver discovery and PubSub topic access so advanced JS220 capabilities remain reachable without adding a bespoke MCP tool for every topic.

## Source APIs

The implementation uses `pyjoulescope_driver`, the current JouleScope driver package. The driver exposes devices through a PubSub topic hierarchy. A connected JS220 has a path such as:

```text
u/js220/005920
```

The JS220 statistics path used for agent measurements is:

```text
<device>/s/stats/value
```

For JS220, statistics sample count is configured using:

```text
<device>/s/stats/scnt
```

The server sets `scnt = round(1_000_000 * interval_s)`, subscribes to statistics, enables statistics with `s/stats/ctrl = 1`, collects the requested number of intervals, and disables statistics in a `finally` block.

## Measurement Semantics

`measure_energy(duration_s, interval_s)` returns:

- one interval sample per JS220 statistics value
- total charge as coulombs and mAh
- total energy as joules and mWh
- average current and power over the actual captured duration
- average, minimum, and maximum voltage over the captured duration
- the average actual interval reported by the statistics payload
- per-interval averages, standard deviation, min, max, peak-to-peak, and integrals

The JS220 statistics payload includes per-interval integrals:

- `signals.current.integral.value`: coulombs
- `signals.power.integral.value`: joules

The server sums these per-interval integrals instead of estimating charge or energy from retained accumulators. This gives the agent the requested fidelity while avoiding an extra baseline interval.

Unit conversions:

```text
mAh = coulombs / 3.6
mWh = joules / 3.6
```

If `duration_s` is not a multiple of `interval_s`, the server captures the next whole interval. The response always includes both requested and actual duration.

## MCP Surface

### Agent-first tools

- `measure_energy`: preferred tool for power optimization loops
- `capture_statistics`: same measurement path, parameterized by frequency
- `configure_frontend`: typed JS220 current/voltage range setup
- `target_power_status`: typed target/DUT power state query
- `set_target_power`: typed target/DUT power connect/disconnect
- `cycle_target_power`: typed target/DUT power cycle with millisecond hold-off and settle waits

### Discovery tools

- `list_devices`
- `device_info`
- `list_topics`
- `query_topic`

### Hardware utility tools

- `read_gpi`
- `record_jls`

### Advanced escape hatch

- `publish_topic`

`publish_topic` is intentionally exposed because the JouleScope driver topic tree is broad and evolves. It is marked as write/destructive-capable in MCP annotations, and documentation directs agents to prefer typed tools first.

## Target Power Control

The JS220 target/DUT power path is controlled by the current range mode topic:

```text
<device>/s/i/range/mode
```

The server follows the official `dut_power.py` example from `pyjoulescope_examples`:

- `off`: disconnects Current+ from Current-
- `auto`: connects the current path and enables autoranging
- `manual`: connects the current path in manual range mode

`cycle_target_power(off_ms, settle_ms)` holds `off` for the requested number of milliseconds, restores `auto` or `manual`, then optionally waits for the target to settle.

## Resource Model

The server provides static URI resources:

- `joulescope://devices`
- `joulescope://driver`

These are useful for clients that present resources separately from tools.

## Prompt

`power_optimization_session` gives an agent a repeatable measurement workflow: establish a baseline, apply one change, measure with identical settings, compare totals and interval samples, and repeat when variance matters.

## Error Handling

The service raises `JoulescopeMcpError` for expected failures:

- no device found
- multiple devices without explicit `device_path`
- invalid measurement intervals
- too many requested intervals
- statistics timeout

The MCP server maps these to `ToolError` so clients receive tool-level errors rather than crashed server sessions.

## Concurrency

The service opens a short-lived driver connection per MCP tool call and serializes driver access with an in-process reentrant lock. This avoids long-lived subscription leaks, prevents overlapping MCP requests from opening the same physical JS220 at the same time, and makes operations deterministic. Multiple independent server processes can still contend for the same physical device, so deployments should run one server process per JS220.

## Guardrails

Default guardrails are conservative:

- `min_interval_s = 0.0005`
- `max_duration_s = 3600`
- `max_intervals = 10000`
- statistics wait timeout includes a fixed margin

These limits prevent accidental million-row MCP responses or hour-long blocking calls while still supporting practical power profiling.

## Test Strategy

The unit suite uses a fake driver and fake JLS recorder to validate:

- interval integral summing
- mAh and mWh conversions
- non-divisible duration rounding
- multiple-device ambiguity handling
- version formatting
- retained topic and metadata handling
- frontend configuration publishing
- GPI decoding
- query/publish topic resolution
- JLS recorder wiring

Hardware verification should additionally run:

```bash
python -m pyjoulescope_driver scan
python -m pyjoulescope_driver statistics --frequency 2 --duration 1
python - <<'PY'
from joulescope_mcp.service import Js220Service
r = Js220Service().measure_energy(duration_s=2, interval_s=0.5)
print(r["total_charge_mAh"], r["average_current_mA"], [s["charge_mAh"] for s in r["samples"]])
PY
python scripts/hardware_smoke.py --duration-s 2 --interval-s 0.5
```

Expected hardware behavior for the current test target is around 1.1 mA to 80 mA, typically near 1.2 mA average depending on target activity.
