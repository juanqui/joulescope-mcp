from __future__ import annotations

from joulescope_mcp.server import create_server
from joulescope_mcp.service import Js220Service


class MinimalService(Js220Service):
    def __init__(self) -> None:
        pass

    @property
    def driver_version(self) -> str:
        return "test"

    def list_devices(self) -> dict:
        return {"driver_version": "test", "devices": []}


def test_create_server_registers_without_hardware() -> None:
    server = create_server(MinimalService())
    assert server.name == "joulescope-js220"
