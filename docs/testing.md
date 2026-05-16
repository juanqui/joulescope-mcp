# Testing

## Unit and Static Checks

Run the local software checks:

```bash
python -m ruff check .
python -m pytest
python -m build
```

The unit suite uses fake JouleScope driver and recorder objects. It does not require attached hardware.

## Driver Hardware Checks

Verify that the official driver can see and stream from the JS220:

```bash
python -m pyjoulescope_driver scan
python -m pyjoulescope_driver statistics --frequency 2 --duration 1
```

## MCP Server Smoke Check

Launch through the MCP Python client and call `measure_energy`:

```bash
python - <<'PY'
import anyio
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

async def main():
    params = StdioServerParameters(command=".venv/bin/joulescope-mcp", args=[])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print([tool.name for tool in tools.tools])
            result = await session.call_tool(
                "measure_energy",
                {"duration_s": 1.0, "interval_s": 0.5, "compact": True},
            )
            print(result.content[0].text)

anyio.run(main)
PY
```

## Hardware Smoke Script

Run:

```bash
python scripts/hardware_smoke.py --duration-s 2 --interval-s 0.5
```

The script prints JSON containing:

- device discovery results
- GPI state
- total charge and energy
- average current and power
- compact per-interval charge and energy arrays

Only run one hardware smoke or MCP server process against a JS220 at a time.
