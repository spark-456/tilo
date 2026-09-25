"""D-11, PRD 15.3, P0-09 fix round 2 -- security-reviewer: `WorldWriter` built its Firestore
paths from `org_id`/`world_id`/`run_id` with plain f-strings and never checked them against
`common.schema.json`'s `org_, w_, r_` patterns, so a `world_id` such as
`"w_victim/events/00000001"` was not a world id at all but an extra path segment: `open()`'s
`transaction.set` on the head document then replaced `orgs/org_demo/worlds/w_victim`'s
`events/00000001` document -- an already-written event of a *different* world -- breaking both
"never overwriting an existing event" and "validate before writing".

`WorldWriter.__init__` now rejects any `org_id`/`world_id`/`run_id` that does not match its
`common.schema.json` pattern before any store call (`tilo_harness.ids`); every one of those
patterns excludes "/", so the attack string can never reach a path-building f-string.
`FirestoreStore` checks the same patterns again (plus `scope`) at every path it actually builds,
so the guard holds even for a caller that bypasses `WorldWriter`.
"""

from __future__ import annotations

import pytest
from conftest import world_requested_kwargs
from tilo_harness.ids import DISTRICT_ID, ORG_ID, RUN_ID, WORLD_ID, check_id, is_scope
from tilo_harness.store import MemoryStore
from tilo_harness.writer import WorldWriter


def test_D_11_writer_rejects_a_world_id_that_injects_a_path_segment(village_basic_layout) -> None:
    store = MemoryStore()

    # A legitimate writer for a different, "victim" world writes one real event first.
    victim = WorldWriter(
        store,
        org_id="org_demo",
        world_id="w_victim",
        run_id="r_test_1",
        layout=village_basic_layout,
        writer_id="writer_victim",
    )
    victim.open()
    victim.emit(**world_requested_kwargs(target="w_victim"))

    with pytest.raises(ValueError, match="world_id"):
        WorldWriter(
            store,
            org_id="org_demo",
            world_id="w_victim/events/00000001",
            run_id="r_test_1",
            layout=village_basic_layout,
            writer_id="attacker",
        )

    victim_events = store.read_events("org_demo", "w_victim")
    assert [e["seq"] for e in victim_events] == [1]
    assert victim_events[0]["type"] == "world.requested", (
        "D-11: rejecting the malicious world_id at construction must leave the victim world's "
        "stream completely unchanged"
    )


def test_D_11_writer_rejects_a_path_injecting_org_id(village_basic_layout) -> None:
    with pytest.raises(ValueError, match="org_id"):
        WorldWriter(
            MemoryStore(),
            org_id="org_demo/worlds/w_victim",
            world_id="w_attacker",
            run_id="r_test_1",
            layout=village_basic_layout,
            writer_id="attacker",
        )


def test_D_11_writer_rejects_a_path_injecting_run_id(village_basic_layout) -> None:
    with pytest.raises(ValueError, match="run_id"):
        WorldWriter(
            MemoryStore(),
            org_id="org_demo",
            world_id="w_attacker",
            run_id="r_test_1/../w_victim",
            layout=village_basic_layout,
            writer_id="attacker",
        )


@pytest.mark.parametrize(
    "value,pattern",
    [
        ("org_demo", ORG_ID),
        ("w_village_basic", WORLD_ID),
        ("r_test_1", RUN_ID),
        ("D1", DISTRICT_ID),
    ],
)
def test_D_11_ids_accept_well_formed_ids(value: str, pattern) -> None:
    check_id(value, pattern, label="id")  # must not raise


@pytest.mark.parametrize(
    "value,pattern,label",
    [
        ("w_victim/events/00000001", WORLD_ID, "world_id"),
        ("org_demo/worlds/w_x", ORG_ID, "org_id"),
        ("r_x/../y", RUN_ID, "run_id"),
        ("", WORLD_ID, "world_id"),
        ("not_prefixed", WORLD_ID, "world_id"),
    ],
)
def test_D_11_ids_reject_path_injecting_or_malformed_values(value: str, pattern, label: str) -> None:
    with pytest.raises(ValueError, match=label):
        check_id(value, pattern, label=label)


def test_D_11_is_scope_accepts_shared_and_district_ids_only() -> None:
    assert is_scope("shared") is True
    assert is_scope("D1") is True
    assert is_scope("D42") is True
    assert is_scope("shared/../D1") is False
    assert is_scope("D1/events/00000001") is False
    assert is_scope("not_a_scope") is False


# --- FirestoreStore path guard (no live emulator needed: the ValueError must raise before any
# network call, inside the path-building methods themselves -- same style as
# test_PRD_15_3_firestore_store_guard.py's config guards). ---------------------------------------


def test_D_11_firestore_store_refuses_a_path_injecting_world_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FIRESTORE_EMULATOR_HOST", "127.0.0.1:8199")
    from tilo_harness.store import FirestoreStore

    store = FirestoreStore(project_id="demo-tilo")
    with pytest.raises(ValueError, match="world_id"):
        store.read_events("org_demo", "w_victim/events/00000001")


def test_D_11_firestore_store_refuses_a_scope_that_is_not_shared_or_a_district_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FIRESTORE_EMULATOR_HOST", "127.0.0.1:8199")
    from tilo_harness.store import FirestoreStore

    store = FirestoreStore(project_id="demo-tilo")
    with pytest.raises(ValueError, match="scope"):
        store.read_view("org_demo", "w_village_basic", "D1/events/00000001")
