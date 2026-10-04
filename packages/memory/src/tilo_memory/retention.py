"""Retention windows and the purge that applies them (FR-MEM-09, PRD 15.1, 16.5).

Every store sits behind `RetentionStore` (duck-typed): `records()` is a fresh read of everything the store holds and
`delete(record_id)` is idempotent. A record is expired only when it is strictly older than its window (BQ-196). An
entity with no window (None) lives until its account, binding or connection goes. An entity the table does not know
is an error: it is never kept forever by default.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta
from types import MappingProxyType
from typing import Protocol

USER_ID_PATTERN = re.compile(r"u_[0-9A-Za-z_]{1,48}")  # contracts/common.schema.json user_id; use with fullmatch

# PRD 15.1 "Retention (default)". None = life of account / until unbound / until disconnected.
RETENTION_DAYS: Mapping[str, int | None] = MappingProxyType(
    {
        "org": None,
        "user": None,
        "channel_binding": None,
        "connection": None,
        "policy": None,
        "policy_history": 365,
        "task": 90,
        "world": 90,
        "run": 90,
        "card": 90,
        "artifact": 90,
        "event_live": 30,
        "event_ledger": 365,
        "decision": 365,
        "archive_record": 30,
        "cache_entry": 30,  # "7-30 days by source": the upper bound; a source with a shorter window expires sooner
    }
)


class Record(Protocol):
    """What a store reports for one stored item. Never carries the item's content."""

    @property
    def entity(self) -> str: ...
    @property
    def record_id(self) -> str: ...
    @property
    def created_at(self) -> datetime: ...
    @property
    def user_id(self) -> str | None: ...


class RetentionStore(Protocol):
    """`record_id` is unique within one store (an adapter whose natural key is not must compose one)."""

    def records(self) -> Iterable[Record]: ...

    def delete(self, record_id: str) -> None: ...


def retention_days(entity: str) -> int | None:
    try:
        return RETENTION_DAYS[entity]
    except (KeyError, TypeError):
        raise ValueError("unknown entity: no retention window") from None


def purge_expired(registry: Mapping[str, RetentionStore], *, now: datetime) -> dict[str, int]:
    """Delete every record older than its window; return store name -> number removed (0 when nothing was).

    Reads every store and checks every entity first, so an unknown entity or an unreadable store stops the purge
    before anything is deleted. The registry need not be complete (that rule is for erasure)."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    plan: dict[str, list[str]] = {}
    for name, store in registry.items():
        expired: list[str] = []
        for rec in list(store.records()):
            days = retention_days(rec.entity)
            if days is not None and now - rec.created_at > timedelta(days=days):
                expired.append(rec.record_id)
        plan[name] = expired
    for name, ids in plan.items():
        for record_id in ids:
            registry[name].delete(record_id)
    return {name: len(ids) for name, ids in plan.items()}
