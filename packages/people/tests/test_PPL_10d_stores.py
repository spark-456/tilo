"""PPL-10d: `RecordStore`, `MemoryStore`, `PeopleStores`, the meeting tombstone, calendar disconnect and
person erasure (contracts/people.rules.md PE-13, PE-16, PE-19; FR-MEM-09; BQ-PPL10-2, -8, -11).
Spec: API.md section 5.

The stores authorise nothing (callers run `decide` and `check_write` first); they key records by
`(org_id, id)`, validate them against their schema, and update only by compare-and-set.

Ambiguities settled here (PRD / rule in brackets; also listed in the hand-back):

- A: `expected_version` that is not an int (`"1"`, `None`, `1.5`) is a malformed argument, so
  `PeopleInputError`; an int that is not current (0, -1, 99) is a `VersionConflict`. [API.md "Errors"]
- B: erasing a person counts a meeting only when it tombstones one, so a meeting that is already a
  tombstone is not counted and "a second run returns all zeros". [API.md erase_person]
- C: the first-run erasure counts are asserted only for data that makes them unambiguous (no meeting
  that is already deleted). [BQ-PPL10-8]
- D: a tombstone of a meeting that never had a `world_id` has no `world_id` key at all (the schema
  says absent, never null). [meeting.schema.json 1.1.0]
"""

from __future__ import annotations

import copy
import dataclasses
import logging
import sys
import threading
import traceback

import _ppl10_testlib as t
import pytest
from _ppl10_testlib import errors, pl, stores

KINDS = ("person", "meeting", "work_item", "pinboard_item", "mention", "calendar_entry")  # + world_share: TSW-1a
STORE_OF = {
    "person": "persons",
    "meeting": "meetings",
    "work_item": "work_items",
    "pinboard_item": "pins",
    "mention": "mentions",
    "calendar_entry": "calendar",
    "world_share": "world_shares",
}
ORG = t.ORG
OTHER = t.OTHER_ORG


def make(kind, n, **ov):
    """A schema-valid record of `kind` whose id carries `n`."""
    if kind == "person":
        return t.with_(t.make_person(f"u_p{n}", f"Person {n}", teams=()), **ov)
    if kind == "meeting":
        return t.meeting(id=f"mt_m{n}", **ov)
    if kind == "work_item":
        return t.own_item(id=f"wi_w{n}", **ov)
    if kind == "pinboard_item":
        return t.team_pin(id=f"pb_p{n}", **ov)
    if kind == "mention":
        return t.tag(id=f"mn_t{n}", **ov)
    return t.entry(id=f"ce_c{n}", **ov)


def edited(kind, record):
    """The same key with other content."""
    out = copy.deepcopy(record)
    if kind == "person":
        out["display_name"] = "Renamed Person"
    elif kind == "mention":
        out["removed"] = {"by": "u_riya", "at": t.T1}
    else:
        out["title"] = "Edited title"
    return out


def new_store(kind):
    return stores.MemoryStore(kind)


class Spy:
    """A RecordStore that is only the protocol (no helper attributes a caller could lean on) and logs calls."""

    def __init__(self, kind, log):
        self.kind = kind
        self._inner = stores.MemoryStore(kind)
        self._log = log

    def get(self, org_id, record_id):
        self._log.append((self.kind, "get"))
        return self._inner.get(org_id, record_id)

    def create(self, record):
        self._log.append((self.kind, "create"))
        return self._inner.create(record)

    def replace(self, record, *, expected_version):
        self._log.append((self.kind, "replace"))
        return self._inner.replace(record, expected_version=expected_version)

    def delete(self, org_id, record_id, *, expected_version):
        self._log.append((self.kind, "delete"))
        return self._inner.delete(org_id, record_id, expected_version=expected_version)

    def list(self, org_id, field=None, value=None):
        self._log.append((self.kind, "list"))
        return self._inner.list(org_id, field, value)


def spy_stores():
    log = []
    s = {name: Spy(kind, log) for kind, name in STORE_OF.items()}
    return stores.PeopleStores(**s), log


# ---------------------------------------------------------------------------------------------
# 0. Shapes
# ---------------------------------------------------------------------------------------------
def test_PPL_10d_PE_16_indexes_are_pinned():
    assert {k: tuple(v) for k, v in stores.INDEXES.items()} == {
        "person": (),
        "meeting": ("owner",),
        "work_item": ("owner",),
        "pinboard_item": ("scope.user", "scope.team", "set_up_by"),
        "mention": ("pin_id", "user"),
        "calendar_entry": ("owner",),
        "world_share": ("world_id", "team"),
    }


@pytest.mark.parametrize("kind", ["", "note", "Person", "work_items", None, 5, "person ", "pin"])
def test_PPL_10d_PE_16_an_unknown_store_kind_is_a_malformed_argument(kind):
    with pytest.raises(errors.PeopleInputError):
        stores.MemoryStore(kind)


@pytest.mark.parametrize("kind", KINDS)
def test_PPL_10d_PE_16_a_memory_store_has_the_record_store_surface(kind):
    store = new_store(kind)
    assert store.kind == kind
    for name in ("get", "create", "replace", "delete", "list"):
        assert callable(getattr(store, name)), name
    assert hasattr(stores, "RecordStore")
    assert store.get(ORG, make(kind, 1)["id"]) is None
    assert store.list(ORG) == ()


def test_PPL_10d_PE_16_people_stores_in_memory_gives_seven_fresh_stores_of_the_right_kinds():
    one, two = stores.PeopleStores.in_memory(), stores.PeopleStores.in_memory()
    for kind, name in STORE_OF.items():
        assert getattr(one, name).kind == kind
        assert getattr(one, name) is not getattr(two, name)
    assert len({id(getattr(one, name)) for name in STORE_OF.values()}) == 7
    one.work_items.create(make("work_item", 1))
    assert two.work_items.get(ORG, "wi_w1") is None  # no hidden global state
    assert one.work_items.get(ORG, "wi_w1") is not None
    with pytest.raises(dataclasses.FrozenInstanceError):
        one.persons = two.persons  # type: ignore[misc]


def test_PPL_10d_PE_16_stored_is_a_frozen_value_with_a_hidden_record():
    s = stores.Stored(kind="work_item", record={"id": "wi_w1", "title": t.SENTINEL}, version=3)
    assert (s.kind, s.version, s.record["id"]) == ("work_item", 3, "wi_w1")
    assert [f.name for f in dataclasses.fields(stores.Stored)] == ["kind", "record", "version"]
    assert t.SENTINEL not in repr(s) and t.SENTINEL not in str(s)
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.version = 4  # type: ignore[misc]


# ---------------------------------------------------------------------------------------------
# 1. CRUD and compare-and-set, for every kind
# ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize("kind", KINDS)
def test_PPL_10d_PE_16_create_get_replace_delete_with_versions(kind):
    store, record = new_store(kind), make(kind, 1)
    created = store.create(record)
    assert (created.kind, created.version, created.record) == (kind, 1, record)
    assert store.get(ORG, record["id"]) == created
    changed = edited(kind, record)
    replaced = store.replace(changed, expected_version=1)
    assert (replaced.version, replaced.record) == (2, changed)
    assert store.get(ORG, record["id"]).version == 2
    assert store.replace(edited(kind, changed), expected_version=2).version == 3  # +1 per replace
    assert store.delete(ORG, record["id"], expected_version=3) is None
    assert store.get(ORG, record["id"]) is None
    assert store.create(record).version == 1  # a fresh create starts again


@pytest.mark.parametrize("kind", KINDS)
def test_PPL_10d_PE_16_create_twice_is_already_exists_and_replace_or_delete_of_nothing_is_not_found(kind):
    store, record = new_store(kind), make(kind, 1)
    store.create(record)
    with pytest.raises(errors.AlreadyExists):
        store.create(edited(kind, record))
    assert store.get(ORG, record["id"]).record == record  # the first one stays
    ghost = make(kind, 9)
    with pytest.raises(errors.NotFound):
        store.replace(ghost, expected_version=1)
    with pytest.raises(errors.NotFound):
        store.delete(ORG, ghost["id"], expected_version=1)


@pytest.mark.parametrize("kind", KINDS)
def test_PPL_10d_PE_16_a_stale_or_wrong_version_is_a_version_conflict_and_changes_nothing(kind):
    store, record = new_store(kind), make(kind, 1)
    store.create(record)
    store.replace(edited(kind, record), expected_version=1)  # now at version 2
    for wrong in (1, 0, -1, 3, 99):
        with pytest.raises(errors.VersionConflict):
            store.replace(record, expected_version=wrong)
        with pytest.raises(errors.VersionConflict):
            store.delete(ORG, record["id"], expected_version=wrong)
    still = store.get(ORG, record["id"])
    assert (still.version, still.record) == (2, edited(kind, record))


@pytest.mark.parametrize("version", ["1", None, 1.5, [1], {}, b"1"])
def test_PPL_10d_PE_16_a_version_that_is_not_an_int_is_a_malformed_argument(version):
    """Ambiguity A in the module docstring."""
    store, record = new_store("work_item"), make("work_item", 1)
    store.create(record)
    with pytest.raises(errors.PeopleInputError):
        store.replace(record, expected_version=version)
    with pytest.raises(errors.PeopleInputError):
        store.delete(ORG, record["id"], expected_version=version)
    assert store.get(ORG, record["id"]).version == 1


@pytest.mark.parametrize("kind", KINDS)
def test_PPL_10d_PE_16_a_record_that_fails_its_schema_is_refused_on_create_and_replace(kind):
    store, record = new_store(kind), make(kind, 1)
    bad_records = [
        {**record, "x_extra": 1},
        {k: v for k, v in record.items() if k != "id"},
        {**record, "id": "not an id"},
        {**record, "org_id": "acme"},
        [],
        None,
        "record",
        5,
    ]
    for bad in bad_records:
        with pytest.raises(errors.PeopleInputError):
            store.create(bad)
    assert store.list(ORG) == ()
    store.create(record)
    for bad in bad_records:
        if isinstance(bad, dict) and bad.get("id") != record["id"]:
            continue  # a replace is keyed by the record's own id; those are covered by create
        with pytest.raises(errors.PeopleInputError):
            store.replace(bad, expected_version=1)
    assert store.get(ORG, record["id"]).record == record


@pytest.mark.parametrize("kind", [k for k in KINDS])
def test_PPL_10d_PE_16_a_store_takes_only_its_own_kind(kind):
    store = new_store(kind)
    for other in KINDS:
        if other == kind:
            continue
        with pytest.raises(errors.PeopleInputError):
            store.create(make(other, 1))
    assert store.list(ORG) == ()


@pytest.mark.parametrize("kind", KINDS)
def test_PPL_10d_PE_16_records_are_keyed_by_org_and_id_so_two_orgs_never_see_each_other(kind):
    store = new_store(kind)
    mine = make(kind, 1)
    theirs = {**copy.deepcopy(mine), "org_id": OTHER}
    store.create(mine)
    assert store.get(OTHER, mine["id"]) is None  # another org's id lookup is blank, never a leak
    store.create(theirs)  # the same id in another org is a different record, not AlreadyExists
    assert store.get(ORG, mine["id"]).record == mine and store.get(OTHER, mine["id"]).record == theirs
    store.replace(edited(kind, mine), expected_version=1)
    assert store.get(OTHER, mine["id"]).version == 1 and store.get(OTHER, mine["id"]).record == theirs
    store.delete(ORG, mine["id"], expected_version=2)
    assert store.get(ORG, mine["id"]) is None and store.get(OTHER, mine["id"]).record == theirs
    assert [s.record["org_id"] for s in store.list(OTHER)] == [OTHER] and store.list(ORG) == ()
    with pytest.raises(errors.NotFound):
        store.delete(ORG, mine["id"], expected_version=1)  # not found in this org, though it exists in the other


@pytest.mark.parametrize(
    "org", [None, 5, "", "acme", "org_acme\n", "org_", ["org_acme"], b"org_acme", "org_" + "x" * 80]
)
@pytest.mark.parametrize("record_id", [None, 5, "", "wi_w1\n", "w1", ["wi_w1"]])
def test_PPL_10d_PE_16_get_with_a_malformed_org_or_id_is_none_never_an_error(org, record_id):
    store = new_store("work_item")
    store.create(make("work_item", 1))
    assert store.get(org, record_id) is None
    assert store.get(org, "wi_w1") is None
    assert store.get(ORG, record_id) is None


def test_PPL_10d_PE_16_records_go_in_and_out_as_deep_copies():
    store = new_store("work_item")
    record = make("work_item", 1)
    created = store.create(record)
    record["title"] = "mutated after create"
    record["history"].append("junk")
    assert store.get(ORG, "wi_w1").record["title"] == "Water the plants"
    created.record["title"] = "mutated through the result"
    fetched = store.get(ORG, "wi_w1")
    fetched.record["history"].clear()
    assert (
        store.get(ORG, "wi_w1").record["title"] == "Water the plants"
        and len(store.get(ORG, "wi_w1").record["history"]) == 1
    )
    listed = store.list(ORG)
    listed[0].record["history"].clear()
    assert len(store.get(ORG, "wi_w1").record["history"]) == 1
    new = make("work_item", 1, title="Replacement")
    replaced = store.replace(new, expected_version=1)
    new["title"] = "mutated after replace"
    replaced.record["title"] = "mutated through the result"
    assert store.get(ORG, "wi_w1").record["title"] == "Replacement"


# ---------------------------------------------------------------------------------------------
# 2. list and the indexes
# ---------------------------------------------------------------------------------------------
def _fill(kind):
    """Three records of one org (ids sorted differently from creation order) and one of another org."""
    store = new_store(kind)
    rows = {
        "person": [make("person", 3), make("person", 1), make("person", 2)],
        "meeting": [make("meeting", 3, owner="u_b"), make("meeting", 1, owner="u_a"), make("meeting", 2, owner="u_a")],
        "work_item": [
            make("work_item", 3, owner="u_b"),
            make("work_item", 1, owner="u_a"),
            make("work_item", 2, owner="u_a"),
        ],
        "pinboard_item": [
            make("pinboard_item", 3, scope={"kind": "personal", "user": "u_x"}, owner=None, set_up_by="u_x"),
            make("pinboard_item", 1, scope={"kind": "team", "team": "tm_sales"}, set_up_by="u_a"),
            make("pinboard_item", 2, scope={"kind": "team", "team": "tm_ops"}, set_up_by="u_a"),
        ],
        "mention": [
            make("mention", 3, pin_id="pb_p9", user="u_b"),
            make("mention", 1, pin_id="pb_p1", user="u_a"),
            make("mention", 2, pin_id="pb_p1", user="u_b"),
        ],
        "calendar_entry": [
            make("calendar_entry", 3, owner="u_b"),
            make("calendar_entry", 1, owner="u_a"),
            make("calendar_entry", 2, owner="u_a"),
        ],
    }[kind]
    for r in rows:
        store.create(r)
    stray = {**copy.deepcopy(rows[1]), "org_id": OTHER, "id": rows[1]["id"][:3] + "z9"}
    store.create(stray)
    return store, rows


@pytest.mark.parametrize("kind", KINDS)
def test_PPL_10d_PE_16_list_returns_the_orgs_records_sorted_by_id_as_a_tuple(kind):
    store, rows = _fill(kind)
    got = store.list(ORG)
    assert isinstance(got, tuple) and all(isinstance(s, stores.Stored) for s in got)
    assert [s.record["id"] for s in got] == sorted(r["id"] for r in rows)
    assert all(s.record["org_id"] == ORG and s.version == 1 and s.kind == kind for s in got)
    assert [s.record["org_id"] for s in store.list(OTHER)] == [OTHER]
    assert store.list("org_nobody") == ()


INDEX_EXPECTATIONS = {
    "meeting": [
        ("owner", "u_a", ["mt_m1", "mt_m2"]),
        ("owner", "u_b", ["mt_m3"]),
        ("owner", "u_none", []),
        ("owner", "u_", []),
    ],
    "work_item": [("owner", "u_a", ["wi_w1", "wi_w2"]), ("owner", "u_b", ["wi_w3"]), ("owner", "U_A", [])],
    "calendar_entry": [("owner", "u_a", ["ce_c1", "ce_c2"]), ("owner", "u_b", ["ce_c3"])],
    "pinboard_item": [
        ("scope.user", "u_x", ["pb_p3"]),
        ("scope.team", "tm_sales", ["pb_p1"]),
        ("scope.team", "tm_ops", ["pb_p2"]),
        ("scope.user", "tm_sales", []),
        ("set_up_by", "u_a", ["pb_p1", "pb_p2"]),
        ("set_up_by", "u_x", ["pb_p3"]),
    ],
    "mention": [
        ("pin_id", "pb_p1", ["mn_t1", "mn_t2"]),
        ("pin_id", "pb_p9", ["mn_t3"]),
        ("user", "u_b", ["mn_t2", "mn_t3"]),
        ("user", "u_a", ["mn_t1"]),
        ("pin_id", "pb_p", []),
    ],
}


@pytest.mark.parametrize("kind", sorted(INDEX_EXPECTATIONS))
def test_PPL_10d_PE_16_list_by_an_index_is_equality_on_that_field_within_the_org(kind):
    store, _ = _fill(kind)
    for field, value, ids in INDEX_EXPECTATIONS[kind]:
        got = store.list(ORG, field, value)
        assert [s.record["id"] for s in got] == ids, (field, value)
        assert all(s.record["org_id"] == ORG for s in got)


@pytest.mark.parametrize("kind", KINDS)
def test_PPL_10d_PE_16_list_by_a_field_that_is_not_an_index_is_a_malformed_argument(kind):
    store, _ = _fill(kind)
    allowed = set(stores.INDEXES[kind])
    for field in (
        "title",
        "id",
        "org_id",
        "status",
        "email",
        "display_name",
        "scope",
        "scope.kind",
        "owner.x",
        "",
        " owner",
        "OWNER",
        "created_by.ref",
        "history",
        "NoneType",
    ):
        if field in allowed:
            continue
        with pytest.raises(errors.PeopleInputError):
            store.list(ORG, field, "u_a")
    for junk in (5, ["owner"], b"owner"):
        with pytest.raises(errors.PeopleInputError):
            store.list(ORG, junk, "u_a")


def test_PPL_10d_PE_16_a_person_store_has_no_index_at_all():
    store, _ = _fill("person")
    for field in ("owner", "id", "email", "scope.user"):
        with pytest.raises(errors.PeopleInputError):
            store.list(ORG, field, "u_p1")


# ---------------------------------------------------------------------------------------------
# 3. No record text in an error, a repr, a traceback or a log
# ---------------------------------------------------------------------------------------------
def _everything_said(exc):
    """What a log handler or a traceback printer would show: the message, the args, the chained causes."""
    return " ".join([str(exc), repr(exc), " ".join(map(str, exc.args)), "".join(traceback.format_exception(exc))])


@pytest.mark.parametrize("kind", KINDS)
def test_PPL_10d_PE_16_errors_name_the_kind_id_and_versions_and_never_record_text(kind, caplog):
    caplog.set_level(logging.DEBUG)
    store = new_store(kind)
    record = make(kind, 1)
    if kind == "person":
        record["display_name"] = t.SENTINEL
        record["aliases"] = [t.SENTINEL]
    elif kind == "mention":
        record["added_by"] = pl.maker_person("u_owner", t.T0)
    else:
        record["title"] = t.SENTINEL
    store.create(record)
    store.replace(record, expected_version=1)  # now version 2
    seen = []
    mine, ghost = make(kind, 1)["id"], make(kind, 9)["id"]
    for call, record_id in (
        (lambda: store.create(record), mine),
        (lambda: store.replace(record, expected_version=7), mine),
        (lambda: store.delete(ORG, record["id"], expected_version=7), mine),
        (lambda: store.replace({**record, "id": ghost}, expected_version=1), ghost),
        (lambda: store.delete(ORG, ghost, expected_version=1), ghost),
    ):
        with pytest.raises(errors.PeopleError) as caught:
            call()
        seen.append(caught.value)
        assert t.SENTINEL not in _everything_said(caught.value), type(caught.value).__name__
        assert kind in str(caught.value) and record_id in str(caught.value), str(caught.value)
    conflict = seen[1]
    assert (
        isinstance(conflict, errors.VersionConflict) and "7" in str(conflict) and "2" in str(conflict)
    )  # expected and current
    assert t.SENTINEL not in caplog.text and not caplog.records, "the stores never log"


def test_PPL_10d_PE_16_a_schema_failure_message_does_not_echo_the_bad_value_or_the_bad_key(caplog):
    caplog.set_level(logging.DEBUG)
    store = new_store("work_item")
    leaky = [
        {**make("work_item", 1), "status": t.SENTINEL},  # an enum violation echoes its value in jsonschema
        {**make("work_item", 1), t.SENTINEL: "x"},  # an unexpected key is echoed by name
        {**make("work_item", 1), "title": t.SENTINEL * 20},  # too long
        {
            **make("work_item", 1),
            "history": [{"at": t.SENTINEL, "by": "u_riya", "change": "created", "status": "open"}],
        },
        {**make("work_item", 1), "source": {"kind": t.SENTINEL, "ref": None, "evidence": []}},
        {**make("work_item", 1), "due": t.SENTINEL},
    ]
    for record in leaky:
        for call in (lambda r=record: store.create(r),):
            with pytest.raises(errors.PeopleInputError) as caught:
                call()
            assert t.SENTINEL not in _everything_said(caught.value)
    assert t.SENTINEL not in caplog.text and not caplog.records


def test_PPL_10d_PE_16_the_store_holds_the_record_but_says_nothing_of_it(caplog):
    caplog.set_level(logging.DEBUG)
    store = new_store("pinboard_item")
    record = make("pinboard_item", 1, title=t.SENTINEL, body=t.SENTINEL)
    stored = store.create(record)
    for shown in (
        repr(store),
        str(store),
        repr(stored),
        str(stored),
        repr(store.list(ORG)),
        repr(store.get(ORG, "pb_p1")),
    ):
        assert t.SENTINEL not in shown
    assert not caplog.records


# ---------------------------------------------------------------------------------------------
# 4. Compare-and-set under concurrent writers
# ---------------------------------------------------------------------------------------------
def race(workers):
    """Run every worker at once (they wait on one barrier) and return [("ok", result) | ("err", exception)]."""
    barrier = threading.Barrier(len(workers))
    results = [None] * len(workers)

    def run(i):
        barrier.wait()
        try:
            results[i] = ("ok", workers[i]())
        except BaseException as exc:  # noqa: BLE001 - the test inspects whatever the store raised
            results[i] = ("err", exc)

    threads = [threading.Thread(target=run, args=(i,)) for i in range(len(workers))]
    previous = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)  # make interleaving between the check and the write as likely as possible
    try:
        for th in threads:
            th.start()
        for th in threads:
            th.join(timeout=30)
    finally:
        sys.setswitchinterval(previous)
    assert all(r is not None for r in results), "a worker hung"
    return results


def test_PPL_10d_PE_16_two_writers_who_both_read_version_1_cannot_both_win_deterministic():
    store = new_store("work_item")
    store.create(make("work_item", 1))
    seen_a, seen_b = store.get(ORG, "wi_w1"), store.get(ORG, "wi_w1")
    store.replace(make("work_item", 1, title="A wins"), expected_version=seen_a.version)
    with pytest.raises(errors.VersionConflict):
        store.replace(make("work_item", 1, title="B loses"), expected_version=seen_b.version)
    got = store.get(ORG, "wi_w1")
    assert (got.version, got.record["title"]) == (2, "A wins")


@pytest.mark.parametrize("round_", range(10))
def test_PPL_10d_PE_16_racing_replaces_on_one_version_exactly_one_wins(round_):
    store = new_store("work_item")
    store.create(make("work_item", 1))
    records = [make("work_item", 1, title=f"Writer {n}") for n in range(8)]
    results = race([lambda r=r: store.replace(r, expected_version=1) for r in records])
    winners = [i for i, (kind, _) in enumerate(results) if kind == "ok"]
    assert len(winners) == 1, results
    assert all(isinstance(res, errors.VersionConflict) for kind, res in results if kind == "err")
    got = store.get(ORG, "wi_w1")
    assert got.version == 2 and got.record == records[winners[0]]


@pytest.mark.parametrize("round_", range(10))
def test_PPL_10d_PE_16_two_confirms_racing_on_one_version_one_replace_wins_the_other_conflicts(round_):
    store = new_store("work_item")
    proposed = t.proposed_tilo_item()
    store.create(proposed)

    def confirmed_by(who, stamp):
        after = copy.deepcopy(proposed)
        after.update(status="open", confirmed_by={"by": "u_owner", "at": stamp}, updated_at=stamp)
        after["history"].append({"at": stamp, "by": who, "change": "confirmed", "status": "open"})
        return after

    first, second = confirmed_by("u_owner", t.NOW), confirmed_by("u_owner", t.LATER)
    results = race(
        [lambda: store.replace(first, expected_version=1), lambda: store.replace(second, expected_version=1)]
    )
    assert sorted(kind for kind, _ in results) == ["err", "ok"]
    loser = next(res for kind, res in results if kind == "err")
    assert isinstance(loser, errors.VersionConflict)
    got = store.get(ORG, proposed["id"])
    assert got.version == 2 and got.record in (first, second)
    assert len([h for h in got.record["history"] if h["change"] == "confirmed"]) == 1  # never both confirmations


@pytest.mark.parametrize("round_", range(10))
def test_PPL_10d_PE_16_racing_creates_of_one_key_exactly_one_wins(round_):
    store = new_store("work_item")
    records = [make("work_item", 1, title=f"Writer {n}") for n in range(8)]
    results = race([lambda r=r: store.create(r) for r in records])
    winners = [i for i, (kind, _) in enumerate(results) if kind == "ok"]
    assert len(winners) == 1
    assert all(isinstance(res, errors.AlreadyExists) for kind, res in results if kind == "err")
    assert store.get(ORG, "wi_w1").record == records[winners[0]] and len(store.list(ORG)) == 1


@pytest.mark.parametrize("round_", range(10))
def test_PPL_10d_PE_16_racing_deletes_exactly_one_wins_and_the_rest_find_nothing(round_):
    store = new_store("work_item")
    store.create(make("work_item", 1))
    results = race([lambda: store.delete(ORG, "wi_w1", expected_version=1) for _ in range(8)])
    assert sum(kind == "ok" for kind, _ in results) == 1
    assert all(isinstance(res, errors.NotFound) for kind, res in results if kind == "err")
    assert store.get(ORG, "wi_w1") is None


@pytest.mark.parametrize("round_", range(10))
def test_PPL_10d_PE_16_a_replace_racing_a_delete_leaves_one_consistent_outcome(round_):
    store = new_store("work_item")
    store.create(make("work_item", 1))
    new = make("work_item", 1, title="Replaced")
    results = race(
        [lambda: store.replace(new, expected_version=1), lambda: store.delete(ORG, "wi_w1", expected_version=1)]
    )
    assert sum(kind == "ok" for kind, _ in results) == 1
    loser = next(res for kind, res in results if kind == "err")
    assert isinstance(loser, (errors.VersionConflict, errors.NotFound))
    got = store.get(ORG, "wi_w1")
    if results[1][0] == "ok":  # the delete won
        assert got is None and isinstance(loser, errors.NotFound)
    else:
        assert got.version == 2 and got.record == new and isinstance(loser, errors.VersionConflict)


def test_PPL_10d_PE_16_concurrent_writers_to_different_keys_all_succeed():
    store = new_store("work_item")
    results = race([lambda n=n: store.create(make("work_item", n)) for n in range(1, 17)])
    assert all(kind == "ok" for kind, _ in results)
    assert [s.record["id"] for s in store.list(ORG)] == sorted(f"wi_w{n}" for n in range(1, 17))


# ---------------------------------------------------------------------------------------------
# 5. Meeting tombstone and delete_meeting (PE-19, FR-MTG-10, BQ-PPL10-2)
# ---------------------------------------------------------------------------------------------
def _rich_meeting(**ov):
    return t.minuted_meeting(
        title=t.SENTINEL,
        series="weekly-sync",
        scheduled={"start": t.T1, "end": t.T2},
        agenda=[{"title": t.SENTINEL + " agenda", "minutes": 10}],
        attendees=[{"name": t.SENTINEL + " attendee", "user": "u_riya"}, {"name": "Guest", "user": None}],
        world_id="w_01J8Z3K4M5N6P7Q8R9S0T1V2W3",
        ended_reason="completed",
        source="upload",
        delete_transcript_after="2026-11-01T00:00:00.000Z",
        delete_minutes_after="2027-01-01T00:00:00.000Z",
        **ov,
    )


def test_PPL_10d_PE_19_the_tombstone_keeps_identity_and_drops_all_content():
    from tilo_policy.schemas import conforms

    meeting = _rich_meeting()
    assert conforms("meeting.schema.json", meeting)
    tomb = stores.meeting_tombstone(meeting)
    assert conforms("meeting.schema.json", tomb), "a tombstone is a schema-valid meeting (BQ-PPL10-2: the schema wins)"
    for key in ("id", "org_id", "owner", "world_id", "attestation", "source", "ended_reason", "created_at"):
        assert tomb[key] == meeting[key], key
    assert tomb["status"] == "deleted" and tomb["title"] == "Deleted meeting"
    assert tomb["series"] is None and tomb["scheduled"] is None
    assert tomb["agenda"] == [] and tomb["attendees"] == []
    for key in ("transcript", "minutes", "minutes_confirmed_by", "delete_transcript_after", "delete_minutes_after"):
        assert tomb[key] is None, key
    assert set(tomb) == set(meeting)
    shown = t.dump(tomb)
    assert t.SENTINEL not in shown and "Guest" not in shown and "u_riya" not in shown  # nothing of the content survives


def test_PPL_10d_PE_19_a_tombstone_of_a_meeting_without_a_world_has_no_world_key():
    """Ambiguity D in the module docstring."""
    meeting = t.minuted_meeting()
    assert "world_id" not in meeting
    tomb = stores.meeting_tombstone(meeting)
    assert "world_id" not in tomb
    from tilo_policy.schemas import conforms

    assert conforms("meeting.schema.json", tomb)


def test_PPL_10d_PE_19_the_tombstone_is_pure_idempotent_and_independent_of_its_input():
    meeting = _rich_meeting()
    before = copy.deepcopy(meeting)
    tomb = stores.meeting_tombstone(meeting)
    assert meeting == before
    tomb["attestation"]["by"] = "u_evil"
    tomb["agenda"].append("x")
    assert meeting == before  # deep copy
    again = stores.meeting_tombstone(meeting)
    assert stores.meeting_tombstone(again) == again
    assert again == stores.meeting_tombstone(copy.deepcopy(meeting))


@pytest.mark.parametrize("status", ["scheduled", "joining", "live", "ended", "minuted", "discarded", "deleted"])
def test_PPL_10d_PE_19_a_meeting_of_any_status_has_a_valid_tombstone(status):
    from tilo_policy.schemas import conforms

    fields = {"status": status}
    if status == "minuted":
        fields.update(minutes=copy.deepcopy(pl.ART_MINUTES), transcript=copy.deepcopy(pl.ART))
    tomb = stores.meeting_tombstone(t.meeting(**fields))
    assert conforms("meeting.schema.json", tomb) and tomb["status"] == "deleted" and tomb["owner"] == "u_owner"


def _world_with_meeting():
    s = stores.PeopleStores.in_memory()
    meeting = _rich_meeting()
    s.meetings.create(meeting)
    item = t.tilo_item()
    pin = t.tilo_team_pin()
    entry = t.tilo_proposal(owner="u_riya", source={"kind": "tilo", "from": "meeting", "ref": "mt_weekly1#ai1"})
    s.work_items.create(item)
    s.pins.create(pin)
    s.calendar.create(entry)
    return s, meeting, item, pin, entry


def test_PPL_10d_PE_19_delete_meeting_replaces_it_with_its_tombstone_and_touches_nothing_else():
    s, meeting, item, pin, entry = _world_with_meeting()
    other_org = {**copy.deepcopy(meeting), "org_id": OTHER}
    s.meetings.create(other_org)
    result = stores.delete_meeting(s, ORG, meeting["id"], expected_version=1)
    assert isinstance(result, stores.Stored) and result.version == 2
    assert result.record == stores.meeting_tombstone(meeting)
    assert s.meetings.get(ORG, meeting["id"]) == result
    assert s.work_items.get(ORG, item["id"]).record == item and s.work_items.get(ORG, item["id"]).version == 1
    assert s.pins.get(ORG, pin["id"]).record == pin and s.calendar.get(ORG, entry["id"]).version == 1
    assert s.meetings.get(OTHER, meeting["id"]).record == other_org  # another org's meeting with the same id


def test_PPL_10d_PE_19_delete_meeting_is_compare_and_set():
    s, meeting, *_ = _world_with_meeting()
    with pytest.raises(errors.VersionConflict):
        stores.delete_meeting(s, ORG, meeting["id"], expected_version=5)
    assert s.meetings.get(ORG, meeting["id"]).record == meeting  # the failed delete left the meeting whole
    with pytest.raises(errors.NotFound):
        stores.delete_meeting(s, ORG, "mt_nothere1", expected_version=1)
    with pytest.raises(errors.NotFound):
        stores.delete_meeting(s, OTHER, meeting["id"], expected_version=1)
    stores.delete_meeting(s, ORG, meeting["id"], expected_version=1)
    with pytest.raises(errors.VersionConflict):
        stores.delete_meeting(s, ORG, meeting["id"], expected_version=1)  # the same version twice


def test_PPL_10d_PE_19_what_was_made_from_a_deleted_meeting_stays_readable_through_the_tombstone():
    """Integration with `decide` (PPL-10a): the checks that need the meeting need only its owner and id."""
    s, meeting, item, pin, entry = _world_with_meeting()
    d = t.world_directory()
    live = s.meetings.get(ORG, meeting["id"]).record
    assert t.allowed("u_riya", "read_full", "work_item", item, d, meeting=live)
    tomb = stores.delete_meeting(s, ORG, meeting["id"], expected_version=1).record
    assert t.allowed("u_riya", "read_full", "work_item", item, d, meeting=tomb)  # confirmed item still readable
    assert t.allowed("u_riya", "read_full", "pinboard_item", pin, d, meeting=tomb)
    assert not t.allowed("u_sam", "read_full", "work_item", item, d, meeting=tomb)
    # nobody can read the deleted meeting's content: it has none, and only its owner reads even that
    assert not t.allowed("u_riya", "read_full", "meeting", tomb, d)
    # no new calendar proposal for an attendee can cite it (BQ-PPL10-2: it fails closed)
    proposal = t.tilo_proposal(
        id="ce_new1", owner="u_riya", source={"kind": "tilo", "from": "meeting", "ref": "mt_weekly1#ai1"}
    )
    released = t.tilo_item(source={"kind": "meeting", "ref": "mt_weekly1#ai1", "evidence": ["u0004"]})
    assert t.allowed("A_notes", "create", "calendar_entry", proposal, d, meeting=live, work_item=released)
    assert not t.allowed("A_notes", "create", "calendar_entry", proposal, d, meeting=tomb, work_item=released)


# ---------------------------------------------------------------------------------------------
# 6. Calendar disconnect (PE-13) and the sync writer (BQ-PPL10-11)
# ---------------------------------------------------------------------------------------------
def _google(n, owner="u_owner", org=ORG):
    return t.entry(
        id=f"ce_g{n}",
        org_id=org,
        owner=owner,
        created_by=pl.maker_tilo("A_calendar_sync", t.T0),
        source={"kind": "google", "ref": f"evt_{n}", "synced_at": t.T0},
    )


def _calendar_world():
    s = stores.PeopleStores.in_memory()
    for entry in (
        _google(1),
        _google(2),
        _google(3, owner="u_riya"),
        t.entry(id="ce_m1"),  # u_owner's own manual entry
        t.tilo_proposal(id="ce_t1"),  # a Tilo proposal for u_owner
        _google(1, org=OTHER),  # u_owner's id in another org: a different person's cache
    ):
        s.calendar.create(entry)
    return s


def test_PPL_10d_PE_13_disconnecting_calendar_deletes_exactly_the_owners_google_entries():
    s = _calendar_world()
    assert stores.disconnect_calendar(s, ORG, "u_owner") == 2
    assert [e.record["id"] for e in s.calendar.list(ORG)] == ["ce_g3", "ce_m1", "ce_t1"]
    assert s.calendar.get(OTHER, "ce_g1") is not None  # another org untouched
    assert stores.disconnect_calendar(s, ORG, "u_owner") == 0  # nothing left to delete
    assert stores.disconnect_calendar(s, ORG, "u_riya") == 1
    assert [e.record["id"] for e in s.calendar.list(ORG)] == ["ce_m1", "ce_t1"]
    assert stores.disconnect_calendar(s, ORG, "u_nobody") == 0
    assert stores.disconnect_calendar(s, "org_nobody", "u_owner") == 0


def test_PPL_10d_PE_13_disconnecting_calendar_returns_an_int_and_works_through_the_record_store_protocol_only():
    s, log = spy_stores()
    for entry in (_google(1), _google(2), t.entry(id="ce_m1")):
        s.calendar.create(entry)
    log.clear()
    count = stores.disconnect_calendar(s, ORG, "u_owner")
    assert count == 2 and type(count) is int
    assert {kind for kind, _ in log} == {"calendar_entry"}  # it touched no other store
    assert {method for _, method in log} <= {"get", "list", "delete"}
    assert [e.record["id"] for e in s.calendar.list(ORG)] == ["ce_m1"]


def test_PPL_10d_PE_13_the_sync_writer_acts_as_an_agent_id_and_its_cache_goes_with_the_disconnect():
    """BQ-PPL10-11: a sync stamps `A_calendar_sync` (never `system`), which `decide` accepts."""
    d = t.world_directory()
    entry = _google(1)
    assert t.allowed("A_calendar_sync", "create", "calendar_entry", entry, d, source_owner="u_owner")
    assert not t.allowed("system", "create", "calendar_entry", entry, d, source_owner="u_owner")
    assert not t.allowed(
        "A_calendar_sync", "create", "calendar_entry", entry, d, source_owner="u_riya"
    )  # someone else's calendar
    s = stores.PeopleStores.in_memory()
    stored = s.calendar.create(entry)
    assert stored.record["created_by"]["ref"] == "A_calendar_sync" and stored.record["created_by"]["by"] == "tilo"
    assert stores.disconnect_calendar(s, ORG, "u_owner") == 1 and s.calendar.list(ORG) == ()


# ---------------------------------------------------------------------------------------------
# 7. Erasing a person (PE-16, FR-MEM-09, BQ-PPL10-8)
# ---------------------------------------------------------------------------------------------
def _erasure_world(spy=False):
    s, log = spy_stores() if spy else (stores.PeopleStores.in_memory(), None)
    riya, owner, sam = t.person_in("u_riya"), t.person_in("u_owner"), t.person_in("u_sam")
    for p in (riya, owner, sam, {**copy.deepcopy(riya), "org_id": OTHER}):
        s.persons.create(p)
    rm = t.meeting(
        id="mt_r1",
        owner="u_riya",
        title=t.SENTINEL + " riya meeting",
        attestation={"by": "u_riya", "at": t.T0, "notice_version": "1.0.0"},
    )
    om = t.meeting(id="mt_o1", owner="u_owner", title="Owner meeting", attendees=[{"name": "Riya", "user": "u_riya"}])
    for m in (rm, om, {**copy.deepcopy(rm), "org_id": OTHER, "title": "Other org copy"}):
        s.meetings.create(m)
    for w in (
        t.own_item(id="wi_r1", title=t.SENTINEL + " one"),
        t.own_item(id="wi_r2", title=t.SENTINEL + " two"),
        pl.work_item(
            id="wi_o1",
            owner="u_owner",
            title="Owner item assigned by riya",
            assigned_by={"by": "u_riya", "at": t.T0},
            created_by=pl.maker_person("u_riya", t.T0),
        ),
        t.own_item(id="wi_r1", org_id=OTHER, title="Other org item"),
    ):
        s.work_items.create(w)
    for p in (
        t.personal_pin(id="pb_pr1", title=t.SENTINEL + " personal"),
        t.team_pin(
            id="pb_tr1", set_up_by="u_riya", created_by=pl.maker_person("u_riya", t.T0), title="Team pin riya set up"
        ),
        t.team_pin(id="pb_to1", title="Team pin the owner set up"),
        t.personal_pin(
            id="pb_po1",
            scope={"kind": "personal", "user": "u_owner"},
            set_up_by="u_owner",
            created_by=pl.maker_person("u_owner", t.T0),
            title="Owner personal",
        ),
        t.personal_pin(id="pb_pr1", org_id=OTHER, title="Other org personal"),
    ):
        s.pins.create(p)
    for m in (
        t.tag(id="mn_r1", pin_id="pb_to1", user="u_riya"),
        t.tag(id="mn_r2", pin_id="pb_tr1", user="u_riya"),
        t.tag(id="mn_s1", pin_id="pb_tr1", user="u_sam"),
        t.tag(id="mn_r1", org_id=OTHER, user="u_riya"),
    ):
        s.mentions.create(m)
    for e in (
        t.entry(id="ce_r1", owner="u_riya", title=t.SENTINEL + " cal", created_by=pl.maker_person("u_riya", t.T0)),
        _google(2, owner="u_riya"),
        t.entry(id="ce_o1"),
        t.entry(id="ce_r1", owner="u_riya", org_id=OTHER, title="Other org entry"),
    ):
        s.calendar.create(e)
    return (s, log) if spy else s


EXPECTED_KEYS = ["calendar_entry", "meeting", "mention", "person", "pinboard_item", "work_item", "world_share"]


def _ids(store, org=ORG):
    return [s.record["id"] for s in store.list(org)]


def test_PPL_10d_PE_16_erase_person_counts_and_deletes_what_is_theirs_only():
    s = _erasure_world()
    counts = stores.erase_person(s, ORG, "u_riya")
    assert counts == {
        "meeting": 1,
        "work_item": 2,
        "pinboard_item": 1,
        "mention": 2,
        "calendar_entry": 2,
        "world_share": 0,
        "person": 1,
    }
    assert sorted(counts) == EXPECTED_KEYS and all(type(v) is int for v in counts.values())
    # their meeting is a tombstone (so other people's confirmed items stay checkable), not gone
    tomb = s.meetings.get(ORG, "mt_r1").record
    assert tomb["status"] == "deleted" and tomb["owner"] == "u_riya" and tomb["title"] == "Deleted meeting"
    assert _ids(s.meetings) == ["mt_o1", "mt_r1"] and s.meetings.get(ORG, "mt_o1").record["title"] == "Owner meeting"
    assert _ids(s.work_items) == ["wi_o1"]  # even the one they assigned, because it belongs to its owner
    assert _ids(s.pins) == ["pb_po1", "pb_to1", "pb_tr1"]  # personal pin gone; team pins stay ("a former member")
    assert s.pins.get(ORG, "pb_tr1").record["set_up_by"] == "u_riya"
    assert _ids(s.mentions) == ["mn_s1"]  # the mentions naming them go; others on their pin stay
    assert _ids(s.calendar) == ["ce_o1"]
    assert _ids(s.persons) == ["u_owner", "u_sam"]
    # another org holding the same ids is untouched
    assert (
        _ids(s.persons, OTHER) == ["u_riya"]
        and _ids(s.work_items, OTHER) == ["wi_r1"]
        and _ids(s.pins, OTHER) == ["pb_pr1"]
    )
    assert (
        _ids(s.mentions, OTHER) == ["mn_r1"]
        and _ids(s.calendar, OTHER) == ["ce_r1"]
        and _ids(s.meetings, OTHER) == ["mt_r1"]
    )
    assert s.meetings.get(OTHER, "mt_r1").record["title"] == "Other org copy"


def test_PPL_10d_PE_16_after_erasure_none_of_their_text_is_left_anywhere_in_their_org():
    s = _erasure_world()
    stores.erase_person(s, ORG, "u_riya")
    for name in STORE_OF.values():
        for stored in getattr(s, name).list(ORG):
            assert t.SENTINEL not in t.dump(stored.record), (name, stored.record["id"])


def test_PPL_10d_PE_16_a_second_erasure_returns_zeros_and_changes_nothing():
    s = _erasure_world()
    stores.erase_person(s, ORG, "u_riya")
    snapshot = {
        name: [(x.record["id"], x.version, t.dump(x.record)) for x in getattr(s, name).list(ORG)]
        for name in STORE_OF.values()
    }
    again = stores.erase_person(s, ORG, "u_riya")
    assert again == dict.fromkeys(EXPECTED_KEYS, 0)  # a tombstoned meeting is not counted again (ambiguity B)
    assert snapshot == {
        name: [(x.record["id"], x.version, t.dump(x.record)) for x in getattr(s, name).list(ORG)]
        for name in STORE_OF.values()
    }


@pytest.mark.parametrize(
    ("org", "user"), [("org_nobody", "u_riya"), (ORG, "u_nobody"), (OTHER, "u_owner"), ("org_nobody", "u_nobody")]
)
def test_PPL_10d_PE_16_erasing_someone_who_is_not_in_that_org_deletes_nothing(org, user):
    s = _erasure_world()
    before = {
        name: [(x.record["id"], x.version) for x in getattr(s, name).list(o)]
        for name in STORE_OF.values()
        for o in (ORG, OTHER)
    }
    counts = stores.erase_person(s, org, user)
    after = {
        name: [(x.record["id"], x.version) for x in getattr(s, name).list(o)]
        for name in STORE_OF.values()
        for o in (ORG, OTHER)
    }
    assert counts == dict.fromkeys(EXPECTED_KEYS, 0)
    assert after == before


def test_PPL_10d_PE_16_erase_person_uses_only_the_record_store_protocol_meetings_first_person_last():
    s, log = _erasure_world(spy=True)
    log.clear()
    counts = stores.erase_person(s, ORG, "u_riya")
    assert counts["person"] == 1
    assert {method for _, method in log} <= {"get", "list", "replace", "delete"}  # nothing a Firestore store cannot do
    writes_ = [(kind, method) for kind, method in log if method in ("replace", "delete")]
    assert writes_[-1] == ("person", "delete"), "the person record goes last, so a crash leaves the person to retry"
    first_delete_of_other_kinds = next(i for i, w in enumerate(writes_) if w[1] == "delete" and w[0] != "person")
    assert all(w == ("meeting", "replace") for w in writes_[:first_delete_of_other_kinds]), (
        "meetings are tombstoned before anything is deleted"
    )
    assert [w for w in writes_ if w[0] == "meeting"] == [("meeting", "replace")]  # a meeting is replaced, never deleted
    assert writes_.count(("person", "delete")) == 1


def test_PPL_10d_PE_16_erase_person_survives_a_second_run_after_a_partial_one():
    """Simulates a crash: only the meetings were tombstoned and one work item deleted before the process died."""
    s = _erasure_world()
    stores.delete_meeting(s, ORG, "mt_r1", expected_version=1)
    s.work_items.delete(ORG, "wi_r1", expected_version=1)
    counts = stores.erase_person(s, ORG, "u_riya")
    assert counts == {
        "meeting": 0,
        "work_item": 1,
        "pinboard_item": 1,
        "mention": 2,
        "calendar_entry": 2,
        "world_share": 0,
        "person": 1,
    }
    assert _ids(s.persons) == ["u_owner", "u_sam"] and _ids(s.work_items) == ["wi_o1"]


def test_PPL_10d_PE_16_erasure_logs_nothing(caplog):
    caplog.set_level(logging.DEBUG)
    s = _erasure_world()
    stores.erase_person(s, ORG, "u_riya")
    stores.disconnect_calendar(s, ORG, "u_owner")
    stores.delete_meeting(s, ORG, "mt_o1", expected_version=1)
    assert not caplog.records and t.SENTINEL not in caplog.text
