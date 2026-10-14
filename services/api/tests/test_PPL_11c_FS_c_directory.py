"""PPL-11c-FS FS-07..FS-11: the directory's atomic checks live in the store, not in a process lock (issue #541 items
2 and 3). Spec: `API_PPL_11c_FS.md` section 2.

The person store (`PeopleStores.persons`, both `MemoryStore("person")` and the Firestore store) gains:

* `create_founder(record)`: create-if-absent founder marker + the person + its address reservation in ONE atomic step.
  `OrgAlreadyFounded` when the org has a marker or already has any person; `AlreadyExists` for the id and `EmailTaken`
  for the address, in that order; `PeopleInputError` for a record that is not a schema-valid `owner`.
* `founded(org_id) -> bool`: is there a founder marker. The marker is never removed (erasing the founder keeps it).
* `create`, `replace` and `delete` keep one address reservation per person in step with the record, atomically: a
  second person with the address (lower-cased comparison) is `EmailTaken`; a delete frees it; a replace that changes
  the address moves it, or is `EmailTaken` and changes nothing.
* `tilo_people.stores.erase_person` refuses to erase an org's last person unless the org is `founded`
  (`LastPerson`, nothing changed).

Every test runs against `MemoryStore` (so the rules are the same where there is no database) and, with
`@pytest.mark.emulator`, the Firestore emulator. The races use real threads; the "two service instances" tests use two
adapter objects over two Firestore clients, which no in-process lock can serialise.
"""

from __future__ import annotations

import pytest
from _ppl11c_fs_lib import (
    SENTINEL,
    email_path,
    errs,
    everything_said,
    founder_path,
    make,
    oks,
    person,
    race,
    racers,
    raw,
    raw_ids,
    unique_org,
)
from tilo_people import errors
from tilo_people.stores import erase_person

ROUNDS = range(3)
emulator = pytest.mark.emulator
BAD_ORGS = [None, 5, "", "acme", "org_a/people_person/u_x", "..", ["org_a"]]


def _owner(uid, org, **ov):
    return person(uid, org, role="owner", **ov)


# --- FS-07: the founder --------


def test_PPL_11c_FS_07_the_first_person_of_an_org_is_created_with_the_founder_marker(backend):
    org, stores = unique_org(), backend.stores()
    assert stores.persons.founded(org) is False
    record = _owner("u_first", org)
    stored = stores.persons.create_founder(record)
    assert (stored.kind, stored.version, stored.record) == ("person", 1, record)
    assert stores.persons.founded(org) is True
    assert stores.persons.get(org, "u_first") == stored
    assert [s.record["id"] for s in stores.persons.list(org)] == ["u_first"]
    assert stores.persons.founded(unique_org()) is False, "the marker is per org"


def test_PPL_11c_FS_07_a_second_founder_is_refused_and_changes_nothing(backend):
    org, stores = unique_org(), backend.stores()
    first = stores.persons.create_founder(_owner("u_first", org))
    for rival in (
        _owner("u_second", org, email="second@example.com"),
        _owner("u_first", org),  # the same record again: the marker answers first, not AlreadyExists
        _owner("u_first", org, email="other@example.com"),
    ):
        with pytest.raises(errors.OrgAlreadyFounded):
            stores.persons.create_founder(rival)
    assert [s.record["id"] for s in stores.persons.list(org)] == ["u_first"]
    assert stores.persons.get(org, "u_first") == first
    stores.persons.create(person("u_second", org, email="second@example.com"))  # no reservation was left behind
    stores.persons.create(person("u_other", org, email="other@example.com"))


def test_PPL_11c_FS_07_a_founder_is_a_schema_valid_owner_or_nothing_is_written(backend):
    org, stores = unique_org(), backend.stores()
    member = person("u_member", org, email="member@example.com")  # org_role member
    bad_email = _owner("u_bad", org, email="not an address")
    extra = {**_owner("u_extra", org, email="extra@example.com"), "x_extra": 1}
    for record in (member, bad_email, extra, None, [], "record"):
        with pytest.raises(errors.PeopleInputError):
            stores.persons.create_founder(record)
    assert stores.persons.founded(org) is False and stores.persons.list(org) == ()
    stores.persons.create_founder(_owner("u_ok", org, email="member@example.com"))  # no reservation was left behind
    assert stores.persons.founded(org) is True


def test_PPL_11c_FS_07_an_org_that_already_has_a_person_cannot_be_founded(backend):
    """`/first` on an org seeded by hand (or by an earlier build) is refused: "no person now" and "never founded" are
    both required, and the marker is not invented for the people already there."""
    org, stores = unique_org(), backend.stores()
    stores.persons.create(person("u_seed", org, role="owner"))
    with pytest.raises(errors.OrgAlreadyFounded):
        stores.persons.create_founder(_owner("u_new", org, email="new@example.com"))
    assert stores.persons.founded(org) is False, "a seeded org is not founded, so its last person cannot be erased"
    assert [s.record["id"] for s in stores.persons.list(org)] == ["u_seed"]


def test_PPL_11c_FS_07_the_marker_outlives_every_person_so_an_erased_org_cannot_be_refounded(backend):
    org, stores = unique_org(), backend.stores()
    stores.persons.create_founder(_owner("u_first", org))
    stores.persons.create(person("u_second", org))
    stores.persons.delete(org, "u_first", expected_version=1)
    stores.persons.delete(org, "u_second", expected_version=1)
    assert stores.persons.list(org) == ()
    assert stores.persons.founded(org) is True
    with pytest.raises(errors.OrgAlreadyFounded):
        stores.persons.create_founder(_owner("u_stranger", org, email="stranger@example.com"))
    assert stores.persons.list(org) == ()


def test_PPL_11c_FS_07_a_malformed_org_is_not_founded(backend):
    stores = backend.stores()
    for org in BAD_ORGS:
        assert stores.persons.founded(org) is False, repr(org)


def test_PPL_11c_FS_07_the_refusals_name_ids_and_never_record_text(backend):
    org, stores = unique_org(), backend.stores()
    record = _owner("u_first", org, display_name=SENTINEL, aliases=[SENTINEL], email="sentinel.address@example.com")
    stores.persons.create_founder(record)
    for call in (
        lambda: stores.persons.create_founder(record),
        lambda: stores.persons.create_founder({**record, "id": "u_other"}),
        lambda: stores.persons.create_founder({**record, "org_role": SENTINEL}),
    ):
        with pytest.raises(errors.PeopleError) as caught:
            call()
        said = everything_said(caught.value)
        assert SENTINEL not in said and "sentinel.address" not in said, type(caught.value).__name__


# --- FS-08: founder races --------


@pytest.mark.parametrize("round_", ROUNDS)
def test_PPL_11c_FS_08_racing_founders_leave_exactly_one_founder(backend, round_):
    org, stores = unique_org(), backend.stores()
    results = race([lambda i=i: stores.persons.create_founder(_owner(f"u_f{i}", org)) for i in range(racers(backend))])
    assert len(oks(results)) == 1, results
    assert all(isinstance(e, errors.OrgAlreadyFounded) for e in errs(results)), errs(results)
    winner = oks(results)[0].record["id"]
    assert [s.record["id"] for s in stores.persons.list(org)] == [winner]
    assert stores.persons.founded(org) is True
    if backend.is_firestore:
        assert raw(backend.client, founder_path(org)) == {"uid": winner}
        reservations = [d for d in raw_ids(backend.client, f"orgs/{org}/people_directory") if d.startswith("email_")]
        assert reservations == [email_path(org, f"{winner[2:]}@example.com").rsplit("/", 1)[1]], (
            "the losers wrote no reservation"
        )


@emulator
@pytest.mark.parametrize("round_", ROUNDS)
def test_PPL_11c_FS_08_two_service_instances_cannot_mint_two_founders(fs_backend, round_):
    """Two instances of tilo-api (each with its own adapter objects and Firestore client) claim one empty org at the
    same moment: no process lock can help, so one winner means the transaction decides."""
    org = unique_org()
    one, two = fs_backend.stores_on_new_client(), fs_backend.stores_on_new_client()
    workers = [
        lambda i=i: (one if i % 2 else two).persons.create_founder(_owner(f"u_i{i}", org, email=f"i{i}@example.com"))
        for i in range(4)
    ]
    results = race(workers)
    assert len(oks(results)) == 1, results
    assert all(isinstance(e, errors.OrgAlreadyFounded) for e in errs(results)), errs(results)
    assert len(one.persons.list(org)) == 1 == len(two.persons.list(org))
    assert one.persons.founded(org) and two.persons.founded(org)


def test_PPL_11c_FS_08_a_founder_racing_a_plain_create_leaves_one_consistent_org(backend):
    """A member-create and a founder-create at once on an empty org: whichever commits first, the other is refused
    or lands consistently. If there is a marker, its founder is in the org (or was erased); never two founders."""
    org, stores = unique_org(), backend.stores()
    results = race(
        [
            lambda: stores.persons.create_founder(_owner("u_f", org, email="f@example.com")),
            lambda: stores.persons.create(person("u_m", org, email="m@example.com")),
        ]
    )
    assert not [e for e in errs(results) if not isinstance(e, errors.OrgAlreadyFounded)], errs(results)
    ids = sorted(s.record["id"] for s in stores.persons.list(org))
    if stores.persons.founded(org):
        assert "u_f" in ids
    else:
        assert ids == ["u_m"]


# --- FS-09: the address reservation --------


def test_PPL_11c_FS_09_an_address_belongs_to_one_person_of_the_org_whatever_its_case(backend):
    org, other, stores = unique_org(), unique_org(), backend.stores()
    first = stores.persons.create(person("u_nina", org, email="Nina.Patel@Example.com"))
    for email in ("nina.patel@example.com", "NINA.PATEL@EXAMPLE.COM", "Nina.Patel@Example.com"):
        with pytest.raises(errors.EmailTaken) as caught:
            stores.persons.create(person("u_other", org, email=email))
        said = everything_said(caught.value).lower()
        assert "nina" not in said and "example.com" not in said, "the address is never in an error"
    assert [s.record["id"] for s in stores.persons.list(org)] == ["u_nina"]
    assert stores.persons.get(org, "u_nina") == first
    stores.persons.create(person("u_other", org, email="other@example.com"))
    stores.persons.create(person("u_nina", other, email="Nina.Patel@Example.com"))  # another org's address is no clash


def test_PPL_11c_FS_09_the_id_clash_is_reported_before_the_address_clash(backend):
    org, stores = unique_org(), backend.stores()
    stores.persons.create(person("u_nina", org, email="nina@example.com"))
    with pytest.raises(errors.AlreadyExists):
        stores.persons.create(person("u_nina", org, email="nina@example.com"))
    with pytest.raises(errors.AlreadyExists):
        stores.persons.create(person("u_nina", org, email="someone.else@example.com"))
    stores.persons.create(person("u_new", org, email="someone.else@example.com"))  # the refused create reserved nothing


def test_PPL_11c_FS_09_a_refused_create_leaves_no_reservation(backend):
    """A reservation is written in the same transaction as the person: when the person is not created, the address is
    not held (a wrong schema, a wrong kind of record, an id clash)."""
    org, stores = unique_org(), backend.stores()
    with pytest.raises(errors.PeopleInputError):
        stores.persons.create({**person("u_bad", org, email="held@example.com"), "x_extra": 1})
    with pytest.raises(errors.PeopleInputError):
        stores.persons.create({**person("u_bad", org, email="held@example.com"), "id": "not an id"})
    stores.persons.create(person("u_good", org, email="held@example.com"))
    assert [s.record["id"] for s in stores.persons.list(org)] == ["u_good"]
    if backend.is_firestore:
        assert raw(backend.client, email_path(org, "held@example.com")) == {"person_id": "u_good"}


@pytest.mark.parametrize("round_", ROUNDS)
def test_PPL_11c_FS_09_racing_creates_with_one_address_leave_one_person(backend, round_):
    org, stores = unique_org(), backend.stores()
    cases = [
        "Race@Example.com",
        "race@example.com",
        "RACE@EXAMPLE.COM",
        "rAcE@eXaMpLe.CoM",
    ] * 2  # more than any race uses
    results = race(
        [lambda i=i: stores.persons.create(person(f"u_r{i}", org, email=cases[i])) for i in range(racers(backend))]
    )
    assert len(oks(results)) == 1, results
    assert all(isinstance(e, errors.EmailTaken) for e in errs(results)), errs(results)
    winner = oks(results)[0].record["id"]
    assert [s.record["id"] for s in stores.persons.list(org)] == [winner]
    if backend.is_firestore:
        assert raw(backend.client, email_path(org, "race@example.com")) == {"person_id": winner}


def test_PPL_11c_FS_09_different_addresses_racing_all_succeed(backend):
    org, stores = unique_org(), backend.stores()
    results = race(
        [
            lambda i=i: stores.persons.create(person(f"u_d{i}", org, email=f"d{i}@example.com"))
            for i in range(racers(backend))
        ]
    )
    assert not errs(results), errs(results)
    assert len(stores.persons.list(org)) == racers(backend)


@emulator
@pytest.mark.parametrize("round_", ROUNDS)
def test_PPL_11c_FS_09_two_service_instances_cannot_both_take_an_address(fs_backend, round_):
    org = unique_org()
    one, two = fs_backend.stores_on_new_client(), fs_backend.stores_on_new_client()
    workers = [
        lambda i=i: (one if i % 2 else two).persons.create(person(f"u_i{i}", org, email="shared@example.com"))
        for i in range(4)
    ]
    results = race(workers)
    assert len(oks(results)) == 1, results
    assert all(isinstance(e, errors.EmailTaken) for e in errs(results)), errs(results)
    assert len(one.persons.list(org)) == 1


def test_PPL_11c_FS_09_a_founder_and_a_member_racing_for_one_address_do_not_both_get_it(backend):
    org, stores = unique_org(), backend.stores()
    results = race(
        [
            lambda: stores.persons.create_founder(_owner("u_f", org, email="same@example.com")),
            lambda: stores.persons.create(person("u_m", org, email="same@example.com")),
        ]
    )
    assert len(oks(results)) == 1, results
    assert all(isinstance(e, (errors.EmailTaken, errors.OrgAlreadyFounded)) for e in errs(results)), errs(results)
    holders = [s for s in stores.persons.list(org) if s.record["email"].lower() == "same@example.com"]
    assert len(holders) == 1


# --- FS-10: the reservation follows the person --------


def test_PPL_11c_FS_10_a_delete_frees_the_address(backend):
    org, stores = unique_org(), backend.stores()
    stores.persons.create(person("u_a", org, email="a@example.com"))
    with pytest.raises(errors.EmailTaken):
        stores.persons.create(person("u_b", org, email="A@example.com"))
    stores.persons.delete(org, "u_a", expected_version=1)
    stores.persons.create(person("u_b", org, email="A@example.com"))
    if backend.is_firestore:
        assert raw(backend.client, email_path(org, "a@example.com")) == {"person_id": "u_b"}


def test_PPL_11c_FS_10_a_failed_delete_keeps_the_address(backend):
    org, stores = unique_org(), backend.stores()
    stores.persons.create(person("u_a", org, email="a@example.com"))
    with pytest.raises(errors.VersionConflict):
        stores.persons.delete(org, "u_a", expected_version=9)
    with pytest.raises(errors.EmailTaken):
        stores.persons.create(person("u_b", org, email="a@example.com"))


def test_PPL_11c_FS_10_a_replace_that_changes_the_address_moves_the_reservation(backend):
    org, stores = unique_org(), backend.stores()
    stores.persons.create(person("u_a", org, email="old@example.com"))
    moved = stores.persons.replace(person("u_a", org, email="new@example.com"), expected_version=1)
    assert (moved.version, moved.record["email"]) == (2, "new@example.com")
    stores.persons.create(person("u_b", org, email="old@example.com"))  # the old address is free
    with pytest.raises(errors.EmailTaken):
        stores.persons.create(person("u_c", org, email="NEW@example.com"))  # the new one is held
    if backend.is_firestore:
        assert raw(backend.client, email_path(org, "new@example.com")) == {"person_id": "u_a"}
        assert raw(backend.client, email_path(org, "old@example.com")) == {"person_id": "u_b"}


def test_PPL_11c_FS_10_a_replace_to_a_taken_address_is_refused_and_changes_nothing(backend):
    org, stores = unique_org(), backend.stores()
    a = stores.persons.create(person("u_a", org, email="a@example.com"))
    stores.persons.create(person("u_b", org, email="b@example.com"))
    with pytest.raises(errors.EmailTaken):
        stores.persons.replace(person("u_a", org, email="B@Example.com"), expected_version=1)
    assert stores.persons.get(org, "u_a") == a, "version and record are as they were"
    with pytest.raises(errors.EmailTaken):
        stores.persons.create(person("u_c", org, email="a@example.com"))  # u_a still holds its own address


def test_PPL_11c_FS_10_a_replace_that_keeps_the_address_or_changes_only_its_case_keeps_the_reservation(backend):
    org, stores = unique_org(), backend.stores()
    stores.persons.create(person("u_a", org, email="a@example.com"))
    renamed = stores.persons.replace(
        person("u_a", org, email="a@example.com", display_name="Renamed"), expected_version=1
    )
    assert renamed.version == 2
    recased = stores.persons.replace(
        person("u_a", org, email="A@Example.COM", display_name="Renamed"), expected_version=2
    )
    assert (recased.version, recased.record["email"]) == (3, "A@Example.COM")
    with pytest.raises(errors.EmailTaken):
        stores.persons.create(person("u_b", org, email="a@example.com"))
    if backend.is_firestore:
        assert raw(backend.client, email_path(org, "a@example.com")) == {"person_id": "u_a"}


def test_PPL_11c_FS_10_a_failed_replace_reserves_nothing(backend):
    org, stores = unique_org(), backend.stores()
    stores.persons.create(person("u_a", org, email="a@example.com"))
    with pytest.raises(errors.VersionConflict):
        stores.persons.replace(person("u_a", org, email="moved@example.com"), expected_version=9)
    with pytest.raises(errors.NotFound):
        stores.persons.replace(person("u_ghost", org, email="ghost@example.com"), expected_version=1)
    with pytest.raises(errors.PeopleInputError):
        stores.persons.replace({**person("u_a", org, email="bad@example.com"), "x_extra": 1}, expected_version=1)
    for email in ("moved@example.com", "ghost@example.com", "bad@example.com"):
        stores.persons.create(person("u_" + email[:3], org, email=email))
    assert stores.persons.get(org, "u_a").record["email"] == "a@example.com"


@pytest.mark.parametrize("round_", ROUNDS)
def test_PPL_11c_FS_10_a_replace_and_a_create_racing_for_a_new_address_leave_one_holder(backend, round_):
    org, stores = unique_org(), backend.stores()
    stores.persons.create(person("u_a", org, email="a@example.com"))
    results = race(
        [
            lambda: stores.persons.replace(person("u_a", org, email="wanted@example.com"), expected_version=1),
            lambda: stores.persons.create(person("u_b", org, email="wanted@example.com")),
        ]
    )
    assert len(oks(results)) == 1, results
    assert all(isinstance(e, errors.EmailTaken) for e in errs(results)), errs(results)
    holders = [s.record["id"] for s in stores.persons.list(org) if s.record["email"] == "wanted@example.com"]
    assert len(holders) == 1


def test_PPL_11c_FS_10_erasing_a_person_frees_their_address(backend):
    org, stores = unique_org(), backend.stores()
    stores.persons.create(person("u_a", org, email="a@example.com", role="owner"))
    stores.persons.create(person("u_b", org, email="b@example.com"))
    assert erase_person(stores, org, "u_b")["person"] == 1
    stores.persons.create(person("u_c", org, email="b@example.com"))


# --- FS-11: the last person of an org --------


def _with_data(stores, org, uid):
    """A work item, a meeting and a calendar entry of `uid`, so an erase has something to do."""
    stores.work_items.create(make("work_item", 1, org, owner=uid))
    stores.meetings.create(make("meeting", 1, org, owner=uid))
    stores.calendar.create(make("calendar_entry", 1, org, owner=uid))


def test_PPL_11c_FS_11_the_last_person_of_an_org_without_a_founder_marker_is_not_erased_and_nothing_changes(backend):
    org, stores = unique_org(), backend.stores()
    sole = stores.persons.create(person("u_a", org, role="owner", display_name=SENTINEL))
    _with_data(stores, org, "u_a")
    with pytest.raises(errors.LastPerson) as caught:
        erase_person(stores, org, "u_a")
    assert SENTINEL not in everything_said(caught.value)
    assert stores.persons.get(org, "u_a") == sole
    assert stores.work_items.get(org, "wi_w1").version == 1
    meeting = stores.meetings.get(org, "mt_m1")
    assert meeting.version == 1 and meeting.record["status"] != "deleted", "no meeting was tombstoned"
    assert stores.calendar.get(org, "ce_c1").version == 1
    with pytest.raises(errors.EmailTaken):  # the address is still held
        stores.persons.create(person("u_b", org, email="a@example.com"))


def test_PPL_11c_FS_11_a_founded_org_may_erase_its_last_person_and_stays_founded(backend):
    org, stores = unique_org(), backend.stores()
    stores.persons.create_founder(_owner("u_a", org))
    _with_data(stores, org, "u_a")
    counts = erase_person(stores, org, "u_a")
    assert (counts["person"], counts["work_item"], counts["meeting"], counts["calendar_entry"]) == (1, 1, 1, 1)
    assert stores.persons.list(org) == () and stores.work_items.list(org) == ()
    assert stores.persons.founded(org) is True
    with pytest.raises(errors.OrgAlreadyFounded):
        stores.persons.create_founder(_owner("u_stranger", org, email="stranger@example.com"))
    stores.persons.create(person("u_new", org, email="a@example.com"))  # the address was released
    if backend.is_firestore:
        assert raw(backend.client, founder_path(org)) == {"uid": "u_a"}, "the marker is what is left"


def test_PPL_11c_FS_11_a_person_who_is_not_the_last_is_erased_as_before(backend):
    org, stores = unique_org(), backend.stores()
    stores.persons.create(person("u_a", org, role="owner"))
    stores.persons.create(person("u_b", org))
    _with_data(stores, org, "u_b")
    assert erase_person(stores, org, "u_b")["person"] == 1
    assert [s.record["id"] for s in stores.persons.list(org)] == ["u_a"]


def test_PPL_11c_FS_11_once_founded_the_org_can_be_emptied_person_by_person(backend):
    org, stores = unique_org(), backend.stores()
    stores.persons.create_founder(_owner("u_a", org))
    stores.persons.create(person("u_b", org))
    assert erase_person(stores, org, "u_a")["person"] == 1  # not the last
    assert erase_person(stores, org, "u_b")["person"] == 1  # the last, and the org is founded
    assert erase_person(stores, org, "u_a") == dict.fromkeys(
        ("meeting", "work_item", "pinboard_item", "mention", "calendar_entry", "world_share", "person"), 0
    ), "a second erase of someone already gone is all zeros"


def test_PPL_11c_FS_11_erasing_someone_who_is_not_the_sole_person_is_not_a_last_person_erase(backend):
    org, stores = unique_org(), backend.stores()
    sole = stores.persons.create(person("u_a", org, role="owner"))
    counts = erase_person(stores, org, "u_nobody")
    assert counts == dict.fromkeys(
        ("meeting", "work_item", "pinboard_item", "mention", "calendar_entry", "world_share", "person"), 0
    )
    assert stores.persons.get(org, "u_a") == sole


def test_PPL_11c_FS_11_the_rule_is_per_org(backend):
    org, other, stores = unique_org(), unique_org(), backend.stores()
    stores.persons.create_founder(_owner("u_a", other))  # a founded org does not found this one
    stores.persons.create(person("u_a", org, role="owner"))
    with pytest.raises(errors.LastPerson):
        erase_person(stores, org, "u_a")
    assert erase_person(stores, other, "u_a")["person"] == 1
