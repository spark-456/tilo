"""Fixtures for the whole-stack system tests (see _sys_lib.py). Run: `uv run pytest tests/system -q`."""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest
from _sys_lib import DEV_API_PORT, DEV_API_URL, Server, dev_api_env, free_port, port_in_use


@pytest.fixture(scope="session")
def dev_api() -> Iterator[str]:
    """`tilo-api` in dev mode on its fixed port: the base URL. A dev API already running there (a
    `just dev-api` in another terminal) is used as it is and left running."""
    if port_in_use(DEV_API_PORT):
        spec = httpx.get(f"{DEV_API_URL}/openapi.json", timeout=5).json()
        assert "/intake" in spec["paths"], f"port {DEV_API_PORT} is busy and is not tilo-api"
        yield DEV_API_URL
        return
    server = Server("tilo_api:app", DEV_API_PORT, dev_api_env()).start()
    try:
        yield DEV_API_URL
    finally:
        server.stop()


@pytest.fixture()
def client(dev_api: str) -> Iterator[httpx.Client]:
    with httpx.Client(base_url=dev_api, timeout=30) as c:
        yield c


@pytest.fixture(scope="session")
def prod_api() -> Iterator[Server]:
    """`tilo-api` exactly as its Dockerfile starts it: no dev mode, so no principal, store or writer."""
    server = Server("tilo_api:app", free_port()).start()
    try:
        yield server
    finally:
        server.stop()
