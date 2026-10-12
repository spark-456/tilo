"""The production schedule store (FR-AGT-14b, design decisions 5 and 6; ADR-0003 addendum): Firestore
`orgs/{org}/schedules/{schedule_id}`, and an in-memory twin with the same behaviour.

Both stores run the SAME transition functions over a raw document (`_claim`, `_release`, `_complete`, `_failure`,
`_update`); only where the document lives and where "now" comes from differ. A claim is a lease of `CLAIM_LEASE`
measured on the STORE's clock (the Firestore read time inside the transaction), never the caller's. A record that
cannot be built is quarantined in place (`enabled=False`, `last_error="invalid_record"`) and skipped; `due()` never
raises for one.

`open_schedule_store` is the one explicit-config door to a live Firestore (ADR-0003 addendum): `TILO_SCHEDULES_STORE=
firestore` plus a valid `TILO_FIRESTORE_PROJECT`. With no config it refuses and builds no client. Importing this module
builds none either, and `tilo_harness.store.FirestoreStore` keeps its own emulator/`demo-` guard untouched.

Firestore needs the composite index (collection `schedules`: `enabled` ascending, `next_due` ascending) for `due()`;
the emulator does not enforce it.
"""

from __future__ import annotations

import copy
import os
import random
import re
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, TypeGuard

from tilo_harness.ids import ORG_ID, check_id
from tilo_harness.schedule import CLAIM_LEASE, Cadence, Schedule, ScheduleStore, next_slot, slot_key

SCHEDULE_ID = re.compile(r"^sched_[0-9A-Za-z_]{1,64}$")  # an id can never reach a Firestore path
MAX_FAILURES = 8  # after this many failed or skipped starts in a row the schedule is disabled
MAX_BACKOFF = timedelta(hours=24)
INVALID_RECORD = "invalid_record"
OWNER_DISABLED = "owner_disabled"
_OWNER_ID = re.compile(r"u_[0-9A-Za-z_]{1,48}")  # contracts/common.schema.json user_id; use with fullmatch
_PROJECT = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")  # a GCP project id
_ERROR_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_ATTEMPTS = 8  # whole-transaction retries on contention, with jitter
_MAX_SCAN = 200  # documents one Firestore `due()` call reads at most
_CADENCE_KEYS = {"weekday", "hour", "minute", "tz"}
_NO_CLAIM: dict[str, Any] = {"claim_due": None, "claimed_at": None}


class ScheduleStoreNotConfigured(RuntimeError):
    """No explicit store config: nothing is opened (ADR-0003 addendum)."""


class ScheduleRepository(ScheduleStore, Protocol):
    """What the tilo-api routes need on top of the Ticker's `ScheduleStore` calls."""

    def create(self, schedule: Schedule, *, max_per_owner: int) -> bool: ...
    def get(self, schedule_id: str) -> Schedule | None: ...
    def list_for_owner(self, owner_user_id: str) -> list[Schedule]: ...
    def update(
        self,
        schedule_id: str,
        *,
        enabled: bool | None = None,
        title: str | None = None,
        cadence: Cadence | None = None,
        next_due: datetime | None = None,
    ) -> Schedule | None: ...
    def delete(self, schedule_id: str) -> bool: ...
    def record_failure(
        self, schedule_id: str, due: datetime, *, error: str, next_due: datetime | None = None
    ) -> None: ...
    def record_refusal(self, schedule_id: str, code: str) -> None: ...
    def disable_for_owner(self, owner_user_id: str) -> int: ...
    def documents(self) -> list[tuple[str, dict[str, Any]]]: ...
    def now(self) -> datetime: ...


def backoff_for(failures: int) -> timedelta:
    """min(60 s * 2**failures, 24 h) for failures >= 1; the exponent is capped so a huge count cannot overflow."""
    return min(timedelta(seconds=60 * 2 ** min(max(failures, 1), 20)), MAX_BACKOFF)


# --- documents ------------------------------------------------------------------------------------------------------


def schedule_to_doc(s: Schedule) -> dict[str, Any]:
    return {
        "schedule_id": s.schedule_id,
        "owner_user_id": s.owner_user_id,
        "title": s.title,
        "cadence": _cadence_doc(s.cadence),
        "approved_brief_ref": s.approved_brief_ref,
        "budget_cap": s.budget_cap,
        "enabled": s.enabled,
        "next_due": s.next_due,
        "last_slot": s.last_slot,
        "last_world_id": s.last_world_id,
        "brief": copy.deepcopy(s.brief),
        "approach": copy.deepcopy(s.approach),
        "approaches": copy.deepcopy(s.approaches),
        "failures": s.failures,
        "backoff_until": s.backoff_until,
        "last_error": s.last_error,
        "created_at": s.created_at,
        "demo": s.demo,
    }


def _cadence_doc(c: Cadence) -> dict[str, Any]:
    return {"weekday": c.weekday, "hour": c.hour, "minute": c.minute, "tz": c.tz}


def _is_dt(value: Any) -> TypeGuard[datetime]:
    return isinstance(value, datetime) and value.utcoffset() is not None


def _typed(doc: Mapping[str, Any], name: str, kind: type | tuple[type, ...], *, optional: bool = False) -> Any:
    value = doc.get(name)
    if value is None and optional:
        return None
    if isinstance(value, bool) and bool not in (kind if isinstance(kind, tuple) else (kind,)):
        raise ValueError(f"{name} has the wrong type")
    if not isinstance(value, kind):
        raise ValueError(f"{name} has the wrong type")
    return value


def _approaches(doc: Mapping[str, Any]) -> list[dict[str, Any]] | None:
    value = _typed(doc, "approaches", list, optional=True)  # absent in a document written before SCHED_PLAN
    if value is not None and not all(isinstance(a, dict) for a in value):
        raise ValueError("approaches has the wrong type")
    return copy.deepcopy(value)


def schedule_from_doc(doc: Mapping[str, Any]) -> Schedule:
    """Raises ValueError for anything that cannot be built (bad cadence, next_due missing, naive or not aligned to the
    cadence, bad cap, wrong field types): the store quarantines such a record rather than raising out of `due()`."""
    try:
        raw = _typed(doc, "cadence", dict)
        if set(raw) != _CADENCE_KEYS:
            raise ValueError("cadence has the wrong keys")
        cadence = Cadence(weekday=raw["weekday"], hour=raw["hour"], minute=raw["minute"], tz=raw["tz"])
        next_due = doc.get("next_due")
        if not _is_dt(next_due) or next_slot(cadence, next_due - timedelta(microseconds=1)) != next_due:
            raise ValueError("next_due is not an aware instant aligned to the cadence")
        for name in ("backoff_until", "created_at"):
            if doc.get(name) is not None and not _is_dt(doc[name]):
                raise ValueError(f"{name} is not an aware datetime")
        failures = _typed(doc, "failures", int)
        if failures < 0:
            raise ValueError("failures is negative")
        return Schedule(
            schedule_id=_typed(doc, "schedule_id", str),
            owner_user_id=_typed(doc, "owner_user_id", str),
            title=_typed(doc, "title", str),
            cadence=cadence,
            approved_brief_ref=_typed(doc, "approved_brief_ref", str),
            budget_cap=_typed(doc, "budget_cap", (int, float)),
            enabled=_typed(doc, "enabled", bool),
            next_due=next_due,
            last_slot=_typed(doc, "last_slot", str, optional=True),
            last_world_id=_typed(doc, "last_world_id", str, optional=True),
            brief=copy.deepcopy(_typed(doc, "brief", dict, optional=True)),
            approach=copy.deepcopy(_typed(doc, "approach", dict, optional=True)),
            approaches=_approaches(doc),
            failures=failures,
            backoff_until=doc.get("backoff_until"),
            last_error=_typed(doc, "last_error", str, optional=True),
            created_at=doc.get("created_at"),
            # A record from before the field existed reads as a demo's: it then only replays (safe, BQ-SIGNIN-10).
            demo=_typed(doc, "demo", bool) if "demo" in doc else True,
        )
    except ValueError:
        raise
    except Exception as exc:  # KeyError, TypeError, OverflowError ...: one failure type for the callers
        raise ValueError("schedule document cannot be built") from exc


def _decode(doc: Mapping[str, Any] | None) -> Schedule | None:
    if doc is None:
        return None
    try:
        return schedule_from_doc(doc)
    except ValueError:
        return None


def _check_id(schedule_id: str) -> None:
    if not isinstance(schedule_id, str) or not SCHEDULE_ID.fullmatch(schedule_id):
        raise ValueError(f"schedule_id {schedule_id!r} does not match {SCHEDULE_ID.pattern}")


def _valid_id(schedule_id: str) -> bool:
    return isinstance(schedule_id, str) and SCHEDULE_ID.fullmatch(schedule_id) is not None


# --- the transitions both stores run over a raw document; None = nothing to change ----------------------------------


def _claim(doc: Mapping[str, Any], due: datetime, now: datetime) -> dict[str, Any] | None:
    if doc.get("enabled") is not True or doc.get("next_due") != due:
        return None
    backoff = doc.get("backoff_until")
    if _is_dt(backoff) and backoff > now:
        return None  # a failing start waits out its backoff
    held, at = doc.get("claim_due"), doc.get("claimed_at")
    if held is not None and _is_dt(at) and now - at < CLAIM_LEASE:
        return None  # a live lease; a stale one (crashed holder) is claimable again
    return {"claim_due": due, "claimed_at": now}


def _release(doc: Mapping[str, Any], due: datetime) -> dict[str, Any] | None:
    return dict(_NO_CLAIM) if doc.get("claim_due") == due else None


def _complete(doc: Mapping[str, Any], due: datetime, next_due: datetime, last_world_id: str) -> dict[str, Any] | None:
    if not _is_dt(next_due):
        raise ValueError("next_due must be timezone-aware")
    if doc.get("next_due") != due:
        return None  # the slot already moved: nothing to do twice
    return {
        "next_due": next_due,
        "last_slot": slot_key(str(doc.get("schedule_id")), due),
        "last_world_id": last_world_id,
        "failures": 0,
        "backoff_until": None,
        "last_error": None,
        **_NO_CLAIM,
    }


def _fixed_code(error: Any) -> str:
    """A code, never free text: anything that is not `^[a-z][a-z0-9_]{0,63}$` is recorded as `start_failed`."""
    return error if isinstance(error, str) and _ERROR_CODE.fullmatch(error) else "start_failed"


def _refusal(doc: Mapping[str, Any], code: str) -> dict[str, Any]:
    """FR-AGT-14e: a delivered task was refused for good. Only `last_error` is set: not a failure (no count, no backoff,
    no disabling), and neither the slot nor a held claim is touched. The next `complete` clears it."""
    return {"last_error": _fixed_code(code)}


def _failure(
    doc: Mapping[str, Any], due: datetime, error: str, next_due: datetime | None, now: datetime
) -> dict[str, Any] | None:
    if doc.get("next_due") != due or doc.get("claim_due") != due:
        return None  # a stale call (the slot moved or the claim was never ours) changes nothing
    if next_due is not None and not _is_dt(next_due):
        raise ValueError("next_due must be timezone-aware")
    prior = doc.get("failures")
    failures = (prior if isinstance(prior, int) and not isinstance(prior, bool) else 0) + 1
    changes: dict[str, Any] = {
        "failures": failures,
        "last_error": _fixed_code(error),
        "backoff_until": now + backoff_for(failures),
        **_NO_CLAIM,
    }
    if next_due is not None:
        changes["next_due"] = next_due
    if failures >= MAX_FAILURES:
        changes["enabled"] = False
    return changes


def _stale_cadence(doc: Mapping[str, Any]) -> Cadence | None:
    try:
        raw = doc["cadence"]
        return Cadence(weekday=raw["weekday"], hour=raw["hour"], minute=raw["minute"], tz=raw["tz"])
    except Exception:  # a record that cannot be built is left as it is (quarantine handles it)
        return None


def _update(
    doc: Mapping[str, Any],
    now: datetime,
    enabled: bool | None,
    title: str | None,
    cadence: Cadence | None,
    next_due: datetime | None,
) -> dict[str, Any]:
    changes: dict[str, Any] = {}
    if enabled is not None:
        changes["enabled"] = enabled
        if enabled:  # switching a schedule on again is a fresh start
            changes.update({"failures": 0, "backoff_until": None, "last_error": None})
            stale = doc.get("next_due")
            if next_due is None and doc.get("enabled") is not True and _is_dt(stale) and stale <= now:
                # off since its slot passed: no catch-up run, the first slot strictly after now (store's clock)
                current = cadence if cadence is not None else _stale_cadence(doc)
                if current is not None:
                    changes["next_due"] = next_slot(current, now)
    if title is not None:
        changes["title"] = title
    if cadence is not None:
        changes["cadence"] = _cadence_doc(cadence)
    if next_due is not None:
        if not _is_dt(next_due):
            raise ValueError("next_due must be timezone-aware")
        changes["next_due"] = next_due
    return changes


def _new_doc(schedule: Schedule) -> dict[str, Any]:
    _check_id(schedule.schedule_id)
    return {**schedule_to_doc(schedule), **_NO_CLAIM}


# --- the stores -----------------------------------------------------------------------------------------------------

_Change = Callable[[dict[str, Any], datetime], dict[str, Any] | None]  # (document, the store's now) -> fields to set


class ScheduleStoreBusy(RuntimeError):
    """Firestore contention outlasted the retries (a claim treats it as "someone else has it")."""


class _Store:
    """The calls both stores share, each one `_apply` of a transition above."""

    def _apply(self, schedule_id: str, change: _Change) -> dict[str, Any] | None:
        raise NotImplementedError

    def read_doc(self, schedule_id: str) -> dict[str, Any] | None:
        raise NotImplementedError

    def get(self, schedule_id: str) -> Schedule | None:
        return _decode(self.read_doc(schedule_id))

    def update(
        self,
        schedule_id: str,
        *,
        enabled: bool | None = None,
        title: str | None = None,
        cadence: Cadence | None = None,
        next_due: datetime | None = None,
    ) -> Schedule | None:
        return _decode(self._apply(schedule_id, lambda doc, now: _update(doc, now, enabled, title, cadence, next_due)))

    def owner_ids(self, owner_user_id: str) -> list[str]:
        raise NotImplementedError

    def disable_for_owner(self, owner_user_id: str) -> int:
        """Stops every enabled schedule of one owner (`enabled=False`, `last_error="owner_disabled"`) and returns how
        many changed. Another owner's records are never read as a match; an invalid owner id raises ValueError."""
        if not isinstance(owner_user_id, str) or not _OWNER_ID.fullmatch(owner_user_id):
            raise ValueError("owner_user_id is not a user id")

        def change(doc: dict[str, Any], now: datetime) -> dict[str, Any] | None:
            if doc.get("owner_user_id") != owner_user_id or doc.get("enabled") is not True:
                return None  # re-checked inside the transaction; a held claim does not stop the disable
            return {"enabled": False, "last_error": OWNER_DISABLED}

        return sum(1 for sid in self.owner_ids(owner_user_id) if self._apply(sid, change) is not None)

    def documents(self) -> list[tuple[str, dict[str, Any]]]:
        """A fresh read of every raw document of the store (id, fields), decodable or not."""
        raise NotImplementedError

    def now(self) -> datetime:
        raise NotImplementedError

    def claim(self, schedule_id: str, due: datetime) -> bool:
        try:
            return self._apply(schedule_id, lambda doc, now: _claim(doc, due, now)) is not None
        except ScheduleStoreBusy:
            return False

    def release(self, schedule_id: str, due: datetime) -> None:
        self._apply(schedule_id, lambda doc, now: _release(doc, due))

    def complete(self, schedule_id: str, due: datetime, *, next_due: datetime, last_world_id: str) -> None:
        self._apply(schedule_id, lambda doc, now: _complete(doc, due, next_due, last_world_id))

    def record_failure(self, schedule_id: str, due: datetime, *, error: str, next_due: datetime | None = None) -> None:
        self._apply(schedule_id, lambda doc, now: _failure(doc, due, error, next_due, now))

    def record_refusal(self, schedule_id: str, code: str) -> None:
        """Sets only `last_error` to the fixed `code`. An unknown or malformed id is a no-op."""
        self._apply(schedule_id, lambda doc, now: _refusal(doc, code))


class InMemoryScheduleStore(_Store):
    """Same behaviour as the Firestore store; thread-safe (the lock is the transaction)."""

    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock if clock is not None else (lambda: datetime.now(UTC))
        self._lock = threading.RLock()
        self._rows: dict[str, dict[str, Any]] = {}

    def create(self, schedule: Schedule, *, max_per_owner: int) -> bool:
        doc = _new_doc(schedule)
        with self._lock:
            owned = sum(1 for row in self._rows.values() if row.get("owner_user_id") == schedule.owner_user_id)
            if schedule.schedule_id in self._rows or owned >= max_per_owner:
                return False
            self._rows[schedule.schedule_id] = doc
            return True

    def insert_raw(self, doc: Mapping[str, Any]) -> None:
        _check_id(doc["schedule_id"])
        with self._lock:
            self._rows[doc["schedule_id"]] = copy.deepcopy(dict(doc))

    def read_doc(self, schedule_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._rows.get(schedule_id) if _valid_id(schedule_id) else None
            return copy.deepcopy(row) if row is not None else None

    def list_for_owner(self, owner_user_id: str) -> list[Schedule]:
        with self._lock:
            docs = [r for r in self._rows.values() if r.get("owner_user_id") == owner_user_id]
        return sorted((s for s in map(_decode, docs) if s is not None), key=lambda s: s.schedule_id)

    def delete(self, schedule_id: str) -> bool:
        with self._lock:
            return _valid_id(schedule_id) and self._rows.pop(schedule_id, None) is not None

    def owner_ids(self, owner_user_id: str) -> list[str]:
        with self._lock:
            return [sid for sid, row in self._rows.items() if row.get("owner_user_id") == owner_user_id]

    def documents(self) -> list[tuple[str, dict[str, Any]]]:
        with self._lock:
            return [(sid, copy.deepcopy(row)) for sid, row in self._rows.items()]

    def now(self) -> datetime:
        return self._clock()

    def due(self, now: datetime, limit: int) -> list[Schedule]:
        healthy: list[Schedule] = []
        with self._lock:
            for schedule_id, doc in list(self._rows.items()):
                if doc.get("enabled") is not True:
                    continue
                schedule = _decode(doc)
                if schedule is None:  # every enabled record is checked, due or not
                    self._rows[schedule_id] = {**doc, "enabled": False, "last_error": INVALID_RECORD}
                elif schedule.next_due <= now and (schedule.backoff_until is None or schedule.backoff_until <= now):
                    healthy.append(schedule)
        return sorted(healthy, key=lambda s: (s.next_due, s.schedule_id))[: max(limit, 0)]

    def _apply(self, schedule_id: str, change: _Change) -> dict[str, Any] | None:
        """The document after `change` (None when nothing changed or the id is unknown)."""
        with self._lock:
            doc = self._rows.get(schedule_id) if _valid_id(schedule_id) else None
            changes = change(doc, self._clock()) if doc is not None else None
            if doc is None or changes is None:
                return None
            self._rows[schedule_id] = doc = {**doc, **copy.deepcopy(changes)}
            return copy.deepcopy(doc)


class FirestoreScheduleStore(_Store):
    """`orgs/{org}/schedules/{schedule_id}`. Every read-modify-write is a transaction; leases and backoffs use the
    transaction's server read time. Built by `open_schedule_store` (or the emulator tests, which pass no client)."""

    def __init__(self, *, project_id: str, org_id: str = "org_tilo", client: Any = None) -> None:
        check_id(org_id, ORG_ID, label="org_id")
        if client is None:
            from google.cloud import firestore

            client = firestore.Client(project=project_id)
        self.project_id, self._client = project_id, client
        self._col = client.collection(f"orgs/{org_id}/schedules")
        self._creates = (
            threading.Lock()
        )  # this process's own creates queue up instead of fighting for the owner's range

    def _ref(self, schedule_id: str) -> Any:
        _check_id(schedule_id)
        return self._col.document(schedule_id)

    def _txn(self, work: Callable[[Any], Any]) -> Any:
        """Runs `work` in a transaction, retrying contention (another writer on the same documents) with jitter."""
        from google.api_core.exceptions import Aborted
        from google.cloud import firestore

        @firestore.transactional
        def run(transaction: Any) -> Any:
            return work(transaction)

        for attempt in range(_ATTEMPTS):
            try:
                return run(self._client.transaction())
            except Aborted:
                pass
            except ValueError as exc:  # the library wraps the last Aborted once its own retries are spent
                if not isinstance(exc.__cause__, Aborted):
                    raise
            time.sleep(random.uniform(0, 0.05 * 2**attempt))
        raise ScheduleStoreBusy("schedule store is busy")

    def _by_owner(self, owner_user_id: str) -> Any:
        from google.cloud.firestore_v1.base_query import FieldFilter

        return self._col.where(filter=FieldFilter("owner_user_id", "==", owner_user_id))

    def create(self, schedule: Schedule, *, max_per_owner: int) -> bool:
        doc, ref = _new_doc(schedule), self._ref(schedule.schedule_id)

        def work(tx: Any) -> bool:
            owned = list(self._by_owner(schedule.owner_user_id).stream(transaction=tx))
            if len(owned) >= max_per_owner or ref.get(transaction=tx).exists:
                return False
            tx.create(ref, doc)
            return True

        with self._creates:
            return bool(self._txn(work))

    def insert_raw(self, doc: Mapping[str, Any]) -> None:
        self._ref(doc["schedule_id"]).set(dict(doc))

    def read_doc(self, schedule_id: str) -> dict[str, Any] | None:
        snap = self._ref(schedule_id).get() if _valid_id(schedule_id) else None
        return snap.to_dict() if snap is not None and snap.exists else None

    def list_for_owner(self, owner_user_id: str) -> list[Schedule]:
        docs = (snap.to_dict() for snap in self._by_owner(owner_user_id).stream())
        return sorted((s for s in map(_decode, docs) if s is not None), key=lambda s: s.schedule_id)

    def delete(self, schedule_id: str) -> bool:
        if not _valid_id(schedule_id):
            return False
        ref = self._ref(schedule_id)

        def work(tx: Any) -> bool:
            if not ref.get(transaction=tx).exists:
                return False
            tx.delete(ref)
            return True

        return bool(self._txn(work))

    def owner_ids(self, owner_user_id: str) -> list[str]:
        return [snap.id for snap in self._by_owner(owner_user_id).stream()]

    def documents(self) -> list[tuple[str, dict[str, Any]]]:
        return [(snap.id, snap.to_dict() or {}) for snap in self._col.stream()]

    def now(self) -> datetime:
        return datetime.now(UTC)

    def due(self, now: datetime, limit: int) -> list[Schedule]:
        """Ascending by next_due over the enabled records; stops at the first healthy one in the future. Bad records
        met on the way are quarantined. Reads at most `_MAX_SCAN` documents per call."""
        from google.cloud.firestore_v1.base_query import FieldFilter

        found: list[Schedule] = []
        scanned, cursor, page = 0, None, max(limit, 10)
        while limit > 0 and scanned < _MAX_SCAN:
            query = self._col.where(filter=FieldFilter("enabled", "==", True)).order_by("next_due").limit(page)
            snaps = list((query if cursor is None else query.start_after(cursor)).stream())
            for snap in snaps:
                scanned, cursor = scanned + 1, snap
                schedule = _decode(snap.to_dict())
                if schedule is None:
                    self._quarantine(snap.id)
                elif schedule.next_due > now:
                    return found
                elif schedule.backoff_until is None or schedule.backoff_until <= now:
                    found.append(schedule)
                    if len(found) == limit:
                        return found
            if len(snaps) < page:
                break
        return found

    def _quarantine(self, schedule_id: str) -> None:
        ref = self._ref(schedule_id)

        def work(tx: Any) -> None:
            snap = ref.get(transaction=tx)
            doc = snap.to_dict() if snap.exists else None
            if doc is not None and doc.get("enabled") is True and _decode(doc) is None:
                tx.update(ref, {"enabled": False, "last_error": INVALID_RECORD})

        self._txn(work)

    def _apply(self, schedule_id: str, change: _Change) -> dict[str, Any] | None:
        """One transaction: read the document and the server time, compute the change, write it."""
        if not _valid_id(schedule_id):
            return None
        ref = self._ref(schedule_id)

        def work(tx: Any) -> dict[str, Any] | None:
            snap = ref.get(transaction=tx)
            doc = snap.to_dict() if snap.exists else None
            changes = change(doc, snap.read_time) if doc is not None else None
            if doc is None or changes is None:
                return None
            if changes:  # Firestore refuses an empty update ("Cannot update with an empty document")
                tx.update(ref, changes)
            return {**doc, **changes}

        result: dict[str, Any] | None = self._txn(work)
        return result


@dataclass(frozen=True)
class ScheduleRecord:
    """The `tilo_memory.retention.Record` of one schedule document. Never carries its content."""

    record_id: str
    user_id: str | None
    created_at: datetime
    entity: str = "schedule"


class ScheduleRetention:
    """A `tilo_memory.retention.RetentionStore` over a schedule store, so a registry's `firestore` entry can hold
    `orgs/*/schedules` (erasure, FR-MEM-09). `records()` is a fresh read of EVERY document, enabled or not, and also
    of those that cannot be decoded (quarantined, malformed), by their raw owner; a document with no owner is yielded
    with `user_id=None` and an erasure never deletes it. `entity` is "schedule": it has no window in
    `tilo_memory.retention.RETENTION_DAYS`, so `purge_expired` over a registry holding this adapter needs a decision
    first (BQ-AGT14-4)."""

    def __init__(self, store: ScheduleRepository) -> None:
        self._store = store

    def records(self) -> Iterable[ScheduleRecord]:
        now = self._store.now()
        out: list[ScheduleRecord] = []
        for schedule_id, doc in self._store.documents():
            owner, made = doc.get("owner_user_id"), doc.get("created_at")
            out.append(
                ScheduleRecord(
                    record_id=schedule_id,
                    user_id=owner if isinstance(owner, str) else None,
                    created_at=made if _is_dt(made) else now,
                )
            )
        return out

    def delete(self, record_id: str) -> None:
        self._store.delete(record_id)  # idempotent; an id that is no schedule id is simply not there


def open_schedule_store(
    env: Mapping[str, str] | None = None,
    *,
    clock: Callable[[], datetime] | None = None,
    firestore_client_factory: Callable[[str], Any] | None = None,
) -> ScheduleRepository:
    """The one explicit-config door: `TILO_SCHEDULES_STORE=memory`, or `=firestore` plus a valid
    `TILO_FIRESTORE_PROJECT`; anything else (including no config at all) raises `ScheduleStoreNotConfigured` and builds
    no client."""
    values = os.environ if env is None else env
    kind = values.get("TILO_SCHEDULES_STORE", "")
    if kind == "memory":
        return InMemoryScheduleStore(clock=clock)
    project = values.get("TILO_FIRESTORE_PROJECT", "")
    if kind == "firestore" and _PROJECT.fullmatch(project):
        if firestore_client_factory is not None:
            client = firestore_client_factory(project)
        else:
            from google.cloud import firestore

            client = firestore.Client(project=project)
        return FirestoreScheduleStore(project_id=project, client=client)
    raise ScheduleStoreNotConfigured("set TILO_SCHEDULES_STORE=memory, or =firestore with TILO_FIRESTORE_PROJECT")
