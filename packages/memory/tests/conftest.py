"""Pytest wiring for packages/memory acceptance tests (FR-MEM-01, FR-MEM-02). Helpers live in
`_memory_testlib.py` (see its docstring). This file imports nothing from `tilo_memory`, so it always
collects and the missing package shows up per test module. It blocks the network for every test (EFF-01):
fakes only, loopback allowed."""

from __future__ import annotations

import socket
from typing import Any

import pytest


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    real_connect = socket.socket.connect

    def guarded(self: socket.socket, address: Any, *args: Any, **kwargs: Any) -> Any:
        host = address[0] if isinstance(address, tuple) else address
        if host not in {"127.0.0.1", "::1", "localhost"}:
            raise RuntimeError(f"packages/memory tests must not use the network (EFF-01): blocked {address!r}")
        return real_connect(self, address, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", guarded)
