"""The production composition root's Firestore seam (PROD-WIRE 3, ADR-0026 decision 1): one Firestore client per project
per process, and the one guard every door obeys; plus the Firestore-backed SEC-15 access store.

`firestore_client(project)` reads `os.environ` on every call, before the cache, and refuses with
`FirestoreNotConfigured` unless, in order: the project is a valid id (`store_door.GCP_PROJECT`'s shape); on a managed
runtime (`K_SERVICE` or `CLOUD_RUN_JOB` present, even empty) `FIRESTORE_EMULATOR_HOST` is absent (the library enters
emulator mode whenever the variable exists, even empty); a live project opens only when `K_SERVICE` is non-empty, and
anywhere else only an emulator host AND a `demo-` project open, so a laptop that holds real credentials never reaches a
live project; `GOOGLE_CLOUD_PROJECT`, when set, equals the project. A client is built once per project and emulator
host, single-flight, by `build_client`; a build that raises is not cached and surfaces as `FirestoreUnavailable`,
never with the exception text (only its type is logged).

`store_door.client_factory` and the people door's default factory delegate here lazily (this module imports both of
them), so the api store, the people stores, the access store and the ledger share one client object.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import random
import re
import threading
import time
from datetime import date, datetime
from typing import Any

from google.api_core import exceptions as gexc
from google.api_core import retry as retries
from google.auth import exceptions as gauth_exc
from tilo_metering import LedgerEntry
from tilo_metering.prices import Usage

from tilo_api.people_firestore import PeopleStoreNotConfigured
from tilo_api.store_door import GCP_PROJECT, ApiStoreNotConfigured, ApiStoreUnavailable

logger = logging.getLogger("tilo_api.prod")


class FirestoreNotConfigured(ApiStoreNotConfigured, PeopleStoreNotConfigured):
    """The environment does not permit a Firestore client: both doors answer 503 `not_configured`."""


class FirestoreUnavailable(ApiStoreUnavailable):
    """A permitted client could not be built (no credentials, no network): 503 `store_unavailable`, no detail."""


def build_client(project: str) -> Any:
    """The process's Firestore client for `project`, with the runtime identity's ADC; tests replace this."""
    from google.cloud import firestore

    return firestore.Client(project=project)


_clients: dict[tuple[str, str | None], Any] = {}  # keyed by the project and the emulator host it was built for
_building = threading.Lock()


def _guard(project: str) -> str | None:
    """Raises `FirestoreNotConfigured` unless this environment may hold a client for `project`; returns the emulator
    host (None when it is absent or empty)."""
    if not isinstance(project, str) or GCP_PROJECT.fullmatch(project) is None:
        raise FirestoreNotConfigured("not a project id")
    emulator = os.environ.get("FIRESTORE_EMULATOR_HOST")
    if emulator is not None and ("K_SERVICE" in os.environ or "CLOUD_RUN_JOB" in os.environ):
        raise FirestoreNotConfigured("FIRESTORE_EMULATOR_HOST is set on a managed runtime")
    if not os.environ.get("K_SERVICE") and not (emulator and project.startswith("demo-")):
        raise FirestoreNotConfigured("outside Cloud Run only the emulator and a demo- project open")
    if "GOOGLE_CLOUD_PROJECT" in os.environ and os.environ["GOOGLE_CLOUD_PROJECT"] != project:
        raise FirestoreNotConfigured("the project must equal GOOGLE_CLOUD_PROJECT")
    return emulator or None


def firestore_client(project: str) -> Any:
    """The one client for `project` and this emulator host in this process (guarded on every call)."""
    key = (project, _guard(project))
    client = _clients.get(key)
    if client is not None:
        return client
    with _building:
        client = _clients.get(key)
        if client is None:
            try:
                client = build_client(project)
            except Exception as exc:  # no credentials or no network: closed, never cached, never the text
                logger.warning("firestore client unavailable (%s)", type(exc).__name__)
                raise FirestoreUnavailable from None
            _clients[key] = client
        return client


def reset() -> None:
    """Forgets every cached client (a test starts from a cold process)."""
    with _building:
        _clients.clear()


_DECLARATIONS = ("visitor", "judge")
_ATTEMPTS = 8
_LIBRARY_ERRORS = (gexc.GoogleAPICallError, gexc.RetryError, gauth_exc.GoogleAuthError)
_RESERVED_ID = re.compile(r"__.*__", re.DOTALL)


def _is_document_id(value: object) -> bool:
    """What Firestore accepts as a document id: not empty, no `/`, not `.` or `..`, not `__.*__`, at most 1500 bytes."""
    if not isinstance(value, str) or not value or "/" in value or value in {".", ".."}:
        return False
    if _RESERVED_ID.fullmatch(value):
        return False
    try:
        return len(value.encode("utf-8")) <= 1500
    except UnicodeEncodeError:  # a lone surrogate
        return False


class FirestoreAccessStore:
    """SEC-15's declaration kept at `orgs/{org}/access/{uid}` (field `declaration`). First write wins: `declare` is one
    create-if-absent and, on `AlreadyExists`, a read-back. It never calls `set`, `update` or `delete`. A uid Firestore
    refuses as a document id is a `ValueError` before any path is built; a Google API error is `FirestoreUnavailable`
    (503, only its type logged)."""

    def __init__(self, client: Any, org_id: str = "org_tilo") -> None:
        self._client, self._org = client, org_id

    def _ref(self, user_id: str) -> Any:
        if not _is_document_id(user_id):
            raise ValueError("not a Firestore document id")
        return self._client.document(f"orgs/{self._org}/access/{user_id}")

    @staticmethod
    def _declaration(snapshot: Any) -> str | None:
        data = snapshot.to_dict() if snapshot.exists else None
        value = data.get("declaration") if isinstance(data, dict) else None
        return value if isinstance(value, str) and value in _DECLARATIONS else None  # fail closed on anything else

    def get(self, user_id: str) -> Any:
        ref = self._ref(user_id)
        try:
            return self._declaration(ref.get())
        except _LIBRARY_ERRORS as exc:
            logger.warning("access store unavailable (%s)", type(exc).__name__)
            raise FirestoreUnavailable from None

    def declare(self, user_id: str, declaration: Any) -> Any:
        ref = self._ref(user_id)
        if declaration not in _DECLARATIONS:
            raise ValueError("a declaration is visitor or judge")
        try:
            for attempt in range(_ATTEMPTS):
                try:
                    ref.create({"declaration": declaration})
                    return declaration
                except gexc.AlreadyExists:
                    stored = self._declaration(ref.get())
                    if stored is None:  # a document someone wrote by hand: never overwritten, never believed
                        logger.warning("stored access declaration is malformed")
                        raise FirestoreUnavailable from None
                    return stored
                except gexc.Aborted:  # contention on the one document (the emulator's lock timeout): create again
                    time.sleep(random.uniform(0, 0.05 * (attempt + 1)))  # noqa: S311 - jitter, not security
        except _LIBRARY_ERRORS as exc:
            logger.warning("access store unavailable (%s)", type(exc).__name__)
            raise FirestoreUnavailable from None
        logger.warning("access declaration contended beyond %d attempts", _ATTEMPTS)
        raise FirestoreUnavailable from None


_ENTRY_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")
_ISO_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")


class LedgerConflict(Exception):  # noqa: N818 - the name is the ticket's
    """An entry id already holds another body: the first stands, the ledger never overwrites."""


def _encode(entry: LedgerEntry) -> dict[str, Any]:
    """The JSON-safe document body of an entry (`at` and `day` ISO strings, `usage` a dict)."""
    if not isinstance(entry.at, datetime) or entry.at.tzinfo is None:
        raise ValueError("a ledger entry's `at` is a timezone-aware datetime")
    usage = entry.usage
    return {
        "kind": entry.kind, "run": entry.run, "user": entry.user, "org": entry.org, "at": entry.at.isoformat(),
        "step": entry.step, "credits": entry.credits,
        "usage": None if usage is None else {
            "profile": usage.profile, "tokens_in": usage.tokens_in, "tokens_out": usage.tokens_out,
        },
        "price_effective_date": entry.price_effective_date, "price_source": entry.price_source,
        "day": None if entry.day is None else entry.day.isoformat(),
    }  # fmt: skip


def _optional_text(data: dict[str, Any], key: str) -> str | None:
    value = data.get(key)
    if value is not None and not isinstance(value, str):
        raise ValueError(key)
    return value


_KINDS = frozenset({"reserve", "commit", "release", "grant", "usage"})  # `tilo_metering.LedgerEntry.kind`
_CREATE_TIMEOUT_S = 5.0  # one write, with its retries, never waits longer on Firestore than this


def _create_retry(timeout: float) -> Any:
    transient = (gexc.ServiceUnavailable, gexc.DeadlineExceeded, gexc.InternalServerError)
    return retries.Retry(predicate=retries.if_exception_type(*transient), initial=0.1, maximum=1.0, timeout=timeout)


def _decode(data: object, path_org: str | None = None) -> LedgerEntry:
    """The entry a stored body holds, or `ValueError`/`TypeError` (the caller logs the type, never a value). A body
    whose `kind` is not a ledger kind, whose `credits` are negative, or whose `org` is not the path's is refused."""
    if not isinstance(data, dict):
        raise ValueError("body")
    kind, run, user, org, at = (data.get(k) for k in ("kind", "run", "user", "org", "at"))
    if not (isinstance(kind, str) and isinstance(run, str) and isinstance(user, str) and isinstance(org, str)):
        raise ValueError("required")
    if kind not in _KINDS or (path_org is not None and org != path_org):
        raise ValueError("kind or org")
    if not isinstance(at, str):
        raise ValueError("at")
    moment = datetime.fromisoformat(at)
    if moment.tzinfo is None:
        raise ValueError("at")
    credits = data.get("credits")
    if credits is not None and (
        isinstance(credits, bool) or not isinstance(credits, int | float) or not math.isfinite(credits)
    ):
        raise ValueError("credits")
    if credits is not None and credits < 0:
        raise ValueError("credits")
    usage = data.get("usage")
    if usage is not None:
        if not isinstance(usage, dict) or not isinstance(usage.get("profile"), str):
            raise ValueError("usage")
        usage = Usage(usage["profile"], usage.get("tokens_in"), usage.get("tokens_out"))
    day = data.get("day")
    if day is not None and not (isinstance(day, str) and _ISO_DAY.fullmatch(day)):
        raise ValueError("day")
    return LedgerEntry(
        kind, run, user, org, moment,
        step=_optional_text(data, "step"), credits=None if credits is None else float(credits), usage=usage,
        price_effective_date=_optional_text(data, "price_effective_date"),
        price_source=_optional_text(data, "price_source"), day=None if day is None else date.fromisoformat(day),
    )  # fmt: skip


class FirestoreLedger:
    """The Treasury's ledger kept at `orgs/{org}/ledger/{entry_id}` (FR-MTR-10, COST-FAST-1b; ADR-0018 T4: one org).
    Append-only: `append` is one create-if-absent and, on `AlreadyExists`, a read-back (an equal entry is a no-op,
    another body is `LedgerConflict` and changes nothing); it never overwrites or deletes. `entries()` reads the whole
    org collection each time, skips a document that does not decode (logged by exception type) and sorts by
    `(at, entry_id)`. A Google API error is `FirestoreUnavailable` (503, only its type logged)."""

    def __init__(self, client: Any, org_id: str = "org_tilo") -> None:
        if not _is_document_id(org_id):
            raise ValueError("not a Firestore document id")
        self._client, self._org = client, org_id

    def append(self, entry: LedgerEntry, *, entry_id: str) -> None:
        if not isinstance(entry_id, str) or _ENTRY_ID.fullmatch(entry_id) is None:
            raise ValueError("an entry id is 1 to 128 letters, digits, underscores or hyphens")
        if entry.org != self._org:  # entries() would skip it: refused here, before any write
            raise ValueError("the entry's org is not this ledger's org")
        body = _encode(entry)
        ref = self._client.document(f"orgs/{self._org}/ledger/{entry_id}")
        end = time.monotonic() + _CREATE_TIMEOUT_S
        try:
            for attempt in range(_ATTEMPTS):
                remaining = max(end - time.monotonic(), 0.05)
                try:
                    # A bounded wait, transient errors retried: a create that landed before its reply was lost is
                    # `AlreadyExists` on the retry, which reads back and finds the same body (a no-op).
                    ref.create(body, retry=_create_retry(remaining), timeout=remaining)
                    return
                except gexc.AlreadyExists:
                    left = max(end - time.monotonic(), 0.05)
                    snapshot = ref.get(retry=_create_retry(left), timeout=left)  # held to the same budget
                    try:
                        held = _decode(snapshot.to_dict() if snapshot.exists else None, self._org)
                    except (ValueError, TypeError):
                        raise LedgerConflict(entry_id) from None
                    if held != entry:
                        raise LedgerConflict(entry_id) from None
                    return
                except gexc.Aborted:  # contention on the one document (the emulator's lock timeout): create again
                    if time.monotonic() >= end:
                        break
                    time.sleep(random.uniform(0, 0.05 * (attempt + 1)))  # noqa: S311 - jitter, not security
        except _LIBRARY_ERRORS as exc:
            logger.warning("ledger unavailable (%s)", type(exc).__name__)
            raise FirestoreUnavailable from None
        logger.warning("ledger append contended beyond %d attempts", _ATTEMPTS)
        raise FirestoreUnavailable from None

    def append_entry(self, entry: LedgerEntry) -> None:
        """`append` under an id derived from the body, so a retry of the same entry is the same document."""
        canonical = json.dumps(_encode(entry), sort_keys=True, separators=(",", ":"))
        self.append(entry, entry_id=hashlib.sha256(canonical.encode()).hexdigest())

    def entries(self) -> tuple[LedgerEntry, ...]:
        try:
            snapshots = list(self._client.collection(f"orgs/{self._org}/ledger").stream())
        except _LIBRARY_ERRORS as exc:
            logger.warning("ledger unavailable (%s)", type(exc).__name__)
            raise FirestoreUnavailable from None
        found: list[tuple[datetime, str, LedgerEntry]] = []
        for snapshot in snapshots:
            try:
                entry = _decode(snapshot.to_dict(), self._org)
            except (ValueError, TypeError) as exc:
                logger.warning("skipped a ledger document that does not decode (%s)", type(exc).__name__)
                continue
            found.append((entry.at, snapshot.id, entry))
        found.sort(key=lambda item: (item[0], item[1]))
        return tuple(entry for _, _, entry in found)


class FirestoreLedgerWriter:
    """COST-FAST-1b's write seam (`append(entry)`) over a `FirestoreLedger`: a retry of one entry is one document."""

    def __init__(self, ledger: FirestoreLedger) -> None:
        self._ledger = ledger

    def append(self, entry: LedgerEntry) -> None:
        self._ledger.append_entry(entry)
