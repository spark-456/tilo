"""FR-MTR-10 / BQ-MTR10-4 (ticket T3): the Treasury's credit ledger on Firestore, behind `deps.get_ledger` (the read the
cost routes and the effort route make) and `deps.get_ledger_writer` (the write Quick, the Meeting Hall and the live
metering make; see `tilo_api.spend_units.LedgerSink`).

One document per entry at `orgs/{org}/treasury_ledger/{entry id}`, written once with `create` and never changed or
deleted: append-only, and a retried append (same entry id, same terms) finds its document and counts nothing twice.
The same id on other terms is a `ValueError`, never an overwrite.

T3b (BQ-T3-5): each entry is also folded, in the SAME transaction, into one rollup per person per run at
`orgs/{org}/treasury_rollup/{hash}` (credits per (step, profile) bucket). The cost routes read those (`summary_for`,
one equality query on `user`, no composite index, no rules change), never every entry, so a person with thousands of
small entries is never refused; the entries stay the audit record (`entries_page`). A read that fails, finds a
document it cannot parse or more than `MAX_RUNS` rollups raises: the seam turns that into 503, so a report is complete
or absent (HR-1). Nothing here prices anything: an entry is the credits its writer recorded."""

from __future__ import annotations

import hashlib
import logging
import math
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from google.api_core import exceptions as gexc
from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter
from tilo_metering import LedgerEntry
from tilo_metering.prices import Usage

logger = logging.getLogger("tilo_api.treasury_firestore")
COLLECTION = "treasury_ledger"
ROLLUP = "treasury_rollup"
MAX_ENTRIES = 5000  # `entries_for`, the whole-audit read no route makes any more; more is refused, never truncated
MAX_RUNS = 10_000  # one person's rollups in one read (a run is a world, a room, Quick or the live pseudo run)
MAX_BUCKETS = 500  # (step, profile) buckets in one rollup; the rest fold into (None, None), never a failed write
PAGE_MAX = 200  # `entries_page`'s hard page size
_KINDS = frozenset({"reserve", "commit", "release", "grant", "usage"})
_ENTRY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$")
_ATTEMPTS = 3
_USAGE_FIELDS = ("profile", "tokens_in", "tokens_out", "tokens_cached", "units", "tokens_audio")


class LedgerUnreadable(Exception):
    """A document that is not an entry or a rollup, or more rows than one read serves."""


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value or len(value.encode("utf-8", "replace")) > 400:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _doc(entry: LedgerEntry, org_id: str) -> dict[str, Any]:
    if not isinstance(entry, LedgerEntry) or entry.kind not in _KINDS:
        raise ValueError("not a ledger entry")
    if _text(entry.org, "org") != org_id:
        raise ValueError("the entry is another org's")
    if not isinstance(entry.at, datetime) or entry.at.tzinfo is None:
        raise ValueError("`at` must be a timezone-aware datetime")
    credits = entry.credits
    if credits is not None and (
        isinstance(credits, bool) or not isinstance(credits, int | float) or not math.isfinite(credits) or credits < 0
    ):
        raise ValueError("credits must be a finite number >= 0")
    usage = entry.usage
    if usage is not None and not isinstance(usage, Usage):
        raise ValueError("usage must be a `Usage`")
    return {
        "kind": entry.kind, "run": _text(entry.run, "run"), "user": _text(entry.user, "user"), "org": entry.org,
        "at": entry.at.astimezone(UTC).isoformat(), "step": entry.step if isinstance(entry.step, str) else None,
        "credits": None if credits is None else float(credits),
        "usage": None if usage is None else {name: getattr(usage, name) for name in _USAGE_FIELDS},
        "price_effective_date": entry.price_effective_date, "price_source": entry.price_source,
        "day": entry.day.isoformat() if entry.day is not None else None,
    }  # fmt: skip


def _entry(data: Any, org_id: str) -> LedgerEntry:
    """A stored document as an entry; anything unexpected is `LedgerUnreadable` (the whole read is refused)."""
    try:
        if not isinstance(data, dict) or data.get("org") != org_id:
            raise ValueError("not this org's entry")
        usage = data.get("usage")
        entry = LedgerEntry(
            kind=data["kind"], run=_text(data["run"], "run"), user=_text(data["user"], "user"), org=org_id,
            at=datetime.fromisoformat(data["at"]), step=data.get("step"), credits=data.get("credits"),
            usage=None if usage is None else Usage(**{name: usage[name] for name in _USAGE_FIELDS}),
            price_effective_date=data.get("price_effective_date"), price_source=data.get("price_source"),
            day=datetime.fromisoformat(data["day"]).date() if data.get("day") else None,
        )  # fmt: skip
        if _doc(entry, org_id)["credits"] != entry.credits or not isinstance(data.get("step"), str | None):
            raise ValueError("a field is not what an entry holds")
        return entry
    except (KeyError, TypeError, ValueError) as exc:
        raise LedgerUnreadable("a ledger document is malformed") from exc


def _number(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, int | float) and math.isfinite(value) and value >= 0


def _rollup_run(user: str, run: str) -> str:
    """The run a rollup is kept under: a meter's own request, task or world id is the person's one live pseudo run
    (as `/costs` shows it), so unattributed spend is one document and never one per request."""
    from tilo_api.spend_units import UNATTRIBUTED, live_run_id  # noqa: PLC0415  (spend_units imports deps)

    return live_run_id(user) if run.startswith(UNATTRIBUTED) else run


def _fold(prev: Any, entry: LedgerEntry, run: str) -> dict[str, Any]:
    """The rollup after `entry`: only `commit` credits are spend (`cost_report`), every kind counts as an entry."""
    if prev is None:
        prev = {"user": entry.user, "org": entry.org, "run": run, "entries": 0, "credits": 0.0, "buckets": []}
    if not isinstance(prev, dict) or (prev.get("user"), prev.get("run")) != (entry.user, run):
        raise ValueError("the rollup is not this person's run")
    buckets = [dict(b) for b in prev["buckets"]]
    credits = float(entry.credits or 0.0) if entry.kind == "commit" else 0.0
    if entry.kind == "commit":
        key = (entry.step if isinstance(entry.step, str) else None, entry.usage.profile if entry.usage else None)
        if len(buckets) >= MAX_BUCKETS and not any((b["step"], b["profile"]) == key for b in buckets):
            key = (None, None)
        bucket = next((b for b in buckets if (b["step"], b["profile"]) == key), None)
        if bucket is None:
            buckets.append(bucket := {"step": key[0], "profile": key[1], "credits": 0.0, "entries": 0})
        bucket["credits"] += credits
        bucket["entries"] += 1
    last = max(str(prev.get("last_entry_at") or ""), entry.at.astimezone(UTC).isoformat())
    return {**prev, "entries": prev["entries"] + 1, "credits": prev["credits"] + credits, "buckets": buckets,
            "last_entry_at": last}  # fmt: skip


def _summary(data: Any, org_id: str) -> list[LedgerEntry]:
    """A rollup as one `commit` entry per (step, profile) bucket; anything unexpected is `LedgerUnreadable`."""
    try:
        if not isinstance(data, dict) or data.get("org") != org_id:
            raise ValueError("not this org's rollup")
        user, run = _text(data["user"], "user"), _text(data["run"], "run")
        at = datetime.fromisoformat(data["last_entry_at"])
        if not (_number(data["credits"]) and _number(data["entries"])):
            raise ValueError("a total is not a number")
        rows = []
        for b in data["buckets"]:
            step, profile = b["step"], b["profile"]
            if not (isinstance(step, str | None) and isinstance(profile, str | None) and _number(b["credits"])):
                raise ValueError("a bucket is malformed")
            usage = None if profile is None else Usage(profile, 0, 0)
            rows.append(
                LedgerEntry("commit", run, user, org_id, at, step=step, credits=float(b["credits"]), usage=usage)
            )
        return rows
    except (KeyError, TypeError, ValueError) as exc:
        raise LedgerUnreadable("a rollup document is malformed") from exc


class FirestoreTreasuryLedger:
    def __init__(self, client: Any, *, org_id: str) -> None:
        self._client, self._org = client, _text(org_id, "org_id")

    def _collection(self, name: str = COLLECTION) -> Any:
        return self._client.collection(f"orgs/{self._org}/{name}")

    def append(self, entry: LedgerEntry) -> None:
        """One new entry, with an id of its own."""
        self.append_once(f"e_{uuid.uuid4().hex}", entry)

    def append_once(self, entry_id: str, entry: LedgerEntry) -> None:
        """The entry under `entry_id`, written once and folded into its run's rollup in the same transaction: the same
        id and terms again is a no-op (counted once in both), other terms a `ValueError`. A store error raises (the
        writer's caller decides what a failed write means)."""
        if not isinstance(entry_id, str) or not _ENTRY_ID.fullmatch(entry_id):
            raise ValueError("an entry id is 1 to 200 letters, digits and _ . : -")
        doc = _doc(entry, self._org)
        run = _rollup_run(doc["user"], doc["run"])
        rolled = hashlib.sha256(f"{doc['user']}\x00{run}".encode()).hexdigest()[:40]
        ref = self._client.document(f"orgs/{self._org}/{COLLECTION}/{entry_id}")
        roll = self._client.document(f"orgs/{self._org}/{ROLLUP}/{rolled}")

        @firestore.transactional  # type: ignore[misc]
        def txn(tx: Any) -> None:
            stored, previous = ref.get(transaction=tx), roll.get(transaction=tx)  # every read before any write
            if stored.exists:  # counted already, entry and rollup together
                if any((stored.to_dict() or {}).get(k) != v for k, v in doc.items()):
                    raise ValueError("this entry id was recorded on other terms")
                return
            tx.create(ref, {**doc, "recorded_at": datetime.now(UTC).isoformat()})
            tx.set(roll, _fold(previous.to_dict() if previous.exists else None, entry, run))

        for attempt in range(_ATTEMPTS):
            try:
                txn(self._client.transaction())
                return
            except (gexc.Aborted, gexc.ServiceUnavailable, gexc.DeadlineExceeded):
                if attempt == _ATTEMPTS - 1:
                    raise
            except ValueError as exc:  # the library's "failed in N attempts" wraps the Aborted it gave up on
                if not isinstance(exc.__cause__, gexc.Aborted) or attempt == _ATTEMPTS - 1:
                    raise

    def entries_for(self, user_id: str) -> list[LedgerEntry]:
        """Every entry of `user_id`, oldest first. Raises when it cannot give the whole set."""
        query = self._collection().where(filter=FieldFilter("user", "==", _text(user_id, "user_id")))
        snapshots = list(query.limit(MAX_ENTRIES + 1).stream())
        if len(snapshots) > MAX_ENTRIES:
            logger.error("treasury_ledger_too_large")
            raise LedgerUnreadable("more rows than one read serves")
        rows = [(_entry(s.to_dict(), self._org), str(s.id)) for s in snapshots]
        return [entry for entry, _id in sorted(rows, key=lambda r: (r[0].at, r[1]))]

    def summary_for(self, user_id: str) -> list[LedgerEntry]:
        """The person's spend as one `commit` per (run, step, profile) from their rollups: what the cost routes read.
        Raises when it cannot give the whole set (BQ-T3-5)."""
        query = self._collection(ROLLUP).where(filter=FieldFilter("user", "==", _text(user_id, "user_id")))
        snapshots = list(query.limit(MAX_RUNS + 1).stream())
        if len(snapshots) > MAX_RUNS:
            logger.error("treasury_rollup_too_large")
            raise LedgerUnreadable("more rollups than one read serves")
        rows = [e for s in snapshots for e in _summary(s.to_dict(), self._org)]
        if any(e.user != user_id for e in rows):
            raise LedgerUnreadable("a rollup is another person's")
        return sorted(rows, key=lambda e: (e.run, e.step or "", e.usage.profile if e.usage else ""))

    def entries_page(
        self, user_id: str, *, after: str | None = None, limit: int = 100
    ) -> tuple[list[LedgerEntry], str | None]:
        """The audit drill-down: one page of the person's own entries in entry-id order, and the cursor of the next
        page (None at the end). The page size is at most `PAGE_MAX`; `after` is an entry id of the same shape."""
        if after is not None and not (isinstance(after, str) and _ENTRY_ID.fullmatch(after)):
            raise ValueError("a cursor is an entry id")
        size = max(1, min(int(limit), PAGE_MAX))
        query = self._collection().where(filter=FieldFilter("user", "==", _text(user_id, "user_id")))
        query = query.order_by("__name__").limit(size + 1)
        snapshots = list((query if after is None else query.start_after({"__name__": after})).stream())
        page = snapshots[:size]
        return [_entry(s.to_dict(), self._org) for s in page], (str(page[-1].id) if len(snapshots) > size else None)
