"""MCP server entry point for JouleScope JS220."""

from __future__ import annotations

import argparse
import json
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations

from . import __version__
from .service import JoulescopeMcpError, Js220Service, compact_samples


def _tool_error(exc: Exception) -> ToolError:
    return ToolError(str(exc))


def create_server(service: Js220Service | None = None) -> FastMCP:
    service = service or Js220Service()
    mcp = FastMCP(
        name="joulescope-js220",
        instructions=(
            "Use this server to inspect connected JouleScope JS220 devices and measure "
            "current, voltage, power, charge, and energy. Prefer measure_energy for "
            "agent power-optimization loops because it returns totals plus interval "
            "samples in SI and battery-friendly units."
        ),
    )

    read_only = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=False)
    config_tool = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True)
    file_write_tool = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False)
    write_tool = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False)

    @mcp.tool(
        title="List JouleScope devices",
        description="List connected JouleScope devices, including JS220 serial and firmware details when available.",
        annotations=read_only,
        structured_output=True,
    )
    def list_devices() -> dict[str, Any]:
        try:
            return service.list_devices()
        except JoulescopeMcpError as exc:
            raise _tool_error(exc) from exc

    @mcp.tool(
        title="Get device info",
        description="Return retained device topics and optional metadata for one JouleScope.",
        annotations=read_only,
        structured_output=True,
    )
    def device_info(device_path: str | None = None, include_metadata: bool = False) -> dict[str, Any]:
        try:
            return service.device_info(device_path=device_path, include_metadata=include_metadata)
        except JoulescopeMcpError as exc:
            raise _tool_error(exc) from exc

    @mcp.tool(
        title="Measure energy over time",
        description=(
            "Measure JS220 charge and energy over duration_s using interval_s accumulation. "
            "Returns total charge/energy plus one sample per interval, including mAh, mWh, and optional voltage arrays."
        ),
        annotations=read_only,
        structured_output=True,
    )
    def measure_energy(
        duration_s: float,
        interval_s: float,
        device_path: str | None = None,
        configure_auto_range: bool = True,
        compact: bool = False,
        include_voltage: bool = False,
    ) -> dict[str, Any]:
        try:
            result = service.measure_energy(
                duration_s=duration_s,
                interval_s=interval_s,
                device_path=device_path,
                configure_auto_range=configure_auto_range,
            )
            if compact:
                result["sample_charge_mAh"] = compact_samples(result["samples"], "charge_mAh")
                result["sample_energy_mWh"] = compact_samples(result["samples"], "energy_mWh")
                if include_voltage:
                    result["sample_voltage_avg_v"] = compact_samples(result["samples"], "voltage.avg")
                    result["sample_voltage_min_v"] = compact_samples(result["samples"], "voltage.min")
                    result["sample_voltage_max_v"] = compact_samples(result["samples"], "voltage.max")
                result["samples"] = []
            return result
        except (JoulescopeMcpError, ValueError) as exc:
            raise _tool_error(exc) from exc

    @mcp.tool(
        title="Capture statistics",
        description="Capture JS220 statistics at frequency_hz for duration_s. This is a frequency-based wrapper around measure_energy.",
        annotations=read_only,
        structured_output=True,
    )
    def capture_statistics(
        duration_s: float = 1.0,
        frequency_hz: float = 2.0,
        device_path: str | None = None,
        configure_auto_range: bool = True,
    ) -> dict[str, Any]:
        try:
            return service.capture_statistics(
                duration_s=duration_s,
                frequency_hz=frequency_hz,
                device_path=device_path,
                configure_auto_range=configure_auto_range,
            )
        except (JoulescopeMcpError, ValueError) as exc:
            raise _tool_error(exc) from exc

    @mcp.tool(
        title="Configure JS220 frontend",
        description="Configure JS220 current and voltage range modes. Use auto for normal agent measurements.",
        annotations=config_tool,
        structured_output=True,
    )
    def configure_frontend(
        device_path: str | None = None,
        current_range_mode: Literal["auto", "manual", "off"] | None = "auto",
        voltage_range_mode: Literal["auto", "manual", "off"] | None = "auto",
        current_range: str | None = None,
        voltage_range: str | None = None,
    ) -> dict[str, Any]:
        try:
            return service.configure_frontend(
                device_path=device_path,
                current_range_mode=current_range_mode,
                voltage_range_mode=voltage_range_mode,
                current_range=current_range,
                voltage_range=voltage_range,
            )
        except JoulescopeMcpError as exc:
            raise _tool_error(exc) from exc

    @mcp.tool(
        title="Get target power status",
        description=(
            "Report whether JS220 target/DUT power is connected. The JS220 controls this by "
            "setting current range mode off or auto/manual."
        ),
        annotations=read_only,
        structured_output=True,
    )
    def target_power_status(device_path: str | None = None) -> dict[str, Any]:
        try:
            return service.target_power_status(device_path=device_path)
        except JoulescopeMcpError as exc:
            raise _tool_error(exc) from exc

    @mcp.tool(
        title="Set target power",
        description=(
            "Connect or disconnect power to the DUT through the JS220 current path. "
            "power_on=false sets current range mode to off; power_on=true restores auto/manual."
        ),
        annotations=write_tool,
        structured_output=True,
    )
    def set_target_power(
        power_on: bool,
        device_path: str | None = None,
        on_mode: Literal["auto", "manual"] = "auto",
        settle_ms: int = 0,
    ) -> dict[str, Any]:
        try:
            return service.set_target_power(
                power_on=power_on,
                device_path=device_path,
                on_mode=on_mode,
                settle_ms=settle_ms,
            )
        except JoulescopeMcpError as exc:
            raise _tool_error(exc) from exc

    @mcp.tool(
        title="Cycle target power",
        description=(
            "Power-cycle the DUT by setting JS220 current range mode off, waiting off_ms, "
            "then restoring auto/manual and optionally waiting settle_ms."
        ),
        annotations=write_tool,
        structured_output=True,
    )
    def cycle_target_power(
        off_ms: int,
        device_path: str | None = None,
        on_mode: Literal["auto", "manual"] = "auto",
        settle_ms: int = 0,
    ) -> dict[str, Any]:
        try:
            return service.cycle_target_power(
                off_ms=off_ms,
                device_path=device_path,
                on_mode=on_mode,
                settle_ms=settle_ms,
            )
        except JoulescopeMcpError as exc:
            raise _tool_error(exc) from exc

    @mcp.tool(
        title="Record JLS",
        description="Record raw JS220 samples to a JLS v2 file for later waveform analysis.",
        annotations=file_write_tool,
        structured_output=True,
    )
    def record_jls(
        output_path: str,
        duration_s: float,
        device_path: str | None = None,
        frequency_hz: int | None = None,
        signals: str = "current,voltage,power",
        note: str | None = None,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        try:
            return service.record_jls(
                output_path=output_path,
                duration_s=duration_s,
                device_path=device_path,
                frequency_hz=frequency_hz,
                signals=signals,
                note=note,
                overwrite=overwrite,
            )
        except JoulescopeMcpError as exc:
            raise _tool_error(exc) from exc

    @mcp.tool(
        title="Read GPI",
        description="Read JS220 general-purpose input pin state as a 32-bit value and decoded pins.",
        annotations=read_only,
        structured_output=True,
    )
    def read_gpi(device_path: str | None = None) -> dict[str, Any]:
        try:
            return service.read_gpi(device_path=device_path)
        except JoulescopeMcpError as exc:
            raise _tool_error(exc) from exc

    @mcp.tool(
        title="List topics",
        description="List retained JouleScope driver topics with current values and optional metadata.",
        annotations=read_only,
        structured_output=True,
    )
    def list_topics(device_path: str | None = None, include_metadata: bool = True) -> dict[str, Any]:
        try:
            return service.list_topics(device_path=device_path, include_metadata=include_metadata)
        except JoulescopeMcpError as exc:
            raise _tool_error(exc) from exc

    @mcp.tool(
        title="Query topic",
        description="Query a JouleScope driver topic. Provide a relative topic such as c/fw/version or an absolute device topic.",
        annotations=read_only,
        structured_output=True,
    )
    def query_topic(topic: str, device_path: str | None = None) -> dict[str, Any]:
        try:
            return service.query_topic(topic=topic, device_path=device_path)
        except JoulescopeMcpError as exc:
            raise _tool_error(exc) from exc

    @mcp.tool(
        title="Publish topic",
        description=(
            "Publish a value to a JouleScope driver topic. This exposes advanced JS220 capabilities; "
            "only use when you know the topic semantics."
        ),
        annotations=write_tool,
        structured_output=True,
    )
    def publish_topic(topic: str, value: Any, device_path: str | None = None) -> dict[str, Any]:
        try:
            return service.publish_topic(topic=topic, value=value, device_path=device_path)
        except JoulescopeMcpError as exc:
            raise _tool_error(exc) from exc

    @mcp.resource(
        "joulescope://devices",
        title="Connected JouleScope devices",
        description="JSON list of connected devices.",
        mime_type="application/json",
    )
    def devices_resource() -> str:
        return json.dumps(service.list_devices(), indent=2)

    @mcp.resource(
        "joulescope://driver",
        title="JouleScope driver",
        description="Driver and server version information.",
        mime_type="application/json",
    )
    def driver_resource() -> str:
        return json.dumps(
            {"server_version": __version__, "pyjoulescope_driver_version": service.driver_version},
            indent=2,
        )

    @mcp.prompt(
        title="Power optimization measurement",
        description="Prompt template for agents iterating on firmware or software power optimization.",
    )
    def power_optimization_session(duration_s: float = 15.0, interval_s: float = 0.5) -> str:
        return (
            "Use the JouleScope JS220 to measure power before and after each change. "
            f"Call measure_energy with duration_s={duration_s} and interval_s={interval_s}. "
            "Compare total_charge_mAh, total_energy_mWh, average_current_mA, and interval samples. "
            "Keep the same duration and interval across experiments, and report measurement variance "
            "when repeated runs differ materially."
        )

    return mcp


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the JouleScope JS220 MCP server.")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default="stdio",
        help="MCP transport to use.",
    )
    parser.add_argument("--mount-path", help="Mount path for streamable HTTP or SSE transports.")
    args = parser.parse_args()
    create_server().run(transport=args.transport, mount_path=args.mount_path)


if __name__ == "__main__":  # pragma: no cover
    main()
