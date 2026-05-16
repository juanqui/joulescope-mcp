"""JouleScope JS220 driver service used by the MCP server."""

from __future__ import annotations

import math
import queue
import threading
import time
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:  # pragma: no cover - exercised by integration tests with real hardware
    from pyjoulescope_driver import Driver, Record
    from pyjoulescope_driver import __version__ as DRIVER_VERSION
except Exception:  # pragma: no cover - keeps import errors actionable at tool call time
    Driver = None  # type: ignore[assignment]
    Record = None  # type: ignore[assignment]
    DRIVER_VERSION = "unavailable"


class JoulescopeMcpError(RuntimeError):
    """Raised for expected user-facing JouleScope MCP failures."""


DriverFactory = Callable[[], Any]
RecordFactory = Callable[[Any, list[str], str], Any]


@dataclass(frozen=True)
class MeasurementLimits:
    """Safety limits for blocking agent-facing measurements."""

    min_interval_s: float = 0.0005
    max_duration_s: float = 3600.0
    max_intervals: int = 10_000
    queue_timeout_margin_s: float = 5.0


def _default_driver_factory() -> Any:
    if Driver is None:
        raise JoulescopeMcpError("pyjoulescope_driver is not installed or could not be imported")
    return Driver()


def _default_record_factory(driver: Any, devices: list[str], signals: str) -> Any:
    if Record is None:
        raise JoulescopeMcpError("pyjoulescope_driver.Record is not available")
    return Record(driver, devices, signals)


def _version_to_str(version: Any) -> str:
    if isinstance(version, str):
        return version
    if not isinstance(version, int):
        return str(version)
    v_patch = version & 0xFFFF
    v_minor = (version >> 16) & 0xFF
    v_major = (version >> 24) & 0xFF
    return f"{v_major}.{v_minor}.{v_patch}"


def _jsonable(value: Any) -> Any:
    """Convert common driver/numpy values into JSON-serializable values."""

    if hasattr(value, "item"):
        return value.item()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, bytes):
        return value.hex()
    return value


def _stat_value(stat: dict[str, Any], signal: str, field: str, default: float = 0.0) -> float:
    return float(stat.get("signals", {}).get(signal, {}).get(field, {}).get("value", default))


def _stat_integral(stat: dict[str, Any], signal: str) -> float:
    return _stat_value(stat, signal, "integral")


def _stat_delta(stat: dict[str, Any]) -> float:
    return float(stat.get("time", {}).get("delta", {}).get("value", 0.0))


class Js220Service:
    """High-level API around the JouleScope driver.

    The service opens a short-lived driver connection per operation. This avoids
    leaking subscriptions across MCP tool calls and keeps blocking measurements
    deterministic for agents.
    """

    def __init__(
        self,
        driver_factory: DriverFactory | None = None,
        record_factory: RecordFactory | None = None,
        limits: MeasurementLimits | None = None,
    ) -> None:
        self._driver_factory = driver_factory or _default_driver_factory
        self._record_factory = record_factory or _default_record_factory
        self._limits = limits or MeasurementLimits()
        self._lock = threading.RLock()

    @property
    def driver_version(self) -> str:
        return DRIVER_VERSION

    def _open_driver(self) -> Any:
        return self._driver_factory()

    @contextmanager
    def _driver_session(self) -> Iterator[Any]:
        with self._lock, self._open_driver() as driver:
            yield driver

    def _select_device(self, driver: Any, device_path: str | None = None, require_js220: bool = True) -> str:
        devices = list(driver.device_paths())
        if device_path:
            if device_path not in devices:
                raise JoulescopeMcpError(f"Device not found: {device_path}")
            if require_js220 and "/js220/" not in device_path:
                raise JoulescopeMcpError(f"Device is not a JS220: {device_path}")
            return device_path

        candidates = [d for d in devices if (not require_js220 or "/js220/" in d)]
        if not candidates:
            kind = "JS220 " if require_js220 else ""
            raise JoulescopeMcpError(f"No connected {kind}JouleScope devices found")
        if len(candidates) > 1:
            raise JoulescopeMcpError(
                "Multiple JouleScope devices found. Provide device_path explicitly: "
                + ", ".join(candidates)
            )
        return candidates[0]

    def list_devices(self) -> dict[str, Any]:
        with self._driver_session() as driver:
            devices = []
            for device_path in list(driver.device_paths()):
                item: dict[str, Any] = {
                    "path": device_path,
                    "model": "js220" if "/js220/" in device_path else "unknown",
                    "serial_number": device_path.rstrip("/").split("/")[-1],
                    "available": True,
                }
                try:
                    driver.open(device_path, mode="restore")
                    if "/js220/" in device_path:
                        item["hardware_version"] = _version_to_str(driver.query(f"{device_path}/c/hw/version"))
                        item["firmware_version"] = _version_to_str(driver.query(f"{device_path}/c/fw/version"))
                        item["fpga_version"] = _version_to_str(driver.query(f"{device_path}/s/fpga/version"))
                except Exception as exc:
                    item["available"] = False
                    item["error"] = str(exc)
                finally:
                    with suppress(Exception):
                        driver.close(device_path)
                devices.append(item)
            return {"driver_version": self.driver_version, "devices": devices}

    def device_info(self, device_path: str | None = None, include_metadata: bool = False) -> dict[str, Any]:
        values: dict[str, Any] = {}
        metadata: dict[str, Any] = {}

        def on_pub(topic: str, value: Any) -> None:
            values[topic] = _jsonable(value)

        def on_metadata(topic: str, value: Any) -> None:
            metadata[topic[:-1] if topic.endswith("$") else topic] = _jsonable(value)

        with self._driver_session() as driver:
            device = self._select_device(driver, device_path=device_path, require_js220=False)
            driver.open(device, mode="restore")
            try:
                driver.subscribe(device, "pub_retain", on_pub)
                driver.unsubscribe(device, on_pub)
                if include_metadata:
                    driver.subscribe(device, "metadata_rsp_retain", on_metadata)
                    driver.unsubscribe(device, on_metadata)
            finally:
                driver.close(device)

        def strip_prefix(items: dict[str, Any]) -> dict[str, Any]:
            prefix = device + "/"
            return {k[len(prefix) :] if k.startswith(prefix) else k: v for k, v in sorted(items.items())}

        return {
            "device_path": device,
            "values": strip_prefix(values),
            "metadata": strip_prefix(metadata) if include_metadata else None,
        }

    def configure_frontend(
        self,
        device_path: str | None = None,
        current_range_mode: str | None = "auto",
        voltage_range_mode: str | None = "auto",
        current_range: str | None = None,
        voltage_range: str | None = None,
    ) -> dict[str, Any]:
        allowed_mode = {"auto", "manual", "off"}
        if current_range_mode is not None and current_range_mode not in allowed_mode:
            raise JoulescopeMcpError(f"current_range_mode must be one of {sorted(allowed_mode)}")
        if voltage_range_mode is not None and voltage_range_mode not in allowed_mode:
            raise JoulescopeMcpError(f"voltage_range_mode must be one of {sorted(allowed_mode)}")

        published: list[dict[str, Any]] = []
        with self._driver_session() as driver:
            device = self._select_device(driver, device_path=device_path)
            driver.open(device, mode="restore")
            try:
                commands: list[tuple[str, Any]] = []
                if current_range_mode is not None:
                    commands.append((f"{device}/s/i/range/mode", current_range_mode))
                if voltage_range_mode is not None:
                    commands.append((f"{device}/s/v/range/mode", voltage_range_mode))
                if current_range is not None:
                    commands.append((f"{device}/s/i/range/select", current_range))
                if voltage_range is not None:
                    commands.append((f"{device}/s/v/range/select", voltage_range))
                for topic, value in commands:
                    driver.publish(topic, value)
                    published.append({"topic": topic, "value": value})
            finally:
                driver.close(device)
        return {"device_path": device, "published": published}

    def measure_energy(
        self,
        duration_s: float,
        interval_s: float,
        device_path: str | None = None,
        configure_auto_range: bool = True,
        max_intervals: int | None = None,
    ) -> dict[str, Any]:
        duration_s = float(duration_s)
        interval_s = float(interval_s)
        if duration_s <= 0:
            raise JoulescopeMcpError("duration_s must be greater than 0")
        if interval_s < self._limits.min_interval_s:
            raise JoulescopeMcpError(f"interval_s must be at least {self._limits.min_interval_s}")
        if duration_s > self._limits.max_duration_s:
            raise JoulescopeMcpError(f"duration_s must be <= {self._limits.max_duration_s}")
        if interval_s > duration_s:
            raise JoulescopeMcpError("interval_s must be <= duration_s")

        sample_count = max(1, math.ceil((duration_s - 1e-12) / interval_s))
        max_allowed = self._limits.max_intervals if max_intervals is None else int(max_intervals)
        if sample_count > max_allowed:
            raise JoulescopeMcpError(
                f"Requested {sample_count} intervals, which exceeds max_intervals={max_allowed}"
            )
        scnt = max(1, int(round(1_000_000 * interval_s)))
        requested_duration_s = duration_s

        stats_queue: queue.Queue[dict[str, Any]] = queue.Queue()

        def on_statistics_value(_topic: str, value: dict[str, Any]) -> None:
            stats_queue.put(_jsonable(value))

        stats: list[dict[str, Any]] = []
        with self._driver_session() as driver:
            device = self._select_device(driver, device_path=device_path)
            driver.open(device, mode="restore")
            subscribed = False
            try:
                if configure_auto_range:
                    driver.publish(f"{device}/s/i/range/mode", "auto")
                    driver.publish(f"{device}/s/v/range/mode", "auto")
                driver.publish(f"{device}/s/stats/scnt", scnt)
                driver.subscribe(f"{device}/s/stats/value", "pub", on_statistics_value)
                subscribed = True
                driver.publish(f"{device}/s/stats/ctrl", 1)

                deadline = time.monotonic() + sample_count * interval_s + self._limits.queue_timeout_margin_s
                while len(stats) < sample_count:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise JoulescopeMcpError(
                            f"Timed out waiting for JS220 statistics: got {len(stats)} of {sample_count}"
                        )
                    stats.append(stats_queue.get(timeout=min(max(remaining, 0.001), interval_s + 1.0)))
            finally:
                with suppress(Exception):
                    driver.publish(f"{device}/s/stats/ctrl", 0)
                if subscribed:
                    with suppress(Exception):
                        driver.unsubscribe(f"{device}/s/stats/value", on_statistics_value)
                driver.close(device)

        samples = [self._measurement_sample(idx, stat) for idx, stat in enumerate(stats)]
        elapsed_s = 0.0
        for sample in samples:
            sample["relative_start_s"] = elapsed_s
            elapsed_s += sample["duration_s"]
            sample["relative_end_s"] = elapsed_s
        total_charge_c = sum(sample["charge_c"] for sample in samples)
        total_energy_j = sum(sample["energy_j"] for sample in samples)
        actual_duration_s = sum(sample["duration_s"] for sample in samples)
        avg_current_a = total_charge_c / actual_duration_s if actual_duration_s else 0.0
        avg_power_w = total_energy_j / actual_duration_s if actual_duration_s else 0.0
        voltage_avg_v = (
            sum(sample["voltage"]["avg"] * sample["duration_s"] for sample in samples) / actual_duration_s
            if actual_duration_s
            else 0.0
        )
        voltage_min_v = min((sample["voltage"]["min"] for sample in samples), default=0.0)
        voltage_max_v = max((sample["voltage"]["max"] for sample in samples), default=0.0)

        return {
            "device_path": device,
            "requested_duration_s": requested_duration_s,
            "requested_interval_s": interval_s,
            "actual_duration_s": actual_duration_s,
            "actual_interval_s": actual_duration_s / len(samples) if samples else 0.0,
            "interval_count": len(samples),
            "stats_sample_count": scnt,
            "total_charge_c": total_charge_c,
            "total_charge_mAh": total_charge_c / 3.6,
            "total_energy_j": total_energy_j,
            "total_energy_mWh": total_energy_j / 3.6,
            "average_current_a": avg_current_a,
            "average_current_mA": avg_current_a * 1000.0,
            "average_power_w": avg_power_w,
            "average_power_mW": avg_power_w * 1000.0,
            "average_voltage_v": voltage_avg_v,
            "voltage_min_v": voltage_min_v,
            "voltage_max_v": voltage_max_v,
            "samples": samples,
        }

    def _measurement_sample(self, index: int, stat: dict[str, Any]) -> dict[str, Any]:
        duration = _stat_delta(stat)
        current_integral_c = _stat_integral(stat, "current")
        power_integral_j = _stat_integral(stat, "power")
        time_info = stat.get("time", {})
        return {
            "index": index,
            "start_s": float(time_info.get("range", {}).get("value", [index * duration, 0])[0]),
            "end_s": float(time_info.get("range", {}).get("value", [0, (index + 1) * duration])[1]),
            "duration_s": duration,
            "charge_c": current_integral_c,
            "charge_mAh": current_integral_c / 3.6,
            "energy_j": power_integral_j,
            "energy_mWh": power_integral_j / 3.6,
            "current": self._signal_summary(stat, "current"),
            "voltage": self._signal_summary(stat, "voltage"),
            "power": self._signal_summary(stat, "power"),
            "accumulators": stat.get("accumulators", {}),
        }

    def _signal_summary(self, stat: dict[str, Any], signal: str) -> dict[str, float]:
        fields = ["avg", "std", "min", "max", "p2p"]
        result = {field: _stat_value(stat, signal, field) for field in fields}
        if signal in {"current", "power"}:
            result["integral"] = _stat_integral(stat, signal)
        return result

    def capture_statistics(
        self,
        duration_s: float = 1.0,
        frequency_hz: float = 2.0,
        device_path: str | None = None,
        configure_auto_range: bool = True,
    ) -> dict[str, Any]:
        if frequency_hz <= 0:
            raise JoulescopeMcpError("frequency_hz must be greater than 0")
        interval_s = 1.0 / float(frequency_hz)
        return self.measure_energy(
            duration_s=duration_s,
            interval_s=interval_s,
            device_path=device_path,
            configure_auto_range=configure_auto_range,
        )

    def target_power_status(self, device_path: str | None = None) -> dict[str, Any]:
        with self._driver_session() as driver:
            device = self._select_device(driver, device_path=device_path)
            topic = f"{device}/s/i/range/mode"
            driver.open(device, mode="restore")
            try:
                mode = driver.query(topic)
            finally:
                driver.close(device)
        mode_name = self._current_range_mode_name(mode)
        return {
            "device_path": device,
            "power_on": mode_name != "off",
            "current_range_mode": mode_name,
            "raw_current_range_mode": mode,
            "control_topic": topic,
        }

    def set_target_power(
        self,
        power_on: bool,
        device_path: str | None = None,
        on_mode: str = "auto",
        settle_ms: int = 0,
    ) -> dict[str, Any]:
        if on_mode not in {"auto", "manual"}:
            raise JoulescopeMcpError("on_mode must be 'auto' or 'manual'")
        settle_ms = self._validate_ms(settle_ms, "settle_ms", max_ms=60_000)
        target_mode = on_mode if power_on else "off"
        with self._driver_session() as driver:
            device = self._select_device(driver, device_path=device_path)
            topic = f"{device}/s/i/range/mode"
            driver.open(device, mode="restore")
            try:
                before_raw = driver.query(topic)
                driver.publish(topic, target_mode)
                if settle_ms:
                    time.sleep(settle_ms / 1000.0)
                after_raw = driver.query(topic)
            finally:
                driver.close(device)
        return {
            "device_path": device,
            "power_on": self._current_range_mode_name(after_raw) != "off",
            "requested_power_on": bool(power_on),
            "before_current_range_mode": self._current_range_mode_name(before_raw),
            "after_current_range_mode": self._current_range_mode_name(after_raw),
            "raw_before_current_range_mode": before_raw,
            "raw_after_current_range_mode": after_raw,
            "settle_ms": settle_ms,
            "control_topic": topic,
        }

    def cycle_target_power(
        self,
        off_ms: int,
        device_path: str | None = None,
        on_mode: str = "auto",
        settle_ms: int = 0,
    ) -> dict[str, Any]:
        off_ms = self._validate_ms(off_ms, "off_ms", max_ms=3_600_000)
        settle_ms = self._validate_ms(settle_ms, "settle_ms", max_ms=3_600_000)
        if on_mode not in {"auto", "manual"}:
            raise JoulescopeMcpError("on_mode must be 'auto' or 'manual'")
        with self._driver_session() as driver:
            device = self._select_device(driver, device_path=device_path)
            topic = f"{device}/s/i/range/mode"
            driver.open(device, mode="restore")
            try:
                before_raw = driver.query(topic)
                driver.publish(topic, "off")
                if off_ms:
                    time.sleep(off_ms / 1000.0)
                off_raw = driver.query(topic)
                driver.publish(topic, on_mode)
                if settle_ms:
                    time.sleep(settle_ms / 1000.0)
                after_raw = driver.query(topic)
            finally:
                driver.close(device)
        return {
            "device_path": device,
            "power_on": self._current_range_mode_name(after_raw) != "off",
            "before_current_range_mode": self._current_range_mode_name(before_raw),
            "off_current_range_mode": self._current_range_mode_name(off_raw),
            "after_current_range_mode": self._current_range_mode_name(after_raw),
            "raw_before_current_range_mode": before_raw,
            "raw_off_current_range_mode": off_raw,
            "raw_after_current_range_mode": after_raw,
            "off_ms": off_ms,
            "settle_ms": settle_ms,
            "control_topic": topic,
        }

    def _current_range_mode_name(self, mode: Any) -> str:
        if isinstance(mode, str):
            return mode
        return {
            0: "off",
            4: "auto",
            5: "manual",
            6: "test_dir",
            7: "test_seq",
        }.get(int(mode), str(mode))

    def _validate_ms(self, value: int, name: str, max_ms: int) -> int:
        value = int(value)
        if value < 0:
            raise JoulescopeMcpError(f"{name} must be >= 0")
        if value > max_ms:
            raise JoulescopeMcpError(f"{name} must be <= {max_ms}")
        return value

    def record_jls(
        self,
        output_path: str,
        duration_s: float,
        device_path: str | None = None,
        frequency_hz: int | None = None,
        signals: str = "current,voltage,power",
        note: str | None = None,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        if duration_s <= 0:
            raise JoulescopeMcpError("duration_s must be greater than 0")
        if duration_s > self._limits.max_duration_s:
            raise JoulescopeMcpError(f"duration_s must be <= {self._limits.max_duration_s}")
        path = Path(output_path).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and not overwrite:
            raise JoulescopeMcpError(f"Output path already exists. Set overwrite=true to replace: {path}")

        with self._driver_session() as driver:
            device = self._select_device(driver, device_path=device_path)
            driver.open(device, mode="defaults")
            writer = None
            try:
                if frequency_hz is not None:
                    driver.publish(f"{device}/h/fs", int(frequency_hz))
                driver.publish(f"{device}/s/i/range/mode", "auto")
                driver.publish(f"{device}/s/v/range/mode", "auto")
                writer = self._record_factory(driver, [device], signals)
                user_data = [] if note is None else [[0, note]]
                writer.open(str(path), user_data=user_data)
                stop_at = time.monotonic() + float(duration_s)
                while time.monotonic() < stop_at:
                    time.sleep(min(0.05, stop_at - time.monotonic()))
            finally:
                if writer is not None:
                    writer.close()
                driver.close(device)
        return {
            "device_path": device,
            "output_path": str(path),
            "duration_s": float(duration_s),
            "signals": signals,
            "frequency_hz": frequency_hz,
            "overwrite": overwrite,
        }

    def read_gpi(self, device_path: str | None = None) -> dict[str, Any]:
        with self._driver_session() as driver:
            device = self._select_device(driver, device_path=device_path)
            driver.open(device, mode="restore")
            try:
                value = driver.publish_and_wait(
                    f"{device}/s/gpi/+/!req",
                    0,
                    f"{device}/s/gpi/+/!value",
                    timeout=1.0,
                )
            finally:
                driver.close(device)
        return {
            "device_path": device,
            "gpi_value": int(value),
            "gpi_hex": f"0x{int(value):08x}",
            "pins": {str(i): bool(int(value) & (1 << i)) for i in range(32)},
        }

    def query_topic(self, topic: str, device_path: str | None = None) -> dict[str, Any]:
        with self._driver_session() as driver:
            device = self._select_device(driver, device_path=device_path, require_js220=False)
            full_topic = self._full_topic(device, topic)
            driver.open(device, mode="restore")
            try:
                value = driver.query(full_topic)
            finally:
                driver.close(device)
        return {"device_path": device, "topic": full_topic, "value": _jsonable(value)}

    def publish_topic(self, topic: str, value: Any, device_path: str | None = None) -> dict[str, Any]:
        with self._driver_session() as driver:
            device = self._select_device(driver, device_path=device_path, require_js220=False)
            full_topic = self._full_topic(device, topic)
            driver.open(device, mode="restore")
            try:
                driver.publish(full_topic, value)
            finally:
                driver.close(device)
        return {"device_path": device, "topic": full_topic, "value": _jsonable(value)}

    def list_topics(self, device_path: str | None = None, include_metadata: bool = True) -> dict[str, Any]:
        info = self.device_info(device_path=device_path, include_metadata=include_metadata)
        topics = []
        values = info["values"]
        metadata = info.get("metadata") or {}
        for topic, value in values.items():
            item = {"topic": topic, "value": value}
            if include_metadata and topic in metadata:
                item["metadata"] = metadata[topic]
            topics.append(item)
        return {"device_path": info["device_path"], "topics": topics}

    def _full_topic(self, device: str, topic: str) -> str:
        topic = topic.strip()
        if not topic:
            raise JoulescopeMcpError("topic must not be empty")
        if topic.startswith(device + "/"):
            return topic
        if (
            topic.startswith(("u/", "s/", "c/", "h/"))
            and not topic.startswith(device)
            and topic.startswith(("u/js", "s/js"))
        ):
            return topic
        return f"{device}/{topic.lstrip('/')}"


def compact_samples(samples: Iterable[dict[str, Any]], field: str = "charge_mAh") -> list[float]:
    """Return only one numeric field from measurement samples."""

    result = []
    path = field.split(".")
    for sample in samples:
        value: Any = sample
        for key in path:
            value = value[key]
        result.append(float(value))
    return result
