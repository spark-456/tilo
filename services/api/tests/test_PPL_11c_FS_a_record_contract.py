"""PPL-11c-FS FS-02..FS-05: one `RecordStore` contract, run against `MemoryStore` and against the Firestore store
(`@pytest.mark.emulator`, the `backend` fixture of `conftest.py`). Spec: `API_PPL_11c_FS.md` sections 2 and 3.

The behaviour is the one `packages/people/tests/test_PPL_10d_stores.py` pins for `MemoryStore` (this file ports the
cases that matter to a database: keys, versions, compare-and-set, indexes, isolation, races, no record text in an
error). The MemoryStore rows pass today; the Firestore rows fail until `tilo_api.people_firestore` exists, and are
strict xfails (`_ppl11c_fs_lib.FS_PENDING`) until the builder deletes the entry.

Each test makes its own org (`unique_org()`), so the emulator is never cleared between tests. Records are the
contract builders' (`tests/contracts/_people_lib.py`), moved into that org.
"""

from __future__ import annotations

import copy
import logging

import pytest
from _ppl11c_fs_lib import (
    KINDS,
    SENTINEL,
    STORE_OF,
    edited,
    errs,
    everything_said,
    fill,
    make,
    oks,
    race,
    racers,
    unique_org,
)
from tilo_people import errors
from tilo_people.stores import INDEXES, Stored

ROUNDS = range(3)  # each race is a real transaction fight on the emulator: three rounds, not ten


def store_of(backend, kind, stores=None):
    return getattr(stores or backend.stores(), STORE_OF[kind])


# --- FS-02: the contract -------------------------------------------------------------------------------------------


@pytest.mark.parametrize("kind", KINDS)
def test_PPL_11c_FS_02_create_get_replace_delete_with_versions(backend, kind):
    org, store = unique_org(), store_of(backend, kind)
    record = make(kind, 1, org)
    created = store.create(record)
    assert isinstance(created, Stored)
    assert (created.kind, created.version, created.record) == (kind, 1, record)
    assert store.get(org, record["id"]) == created
    changed = edited(kind, record)
    replaced = store.replace(changed, expected_version=1)
    assert (replaced.version, replaced.record) == (2, changed)
    assert store.get(org, record["id"]).version == 2
    assert store.replace(edited(kind, changed), expected_version=2).version == 3  # +1 per replace
    assert store.delete(org, record["id"], expected_version=3) is None
    assert store.get(org, record["id"]) is None
    assert store.create(record).version == 1  # a fresh create starts again


def test_PPL_11c_FS_02_twenty_replaces_make_version_twenty_one(backend):
    org, store = unique_org(), store_of(backend, "work_item")
    record = make("work_item", 1, org)
    store.create(record)
    for n in range(2, 22):
        assert store.replace(make("work_item", 1, org, title=f"Edit {n}"), expected_version=n - 1).version == n
    assert store.get(org, "wi_w1").version == 21


@pytest.mark.parametrize("kind", KINDS)
def test_PPL_11c_FS_02_create_twice_is_already_exists_and_replace_or_delete_of_nothing_is_not_found(backend, kind):
    org, store = unique_org(), store_of(backend, kind)
    record = make(kind, 1, org)
    store.create(record)
    with pytest.raises(errors.AlreadyExists):
        store.create(edited(kind, record))
    assert store.get(org, record["id"]).record == record  # the first one stays
    ghost = make(kind, 9, org)
    with pytest.raises(errors.NotFound):
        store.replace(ghost, expected_version=1)
    with pytest.raises(errors.NotFound):
        store.delete(org, ghost["id"], expected_version=1)
    assert store.get(org, ghost["id"]) is None, "a refused replace creates nothing"


@pytest.mark.parametrize("kind", KINDS)
def test_PPL_11c_FS_02_a_stale_or_wrong_version_is_a_version_conflict_and_changes_nothing(backend, kind):
    org, store = unique_org(), store_of(backend, kind)
    record = make(kind, 1, org)
    store.create(record)
    store.replace(edited(kind, record), expected_version=1)  # now at version 2
    for wrong in (1, 0, -1, 3, 99):
        with pytest.raises(errors.VersionConflict):
            store.replace(record, expected_version=wrong)
        with pytest.raises(errors.VersionConflict):
            store.delete(org, record["id"], expected_version=wrong)
    still = store.get(org, record["id"])
    assert (still.version, still.record) == (2, edited(kind, record))


@pytest.mark.parametrize("version", ["1", None, 1.5, [1], {}, b"1", True])
def test_PPL_11c_FS_02_a_version_that_is_not_an_int_is_a_malformed_argument(backend, version):
    org, store = unique_org(), store_of(backend, "work_item")
    record = make("work_item", 1, org)
    store.create(record)
    with pytest.raises(errors.PeopleInputError):
        store.replace(record, expected_version=version)
    with pytest.raises(errors.PeopleInputError):
        store.delete(org, record["id"], expected_version=version)
    assert store.get(org, record["id"]).version == 1


@pytest.mark.parametrize("kind", KINDS)
def test_PPL_11c_FS_02_a_record_that_fails_its_schema_is_refused_on_create_and_replace(backend, kind):
    org, store = unique_org(), store_of(backend, kind)
    record = make(kind, 1, org)
    bad_records = [
        {**record, "x_extra": 1},
        {k: v for k, v in record.items() if k != "id"},
        {**record, "id": "not an id"},
        {**record, "id": "../" + record["id"]},
        {**record, "org_id": "acme"},
        {**record, "org_id": "org_x/people_person"},
        [],
        None,
        "record",
        5,
    ]
    for bad in bad_records:
        with pytest.raises(errors.PeopleInputError):
            store.create(bad)
    assert store.list(org) == ()
    store.create(record)
    for bad in bad_records:
        if isinstance(bad, dict) and bad.get("id") != record["id"]:
            continue  # a replace is keyed by the record's own id; those are covered by create
        with pytest.raises(errors.PeopleInputError):
            store.replace(bad, expected_version=1)
    assert store.get(org, record["id"]).record == record


@pytest.mark.parametrize("kind", KINDS)
def test_PPL_11c_FS_02_a_store_takes_only_its_own_kind(backend, kind):
    org, store = unique_org(), store_of(backend, kind)
    for other in KINDS:
        if other != kind:
            with pytest.raises(errors.PeopleInputError):
                store.create(make(other, 1, org))
    assert store.list(org) == ()


@pytest.mark.parametrize("kind", KINDS)
def test_PPL_11c_FS_02_records_are_keyed_by_org_and_id_so_two_orgs_never_see_each_other(backend, kind):
    org, other = unique_org(), unique_org()
    store = store_of(backend, kind)
    mine = make(kind, 1, org)
    theirs = {**copy.deepcopy(mine), "org_id": other}
    store.create(mine)
    assert store.get(other, mine["id"]) is None  # another org's id lookup is blank, never a leak
    store.create(theirs)  # the same id in another org is a different record, not AlreadyExists
    assert store.get(org, mine["id"]).record == mine and store.get(other, mine["id"]).record == theirs
    store.replace(edited(kind, mine), expected_version=1)
    assert store.get(other, mine["id"]).version == 1 and store.get(other, mine["id"]).record == theirs
    store.delete(org, mine["id"], expected_version=2)
    assert store.get(org, mine["id"]) is None and store.get(other, mine["id"]).record == theirs
    assert [s.record["org_id"] for s in store.list(other)] == [other] and store.list(org) == ()
    with pytest.raises(errors.NotFound):
        store.delete(org, mine["id"], expected_version=1)  # not found in this org, though it exists in the other


BAD_ORGS = [
    None,
    5,
    "",
    "acme",
    "org_acme\n",
    "org_",
    ["org_acme"],
    b"org_acme",
    "org_" + "x" * 80,
    "org_a/people_work_item/wi_w1",  # a path, not an id: it must never be read as one
    "orgs/org_a",
    "..",
    ".",
    "__x__",
]
BAD_IDS = [None, 5, "", "wi_w1\n", "w1", ["wi_w1"], "wi_w1/x", "../wi_w1", "..", ".", "__wi__", "wi_w1" + "x" * 2000]


def test_PPL_11c_FS_02_a_malformed_org_or_id_reads_as_nothing_and_is_never_an_error_or_a_path(backend):
    """`get` is None, `list` is empty, `delete` of it is NotFound (or a malformed-argument error), and an id is never
    turned into a Firestore path (a `/` or `..` must not reach another document)."""
    real_org = unique_org()
    store = store_of(backend, "work_item")
    store.create(make("work_item", 1, real_org))
    for org in BAD_ORGS:
        assert store.get(org, "wi_w1") is None, repr(org)
        assert store.list(org) == (), repr(org)
        for record_id in BAD_IDS:
            assert store.get(org, record_id) is None, (org, record_id)
    for record_id in BAD_IDS:
        assert store.get(real_org, record_id) is None, repr(record_id)
        with pytest.raises((errors.NotFound, errors.PeopleInputError)):
            store.delete(real_org, record_id, expected_version=1)
    for org in BAD_ORGS:
        with pytest.raises((errors.NotFound, errors.PeopleInputError)):
            store.delete(org, "wi_w1", expected_version=1)
    assert store.get(real_org, "wi_w1").version == 1, "nothing else was touched"


@pytest.mark.parametrize("kind", ["work_item", "person"])
def test_PPL_11c_FS_02_records_go_in_and_out_as_deep_copies(backend, kind):
    org, store = unique_org(), store_of(backend, kind)
    record = make(kind, 1, org)
    created = store.create(record)
    key = "history" if kind == "work_item" else "aliases"
    record[key].append("junk")
    record["created_by"]["by"] = "u_mutated"
    created.record[key].append("junk")
    again = store.get(org, record["id"])
    assert "junk" not in again.record[key] and again.record["created_by"]["by"] != "u_mutated"
    again.record[key].append("junk")
    listed = store.list(org)
    assert "junk" not in listed[0].record[key]
    listed[0].record[key].append("junk")
    assert "junk" not in store.get(org, record["id"]).record[key]
    new = edited(kind, make(kind, 1, org))
    replaced = store.replace(new, expected_version=1)
    new[key].append("junk")
    replaced.record[key].append("junk")
    assert "junk" not in store.get(org, record["id"]).record[key]


def test_PPL_11c_FS_02_text_numbers_and_nesting_round_trip_exactly(backend):
    """What goes in comes out equal: non-ASCII text, an emoji, quotes, empty lists, nulls, booleans (not 0 and 1) and
    the order of a list; and a record of two orgs with the same text does not mix."""
    org, store = unique_org(), store_of(backend, "work_item")
    history = [
        {"at": "2026-10-01T09:00:00.000Z", "by": "u_riya", "change": "created", "status": "open"},
        {"at": "2026-10-01T09:05:00.000Z", "by": "u_riya", "change": "edited", "status": "open"},
        {"at": "2026-10-01T09:10:00.000Z", "by": "u_riya", "change": "edited", "status": "open"},
    ]
    record = make(
        "work_item",
        1,
        org,
        title="Café ☕ 日本語 — “quoted” \U0001f600 'x'",
        due=None,
        due_text=None,
        flagged=True,
        history=history,
    )
    store.create(record)
    got = store.get(org, "wi_w1")
    assert got.record == record
    assert got.record["flagged"] is True and got.record["due"] is None
    assert [h["at"] for h in got.record["history"]] == [h["at"] for h in history]
    assert store.list(org)[0].record == record


# --- FS-03: list and the indexes -----------------------------------------------------------------------------------

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


@pytest.mark.parametrize("kind", KINDS)
def test_PPL_11c_FS_03_list_returns_the_orgs_records_sorted_by_id_as_a_tuple(backend, kind):
    org, other = unique_org(), unique_org()
    stores = backend.stores()
    rows = fill(stores, kind, org, other)
    store = store_of(backend, kind, stores)
    got = store.list(org)
    assert isinstance(got, tuple) and all(isinstance(s, Stored) for s in got)
    assert [s.record["id"] for s in got] == sorted(r["id"] for r in rows)
    assert all(s.record["org_id"] == org and s.version == 1 and s.kind == kind for s in got)
    assert [s.record["org_id"] for s in store.list(other)] == [other]
    assert store.list(unique_org()) == ()


@pytest.mark.parametrize("kind", sorted(INDEX_EXPECTATIONS))
def test_PPL_11c_FS_03_list_by_an_index_is_equality_on_that_field_within_the_org(backend, kind):
    org, other = unique_org(), unique_org()
    stores = backend.stores()
    fill(stores, kind, org, other)
    store = store_of(backend, kind, stores)
    assert {field for field, _, _ in INDEX_EXPECTATIONS[kind]} == set(INDEXES[kind])
    for field, value, ids in INDEX_EXPECTATIONS[kind]:
        got = store.list(org, field, value)
        assert [s.record["id"] for s in got] == ids, (field, value)
        assert all(s.record["org_id"] == org for s in got)


@pytest.mark.parametrize("kind", KINDS)
def test_PPL_11c_FS_03_list_by_a_field_that_is_not_an_index_is_a_malformed_argument(backend, kind):
    org, other = unique_org(), unique_org()
    stores = backend.stores()
    fill(stores, kind, org, other)
    store = store_of(backend, kind, stores)
    allowed = set(INDEXES[kind])
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
        "record.owner",  # the adapter's own envelope field is not a caller's index
        "version",
        "NoneType",
    ):
        if field not in allowed:
            with pytest.raises(errors.PeopleInputError):
                store.list(org, field, "u_a")
    for junk in (5, ["owner"], b"owner"):
        with pytest.raises(errors.PeopleInputError):
            store.list(org, junk, "u_a")
    if allowed:
        field = next(iter(allowed))
        for bad_value in (5, None, ["u_a"], b"u_a"):
            with pytest.raises(errors.PeopleInputError):
                store.list(org, field, bad_value)


def test_PPL_11c_FS_03_an_index_follows_replace_and_delete(backend):
    """A list by index reflects every committed change at once (no stale index, no second copy)."""
    org, store = unique_org(), store_of(backend, "work_item")
    for n in (1, 2, 3):
        store.create(make("work_item", n, org, owner="u_a"))
    assert [s.record["id"] for s in store.list(org, "owner", "u_a")] == ["wi_w1", "wi_w2", "wi_w3"]
    store.replace(make("work_item", 2, org, owner="u_b"), expected_version=1)
    store.delete(org, "wi_w3", expected_version=1)
    assert [s.record["id"] for s in store.list(org, "owner", "u_a")] == ["wi_w1"]
    assert [(s.record["id"], s.version) for s in store.list(org, "owner", "u_b")] == [("wi_w2", 2)]


def test_PPL_11c_FS_03_list_returns_every_record_not_a_page(backend):
    org, store = unique_org(), store_of(backend, "work_item")
    for n in range(120):
        store.create(make("work_item", n, org, owner="u_a" if n % 2 else "u_b"))
    assert len(store.list(org)) == 120
    assert len(store.list(org, "owner", "u_a")) == 60
    ids = [s.record["id"] for s in store.list(org)]
    assert ids == sorted(ids)


def test_PPL_11c_FS_03_a_person_store_has_no_index_at_all(backend):
    org, other = unique_org(), unique_org()
    stores = backend.stores()
    fill(stores, "person", org, other)
    for field in ("owner", "id", "email", "scope.user"):
        with pytest.raises(errors.PeopleInputError):
            stores.persons.list(org, field, "u_p1")


# --- FS-04: compare-and-set and create-if-absent are the database's, not the process's -----------------------------


@pytest.mark.parametrize("round_", ROUNDS)
def test_PPL_11c_FS_04_racing_replaces_on_one_version_exactly_one_wins(backend, round_):
    org, store = unique_org(), store_of(backend, "work_item")
    store.create(make("work_item", 1, org))
    records = [make("work_item", 1, org, title=f"Writer {n}") for n in range(racers(backend))]
    results = race([lambda r=r: store.replace(r, expected_version=1) for r in records])
    assert len(oks(results)) == 1, results
    assert all(isinstance(e, errors.VersionConflict) for e in errs(results)), errs(results)
    got = store.get(org, "wi_w1")
    assert got.version == 2 and got.record in records


@pytest.mark.parametrize("round_", ROUNDS)
def test_PPL_11c_FS_04_racing_creates_of_one_key_exactly_one_wins(backend, round_):
    org, store = unique_org(), store_of(backend, "work_item")
    records = [make("work_item", 1, org, title=f"Writer {n}") for n in range(racers(backend))]
    results = race([lambda r=r: store.create(r) for r in records])
    assert len(oks(results)) == 1, results
    assert all(isinstance(e, errors.AlreadyExists) for e in errs(results)), errs(results)
    assert store.get(org, "wi_w1").record in records and len(store.list(org)) == 1


@pytest.mark.parametrize("round_", ROUNDS)
def test_PPL_11c_FS_04_racing_deletes_exactly_one_wins_and_the_rest_find_nothing(backend, round_):
    org, store = unique_org(), store_of(backend, "work_item")
    store.create(make("work_item", 1, org))
    results = race([lambda: store.delete(org, "wi_w1", expected_version=1) for _ in range(racers(backend))])
    assert len(oks(results)) == 1, results
    assert all(isinstance(e, errors.NotFound) for e in errs(results)), errs(results)
    assert store.get(org, "wi_w1") is None


@pytest.mark.parametrize("round_", ROUNDS)
def test_PPL_11c_FS_04_a_replace_racing_a_delete_leaves_one_consistent_outcome(backend, round_):
    org, store = unique_org(), store_of(backend, "work_item")
    store.create(make("work_item", 1, org))
    new = make("work_item", 1, org, title="Replaced")
    results = race(
        [lambda: store.replace(new, expected_version=1), lambda: store.delete(org, "wi_w1", expected_version=1)]
    )
    assert len(oks(results)) == 1, results
    loser = errs(results)[0]
    got = store.get(org, "wi_w1")
    if results[1][0] == "ok":  # the delete won
        assert got is None and isinstance(loser, errors.NotFound)
    else:
        assert got.version == 2 and got.record == new and isinstance(loser, errors.VersionConflict)


def test_PPL_11c_FS_04_concurrent_writers_to_different_keys_all_succeed(backend):
    """Contention on one collection is not a failure: creates of different ids all land (no `Aborted`, no
    `WriterBusy`, no lost write)."""
    org, store = unique_org(), store_of(backend, "work_item")
    count = racers(backend) * 2
    results = race([lambda n=n: store.create(make("work_item", n, org)) for n in range(1, count + 1)])
    assert not errs(results), errs(results)
    assert [s.record["id"] for s in store.list(org)] == sorted(f"wi_w{n}" for n in range(1, count + 1))


def test_PPL_11c_FS_04_two_service_instances_cannot_both_win_one_version(backend):
    """The compare-and-set is the database's: two adapter objects (two instances of the service, each with its own
    client where the backend has one) racing on one version still leave one winner. Memory: one object, same rule."""
    org = unique_org()
    one = backend.stores()
    two = backend.stores_on_new_client() if backend.is_firestore else one
    one.work_items.create(make("work_item", 1, org))
    results = race(
        [
            lambda: one.work_items.replace(make("work_item", 1, org, title="One"), expected_version=1),
            lambda: two.work_items.replace(make("work_item", 1, org, title="Two"), expected_version=1),
        ]
    )
    assert len(oks(results)) == 1, results
    assert all(isinstance(e, errors.VersionConflict) for e in errs(results))
    assert one.work_items.get(org, "wi_w1").version == 2 == two.work_items.get(org, "wi_w1").version


# --- FS-05: no record text in an error, a repr or a log ------------------------------------------------------------


def _with_text(kind, org):
    record = make(kind, 1, org)
    if kind == "person":
        record["display_name"] = SENTINEL
        record["aliases"] = [SENTINEL]
        record["email"] = "sentinel.address@example.com"
    elif kind != "mention":  # a mention holds no text
        record["title"] = SENTINEL
    return record


def _tilo_records(caplog):
    return [r for r in caplog.records if r.name.startswith("tilo")]


@pytest.mark.parametrize("kind", KINDS)
def test_PPL_11c_FS_05_errors_name_the_kind_id_and_versions_and_never_record_text(backend, kind, caplog):
    caplog.set_level(logging.DEBUG)
    org, store = unique_org(), store_of(backend, kind)
    record = _with_text(kind, org)
    store.create(record)
    store.replace(record, expected_version=1)  # now version 2
    seen = []
    mine, ghost = record["id"], make(kind, 9, org)["id"]
    for call, record_id in (
        (lambda: store.create(record), mine),
        (lambda: store.replace(record, expected_version=7), mine),
        (lambda: store.delete(org, record["id"], expected_version=7), mine),
        (lambda: store.replace({**record, "id": ghost}, expected_version=1), ghost),
        (lambda: store.delete(org, ghost, expected_version=1), ghost),
    ):
        with pytest.raises(errors.PeopleError) as caught:
            call()
        seen.append(caught.value)
        said = everything_said(caught.value)
        assert SENTINEL not in said and "sentinel.address" not in said, type(caught.value).__name__
        assert kind in str(caught.value) and record_id in str(caught.value), str(caught.value)
        assert type(caught.value).__module__.startswith("tilo_people"), "a library exception leaked out"
    conflict = seen[1]
    assert isinstance(conflict, errors.VersionConflict) and "7" in str(conflict) and "2" in str(conflict)
    assert SENTINEL not in caplog.text and not _tilo_records(caplog), "the stores never log"


def test_PPL_11c_FS_05_a_schema_failure_message_does_not_echo_the_bad_value_or_the_bad_key(backend, caplog):
    caplog.set_level(logging.DEBUG)
    org, store = unique_org(), store_of(backend, "work_item")
    leaky = [
        {**make("work_item", 1, org), "status": SENTINEL},
        {**make("work_item", 1, org), SENTINEL: "x"},
        {**make("work_item", 1, org), "title": SENTINEL * 20},
        {
            **make("work_item", 1, org),
            "history": [{"at": SENTINEL, "by": "u_riya", "change": "created", "status": "open"}],
        },
        {**make("work_item", 1, org), "source": {"kind": SENTINEL, "ref": None, "evidence": []}},
        {**make("work_item", 1, org), "due": SENTINEL},
    ]
    for record in leaky:
        with pytest.raises(errors.PeopleInputError) as caught:
            store.create(record)
        assert SENTINEL not in everything_said(caught.value)
    assert SENTINEL not in caplog.text and not _tilo_records(caplog)


def test_PPL_11c_FS_05_the_store_holds_the_record_but_says_nothing_of_it(backend, caplog):
    caplog.set_level(logging.DEBUG)
    org = unique_org()
    stores = backend.stores()
    record = make("pinboard_item", 1, org, title=SENTINEL, body=SENTINEL)
    stored = stores.pins.create(record)
    for shown in (
        repr(stores),
        str(stores),
        repr(stores.pins),
        str(stores.pins),
        repr(stored),
        str(stored),
        repr(stores.pins.list(org)),
        repr(stores.pins.get(org, "pb_p1")),
    ):
        assert SENTINEL not in shown
    assert not _tilo_records(caplog) and SENTINEL not in caplog.text
