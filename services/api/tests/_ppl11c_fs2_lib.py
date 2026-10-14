"""Helpers for the PPL-11c-FS-2 acceptance tests (the people API's write limits, `Idempotency-Key` records and PE-12
event writes on durable stores; the interface is pinned in `API_PPL_11c_FS_2.md`).

Built on `_ppl11a_lib` (the `Rig`), `_ppl11c_lib` (`work_rig`'s seeds) and `_ppl11c_fs2_fake` (a Firestore stand-in with
serializable transactions, outage and lost-answer levers). Named `_ppl11c_fs2_lib` for the same global-bare-module-name
reason as the other `_*_lib.py` files. Nothing here is business logic: it builds a rig over Firestore-backed people
stores, swaps in "another instance of the service" (new adapter objects over the same client) and scripts event
writers. No network, no paid call, no secret (every token is assembled at run time).
"""

from __future__ import annotations

import os
import secrets
from collections.abc import Iterable
from typing import Any

from _api_lib import FakeEventWriter
from _ppl11a_lib import PRIYA, Rig, own_item
from _ppl11c_fs2_fake import SENTINEL, FakeFirestore2, is_record_path
from _ppl11c_lib import confirmed_item, transcript_case

# Each group of tests is a strict xfail until its builder removes its entry (API_PPL_11c_FS_2.md section 0). An entry
# is (a substring of a pytest node id, a substring that must also be there: "" for every row). A group that goes green
# with its entry still here fails (strict), which is the reminder to delete it. Rows of the `backend` parameter named
# "memory" already pass at the head of `phase0-stack` (the in-memory limits are the model the durable ones copy) and
# are never pending; `..._guard_...` tests pass today and must stay green.
FS2_PENDING: tuple[tuple[str, str], ...] = ()
FS2_EXEMPT: tuple[str, ...] = ("test_PPL_11c_FS_2_guard_",)
# Rows that pass at the head of `phase0-stack` with the Firestore stores (a single instance behaves like the in-memory
# model, and today's route already answers a dead event writer with the fixed 503): regression pins, never a strict
# xfail. What makes the limiter durable is pinned by the pending rows around them.
FS2_GREEN_TODAY: tuple[str, ...] = (
    "test_PPL_11c_FS_2_limit_01_",
    "test_PPL_11c_FS_2_limit_04_",
    "test_PPL_11c_FS_2_limit_05_",
    "test_PPL_11c_FS_2_limit_06_",
    "test_PPL_11c_FS_2_limit_07_",
    "test_PPL_11c_FS_2_limit_08_",
    "test_PPL_11c_FS_2_limit_09_",
    "test_PPL_11c_FS_2_limit_11_",
    "test_PPL_11c_FS_2_limit_12_",
    "test_PPL_11c_FS_2_key_01_a_replay_is_the_first_answer_byte_for_byte_and_writes_nothing[firestore",
    "test_PPL_11c_FS_2_key_07_",
    "test_PPL_11c_FS_2_store_06_",
    "test_PPL_11c_FS_2_event_03_",
)


def is_pending(nodeid: str) -> bool:
    """Is this test a strict xfail until its builder lands (see `FS2_PENDING`)?"""
    if any(entry in nodeid for entry in (*FS2_EXEMPT, *FS2_GREEN_TODAY)) or "[memory" in nodeid:
        return False
    return any(name in nodeid and param in nodeid for name, param in FS2_PENDING)


def fresh_token(prefix: str = "k") -> str:
    """A fresh `Idempotency-Key` (1 to 64 of letters, digits, `_`, `-`): assembled at run time, never a literal."""
    return f"{prefix}-{secrets.token_hex(8)}"


def emulator_host() -> str | None:
    return os.environ.get("FIRESTORE_EMULATOR_HOST") or None


# --- rigs over the stores ---------------------------------------------------------------------------------------------


def seed_work_rig(rig: Rig) -> Rig:
    """What `_ppl11c_lib.work_rig` seeds: the standard people, u_owner's meeting `mt_q4_plan`, u_priya's confirmed item
    `wi_rate_sheet` and her own `wi_own1`; signed in as u_priya."""
    rig.add_people()
    rig.add("meetings", transcript_case()["meeting"])
    rig.add("work_items", confirmed_item())
    rig.add("work_items", own_item("wi_own1", PRIYA))
    rig.as_user(PRIYA)
    return rig


def firestore_rig(people_rig: Any, client: Any = None) -> Rig:
    """A `work_rig` whose people stores are the Firestore adapters over `client` (default: a `FakeFirestore2`), built
    through `firestore_people_stores` as FS-1b's `open_people_stores` does. `rig.fake` is the client."""
    from tilo_api.people_firestore import firestore_people_stores  # noqa: PLC0415

    fake = FakeFirestore2() if client is None else client
    rig = people_rig()
    stores = firestore_people_stores(fake)
    rig.real = rig.stores = stores
    rig.fake = fake
    return seed_work_rig(rig)


def memory_rig(people_rig: Any) -> Rig:
    rig = seed_work_rig(people_rig())
    rig.fake = None
    return rig


def backend_rig(people_rig: Any, backend: str) -> Rig:
    return memory_rig(people_rig) if backend == "memory" else firestore_rig(people_rig)


def new_instance(rig: Rig) -> Any:
    """Another instance of the service (or a restart): fresh adapter objects over the same Firestore client, so nothing
    but Firestore is shared with the stores the rig had."""
    from tilo_api.people_firestore import firestore_people_stores  # noqa: PLC0415

    stores = firestore_people_stores(rig.fake)
    rig.real = rig.stores = stores
    return stores


def alternate_instances(rig: Rig, count: int = 2) -> list[Any]:
    """Every request resolves `deps.get_people_stores` to the next of `count` instances in turn."""
    import itertools  # noqa: PLC0415
    import threading  # noqa: PLC0415

    from _clint1_lib import seam  # noqa: PLC0415
    from tilo_api.people_firestore import firestore_people_stores  # noqa: PLC0415

    instances = [firestore_people_stores(rig.fake) for _ in range(count)]
    cycle, guard = itertools.cycle(instances), threading.Lock()

    def next_instance() -> Any:
        with guard:
            return next(cycle)

    rig.app.dependency_overrides[seam(rig.deps, "get_people_stores")] = next_instance
    return instances


def work_items_titled(rig: Rig, title: str) -> list[dict[str, Any]]:
    return [s.record for s in rig.real.work_items.list(rig.org) if s.record["title"] == title]


def stamped_events_of(rig: Rig, work_item_id: str) -> list[dict[str, Any]]:
    """The committed events (deduplicated by the writer) that name this work item, in any Desk world."""
    return [
        e
        for world in rig.event_store.events.values()
        for e in world
        if isinstance(e.get("data"), dict) and e["data"].get("work_item_id") == work_item_id
    ]


def all_stamped_events(rig: Rig) -> list[dict[str, Any]]:
    return [e for world in rig.event_store.events.values() for e in world]


# --- what the limiter wrote -------------------------------------------------------------------------------------------


def serialized(doc: Any) -> str:
    """Every id, key and value of a document as text (what a scanner for personal data would read)."""
    import json  # noqa: PLC0415

    return json.dumps(doc, sort_keys=True, default=str)


def docs_text(docs: dict[str, Any]) -> str:
    return " ".join(f"{path} {serialized(doc)}" for path, doc in docs.items())


def assert_no_record_collection_holds_limiter_docs(fake: FakeFirestore2) -> None:
    assert not [p for p in fake.limiter_docs() if is_record_path(p)]


# --- event writers ----------------------------------------------------------------------------------------------------


class ScriptedWriter(FakeEventWriter):
    """The single event writer with a script, one step per `append` call: "ok" commits and answers; "lands" commits
    and then raises (the answer was lost: the caller cannot tell whether it happened); "fail" raises without
    committing. After the script, every call is "ok". Idempotent by part id like the real writer (the base class).
    `attempts` is every part handed over, in order, whatever came of it."""

    def __init__(self, store: Any, script: Iterable[str] = ()) -> None:
        super().__init__(store)
        self.script = list(script)
        self.attempts: list[dict[str, Any]] = []

    def append(self, world_id: str, part: dict) -> dict:
        step = self.script.pop(0) if self.script else "ok"
        self.attempts.append(dict(part))
        if step == "fail":
            raise RuntimeError(f"event store unavailable {SENTINEL}")
        committed = super().append(world_id, part)
        if step == "lands":
            raise RuntimeError(f"deadline exceeded after the write landed {SENTINEL}")
        return committed
