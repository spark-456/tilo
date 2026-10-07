"""Helpers for the PPL-11c-FS acceptance tests (Firestore adapters for the people API's record stores; the interface
is pinned in `API_PPL_11c_FS.md`).

Built on `_ppl11a_lib` (the `pl` record builders, the `Rig`). Named `_ppl11c_fs_lib` for the same
global-bare-module-name reason as the other `_*_lib.py` files. Nothing here is business logic: it builds schema-valid
records, names the Firestore documents the spec pins, races callers and reads raw documents. Every Firestore test runs
against the Firestore emulator (`tilo_harness.emulator.running_emulator()`, a `demo-` project, no credentials); an
`org` is unique per test, so no test ever has to clear the emulator. No network, no paid call, no secret.
"""

from __future__ import annotations

import hashlib
import secrets
import sys
import threading
from collections.abc import Callable
from typing import Any

from _ppl11a_lib import pl

DEMO_PROJECT = "demo-tilo"
SENTINEL = "SENTINEL-7c41f9e2-record-text"  # text no error, repr or log of a store may ever carry

KINDS = ("person", "meeting", "work_item", "pinboard_item", "mention", "calendar_entry")
STORE_OF = {
    "person": "persons",
    "meeting": "meetings",
    "work_item": "work_items",
    "pinboard_item": "pins",
    "mention": "mentions",
    "calendar_entry": "calendar",
}

# Each requirement is a strict xfail until its builder removes its entry (API_PPL_11c_FS.md section 0). An entry is
# (a substring of a pytest node id naming the requirement, a substring that must also be there: "" for every row, or
# "firestore" for the rows of the `backend` fixture that need the adapter). A requirement that goes green with its
# entry still here fails (strict), which is the reminder to delete it.
FS_PENDING: tuple[tuple[str, str], ...] = (
    ("test_PPL_11c_FS_01_", ""),  # the documents' layout: Firestore only
    ("test_PPL_11c_FS_02_", "firestore"),  # the RecordStore contract: MemoryStore rows already pass
    ("test_PPL_11c_FS_03_", "firestore"),
    ("test_PPL_11c_FS_04_", "firestore"),
    ("test_PPL_11c_FS_05_", "firestore"),
    ("test_PPL_11c_FS_06_", ""),  # the three doors and "no I/O until asked"
    ("test_PPL_11c_FS_07_", "firestore"),  # the founder: create-if-absent, and the marker (both stores)
    ("test_PPL_11c_FS_08_", "firestore"),  # founder races (both stores; two adapters: Firestore)
    ("test_PPL_11c_FS_09_", "firestore"),  # the email reservation
    ("test_PPL_11c_FS_10_", "firestore"),  # release and swap
    ("test_PPL_11c_FS_11_", "firestore"),  # last-person erase
    ("test_PPL_11c_FS_13_", ""),  # wiring
    ("test_PPL_11c_FS_14_", "firestore"),  # the API over the stores (memory rows pass)
)
# MemoryStore rows that already pass at the head of `phase0-stack` (a "nothing was left behind" check is true of a store
# that never reserved anything): pinned, never a strict xfail. Their Firestore rows stay pending like the rest.
FS_MEMORY_GREEN: tuple[str, ...] = (
    "test_PPL_11c_FS_09_the_id_clash_is_reported_before_the_address_clash",
    "test_PPL_11c_FS_09_a_refused_create_leaves_no_reservation",
    "test_PPL_11c_FS_09_different_addresses_racing_all_succeed",
    "test_PPL_11c_FS_10_a_failed_replace_reserves_nothing",
    "test_PPL_11c_FS_10_erasing_a_person_frees_their_address",
    "test_PPL_11c_FS_11_a_person_who_is_not_the_last_is_erased_as_before",
    "test_PPL_11c_FS_11_erasing_someone_who_is_not_the_sole_person_is_not_a_last_person_erase",
)
# Pass at the head of `phase0-stack` and must stay true: strict xfail would fail them, so they are pinned instead.
FS_EXEMPT: tuple[str, ...] = (
    "test_PPL_11c_FS_06_the_people_package_stays_pure",
    "test_PPL_11c_FS_12_an_org_that_already_has_people",
    "test_PPL_11c_FS_12_the_configured_uid_has_no_other_power",
    "test_PPL_11c_FS_13_the_default_is_503_and_builds_no_client",
    "test_PPL_11c_FS_14_an_address_taken_by_a_person_who_is_then_erased",
    "test_PPL_11c_FS_15_",  # regression guard for issue #541 item 4a
)


def is_pending(nodeid: str) -> bool:
    """Is this test a strict xfail until its builder lands (see `FS_PENDING`)?"""
    if any(entry in nodeid for entry in FS_EXEMPT):
        return False
    if "[memory" in nodeid and any(entry in nodeid for entry in FS_MEMORY_GREEN):
        return False
    return any(name in nodeid and param in nodeid for name, param in FS_PENDING)


# --- records (schema-valid, in the org the test made) -----------------------------------------------------------------


def unique_org() -> str:
    """A fresh org id per test (`org_` + 12 hex), so tests on one emulator never see each other's documents."""
    return "org_fs" + secrets.token_hex(6)


def make(kind: str, n: int, org: str, **ov: Any) -> dict[str, Any]:
    """A schema-valid record of `kind` whose id carries `n`."""
    if kind == "person":
        return pl.with_(
            pl.person(
                id=f"u_p{n}",
                org_id=org,
                display_name=f"Person {n}",
                aliases=[],
                email=f"p{n}@example.com",
                memberships=[],
            ),
            **ov,
        )
    if kind == "meeting":
        return pl.with_(pl.meeting(id=f"mt_m{n}", org_id=org), **ov)
    if kind == "work_item":
        return pl.with_(pl.work_item(id=f"wi_w{n}", org_id=org), **ov)
    if kind == "pinboard_item":
        return pl.with_(pl.pin(id=f"pb_p{n}", org_id=org), **ov)
    if kind == "mention":
        return pl.with_(pl.mention(id=f"mn_t{n}", org_id=org), **ov)
    return pl.with_(pl.calendar_entry(id=f"ce_c{n}", org_id=org), **ov)


def person(uid: str, org: str, *, email: str | None = None, role: str = "member", **ov: Any) -> dict[str, Any]:
    """A person record: id `uid` (a `u_` id), a unique address unless one is given."""
    return pl.with_(
        pl.person(
            id=uid,
            org_id=org,
            display_name=f"Name of {uid}",
            aliases=[],
            email=email or f"{uid[2:]}@example.com",
            org_role=role,
            memberships=[],
        ),
        **ov,
    )


def edited(kind: str, record: dict[str, Any]) -> dict[str, Any]:
    """The same key with other content."""
    out = pl.with_(record)
    if kind == "person":
        out["display_name"] = "Renamed Person"
    elif kind == "mention":
        out["removed"] = {"by": "u_owner", "at": pl.T1}
    else:
        out["title"] = "Edited title"
    return out


def fill(stores: Any, kind: str, org: str, other_org: str) -> list[dict[str, Any]]:
    """Three records of `org` (ids sorted differently from creation order, owners and scopes varied for the indexes)
    and one of `other_org`; returns the three."""
    rows = {
        "person": [make("person", 3, org), make("person", 1, org), make("person", 2, org)],
        "meeting": [
            make("meeting", 3, org, owner="u_b"),
            make("meeting", 1, org, owner="u_a"),
            make("meeting", 2, org, owner="u_a"),
        ],
        "work_item": [
            make("work_item", 3, org, owner="u_b"),
            make("work_item", 1, org, owner="u_a"),
            make("work_item", 2, org, owner="u_a"),
        ],
        "pinboard_item": [
            make("pinboard_item", 3, org, scope={"kind": "personal", "user": "u_x"}, owner=None, set_up_by="u_x"),
            make("pinboard_item", 1, org, scope={"kind": "team", "team": "tm_sales"}, set_up_by="u_a"),
            make("pinboard_item", 2, org, scope={"kind": "team", "team": "tm_ops"}, set_up_by="u_a"),
        ],
        "mention": [
            make("mention", 3, org, pin_id="pb_p9", user="u_b"),
            make("mention", 1, org, pin_id="pb_p1", user="u_a"),
            make("mention", 2, org, pin_id="pb_p1", user="u_b"),
        ],
        "calendar_entry": [
            make("calendar_entry", 3, org, owner="u_b"),
            make("calendar_entry", 1, org, owner="u_a"),
            make("calendar_entry", 2, org, owner="u_a"),
        ],
    }[kind]
    store = getattr(stores, STORE_OF[kind])
    for record in rows:
        store.create(record)
    stray = {**pl.with_(rows[1]), "org_id": other_org, "id": rows[1]["id"][:3] + "z9"}
    if kind == "person":
        stray["email"] = "z9@example.com"
    store.create(stray)
    return rows


# --- the documents the spec pins (API_PPL_11c_FS.md section 1) --------------------------------------------------------


def record_path(org: str, kind: str, record_id: str) -> str:
    return f"orgs/{org}/people_{kind}/{record_id}"


def founder_path(org: str) -> str:
    return f"orgs/{org}/people_directory/founder"


def email_path(org: str, email: str) -> str:
    """The reservation of an address: SHA-256 of the lower-cased address, hex."""
    return f"orgs/{org}/people_directory/email_{hashlib.sha256(email.lower().encode('utf-8')).hexdigest()}"


def raw(client: Any, path: str) -> dict[str, Any] | None:
    """One raw Firestore document, or None."""
    snap = client.document(path).get()
    return snap.to_dict() if snap.exists else None


def raw_ids(client: Any, collection_path: str) -> list[str]:
    return sorted(snap.id for snap in client.collection(collection_path).stream())


def collections_of(client: Any, org: str) -> set[str]:
    """The names of the collections that hold anything under `orgs/{org}`."""
    return {c.id for c in client.document(f"orgs/{org}").collections() if any(True for _ in c.limit(1).stream())}


# --- backends ---------------------------------------------------------------------------------------------------------


class Backend:
    """`PeopleStores` over `MemoryStore` ("memory") or over the Firestore emulator ("firestore")."""

    def __init__(self, name: str, client: Any) -> None:
        self.name, self.client = name, client

    @property
    def is_firestore(self) -> bool:
        return self.name == "firestore"

    def stores(self) -> Any:
        """A fresh `PeopleStores` (for memory, empty; for Firestore, a new adapter object over the shared client)."""
        if not self.is_firestore:
            from tilo_people.stores import PeopleStores  # noqa: PLC0415

            return PeopleStores.in_memory()
        from tilo_api.people_firestore import firestore_people_stores  # noqa: PLC0415

        return firestore_people_stores(self.client)

    def stores_on_new_client(self) -> Any:
        """A second instance of the service: its own adapter objects over its own Firestore client."""
        assert self.is_firestore
        from google.cloud import firestore  # noqa: PLC0415
        from tilo_api.people_firestore import firestore_people_stores  # noqa: PLC0415

        return firestore_people_stores(firestore.Client(project=DEMO_PROJECT))


# --- concurrency ------------------------------------------------------------------------------------------------------


def race(workers: list[Callable[[], Any]]) -> list[tuple[str, Any]]:
    """Runs every worker at once (they wait on one barrier); returns [("ok", result) | ("err", exception)] in order."""
    barrier = threading.Barrier(len(workers))
    results: list[tuple[str, Any] | None] = [None] * len(workers)

    def run(i: int) -> None:
        barrier.wait()
        try:
            results[i] = ("ok", workers[i]())
        except BaseException as exc:  # noqa: BLE001 - the test inspects whatever the store raised
            results[i] = ("err", exc)

    threads = [threading.Thread(target=run, args=(i,)) for i in range(len(workers))]
    previous = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)  # make interleaving between a check and a write as likely as possible
    try:
        for th in threads:
            th.start()
        for th in threads:
            th.join(timeout=120)
    finally:
        sys.setswitchinterval(previous)
    assert all(r is not None for r in results), "a worker hung"
    return [r for r in results if r is not None]


def racers(backend: Any) -> int:
    """How many callers a race uses: eight in memory; three on the emulator, where every read inside a Firestore
    transaction takes a lock and eight transactions on one document stall for minutes (a two-way race on one
    document already takes about 15 s there). An implementation should not rely on read locks for a
    single-document compare-and-set (API_PPL_11c_FS.md section 2)."""
    return 3 if backend.is_firestore else 8


def oks(results: list[tuple[str, Any]]) -> list[Any]:
    return [value for kind, value in results if kind == "ok"]


def errs(results: list[tuple[str, Any]]) -> list[BaseException]:
    return [value for kind, value in results if kind == "err"]


def everything_said(exc: BaseException) -> str:
    """What a log handler or a traceback printer would show: the message, the args, the chained causes."""
    import traceback  # noqa: PLC0415

    return " ".join([str(exc), repr(exc), " ".join(map(str, exc.args)), "".join(traceback.format_exception(exc))])
