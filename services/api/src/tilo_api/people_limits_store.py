"""The people write limiter on the people stores' own Firestore client (PPL-11c-FS-2 (a); SEC-10; PE-19; FR-MEM-09;
tests/API_PPL_11c_FS_2.md).

Two collections under `orgs/{deps.ORG_ID}/`, outside every `people_*` record collection, every document with an aware
`expires_at` (a TTL policy on it is infra; an expired document that is still stored is ignored here):

* `limiter_counters/{sha256(uid)}`: `hits`, the accepted attempts of the sliding minute (floats of the request clock).
  A transaction reads, prunes, and writes the new hit only when fewer than 60 remain, so instances never double-count.
  `expires_at` = clock + 120 s (a counter must outlive the minute it counts).
* `limiter_keys/{sha256(uid, route, key)}`: `p` (hash of the uid, for erasure), `fp` (body fingerprint), `kind`, `rid`
  (a reference to the record, never answer text; `None` is the principal's own record), `state` and `token`.
  `pending` is a claim made in a transaction before `make()` runs (so racing retries create once; it lapses after
  5 minutes); `done` lasts 24 h of the request clock. A replay re-reads the record by reference; a record that is gone
  (erased or undone) frees the key. A claim whose answer was lost is recognised by its `token`.

A failure of the store leaves as `HTTPException(503, "unavailable")`: no key, body or library text is raised, logged
or stored. No model call, no log, no clock read (`now` is handed in).
"""

from __future__ import annotations

import hashlib
import math
import re
import secrets
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException
from google.api_core import exceptions as gexc
from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter
from pydantic import BaseModel
from tilo_people.access import project

from tilo_api import deps
from tilo_api.people_limits import _KEY, WRITES_PER_MINUTE, Limits
from tilo_api.people_writes import Refusal

COUNTER_TTL = timedelta(seconds=120)
KEY_TTL = timedelta(hours=24)
CLAIM_TTL = timedelta(minutes=5)
_KINDS = {
    "/v1/meetings": "meeting",
    "/v1/people": "person",
    "/v1/people/first": "person",
    "/v1/work-items": "work_item",
}
_ORG = re.compile(r"org_[0-9A-Za-z_]{1,48}")
_UID = re.compile(r"u_[0-9A-Za-z_]{1,48}")


def _unavailable() -> HTTPException:
    return HTTPException(503, "unavailable")  # the one fixed body: never the library's text


def _hash(*parts: str) -> str:
    return hashlib.sha256("\0".join(parts).encode()).hexdigest()


def _ordered(value: Any) -> Any:
    """Same response bytes before/after Firestore's map ordering, without storing answer text."""
    if isinstance(value, dict):
        return {key: _ordered(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        return [_ordered(item) for item in value]
    return value


def _live(doc: dict[str, Any] | None, now: datetime) -> bool:
    stamp = None if doc is None else doc.get("expires_at")
    return isinstance(stamp, datetime) and stamp > now


class DurableLimits(Limits):
    """The same `attempt`/`once` as `Limits`, over Firestore; one per `PeopleStores`, sharing its client."""

    def __init__(self, client: Any, record_stores: dict[str, Any]) -> None:
        super().__init__()
        self._c, self._records = client, record_stores

    def _collection(self, name: str, org_id: str | None = None) -> str:
        return f"orgs/{deps.ORG_ID if org_id is None else org_id}/{name}"

    def _txn(self, work: Callable[[Any], Any]) -> Any:
        """One serializable transaction, retried on contention; any other failure is the fixed 503."""
        for _ in range(4):
            try:
                return firestore.transactional(work)(self._c.transaction())
            except gexc.Aborted:
                continue
            except Exception:
                break
        raise _unavailable() from None

    def attempt(self, user_id: str, now: float, *, limit: int = WRITES_PER_MINUTE) -> None:
        ref = self._c.document(f"{self._collection('limiter_counters')}/{_hash('c', user_id)}")
        at = datetime.fromtimestamp(now, UTC)

        def work(txn: Any) -> int | None:
            snap = ref.get(transaction=txn)
            doc = snap.to_dict() if snap.exists else None
            held = sorted(h for h in doc["hits"] if h > now - 60) if _live(doc, at) and doc else []
            if len(held) >= limit:
                return min(60, max(1, math.ceil(held[0] + 60 - now)))  # a refused attempt is not counted
            txn.set(ref, {"hits": [*held, now], "expires_at": at + COUNTER_TTL})
            return None

        wait = self._txn(work)
        if wait is not None:
            raise Refusal(429, "rate_limited", headers={"Retry-After": str(wait)}, code="rate_limited")

    def _claim(self, ref: Any, mine: dict[str, Any], at: datetime, stale: str | None) -> tuple[bool, dict[str, Any]]:
        def work(txn: Any) -> tuple[bool, dict[str, Any]]:
            snap = ref.get(transaction=txn)
            doc = snap.to_dict() if snap.exists else None
            if _live(doc, at) and doc and doc.get("token") != stale:
                return False, doc
            txn.set(ref, mine)
            return True, mine

        return self._txn(work)  # type: ignore[no-any-return]

    def _recognise(self, ref: Any, token: str, at: datetime) -> tuple[bool, dict[str, Any]] | None:
        """A claim that failed may have landed (a lost answer): is the document ours?"""
        try:
            snap = ref.get()
            doc = snap.to_dict() if snap.exists else None
        except Exception:
            return None
        return (doc.get("token") == token, doc) if doc is not None and _live(doc, at) else None

    def _read(self, kind: str, rid: str) -> dict[str, Any] | None:
        try:
            found = self._records[kind].get(deps.ORG_ID, rid)
        except Exception:
            raise _unavailable() from None
        if found is None:
            return None
        if kind == "person":
            return project("person", "membership", found.record) or {}
        return None if found.record.get("status") == "deleted" else dict(found.record)

    def _retry(self, step: Callable[[], Any]) -> bool:
        for _ in range(3):
            try:
                step()
                return True
            except Exception:  # noqa: S112 - idempotent step; the failure is never echoed or logged
                continue
        return False

    def once(
        self,
        user_id: str,
        route: str,
        key: str,
        body: BaseModel,
        make: Callable[[], dict[str, Any]],
        now: float | None = None,
    ) -> dict[str, Any]:
        if _KEY.fullmatch(key) is None:
            raise Refusal(422, "invalid_idempotency_key")  # never echoes the key
        if now is None or route not in _KINDS:
            raise _unavailable()
        kind, at = _KINDS[route], datetime.fromtimestamp(now, UTC)
        fp = _hash("fp", user_id, route, key, body.model_dump_json())
        ref = self._c.document(f"{self._collection('limiter_keys')}/{_hash('k', user_id, route, key)}")
        token = secrets.token_hex(8)
        claim = {"p": _hash("p", user_id), "fp": fp, "kind": kind, "rid": None, "state": "pending", "token": token}
        stale: str | None = None
        for _ in range(25):
            try:
                won, doc = self._claim(ref, {**claim, "expires_at": at + CLAIM_TTL}, at, stale)
            except HTTPException:
                found = self._recognise(ref, token, at)
                if found is None:
                    raise
                won, doc = found
            if won:
                break
            if doc["fp"] != fp:
                raise Refusal(422, "idempotency_key_reused", code="idempotency_key_reused")
            if doc["state"] == "done":
                replay = self._read(kind, doc["rid"] or user_id)
                if replay is not None:
                    return _ordered(replay)
                stale = doc["token"]  # the record is gone (erased or undone): the key is free
            else:
                time.sleep(0.05)  # another request holds the claim: its answer is what this one replays
        else:
            raise Refusal(409, "request_in_flight", code="request_in_flight")
        try:
            answer = make()
        except BaseException:
            self._retry(ref.delete)  # nothing was created: the key stays free
            raise
        rid = answer["id"]
        done = {**claim, "rid": None if rid == user_id else rid, "state": "done", "expires_at": at + KEY_TTL}
        self._retry(lambda: ref.set(done))  # if this never lands the claim lapses; the answer was created, so it stands
        return _ordered(answer)

    def erase_person(self, org_id: str, user_id: str) -> int:
        if _ORG.fullmatch(org_id) is None or _UID.fullmatch(user_id) is None:
            raise ValueError("malformed id")  # nothing is deleted for an id that is not plainly one
        try:
            refs = [
                snap.reference
                for snap in self._c.collection(self._collection("limiter_keys", org_id))
                .where(filter=FieldFilter("p", "==", _hash("p", user_id)))
                .stream()
            ]
            counter = self._c.document(f"{self._collection('limiter_counters', org_id)}/{_hash('c', user_id)}")
            if counter.get().exists:
                refs.append(counter)
            for start in range(0, len(refs), 400):
                batch = self._c.batch()
                for doomed in refs[start : start + 400]:
                    batch.delete(doomed)
                batch.commit()
        except Exception:
            raise RuntimeError("the limiter store is unavailable") from None  # a partial erase is never reported done
        return len(refs)
