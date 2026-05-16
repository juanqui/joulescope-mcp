#!/usr/bin/env python3
"""Hardware smoke test for a connected JouleScope JS220."""

from __future__ import annotations

import argparse
import json
from typing import Any

from joulescope_mcp.service import Js220Service


def summarize_measurement(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "device_path": result["device_path"],
        "requested_duration_s": result["requested_duration_s"],
        "requested_interval_s": result["requested_interval_s"],
        "actual_duration_s": result["actual_duration_s"],
        "actual_interval_s": result["actual_interval_s"],
        "interval_count": result["interval_count"],
        "total_charge_mAh": result["total_charge_mAh"],
        "total_energy_mWh": result["total_energy_mWh"],
        "average_current_mA": result["average_current_mA"],
        "average_power_mW": result["average_power_mW"],
        "sample_charge_mAh": [sample["charge_mAh"] for sample in result["samples"]],
        "sample_energy_mWh": [sample["energy_mWh"] for sample in result["samples"]],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration-s", type=float, default=2.0)
    parser.add_argument("--interval-s", type=float, default=0.5)
    parser.add_argument("--device-path")
    args = parser.parse_args()

    service = Js220Service()
    payload = {
        "devices": service.list_devices(),
        "gpi": service.read_gpi(device_path=args.device_path),
        "measurement": summarize_measurement(
            service.measure_energy(
                duration_s=args.duration_s,
                interval_s=args.interval_s,
                device_path=args.device_path,
            )
        ),
    }
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
