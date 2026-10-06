"""Shared helpers for packages/memory tests (FR-MEM-03, FR-MEM-09). Not conftest.py: prepend import mode needs unique
basenames, and other test directories already have a conftest.py.

Nothing here imports `tilo_memory`: the fakes below implement the duck-typed protocols in `API_FR_MEM_03_09.md`, so a
test file that imports `tilo_memory` is the only thing that fails while the package does not exist.
"""

from __future__ import annotations

import copy
import json
import pathlib
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
FIXTURES = REPO_ROOT / "contracts" / "fixtures" / "events" / "valid"
REGISTRY = REPO_ROOT / "contracts" / "events" / "registry.yaml"
NOW = datetime(2026, 10, 4, 12, 0, 0, tzinfo=UTC)

# The top-level TiloEvent columns that are REQUIRED in the ledger table (infra/modules/events/main.tf, PRD 9.3).
REQUIRED_COLUMNS = ("v", "id", "seq", "ts", "world_id", "type", "severity")


def fixture_event(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def all_fixture_events() -> list[dict[str, Any]]:
    """The canonical fixture of every registered type, `<type>.json`, one event per type. Further valid cases
    (`<type>--<case>.json`, contracts/event.rules.md) are left out. Their ids are unique (checked by the tests)."""
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(FIXTURES.glob("*.json")) if "--" not in p.stem]


def registered_types() -> set[str]:
    """Every event type listed in contracts/events/registry.yaml."""
    return set(yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))["types"])


def make_event(
    n: int, *, world: str = "w_alpha", run: str = "r_alpha1", ts: datetime | None = None, uid: int | None = None, **data
) -> dict:
    """A valid `memory.hit` TiloEvent: seq `n` in `world`, ULID-shaped id from `uid` (default `n`; pass a distinct
    `uid` when the same seq appears in more than one world)."""
    event = copy.deepcopy(fixture_event("memory.hit"))
    event["id"] = f"01JB5VQ{(n if uid is None else uid):019d}"
    event["seq"] = n
    event["world_id"] = world
    event["run_id"] = run
    event["ts"] = (ts or NOW).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    if data:
        event["data"] = {"origin_cost": data["origin_cost"], "lookup_cost": data["lookup_cost"]}
        event["data"]["saved"] = data.get("saved", data["origin_cost"] - data["lookup_cost"])
    return event


@dataclass(frozen=True)
class FakePubSubMessage:
    """What a Pub/Sub pull or push subscriber hands over: the payload bytes plus the broker's message id."""

    data: bytes
    message_id: str
    attributes: dict[str, str] = field(default_factory=dict)
    publish_time: datetime = NOW


def message_for(event: dict, message_id: str) -> FakePubSubMessage:
    return FakePubSubMessage(data=json.dumps(event).encode("utf-8"), message_id=message_id)


def as_json(value: Any) -> Any:
    """A BigQuery JSON column may come back as a JSON string or as a decoded object; accept both."""
    return json.loads(value) if isinstance(value, str) else value


@dataclass(frozen=True)
class Rec:
    """One stored record, as the retention protocol sees it (API_FR_MEM_03_09.md)."""

    entity: str
    record_id: str
    created_at: datetime
    user_id: str | None
    payload: str = ""


class FakeStore:
    """In-memory `RetentionStore`: `records()` is a fresh read; `delete(record_id)` is idempotent."""

    def __init__(self, records: Iterable[Rec] = ()):
        self._records: dict[str, Rec] = {r.record_id: r for r in records}
        self.delete_calls: list[str] = []

    def add(self, rec: Rec) -> None:
        self._records[rec.record_id] = rec

    def records(self) -> Iterable[Rec]:
        return list(self._records.values())

    def delete(self, record_id: str) -> None:
        self.delete_calls.append(record_id)
        self._records.pop(record_id, None)

    def ids(self) -> set[str]:
        return set(self._records)


class FailingDeleteStore(FakeStore):
    """A store whose delete always raises, like an unreachable service."""

    def delete(self, record_id: str) -> None:
        self.delete_calls.append(record_id)
        raise RuntimeError("store unavailable")


class LyingStore(FakeStore):
    """A store that reports a successful delete but keeps the data. Only an independent re-read catches it."""

    def delete(self, record_id: str) -> None:
        self.delete_calls.append(record_id)


def build_registry(names: Iterable[str], *, store_cls: type[FakeStore] = FakeStore) -> dict[str, FakeStore]:
    return {name: store_cls() for name in names}


def ago(days: float, seconds: float = 0.0, *, now: datetime = NOW) -> datetime:
    return now - timedelta(days=days, seconds=seconds)
