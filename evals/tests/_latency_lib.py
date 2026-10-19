"""Helpers for the NFR-02 / NFR-03 / NFR-05 latency tests (PRD 17.1). Not a conftest (see _evals_lib.py).

The module under test, `tilo_evals.latency`, is imported lazily through `latency()` so that, until it exists, every
test fails on its own with ModuleNotFoundError instead of the whole directory failing at collection.

Pinned interface (the builder implements to this; PRD 17.1 gives the numbers):
- `percentiles(samples) -> {"p50": x, "p95": x, "n": int}`: nearest rank (rank = ceil(p/100 * n), 1-based) on the
  sorted samples; the result is always one of the input values; empty input, a non-finite or negative sample raise
  ValueError, never 0.
- `measure(n) -> {"NFR-02": entry, "NFR-03": entry, "NFR-05": entry}` where entry is
  `{"p50_ms", "p95_ms", "n", "budget": {...}, "scope": "local_overhead_fake_providers", "live": None}` and the NFR-05
  entry also has a `note` that says it stops at client receipt. Samples are milliseconds from `time.perf_counter()`
  (called as the module attribute, so a test can move the clock). `LatencyRefused` (a RuntimeError) when LIVE,
  K_SERVICE or CLOUD_RUN_JOB is set; `LatencyError` (a RuntimeError) when a seam does not answer (a failed sample is
  never timed as a success); ValueError for n < 1.
- Seams, all through the real tilo-api app in process with the dev models file (a deterministic fake Director):
  NFR-02 `POST /intake` (text + 3 files) until its 201 response, whose `brief` holds the chips;
  NFR-03 `POST /intake`, `POST /tasks/{id}/answers` (every question skipped), then `GET /tasks/{id}/approaches` until
  it first returns approaches (the way the web client does);
  NFR-05 an event appended through the dev event writer (`tilo_api.dev.DevEventWriter.append`, the timer starts just
  before the call) until a `GET /worlds/{id}/events` response contains it.
- CLI: `python -m tilo_evals latency --n N [--json]`; `python -m tilo_evals metrics ... [--latency-n N]`.
"""

import importlib
import math
import socket
import time
from collections.abc import Iterator
from typing import Any

import pytest

SCOPE = "local_overhead_fake_providers"
IDS = ("NFR-02", "NFR-03", "NFR-05")
BUDGETS = {  # PRD 17.1, in milliseconds
    "NFR-02": {"p50_ms": 4000},
    "NFR-03": {"p50_ms": 12000, "p95_ms": 25000},
    "NFR-05": {"p95_ms": 1000},
}
REFUSING_ENV = ("LIVE", "K_SERVICE", "CLOUD_RUN_JOB")
ENTRY_KEYS = {"p50_ms", "p95_ms", "n", "budget", "scope", "live"}


def latency() -> Any:
    return importlib.import_module("tilo_evals.latency")


@pytest.fixture(autouse=True)
def _offline_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """No live or deployed switch, no model file chosen for the harness (it picks the dev one itself), and no
    network: a connection attempt or a DNS lookup fails the test (EFF-01, PRD 6.6)."""
    for name in (*REFUSING_ENV, "TILO_MODELS_FILE", "TILO_API_DEV"):
        monkeypatch.delenv(name, raising=False)

    def refuse(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("the latency harness made a network call")

    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)


class Clock:
    """`time.perf_counter()` plus an offset a test bumps at a seam: it stands in for work taking that long without
    sleeping. Only the module attribute `time.perf_counter` moves, so a harness that reads another clock sees no
    injected delay and fails the test that injected it."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.offset_s = 0.0
        real = time.perf_counter
        monkeypatch.setattr(time, "perf_counter", lambda: real() + self.offset_s)

    def add_ms(self, ms: float) -> None:
        self.offset_s += ms / 1000.0


def slow(monkeypatch: pytest.MonkeyPatch, clock: Clock, target: Any, name: str, ms: float) -> None:
    """Wraps `target.name` (a module function or a class method) so each call first advances `clock` by `ms`."""
    original = getattr(target, name)

    def wrapped(*args: Any, **kwargs: Any) -> Any:
        clock.add_ms(ms)
        return original(*args, **kwargs)

    monkeypatch.setattr(target, name, wrapped)


class RequestSpy:
    """Every HTTP request any in-process ASGI app receives, as (method, path), whichever client sent it."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from starlette.applications import Starlette

        self.requests: list[tuple[str, str]] = []
        original = Starlette.__call__
        spy = self

        async def call(app: Any, scope: Any, receive: Any, send: Any) -> None:
            if scope.get("type") == "http":
                spy.requests.append((scope["method"], scope["path"]))
            await original(app, scope, receive, send)

        monkeypatch.setattr(Starlette, "__call__", call)

    def count(self, method: str, path_prefix: str, suffix: str = "") -> int:
        return sum(m == method and p.startswith(path_prefix) and p.endswith(suffix) for m, p in self.requests)


def walk(value: Any, path: str = "") -> Iterator[tuple[str, Any]]:
    """Every (dotted key path, value) in a nested report, keys and leaves."""
    yield path, value
    if isinstance(value, dict):
        for key, inner in value.items():
            yield from walk(inner, f"{path}.{key}" if path else str(key))
    elif isinstance(value, list | tuple):
        for i, inner in enumerate(value):
            yield from walk(inner, f"{path}[{i}]")


def is_finite_number(x: Any) -> bool:
    return isinstance(x, int | float) and not isinstance(x, bool) and math.isfinite(x)
