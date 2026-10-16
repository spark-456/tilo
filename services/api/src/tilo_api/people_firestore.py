"""Firestore adapters for the people API's record stores (PPL-11c-FS, services/api/tests/API_PPL_11c_FS.md).

`tilo_people` stays pure, so the adapter lives here. Layout: `orgs/{org}/people_{kind}/{id}` holds exactly
`{"version": n, "record": <record>}`; the founder marker is `orgs/{org}/people_directory/founder` (`{"uid"}`); an
address is reserved at `orgs/{org}/people_directory/email_{sha256 hex of the lower-cased address}`
(`{"person_id"}`), so the address is in the person record only. A single-document compare-and-set or create uses a
write precondition (`exists=False`, `last_update_time`); transactions are only for the multi-document steps. Errors
are `tilo_people` errors that name kind, id and versions, never record text, an address or a library exception.
Nothing here does I/O until a store method is called, and nothing logs.
"""

from __future__ import annotations

import contextlib
import copy
import hashlib
import os
import random
import re
import time
from collections.abc import Callable, Iterator, Mapping
from typing import Any

from google.api_core import exceptions as gexc
from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter
from tilo_people._schema import valid
from tilo_people.errors import (
    AlreadyExists,
    EmailTaken,
    LastPerson,
    NotFound,
    OrgAlreadyFounded,
    PeopleError,
    PeopleInputError,
    VersionConflict,
)
from tilo_people.stores import BOUNDED_INDEXES, INDEXES, PeopleStores, Stored

_ORG = re.compile(r"org_[0-9A-Za-z_]{1,48}")
_IDS = {
    "person": re.compile(r"u_[0-9A-Za-z_]{1,48}"),
    "meeting": re.compile(r"mt_[0-9A-Za-z_]{1,48}"),
    "work_item": re.compile(r"wi_[0-9A-Za-z_]{1,48}"),
    "pinboard_item": re.compile(r"pb_[0-9A-Za-z_]{1,48}"),
    "mention": re.compile(r"mn_[0-9A-Za-z_]{1,48}"),
    "calendar_entry": re.compile(r"ce_[0-9A-Za-z_]{1,48}"),
    "world_share": re.compile(r"ws_[0-9a-f]{32}"),  # ADR-0040: derived from the world and the team, never minted
}
_DEMO_PROJECT = re.compile(r"demo-[0-9a-z-]+")
_PROJECT = re.compile(r"[a-z][a-z0-9-]{4,28}[a-z0-9]")
_SAFE_ID = re.compile(r"[A-Za-z0-9_.-]{1,128}")
_ATTEMPTS = 8
_CONTENDED = (gexc.FailedPrecondition, gexc.Aborted, gexc.NotFound)
_LOCK_WAIT = (gexc.Aborted, gexc.Conflict)  # `AlreadyExists` is a Conflict too: caught first, never retried


class PeopleStoreNotConfigured(RuntimeError):
    """`open_people_stores` was not given an explicit Firestore choice and a valid project."""


def _safe(value: Any) -> str:
    """An id for a message; anything that is not plainly an id is not echoed."""
    return value if isinstance(value, str) and _SAFE_ID.fullmatch(value) else "<malformed>"


@contextlib.contextmanager
def _guarded() -> Iterator[None]:
    """Whatever a Firestore call raises leaves as a plain `PeopleError` with no cause text."""
    try:
        yield
    except PeopleError:
        raise
    except Exception:
        raise PeopleError("the people store is unavailable") from None


def _pause(attempt: int) -> None:
    time.sleep(random.uniform(0, 0.02 * 2**attempt))


def _digest(email: str) -> str:
    return hashlib.sha256(email.lower().encode("utf-8")).hexdigest()


def _doc(version: int, record: Mapping[str, Any]) -> dict[str, Any]:
    return {"version": version, "record": copy.deepcopy(dict(record))}


class FirestoreRecordStore:
    """A `RecordStore` for one kind of `INDEXES` on Firestore, same behaviour as `MemoryStore`."""

    def __init__(self, client: Any, kind: str) -> None:
        if not isinstance(kind, str) or kind not in INDEXES:
            raise PeopleInputError("unknown record kind")
        self._client, self.kind = client, kind
        self._schema, self._id = f"{kind}.schema.json", _IDS[kind]

    def __repr__(self) -> str:
        return f"{type(self).__name__}(kind={self.kind!r})"

    # -- addressing: an id reaches a path only after its pattern ----------------------------------------------------
    def _addressable(self, org_id: Any, record_id: Any) -> bool:
        return (
            isinstance(org_id, str)
            and isinstance(record_id, str)
            and _ORG.fullmatch(org_id) is not None
            and self._id.fullmatch(record_id) is not None
        )

    def _ref(self, org_id: str, record_id: str) -> Any:
        return self._client.document(f"orgs/{org_id}/people_{self.kind}/{record_id}")

    def _collection(self, org_id: str) -> Any:
        return self._client.collection(f"orgs/{org_id}/people_{self.kind}")

    def _checked(self, record: Any) -> tuple[str, str]:
        if not isinstance(record, Mapping) or not valid(self._schema, record):
            raise PeopleInputError(f"malformed {self.kind} record")
        if not self._addressable(record["org_id"], record["id"]):
            raise PeopleInputError(f"malformed {self.kind} record")
        return record["org_id"], record["id"]

    @staticmethod
    def _version(expected_version: Any) -> int:
        if type(expected_version) is not int:
            raise PeopleInputError("expected_version must be an int")
        return expected_version

    def _stored(self, snap: Any) -> Stored:
        data = snap.to_dict()
        return Stored(self.kind, data["record"], int(data["version"]))

    def _conflict(self, record_id: str, expected: int, current: Any) -> VersionConflict:
        return VersionConflict(f"VersionConflict: {self.kind} {_safe(record_id)} expected {expected} current {current}")

    # -- the RecordStore calls --------------------------------------------------------------------------------------
    def get(self, org_id: str, record_id: str) -> Stored | None:
        if not self._addressable(org_id, record_id):
            return None
        with _guarded():
            snap = self._ref(org_id, record_id).get()
            return self._stored(snap) if snap.exists else None

    def create(self, record: Mapping[str, Any]) -> Stored:
        org, rid = self._checked(record)
        data = _doc(1, record)
        ref = self._ref(org, rid)
        with _guarded():
            for attempt in range(_ATTEMPTS):
                try:
                    ref.create(data)
                except gexc.AlreadyExists:
                    # after a contention retry our own create may have landed (a lost answer): the same document is ours
                    if attempt and self._is(ref, data):
                        break
                    raise AlreadyExists(f"AlreadyExists: {self.kind} {rid}") from None
                except _LOCK_WAIT:  # the emulator's "409 Transaction lock timeout" (Aborted): try again, bounded
                    _pause(attempt)
                    continue
                break
            else:
                raise PeopleError("the people store is busy")
        return Stored(self.kind, copy.deepcopy(data["record"]), 1)

    @staticmethod
    def _is(ref: Any, data: Mapping[str, Any]) -> bool:
        snap = ref.get()
        return bool(snap.exists and snap.to_dict() == data)

    def replace(self, record: Mapping[str, Any], *, expected_version: int) -> Stored:
        org, rid = self._checked(record)
        expected = self._version(expected_version)
        data = _doc(expected + 1, record)
        ref = self._ref(org, rid)
        with _guarded():
            for attempt in range(_ATTEMPTS):
                snap = ref.get()
                if not snap.exists:
                    raise NotFound(f"NotFound: {self.kind} {rid}")
                current = snap.get("version")
                if current != expected:
                    raise self._conflict(rid, expected, current)
                try:
                    ref.update(data, option=self._client.write_option(last_update_time=snap.update_time))
                except _CONTENDED:
                    _pause(attempt)  # changed under us: read again, which says which error it now is
                    continue
                return Stored(self.kind, copy.deepcopy(data["record"]), expected + 1)
        raise self._conflict(rid, expected, "changing")

    def delete(self, org_id: str, record_id: str, *, expected_version: int) -> None:
        expected = self._version(expected_version)
        if not self._addressable(org_id, record_id):
            raise NotFound(f"NotFound: {self.kind} {_safe(record_id)}")
        ref = self._ref(org_id, record_id)
        with _guarded():
            for attempt in range(_ATTEMPTS):
                snap = ref.get()
                if not snap.exists:
                    raise NotFound(f"NotFound: {self.kind} {record_id}")
                current = snap.get("version")
                if current != expected:
                    raise self._conflict(record_id, expected, current)
                try:
                    ref.delete(option=self._client.write_option(last_update_time=snap.update_time))
                except _CONTENDED:
                    _pause(attempt)
                    continue
                return
        raise self._conflict(record_id, expected, "changing")

    def list(self, org_id: str, field: str | None = None, value: str | None = None) -> tuple[Stored, ...]:
        if field is not None and (not isinstance(field, str) or field not in INDEXES[self.kind]):
            raise PeopleInputError(f"{self.kind} has no such index")
        if field is not None and not isinstance(value, str):
            raise PeopleInputError("index value must be a string")
        if not isinstance(org_id, str) or _ORG.fullmatch(org_id) is None:
            return ()
        with _guarded():
            query = self._collection(org_id)
            if field is not None:
                query = query.where(filter=FieldFilter(f"record.{field}", "==", value))
            rows = [self._stored(snap) for snap in query.stream()]
        return tuple(sorted(rows, key=lambda s: s.record["id"]))

    def list_bounded(self, org_id: str, field: str, value: str, *, limit: int) -> tuple[Stored, ...]:
        if field not in BOUNDED_INDEXES[self.kind] or not isinstance(value, str) or type(limit) is not int or limit < 1:
            raise PeopleInputError("invalid bounded index query")
        if not isinstance(org_id, str) or _ORG.fullmatch(org_id) is None:
            return ()
        rows = []
        with _guarded():
            query = self._collection(org_id).where(filter=FieldFilter(f"record.{field}", "==", value)).limit(limit)
            for snap in query.stream():
                try:
                    rows.append(self._stored(snap))
                except (KeyError, TypeError, ValueError, OverflowError):
                    continue  # corrupt document only; stream/storage failures still reach the caller
        return tuple(rows)


class FirestorePersonStore(FirestoreRecordStore):
    """The person store: every write keeps one address reservation per person, in one transaction with the record;
    `create_founder` writes the founder marker, the person and its reservation in one."""

    def __init__(self, client: Any) -> None:
        super().__init__(client, "person")

    def _directory(self, org_id: str, name: str) -> Any:
        return self._client.document(f"orgs/{org_id}/people_directory/{name}")

    def _reservation(self, org_id: str, email: str) -> Any:
        return self._directory(org_id, f"email_{_digest(email)}")

    def _transact(self, work: Callable[[Any], Any], pid: str) -> Any:
        """Runs `work(transaction)` and retries contention (a lost commit, or a lock that was not granted). A document
        a rival created between our read and our commit is reported by the path in the error (FS-16)."""
        for attempt in range(_ATTEMPTS):
            try:
                return firestore.transactional(work)(self._client.transaction())
            except gexc.Aborted:
                pass
            except gexc.AlreadyExists as exc:
                raise _collided(str(exc), pid) from None
            except ValueError as exc:  # the library's "failed in N attempts" wraps the Aborted it gave up on
                if not isinstance(exc.__cause__, gexc.Aborted):
                    raise
            _pause(attempt)
        raise PeopleError("the people store is busy")

    # A transaction reads first and writes last (the SDK refuses a read after a buffered write): `_slot` is the read
    # of an address's reservation, `_claim` and `_release` are the writes that follow once every read is done.
    def _slot(self, txn: Any, org: str, email: str) -> tuple[Any, Any]:
        ref = self._reservation(org, email)
        return ref, ref.get(transaction=txn)

    @staticmethod
    def _claim(txn: Any, slot: tuple[Any, Any], pid: str) -> None:
        """Reserves the address for the person: created (never set) when the read found none, `EmailTaken` when another
        person holds it; one the person already holds is left as it is."""
        ref, held = slot
        if not held.exists:
            txn.create(ref, {"person_id": pid})
        elif held.get("person_id") != pid:
            raise EmailTaken(f"EmailTaken: person {pid}")

    @staticmethod
    def _release(txn: Any, slot: tuple[Any, Any], pid: str) -> None:
        """Deletes the person's reservation; one held by someone else fails the whole transaction (nothing is written,
        no address or text in the error), an absent one is no error."""
        ref, held = slot
        if held.exists:
            if held.get("person_id") != pid:
                raise PeopleError("the people store is inconsistent")
            txn.delete(ref)

    def create(self, record: Mapping[str, Any]) -> Stored:
        org, pid = self._checked(record)
        data, ref = _doc(1, record), self._ref(org, pid)

        def work(txn: Any) -> None:
            exists, slot = ref.get(transaction=txn).exists, self._slot(txn, org, record["email"])
            if exists:
                raise AlreadyExists(f"AlreadyExists: person {pid}")
            self._claim(txn, slot, pid)
            txn.create(ref, data)

        with _guarded():
            self._transact(work, pid)
        return Stored(self.kind, copy.deepcopy(data["record"]), 1)

    def create_founder(self, record: Mapping[str, Any]) -> Stored:
        org, pid = self._checked(record)
        if record.get("org_role") != "owner":
            raise PeopleInputError("a founder is an owner")
        data, ref, founder = _doc(1, record), self._ref(org, pid), self._directory(org, "founder")

        def work(txn: Any) -> None:
            if founder.get(transaction=txn).exists:  # members who joined first do not block it (ADR-0044)
                raise OrgAlreadyFounded("OrgAlreadyFounded")
            exists, slot = ref.get(transaction=txn).exists, self._slot(txn, org, record["email"])
            if exists:
                raise AlreadyExists(f"AlreadyExists: person {pid}")
            self._claim(txn, slot, pid)
            txn.create(founder, {"uid": pid})
            txn.create(ref, data)

        with _guarded():
            self._transact(work, pid)
        return Stored(self.kind, copy.deepcopy(data["record"]), 1)

    def founded(self, org_id: str) -> bool:
        if not isinstance(org_id, str) or _ORG.fullmatch(org_id) is None:
            return False
        with _guarded():
            return bool(self._directory(org_id, "founder").get().exists)

    def replace(self, record: Mapping[str, Any], *, expected_version: int) -> Stored:
        org, pid = self._checked(record)
        expected = self._version(expected_version)
        data, ref = _doc(expected + 1, record), self._ref(org, pid)

        def work(txn: Any) -> None:
            snap = ref.get(transaction=txn)
            if not snap.exists:
                raise NotFound(f"NotFound: person {pid}")
            if snap.get("version") != expected:
                raise self._conflict(pid, expected, snap.get("version"))
            old, new = str(snap.get("record")["email"]).lower(), record["email"].lower()
            if old != new:
                old_slot, new_slot = self._slot(txn, org, old), self._slot(txn, org, new)  # both reads, then the writes
                self._release(txn, old_slot, pid)
                self._claim(txn, new_slot, pid)
            txn.update(ref, data)

        with _guarded():
            self._transact(work, pid)
        return Stored(self.kind, copy.deepcopy(data["record"]), expected + 1)

    def delete(self, org_id: str, record_id: str, *, expected_version: int) -> None:
        self._delete(org_id, record_id, expected_version, keep_one=False)

    def delete_not_last(self, org_id: str, record_id: str, *, expected_version: int) -> None:
        """`delete`, but `LastPerson` (nothing changed) for the sole person of an org nobody founded; the check reads
        the people collection inside the delete transaction, so a stale `list` cannot beat it (FS-17)."""
        self._delete(org_id, record_id, expected_version, keep_one=True)

    def _delete(self, org_id: str, record_id: str, expected_version: int, *, keep_one: bool) -> None:
        expected = self._version(expected_version)
        if not self._addressable(org_id, record_id):
            raise NotFound(f"NotFound: person {_safe(record_id)}")
        ref = self._ref(org_id, record_id)

        def work(txn: Any) -> None:
            snap = ref.get(transaction=txn)
            if not snap.exists:
                raise NotFound(f"NotFound: person {record_id}")
            if snap.get("version") != expected:
                raise self._conflict(record_id, expected, snap.get("version"))
            if keep_one:
                people = [s.id for s in self._collection(org_id).limit(2).stream(transaction=txn)]
                if people == [record_id] and not self._directory(org_id, "founder").get(transaction=txn).exists:
                    raise LastPerson(f"LastPerson: person {record_id}")
            self._release(txn, self._slot(txn, org_id, snap.get("record")["email"]), record_id)
            txn.delete(ref)

        with _guarded():
            self._transact(work, record_id)


def _collided(where: str, pid: str) -> PeopleError:
    """What a document a rival created first means, from its path in the library's error."""
    if "/people_directory/founder" in where:
        return OrgAlreadyFounded("OrgAlreadyFounded")
    if "/people_directory/email_" in where:
        return EmailTaken(f"EmailTaken: person {pid}")
    if "/people_person/" in where:
        return AlreadyExists(f"AlreadyExists: person {pid}")
    return PeopleError("the people store is unavailable")  # an unknown path: no class we cannot vouch for


def firestore_people_stores(client: Any) -> PeopleStores:
    """The seven stores over one client. Holds the client only: no read, write, query or transaction happens here."""

    def erase_followup(org_id: str, user: str) -> None:
        from tilo_api.brief_store import FirestoreBriefStore  # noqa: PLC0415
        from tilo_api.followup_draft_retention import followup_retention  # noqa: PLC0415
        from tilo_api.followup_outbox_sources import cancel_source_entries  # noqa: PLC0415

        FirestoreBriefStore(client).erase(org_id, user)
        cancel_source_entries(client, org_id, user)
        for policy in followup_retention(client, org_id, lambda: 0.0):
            policy.erase_owner_complete(user)

    return PeopleStores(
        persons=FirestorePersonStore(client),
        meetings=FirestoreRecordStore(client, "meeting"),
        work_items=FirestoreRecordStore(client, "work_item"),
        pins=FirestoreRecordStore(client, "pinboard_item"),
        mentions=FirestoreRecordStore(client, "mention"),
        calendar=FirestoreRecordStore(client, "calendar_entry"),
        world_shares=FirestoreRecordStore(client, "world_share"),
        erase_followup=erase_followup,
    )


def emulator_people_stores(project_id: str = "demo-tilo") -> PeopleStores:
    """ADR-0003: the emulator only. Refuses without `FIRESTORE_EMULATOR_HOST` and for any id that is not `demo-...`,
    before a client is built (`fullmatch`: a trailing newline is not a project id)."""
    if not os.environ.get("FIRESTORE_EMULATOR_HOST"):
        raise RuntimeError("emulator_people_stores needs FIRESTORE_EMULATOR_HOST (the Firestore emulator only)")
    if not isinstance(project_id, str) or _DEMO_PROJECT.fullmatch(project_id) is None:
        raise RuntimeError("emulator_people_stores takes a demo- project id only")
    return firestore_people_stores(firestore.Client(project=project_id))


def _shared_client(project: str) -> Any:
    """The process's one client (PROD-WIRE 3: `tilo_api.prod`, which also guards it; it imports this module)."""
    from tilo_api import prod

    return prod.firestore_client(project)


def open_people_stores(
    env: Mapping[str, str] | None = None, *, client_factory: Callable[[str], Any] | None = None
) -> PeopleStores:
    """The one live door (ADR-0023 decision 2): `TILO_PEOPLE_STORE=firestore` plus a valid `TILO_FIRESTORE_PROJECT`.
    Anything else raises `PeopleStoreNotConfigured` with no client built."""
    source = os.environ if env is None else env
    project = source.get("TILO_FIRESTORE_PROJECT", "")
    if source.get("TILO_PEOPLE_STORE") != "firestore" or _PROJECT.fullmatch(project) is None:
        raise PeopleStoreNotConfigured("set TILO_PEOPLE_STORE=firestore and a valid TILO_FIRESTORE_PROJECT")
    return firestore_people_stores((client_factory or _shared_client)(project))
