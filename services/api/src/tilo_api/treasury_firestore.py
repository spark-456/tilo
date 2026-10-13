"""FR-MTR-10 / BQ-MTR10-4 (ticket T3): the Treasury's credit ledger on Firestore, behind `deps.get_ledger` (the read the
cost routes and the effort route make) and `deps.get_ledger_writer` (the write Quick, the Meeting Hall and the live
metering make; see `tilo_api.spend_units.LedgerSink`).

One document per entry at `orgs/{org}/treasury_ledger/{entry id}`, written once with `create` and never changed or
deleted: append-only, and a retried append (same entry id, same terms) finds its document and counts nothing twice.
The same id on other terms is a `ValueError`, never an overwrite. Reads are one equality query on `user` (the signed-in
person's own rows; Firestore's automatic single-field index serves it, no composite index, no rules change: the API's
own service account is the only reader and writer). A read that fails, finds a document it cannot parse, or finds more
than `MAX_ENTRIES` raises: the seam turns that into 503, so a report is complete or absent (HR-1), never partial.
Nothing here prices anything: an entry is the credits its writer recorded."""

from __future__ import annotations

import logging
import math
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from google.api_core import exceptions as gexc
from google.cloud.firestore_v1.base_query import FieldFilter
from tilo_metering import LedgerEntry
from tilo_metering.prices import Usage

logger = logging.getLogger("tilo_api.treasury_firestore")
COLLECTION = "treasury_ledger"
MAX_ENTRIES = 5000  # one person's rows in one read; more is refused (503), never truncated
_KINDS = frozenset({"reserve", "commit", "release", "grant", "usage"})
_ENTRY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$")
_ATTEMPTS = 3
_USAGE_FIELDS = ("profile", "tokens_in", "tokens_out", "tokens_cached", "units", "tokens_audio")


class LedgerUnreadable(Exception):
    """A document that is not an entry, or more rows than one read serves."""


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


class FirestoreTreasuryLedger:
    def __init__(self, client: Any, *, org_id: str) -> None:
        self._client, self._org = client, _text(org_id, "org_id")

    def _collection(self) -> Any:
        return self._client.collection(f"orgs/{self._org}/{COLLECTION}")

    def append(self, entry: LedgerEntry) -> None:
        """One new entry, with an id of its own."""
        self.append_once(f"e_{uuid.uuid4().hex}", entry)

    def append_once(self, entry_id: str, entry: LedgerEntry) -> None:
        """The entry under `entry_id`, written once: the same id and terms again is a no-op, other terms a
        `ValueError`. A store error raises (the writer's caller decides what a failed write means)."""
        if not isinstance(entry_id, str) or not _ENTRY_ID.fullmatch(entry_id):
            raise ValueError("an entry id is 1 to 200 letters, digits and _ . : -")
        doc = _doc(entry, self._org)
        ref = self._client.document(f"orgs/{self._org}/{COLLECTION}/{entry_id}")
        for attempt in range(_ATTEMPTS):
            try:
                ref.create({**doc, "recorded_at": datetime.now(UTC).isoformat()})
                return
            except gexc.AlreadyExists:
                stored = ref.get().to_dict() or {}
                if any(stored.get(k) != v for k, v in doc.items()):
                    raise ValueError("this entry id was recorded on other terms") from None
                return
            except (gexc.Aborted, gexc.ServiceUnavailable, gexc.DeadlineExceeded):
                if attempt == _ATTEMPTS - 1:
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
