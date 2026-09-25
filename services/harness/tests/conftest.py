"""Shared fixtures for services/harness acceptance tests (ticket P0-09, FR-AGT-01 partial,
D-11, PRD 15.3).

Run with `uv run pytest services/harness/tests` from the repo root (or `uv run --package
tilo-harness pytest` once services/harness is a uv workspace member -- ticket P0-09 item 1).
This directory has no __init__.py, so pytest's default "prepend" import mode puts it on
sys.path when collecting any test_*.py here, same convention as packages/providers/tests and
tests/contracts (see those conftest.py files).

`tilo_harness` does not exist yet: every test module here imports it and is expected to fail
collection with ImportError until the builder lands P0-09. That is the "right kind of failure"
this ticket's test-writer brief asks for -- do not add stubs to make it pass.

`@pytest.mark.emulator` tests need Java (for the Firestore emulator binary) and firebase-tools
(a pinned root devDependency, run through `pnpm exec`) and are excluded from the default `just
check` fast path the way `slow`-marked tests are in the root pyproject; run them explicitly with
`uv run pytest services/harness/tests -m emulator`.
"""

from __future__ import annotations

import json
import re
import socket
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

TESTS_DIR = Path(__file__).resolve().parent
HARNESS_DIR = TESTS_DIR.parent
REPO_ROOT = HARNESS_DIR.parent.parent
CONTRACTS_DIR = REPO_ROOT / "contracts"

# common.schema.json #/$defs/ulid: canonical upper-case Crockford base32, 26 characters.
ULID_PATTERN = re.compile(r"^[0-7][0-9A-HJKMNP-TV-Z]{25}$")


def pytest_configure(config: pytest.Config) -> None:
    # Registered here (not in the root pyproject.toml, which SH does not own -- see
    # docs/parallel-sessions.md's path ownership table) so `-m emulator` and
    # `-m "not emulator"` work without an "unknown marker" warning turning into a failure.
    config.addinivalue_line(
        "markers",
        "emulator: exercises the real Firestore emulator via tilo_harness.emulator "
        "(needs Java + firebase-tools); slower than the rest of the suite.",
    )


# ---------------------------------------------------------------------------
# Paths and repo-level fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def contracts_dir() -> Path:
    return CONTRACTS_DIR


@pytest.fixture(scope="session")
def harness_tests_fixtures_dir() -> Path:
    return TESTS_DIR / "fixtures"


# ---------------------------------------------------------------------------
# contracts/ fixture data every test file can reuse rather than re-reading it
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def village_basic_layout() -> dict[str, Any]:
    path = CONTRACTS_DIR / "fixtures/layout/valid/village_basic.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def village_basic_stream() -> list[dict[str, Any]]:
    """The 44-event fixture stream (contracts/event.rules.md), in file order (already `seq`-sorted)."""
    path = CONTRACTS_DIR / "fixtures/streams/village-basic.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


@pytest.fixture
def two_district_layout(harness_tests_fixtures_dir: Path) -> dict[str, Any]:
    """A minimal, test-owned two-district village layout (D1 lead A_l1, D2 lead A_l2), used to
    exercise per-district view scoping (contracts/event.rules.md EV-13, PRD 15.3) where
    village_basic's single district (D1) cannot show scope exclusivity."""
    path = harness_tests_fixtures_dir / "two_district_layout.json"
    return json.loads(path.read_text(encoding="utf-8"))


def event_fixture_paths(kind: str) -> list[Path]:
    """contracts/fixtures/events/<kind>/*.json, sorted for stable parametrize ids.
    kind is "valid", "invalid" or "registry/invalid"."""
    folder = CONTRACTS_DIR / "fixtures/events" / kind
    return sorted(folder.glob("*.json"))


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# emit() kwargs builders -- reused across writer test files so each one does
# not have to restate a schema-valid payload for a registered type.
# ---------------------------------------------------------------------------


def world_requested_kwargs(*, target: str = "w_village_basic") -> dict[str, Any]:
    """A schema-valid `world.requested` emit() call. Its actor (a user id) and target (a world
    id) are never layout ids (contracts/scripts/contracts_events.py's LAYOUT_ID only matches
    agent/level/district/building/gate/island ids), so this is safe to reuse against any
    layout, including a layout for a different world than `target` names."""
    return {
        "type": "world.requested",
        "actor": "u_owner",
        "target": target,
        "summary": "You asked Tilo to do some work.",
        "data": {"title": "Do some work", "channel": "web", "destination": None},
    }


def agent_idle_kwargs(
    actor: str, target: str, *, level: str | None = None, district: str | None = None
) -> dict[str, Any]:
    """A schema-valid `agent.idle` emit() call (empty `data`, the smallest registered payload),
    for layout-id-sensitive tests (EV-12) where actor/target must resolve in the layout."""
    return {
        "type": "agent.idle",
        "actor": actor,
        "target": target,
        "level": level,
        "district": district,
        "severity": "info",
        "summary": "The agent is waiting for work.",
        "data": {},
    }


def sequential_ulid(i: int) -> str:
    """A deterministic, schema-valid ULID (common.schema.json ulid pattern
    ^[0-7][0-9A-HJKMNP-TV-Z]{25}$) for test event ids: a fixed 20-char Crockford-safe prefix
    plus a 6-digit zero-padded index, 26 characters total."""
    return f"01JB5VQ0000000000000{i:06d}"


def make_memory_writer(
    layout: dict[str, Any],
    *,
    world_id: str = "w_village_basic",
    org_id: str = "org_demo",
    run_id: str = "r_test_1",
    writer_id: str = "writer_1",
    lease_s: float = 30.0,
    clock: Any = None,
) -> tuple[Any, Any]:
    """Builds an opened `WorldWriter` over a fresh `MemoryStore` and returns `(writer, store)`,
    so tests read the store back explicitly rather than relying on any undocumented WorldWriter
    attribute -- only `WorldWriter(store, ...)`'s constructor and methods are the public API
    (see the ticket brief). Imports `tilo_harness` lazily so conftest.py itself still collects
    (and every test file's own module-level import still fails with the expected ImportError)
    before the harness package exists.
    """
    from tilo_harness.store import MemoryStore
    from tilo_harness.writer import WorldWriter

    store = MemoryStore()
    kwargs: dict[str, Any] = {
        "org_id": org_id,
        "world_id": world_id,
        "run_id": run_id,
        "layout": layout,
        "writer_id": writer_id,
        "lease_s": lease_s,
    }
    if clock is not None:
        kwargs["clock"] = clock
    writer = WorldWriter(store, **kwargs)
    writer.open()
    return writer, store


# ---------------------------------------------------------------------------
# Injectable clock (WorldWriter(..., clock=...)) for lease/heartbeat tests
# ---------------------------------------------------------------------------


class FakeClock:
    """A manually-advanced clock matching WorldWriter's `Callable[[], datetime]` clock param, so
    lease-expiry tests never depend on wall-clock sleeps."""

    def __init__(self, start: datetime) -> None:
        self._now = start

    def __call__(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)


@pytest.fixture
def fake_clock() -> FakeClock:
    return FakeClock(datetime(2026, 9, 25, 9, 0, 0, tzinfo=UTC))


# ---------------------------------------------------------------------------
# Network guard -- proves the ADK skeleton (FR-AGT-01 partial) makes no real call
# ---------------------------------------------------------------------------


class NetworkBlocked(RuntimeError):
    pass


@pytest.fixture(scope="session")
def emulator_host() -> Iterator[str]:
    """Starts (or reuses) the Firestore emulator once for the whole session, via
    `tilo_harness.emulator.running_emulator()`, for every `@pytest.mark.emulator` test."""
    from tilo_harness.emulator import running_emulator

    with running_emulator() as host:
        yield host


@pytest.fixture
def block_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Makes any real TCP connect() other than to loopback raise, so a test that accidentally
    reaches a model API or the open internet fails loudly and immediately instead of hanging,
    recording a paid call, or silently "working" against a live service (EFF-01, CLAUDE.md
    "Dev and CI make no paid calls")."""
    real_connect = socket.socket.connect

    def guarded_connect(self: socket.socket, address: Any, *a: Any, **kw: Any) -> Any:
        host = address[0] if isinstance(address, tuple) else str(address)
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise NetworkBlocked(f"P0-09: network disabled in this test, blocked connect to {address!r}")
        return real_connect(self, address, *a, **kw)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    yield
