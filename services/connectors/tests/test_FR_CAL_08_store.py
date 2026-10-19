"""FR-CAL-08 / FR-CAL-02: the calendar cache store (`tilo_connectors.calendar_cache`). API_FR_CAL_08.md
"tilo_connectors.calendar_cache": `CalendarConnection`, `SyncState`, `entry_id`, `CalendarStore`,
`InMemoryCalendarStore` (atomic compare-and-set `commit`, `forget`), PE-04 (the owner), PE-13 (only Google
entries, deleted with the person), PE-16.

`commit` applies only when a state is stored for `expected.connection.user_id` with the same connection_id and
generation; then it writes `new`, upserts by id and removes the listed ids, and returns True. Otherwise it
changes nothing and returns False. It raises ValueError (and changes nothing) for an upsert whose owner is not
the connection's user, whose org differs, whose source.kind is not google, or that fails the schema, and for a
`new` with another connection or a generation other than expected + 1. Every test fails today with
ModuleNotFoundError: tilo_connectors.calendar_cache.
"""

from __future__ import annotations

import dataclasses
import hashlib
import re

import pytest
from _calendar_lib import (
    DANA,
    ORG_B,
    PRIYA,
    W_DANA,
    make_conn,
    make_entry,
    make_state,
)

LATER = "2026-10-07T00:15:00.000Z"


def _store():
    from tilo_connectors.calendar_cache import InMemoryCalendarStore

    return InMemoryCalendarStore()


def _snapshot(store, *users):
    return {u: (store.get(u), store.entries(u)) for u in users}


def test_FR_CAL_08_the_cache_constants_and_the_entry_id_formula():
    from tilo_connectors.calendar_cache import CALENDAR_ID, entry_id

    assert CALENDAR_ID == "primary"
    expected = "ce_g" + hashlib.sha256(f"{PRIYA}\x00primary\x00evt_1".encode()).hexdigest()[:40]
    assert entry_id(PRIYA, "evt_1") == expected
    assert re.fullmatch(r"ce_[0-9A-Za-z_]{1,48}", expected)
    assert entry_id(PRIYA, "evt_1") != entry_id(DANA, "evt_1") != entry_id(PRIYA, "evt_2")


def test_FR_CAL_08_a_connection_and_a_state_are_immutable_and_a_state_hides_its_sealed_token_in_repr():
    conn = make_conn()
    state = make_state(conn, sealed_token=b"SEALED-BYTES-CANARY")

    assert [f.name for f in dataclasses.fields(type(conn))] == [
        "user_id",
        "org_id",
        "world_id",
        "connection_id",
        "registered_at",
    ]
    assert [f.name for f in dataclasses.fields(type(state))] == [
        "connection",
        "generation",
        "sealed_token",
        "next_due_at",
        "last_run_at",
        "failures",
    ]
    assert "SEALED-BYTES-CANARY" not in repr(state) and "SEALED" not in str(state)
    with pytest.raises(dataclasses.FrozenInstanceError):
        conn.user_id = "u_other"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        state.generation = 9  # type: ignore[misc]


def test_FR_CAL_08_add_stores_a_state_unless_the_user_has_one_and_returns_the_stored_one():
    store = _store()
    first, second = make_state(make_conn()), make_state(make_conn())

    assert store.get(PRIYA) is None
    assert store.add(first) == first
    assert store.add(second) == first, "the user already has one: the stored state is returned, nothing replaced"
    assert store.get(PRIYA) == first


def test_FR_CAL_08_user_ids_are_sorted():
    store = _store()
    for user, org, world in (("u_zed", "org_a", "w_z"), (PRIYA, "org_a", "w_p"), (DANA, ORG_B, W_DANA)):
        store.add(make_state(make_conn(user, org, world)))

    assert store.user_ids() == (DANA, PRIYA, "u_zed")


def test_FR_CAL_08_a_matching_commit_writes_the_state_upserts_and_removals_and_returns_true():
    store = _store()
    conn = make_conn()
    s0 = store.add(make_state(conn))
    entries = [make_entry(conn, f"e{k}", title=f"T{k}", start=f"2026-10-0{8 - k}T04:00:00.000Z") for k in range(3)]
    assert store.commit(
        s0,
        make_state(conn, generation=1, sealed_token=b"x", next_due_at=LATER, last_run_at=LATER),
        upserts=entries,
        removals=[],
    )
    s1 = store.get(PRIYA)
    assert (s1.generation, s1.sealed_token, s1.next_due_at, s1.last_run_at) == (1, b"x", LATER, LATER)
    assert [e["title"] for e in store.entries(PRIYA)] == ["T2", "T1", "T0"], "sorted by (start, id)"

    renamed = make_entry(conn, "e1", title="T1 renamed", start="2026-10-07T04:00:00.000Z")
    assert store.commit(
        s1, make_state(conn, generation=2), upserts=[renamed], removals=[entries[0]["id"], "ce_gdoesnotexist"]
    )

    assert [e["title"] for e in store.entries(PRIYA)] == ["T2", "T1 renamed"]
    assert store.get(PRIYA).generation == 2


def test_FR_CAL_08_a_stale_wrong_connection_or_forgotten_commit_returns_false_and_changes_nothing():
    store = _store()
    conn = make_conn()
    s0 = store.add(make_state(conn))
    assert store.commit(s0, make_state(conn, generation=1), upserts=[make_entry(conn, "e1")], removals=[])
    before = _snapshot(store, PRIYA)
    stale_generation = s0  # generation 0, the state another instance already replaced
    other_connection = make_state(make_conn(), generation=1)

    assert (
        store.commit(stale_generation, make_state(conn, generation=1), upserts=[make_entry(conn, "e2")], removals=[])
        is False
    )
    assert (
        store.commit(other_connection, make_state(other_connection.connection, generation=2), upserts=[], removals=[])
        is False
    )
    dana = make_conn(DANA, ORG_B, W_DANA)
    assert store.commit(make_state(dana), make_state(dana, generation=1), upserts=[], removals=[]) is False, (
        "no state stored"
    )
    assert _snapshot(store, PRIYA) == before
    assert store.get(DANA) is None

    store.forget(PRIYA)
    current = make_state(conn, generation=1)
    assert store.commit(current, make_state(conn, generation=2), upserts=[make_entry(conn, "e3")], removals=[]) is False
    assert store.get(PRIYA) is None and store.entries(PRIYA) == (), (
        "a forgotten person is not resurrected by a late commit"
    )


@pytest.mark.parametrize(
    "case",
    [
        "owner is someone else",
        "org differs",
        "source is manual",
        "schema: empty title",
        "schema: extra key",
        "schema: attendee_count 501",
        "schema: bad timestamp",
        "new is another connection",
        "new generation unchanged",
        "new generation skips one",
        "new generation goes back",
    ],
)
def test_FR_CAL_08_commit_raises_value_error_and_changes_nothing_for_an_unsafe_write(case):
    store = _store()
    conn = make_conn()
    s0 = store.add(make_state(conn))
    keep = make_entry(conn, "keep")
    assert store.commit(s0, make_state(conn, generation=1), upserts=[keep], removals=[])
    expected = store.get(PRIYA)
    before = _snapshot(store, PRIYA)
    good = make_entry(conn, "good", title="Good")
    new = make_state(conn, generation=2)
    bad = make_entry(conn, "bad")
    if case == "owner is someone else":
        bad = make_entry(conn, "bad", owner=DANA)
    elif case == "org differs":
        bad = make_entry(conn, "bad", org=ORG_B)
    elif case == "source is manual":
        bad = make_entry(conn, "bad", kind="manual")
    elif case == "schema: empty title":
        bad = make_entry(conn, "bad", title="")
    elif case == "schema: extra key":
        bad["description"] = "not a calendar_entry field"
    elif case == "schema: attendee_count 501":
        bad = make_entry(conn, "bad", attendee_count=501)
    elif case == "schema: bad timestamp":
        bad = make_entry(conn, "bad", start="soon")
    elif case == "new is another connection":
        new = make_state(make_conn(), generation=2)
    elif case == "new generation unchanged":
        new = make_state(conn, generation=1)
    elif case == "new generation skips one":
        new = make_state(conn, generation=3)
    elif case == "new generation goes back":
        new = make_state(conn, generation=0)
    upserts = [good] if case.startswith("new") else [good, bad]

    with pytest.raises(ValueError):
        store.commit(expected, new, upserts=upserts, removals=[keep["id"]])

    assert _snapshot(store, PRIYA) == before, "atomic: the good upsert and the removal were not applied either"


def test_FR_CAL_08_entries_are_copies_sorted_by_start_then_id():
    store = _store()
    conn = make_conn()
    s0 = store.add(make_state(conn))
    same_time = [make_entry(conn, f"x{k}", start="2026-10-08T04:00:00.000Z") for k in range(4)]
    early = make_entry(conn, "early", start="2026-10-07T04:00:00.000Z")
    store.commit(s0, make_state(conn, generation=1), upserts=[*same_time, early], removals=[])

    got = store.entries(PRIYA)

    assert got[0]["id"] == early["id"]
    assert [e["id"] for e in got[1:]] == sorted(e["id"] for e in same_time)
    got[0]["title"] = "tampered"
    got[0]["source"]["ref"] = "tampered"
    assert store.entries(PRIYA)[0]["title"] == "Standup" and store.entries(PRIYA)[0]["source"]["ref"] == "early"


def test_FR_CAL_08_forget_deletes_the_state_with_its_token_and_every_entry_of_that_person_only_and_is_idempotent():
    store = _store()
    a, b = make_conn(), make_conn(DANA, ORG_B, W_DANA)
    for conn in (a, b):
        s0 = store.add(make_state(conn, sealed_token=b"tok"))
        store.commit(
            s0, make_state(conn, generation=1, sealed_token=b"tok2"), upserts=[make_entry(conn, "e1")], removals=[]
        )

    store.forget(PRIYA)
    store.forget(PRIYA)
    store.forget("u_nobody")

    assert store.get(PRIYA) is None and store.entries(PRIYA) == ()
    assert store.user_ids() == (DANA,)
    assert len(store.entries(DANA)) == 1 and store.get(DANA).sealed_token == b"tok2"


def test_FR_CAL_08_the_store_never_holds_anything_but_google_entries():
    store = _store()
    conn = make_conn()
    s0 = store.add(make_state(conn))

    with pytest.raises(ValueError):
        store.commit(s0, make_state(conn, generation=1), upserts=[make_entry(conn, "m", kind="manual")], removals=[])

    assert store.entries(PRIYA) == () and store.get(PRIYA).generation == 0
