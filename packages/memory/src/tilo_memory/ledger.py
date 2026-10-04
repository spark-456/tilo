"""Event ledger with deduplication (FR-MEM-03, PRD 13.2, 13.5, 22.2 D-11).

Every TiloEvent lands once. The key is the event `id`, never the Pub/Sub message id, and the first write wins: a later
message with the same id never rewrites the row. `EventLedger` has no method that updates or deletes a row; removal
for retention or erasure (FR-MEM-09) is `LedgerRetentionStore`, the one path that deletes rows (BQ-195). A message
that cannot be read is `rejected` and acknowledged, so one poison message cannot make the stream loop (BQ-194).

Table protocol (duck-typed): `insert_if_absent(row) -> dict | None` (atomic; None when inserted, else the row already
there), `rows() -> list[dict]`, and `delete_row(id)` (idempotent; only `LedgerRetentionStore` calls it). Two table
classes implement it: an in-memory one for dev and tests, and `BigQueryLedgerTable`, tested against a mock client only
(no cloud calls here).
"""

from __future__ import annotations

import copy
import json
import re
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

REQUIRED = ("v", "id", "seq", "ts", "world_id", "type", "severity")
JSON_COLUMNS = ("item", "vis", "authz", "data", "trace")
COLUMNS: tuple[str, ...] = ("v", "id", "seq", "ts", "world_id", "run_id", "type", "actor", "target", "level")
COLUMNS += ("district", "item", "severity", "credits", "summary", "cause", "vis", "authz", "data", "trace")
_TABLE_ID = re.compile(r"^[A-Za-z0-9_.-]{1,200}$")


@dataclass(frozen=True)
class IngestResult:
    """`status` is inserted, duplicate, conflict (same id, other content) or rejected. Never carries content."""

    status: str
    event_id: str | None = None


def _reject_constant(name: str) -> Any:
    raise ValueError(name)


def _to_row(event: Mapping[str, Any]) -> dict[str, Any]:
    """Top-level columns only; an absent key stays absent and an explicit null stays null (the fixtures carry nulls).
    Nested payloads become JSON strings (BigQuery JSON columns)."""
    row: dict[str, Any] = {}
    for column in COLUMNS:
        if column in event:
            value = event[column]
            row[column] = json.dumps(value, sort_keys=True) if column in JSON_COLUMNS and value is not None else value
    return row


def _to_event(row: Mapping[str, Any]) -> dict[str, Any]:
    event: dict[str, Any] = {}
    for column in COLUMNS:
        if column in row:
            value = row[column]
            event[column] = json.loads(value) if column in JSON_COLUMNS and isinstance(value, str) else value
    return event


def _parse(message: Any) -> dict[str, Any] | None:
    """The event in the message, or None if it is not one (not JSON, not an object, a required field missing)."""
    try:
        event = json.loads(bytes(message.data), parse_constant=_reject_constant)
    except (ValueError, TypeError, AttributeError, RecursionError):  # includes bad UTF-8 and JSON errors
        return None
    if not isinstance(event, dict):
        return None
    for column in REQUIRED:
        if event.get(column) is None:
            return None
    for column in ("v", "id", "ts", "world_id", "type", "severity"):
        if not isinstance(event[column], str) or not event[column]:
            return None
    if isinstance(event["seq"], bool) or not isinstance(event["seq"], int):
        return None
    return event


class EventLedger:
    """Append-only, deduplicating front for a ledger table. Safe to run in several instances on one table."""

    def __init__(self, table: Any):
        self._table = table

    def ingest(self, message: Any) -> IngestResult:
        event = _parse(message)
        if event is None:
            return IngestResult("rejected")
        row = _to_row(event)
        existing = self._table.insert_if_absent(row)
        if existing is None:
            return IngestResult("inserted", event["id"])
        same = _to_event(existing) == _to_event(row)
        return IngestResult("duplicate" if same else "conflict", event["id"])

    def events(self, world_id: str | None = None) -> list[dict[str, Any]]:
        events = [_to_event(row) for row in self._table.rows()]
        if world_id is not None:
            events = [e for e in events if e["world_id"] == world_id]
        return sorted(events, key=lambda e: (e["world_id"], e["seq"]))

    def count(self) -> int:
        return len(self._table.rows())


class InMemoryLedgerTable:
    """Stands for BigQuery `tilo_ledger.events` in dev and tests. One lock makes insert-if-absent atomic."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rows: dict[str, dict[str, Any]] = {}

    def insert_if_absent(self, row: Mapping[str, Any]) -> dict[str, Any] | None:
        with self._lock:
            existing = self._rows.get(row["id"])
            if existing is not None:
                return copy.deepcopy(existing)
            self._rows[row["id"]] = copy.deepcopy(dict(row))
            return None

    def rows(self) -> list[dict[str, Any]]:
        with self._lock:
            return [copy.deepcopy(r) for r in self._rows.values()]

    def delete_row(self, row_id: str) -> None:
        with self._lock:
            self._rows.pop(row_id, None)


class BigQueryClient(Protocol):
    """The two calls the adapter needs; a thin wrapper over google-cloud-bigquery is wired at deploy time."""

    def run_dml(self, sql: str, params: Mapping[str, str | None]) -> int:
        """Run one DML statement with string query parameters; return the affected row count."""
        ...

    def query(self, sql: str, params: Mapping[str, str | None]) -> list[Mapping[str, Any]]: ...


_CASTS = {"seq": "CAST(@seq AS INT64)", "ts": "TIMESTAMP(@ts)", "credits": "CAST(@credits AS FLOAT64)"}
_READ = {"ts": "FORMAT_TIMESTAMP('%Y-%m-%dT%H:%M:%E*SZ', ts) AS ts"}


class BigQueryLedgerTable:
    """`tilo_ledger.events` behind the table protocol. BigQuery has no unique key and streaming insert ids dedup only
    best-effort, so the insert is one DML statement that skips an existing id. The Pub/Sub BigQuery subscription in
    infra/modules/events writes straight into the table and bypasses this, so a deduplicating view or an ingester in
    front of the topic is still needed there (follow-up; infra is not changed here)."""

    def __init__(self, client: BigQueryClient, table: str):
        if not _TABLE_ID.match(table):  # identifiers cannot be query parameters
            raise ValueError("invalid table id")
        self._client, self._table = client, table

    def insert_if_absent(self, row: Mapping[str, Any]) -> dict[str, Any] | None:
        params = {c: None if row.get(c) is None else str(row[c]) for c in COLUMNS}
        values = ", ".join(_CASTS.get(c) or (f"PARSE_JSON(@{c})" if c in JSON_COLUMNS else f"@{c}") for c in COLUMNS)
        sql = (
            f"INSERT INTO `{self._table}` ({', '.join(COLUMNS)}) SELECT {values} "
            f"FROM (SELECT 1) WHERE NOT EXISTS (SELECT 1 FROM `{self._table}` WHERE id = @id)"
        )
        for _ in range(2):  # the second pass covers a row erased between the insert and the lookup
            if self._client.run_dml(sql, params) > 0:
                return None
            found = self._client.query(f"{self._select()} WHERE id = @id", {"id": params["id"]})
            if found:
                return dict(found[0])
        raise RuntimeError("ledger insert not confirmed")  # raised so Pub/Sub redelivers the message

    def rows(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self._client.query(self._select(), {})]

    def delete_row(self, row_id: str) -> None:
        self._client.run_dml(f"DELETE FROM `{self._table}` WHERE id = @id", {"id": row_id})

    def _select(self) -> str:
        cols = ", ".join(_READ.get(c) or (f"TO_JSON_STRING({c}) AS {c}" if c in JSON_COLUMNS else c) for c in COLUMNS)
        return f"SELECT {cols} FROM `{self._table}`"


_NEVER = datetime.max.replace(tzinfo=UTC)


@dataclass(frozen=True)
class LedgerRecord:
    """A ledger row as the retention protocol sees it: ids and times only, never the event."""

    record_id: str
    created_at: datetime
    user_id: str | None
    entity: str = "event_ledger"


def _event_time(ts: Any) -> datetime:
    """The event `ts` as aware UTC. Ingest only checks that `ts` is a non-empty string, so an unreadable one is aged
    as never expiring (retention must not delete a row early) but stays findable for erasure."""
    try:
        parsed = datetime.fromisoformat(ts)
    except (TypeError, ValueError):
        return _NEVER
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


class LedgerRetentionStore:
    """The one sanctioned path that removes ledger rows (retention and user erasure, FR-MEM-09, BQ-195). A row belongs
    to the owner of its world, `world_owner(world_id)`; a world with no known owner gives user_id None, which a user
    erasure never touches. A failing `world_owner` raises, so the caller reports the store as unreadable."""

    def __init__(self, table: Any, *, world_owner: Callable[[str], str | None]):
        self._table, self._world_owner = table, world_owner

    def records(self) -> list[LedgerRecord]:
        records = []
        for row in self._table.rows():
            owner = self._world_owner(row["world_id"])
            records.append(
                LedgerRecord(row["id"], _event_time(row.get("ts")), owner if isinstance(owner, str) else None)
            )
        return records

    def delete(self, record_id: str) -> None:
        self._table.delete_row(record_id)
