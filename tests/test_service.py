from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from joulescope_mcp.service import JoulescopeMcpError, Js220Service


def stat(index: int, duration_s: float, charge_c: float, energy_j: float) -> dict[str, Any]:
    return {
        "time": {
            "range": {"value": [index * duration_s, (index + 1) * duration_s]},
            "delta": {"value": duration_s},
        },
        "signals": {
            "current": {
                "avg": {"value": charge_c / duration_s},
                "std": {"value": 0.001},
                "min": {"value": 0.0},
                "max": {"value": 0.01},
                "p2p": {"value": 0.01},
                "integral": {"value": charge_c},
            },
            "voltage": {
                "avg": {"value": 3.7},
                "std": {"value": 0.0},
                "min": {"value": 3.69},
                "max": {"value": 3.71},
                "p2p": {"value": 0.02},
            },
            "power": {
                "avg": {"value": energy_j / duration_s},
                "std": {"value": 0.001},
                "min": {"value": 0.0},
                "max": {"value": 0.1},
                "p2p": {"value": 0.1},
                "integral": {"value": energy_j},
            },
        },
        "accumulators": {
            "charge": {"value": 100 + index * charge_c, "units": "C"},
            "energy": {"value": 200 + index * energy_j, "units": "J"},
        },
    }


class FakeDriver:
    def __init__(self, devices: list[str] | None = None, stats: list[dict[str, Any]] | None = None) -> None:
        self.devices = devices or ["u/js220/005920"]
        self.stats = stats or []
        self.published: list[tuple[str, Any]] = []
        self.opened: list[tuple[str, str | None]] = []
        self.closed: list[str] = []
        self.subscriptions: list[tuple[str, str, Any]] = []

    def __enter__(self) -> FakeDriver:
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None

    def device_paths(self) -> list[str]:
        return self.devices

    def open(self, device: str, mode: str | None = None) -> None:
        self.opened.append((device, mode))

    def close(self, device: str) -> None:
        self.closed.append(device)

    def query(self, topic: str) -> Any:
        if topic.endswith("/c/hw/version"):
            return 0x01020003
        if topic.endswith("/c/fw/version"):
            return 0x02010000
        if topic.endswith("/s/fpga/version"):
            return 0x00040005
        return f"value:{topic}"

    def publish(self, topic: str, value: Any) -> None:
        self.published.append((topic, value))
        if topic.endswith("/s/stats/ctrl") and value == 1:
            for sub_topic, _flags, callback in list(self.subscriptions):
                if sub_topic.endswith("/s/stats/value"):
                    for item in self.stats:
                        callback(sub_topic, item)

    def subscribe(self, topic: str, flags: str, callback: Any) -> None:
        self.subscriptions.append((topic, flags, callback))
        if flags == "pub_retain":
            callback(f"{self.devices[0]}/c/fw/version", 0x02010000)
        if flags == "metadata_rsp_retain":
            callback(f"{self.devices[0]}/c/fw/version$", {"format": "version"})

    def unsubscribe(self, topic: str, callback: Any) -> None:
        self.subscriptions = [s for s in self.subscriptions if s[0] != topic or s[2] is not callback]

    def publish_and_wait(self, *_args: Any, **_kwargs: Any) -> int:
        return 0b101


class FakeRecord:
    instances: list[FakeRecord] = []

    def __init__(self, _driver: Any, devices: list[str], signals: str) -> None:
        self.devices = devices
        self.signals = signals
        self.opened: tuple[str, list[Any]] | None = None
        self.closed = False
        FakeRecord.instances.append(self)

    def open(self, path: str, user_data: list[Any] | None = None) -> None:
        Path(path).touch()
        self.opened = (path, user_data or [])

    def close(self) -> None:
        self.closed = True


def service_with(driver: FakeDriver) -> Js220Service:
    return Js220Service(driver_factory=lambda: driver, record_factory=FakeRecord)


def test_measure_energy_returns_totals_and_interval_samples() -> None:
    driver = FakeDriver(stats=[stat(0, 0.5, 0.0018, 0.006), stat(1, 0.5, 0.0036, 0.012)])
    result = service_with(driver).measure_energy(duration_s=1.0, interval_s=0.5)

    assert result["device_path"] == "u/js220/005920"
    assert result["interval_count"] == 2
    assert result["actual_duration_s"] == pytest.approx(1.0)
    assert result["actual_interval_s"] == pytest.approx(0.5)
    assert result["total_charge_c"] == pytest.approx(0.0054)
    assert result["total_charge_mAh"] == pytest.approx(0.0015)
    assert result["total_energy_j"] == pytest.approx(0.018)
    assert result["total_energy_mWh"] == pytest.approx(0.005)
    assert [sample["charge_mAh"] for sample in result["samples"]] == pytest.approx([0.0005, 0.001])
    assert [sample["relative_start_s"] for sample in result["samples"]] == pytest.approx([0.0, 0.5])
    assert [sample["relative_end_s"] for sample in result["samples"]] == pytest.approx([0.5, 1.0])
    assert ("/s/stats/ctrl", 0) not in driver.published
    assert ("u/js220/005920/s/stats/ctrl", 0) in driver.published


def test_measure_energy_rounds_up_non_divisible_duration() -> None:
    driver = FakeDriver(stats=[stat(0, 0.5, 0.001, 0.004), stat(1, 0.5, 0.001, 0.004)])
    result = service_with(driver).measure_energy(duration_s=0.75, interval_s=0.5)
    assert result["interval_count"] == 2
    assert result["actual_duration_s"] == pytest.approx(1.0)


def test_measure_energy_rejects_too_many_intervals() -> None:
    driver = FakeDriver(stats=[])
    with pytest.raises(JoulescopeMcpError, match="exceeds max_intervals"):
        service_with(driver).measure_energy(duration_s=10, interval_s=0.001, max_intervals=5)


def test_select_device_requires_explicit_path_for_multiple_devices() -> None:
    driver = FakeDriver(devices=["u/js220/1", "u/js220/2"])
    with pytest.raises(JoulescopeMcpError, match="Multiple JouleScope"):
        service_with(driver).measure_energy(duration_s=1, interval_s=0.5)


def test_list_devices_includes_versions() -> None:
    result = service_with(FakeDriver()).list_devices()
    assert result["devices"][0]["hardware_version"] == "1.2.3"
    assert result["devices"][0]["firmware_version"] == "2.1.0"
    assert result["devices"][0]["fpga_version"] == "0.4.5"


def test_device_info_strips_device_prefix_and_metadata_suffix() -> None:
    result = service_with(FakeDriver()).device_info(include_metadata=True)
    assert result["values"] == {"c/fw/version": 0x02010000}
    assert result["metadata"] == {"c/fw/version": {"format": "version"}}


def test_configure_frontend_publishes_expected_topics() -> None:
    driver = FakeDriver()
    result = service_with(driver).configure_frontend(current_range_mode="auto", voltage_range_mode="auto")
    assert result["published"] == [
        {"topic": "u/js220/005920/s/i/range/mode", "value": "auto"},
        {"topic": "u/js220/005920/s/v/range/mode", "value": "auto"},
    ]


def test_read_gpi_decodes_pin_mask() -> None:
    result = service_with(FakeDriver()).read_gpi()
    assert result["gpi_hex"] == "0x00000005"
    assert result["pins"]["0"] is True
    assert result["pins"]["1"] is False
    assert result["pins"]["2"] is True


def test_query_and_publish_topics_accept_relative_topics() -> None:
    driver = FakeDriver()
    svc = service_with(driver)
    assert svc.query_topic("c/fw/version")["topic"] == "u/js220/005920/c/fw/version"
    assert svc.publish_topic("s/led/en", 0)["topic"] == "u/js220/005920/s/led/en"
    assert ("u/js220/005920/s/led/en", 0) in driver.published


def test_record_jls_uses_record_factory(tmp_path: Path) -> None:
    FakeRecord.instances.clear()
    output = tmp_path / "capture.jls"
    result = service_with(FakeDriver()).record_jls(str(output), duration_s=0.01, note="unit test")
    assert output.exists()
    assert result["output_path"] == str(output.resolve())
    assert FakeRecord.instances[-1].signals == "current,voltage,power"
    assert FakeRecord.instances[-1].closed is True


def test_record_jls_rejects_existing_path_without_overwrite(tmp_path: Path) -> None:
    output = tmp_path / "capture.jls"
    output.touch()
    with pytest.raises(JoulescopeMcpError, match="already exists"):
        service_with(FakeDriver()).record_jls(str(output), duration_s=0.01)
