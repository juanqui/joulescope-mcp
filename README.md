# JouleScope JS220 MCP Server

`joulescope-mcp` is a Model Context Protocol (MCP) server for the JouleScope JS220 precision energy analyzer. It exposes agent-friendly tools for measuring current, voltage, power, charge, and energy, plus lower-level access to the JouleScope driver PubSub topic tree.

The primary tool is `measure_energy`: provide a duration and accumulation interval, and it returns total charge and energy plus one sample per interval. For example, `duration_s=15` and `interval_s=0.5` returns 30 interval samples along with totals such as `total_charge_mAh`.

## Status

This project is early but functional. It targets the JS220 through the current `pyjoulescope_driver` package and uses the official Python MCP SDK.

## Requirements

- Python 3.11 or newer
- JouleScope JS220 connected over USB
- `pyjoulescope_driver>=2.1.0`
- `pyjls>=0.17` for `record_jls`
- An MCP client that can run stdio servers

On Linux, configure JouleScope udev rules as documented by JouleScope before running the server.

## Install

From this repository:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[dev]'
```

Verify that the driver can see the JS220:

```bash
.venv/bin/python -m pyjoulescope_driver scan
.venv/bin/python -m pyjoulescope_driver statistics --frequency 2 --duration 1
```

## Run

For MCP over stdio:

```bash
.venv/bin/joulescope-mcp
```

For streamable HTTP:

```bash
.venv/bin/joulescope-mcp --transport streamable-http --mount-path /mcp
```

Example MCP client command configuration:

```json
{
  "mcpServers": {
    "joulescope-js220": {
      "command": "/path/to/joulescope-mcp/.venv/bin/joulescope-mcp",
      "args": []
    }
  }
}
```

## Agent Workflow

For firmware or application power optimization, keep the measurement setup stable:

1. Run a baseline measurement with `measure_energy`.
2. Apply one firmware or software change.
3. Run the same `measure_energy` duration and interval again.
4. Compare `total_charge_mAh`, `total_energy_mWh`, `average_current_mA`, and the interval samples.
5. Repeat the measurement when differences are close to normal run-to-run variance.

Example request:

```json
{
  "duration_s": 15,
  "interval_s": 0.5,
  "compact": true
}
```

The response includes:

- `total_charge_mAh`: total charge over the measurement window
- `total_energy_mWh`: total energy over the measurement window
- `average_current_mA`: average current over the actual captured duration
- `average_power_mW`: average power over the actual captured duration
- `actual_interval_s`: average actual interval captured by the JS220
- `sample_charge_mAh`: compact per-interval charge list when `compact=true`
- `sample_energy_mWh`: compact per-interval energy list when `compact=true`
- `samples`: full per-interval statistics when `compact=false`

If `duration_s` is not an exact multiple of `interval_s`, the server rounds up to the next full interval and reports both `requested_duration_s` and `actual_duration_s`.

## Tools

### `list_devices`

Lists connected JouleScope devices. For JS220 devices, it attempts to include hardware, firmware, and FPGA versions.

### `device_info`

Returns retained driver topic values for a selected device. Set `include_metadata=true` to include topic metadata returned by the driver.

### `measure_energy`

Measures charge and energy using JS220 sensor-side statistics.

Parameters:

- `duration_s`: requested measurement duration in seconds
- `interval_s`: accumulation interval in seconds
- `device_path`: optional explicit device path, such as `u/js220/005920`
- `configure_auto_range`: defaults to true; configures current and voltage range modes to `auto`
- `compact`: returns compact charge and energy arrays and omits full samples

Implementation detail: the JS220 publishes per-interval `current.integral` in coulombs and `power.integral` in joules. The server sums those integrals, then also converts charge to mAh and energy to mWh.

### `capture_statistics`

Frequency-based wrapper around `measure_energy`. Use when you want `frequency_hz` instead of `interval_s`.

### `configure_frontend`

Sets current and voltage range modes and optional range selections. Use `auto` for normal measurements.

### `record_jls`

Records raw samples to a JLS v2 file using the JouleScope driver's `Record` API. This is useful for later waveform analysis in the JouleScope UI or JLS tooling. Existing files are rejected unless `overwrite=true`.

### `read_gpi`

Reads JS220 general-purpose input state and returns a 32-bit value plus decoded pins.

### `list_topics`

Lists retained driver topics, values, and optional metadata. This is the discovery tool for advanced JS220 capabilities.

### `query_topic`

Queries one driver topic. Relative topics are resolved under the selected device, so `c/fw/version` becomes `u/js220/<serial>/c/fw/version`.

### `publish_topic`

Publishes a value to a driver topic. This exposes advanced JS220 features and can change device behavior. Prefer typed tools when available.

## Resources and Prompts

Resources:

- `joulescope://devices`: JSON device list
- `joulescope://driver`: server and driver version information

Prompt:

- `power_optimization_session`: template for measurement-driven power optimization loops

## Safety and Limits

The server opens a short-lived JouleScope driver connection per tool call and serializes device access inside one server process. Blocking measurements have guardrails:

- Minimum interval: 0.5 ms
- Maximum duration: 3600 seconds
- Maximum returned intervals: 10,000
- Statistics collection times out if the JS220 does not publish the expected samples

`publish_topic` is intentionally marked as a write/destructive-capable MCP tool because arbitrary topics can alter hardware behavior. Agents should use it only when they know the driver topic semantics.

## Development

Run tests:

```bash
.venv/bin/python -m pytest
```

Run linting:

```bash
.venv/bin/python -m ruff check .
```

Build the package:

```bash
.venv/bin/python -m build
```

Hardware smoke test:

```bash
.venv/bin/python -m pyjoulescope_driver scan
.venv/bin/python -m pyjoulescope_driver statistics --frequency 2 --duration 1
.venv/bin/python - <<'PY'
from joulescope_mcp.service import Js220Service
r = Js220Service().measure_energy(duration_s=2, interval_s=0.5)
print(r["total_charge_mAh"], r["average_current_mA"], [s["charge_mAh"] for s in r["samples"]])
PY
```

Repeatable hardware smoke script:

```bash
.venv/bin/python scripts/hardware_smoke.py --duration-s 2 --interval-s 0.5
```

## Design

See [docs/design.md](docs/design.md) for the MCP design, measurement semantics, tool rationale, and verification strategy.
See [docs/testing.md](docs/testing.md) for repeatable software, MCP, and hardware checks.
See [docs/adversarial-reviews.md](docs/adversarial-reviews.md) for the initial five-pass review log.

## References

- JouleScope downloads and documentation: <https://www.joulescope.com/pages/downloads>
- JouleScope driver documentation: <https://joulescope-driver.readthedocs.io/>
- JouleScope driver source: <https://github.com/jetperch/joulescope_driver>
- MCP Python SDK: <https://github.com/modelcontextprotocol/python-sdk>

## License

Apache License 2.0. See [LICENSE](LICENSE).
