"""PPL-11c-FS FS-16 (issue #577 item 2): the address reservation is written with a create precondition and a reservation
is deleted only by its holder, so a change of concurrency mode or SDK fails loudly instead of overwriting or deleting
another person's reservation. Spec: `API_PPL_11c_FS1c.md` section 1.

Today `FirestorePersonStore` writes a reservation with `txn.set` and deletes it without looking at `person_id`;
uniqueness rests on the transaction's read locks. The fake client (`_ppl11c_fs_fake.FakeFirestore`) models the mode in
which nothing is locked: a rival takes the address after our read, and only a write precondition can stop us. The
emulator tests arrange an inconsistent reservation by a raw write (a holder that is not the person) and use the real
SDK. Tests named `..._guard_...` pass today and stay green (they pin the fake and the cases the builder must not break).
"""

from __future__ import annotations

import pytest
from _ppl11c_fs_fake import FakeFirestore
from _ppl11c_fs_lib import email_path, everything_said, founder_path, person, raw, record_path, unique_org
from tilo_api.people_firestore import firestore_people_stores
from tilo_people import errors

emulator = pytest.mark.emulator
# The specific refusals: a failed holder check is none of these (it is neither a conflict nor a missing record).
SPECIFIC = (
    errors.NotFound,
    errors.VersionConflict,
    errors.EmailTaken,
    errors.AlreadyExists,
    errors.OrgAlreadyFounded,
    errors.LastPerson,
    errors.PeopleInputError,
)
RIVAL = {"person_id": "u_rival"}
OTHER = {"person_id": "u_other"}


def _org_stores():
    db = FakeFirestore()
    return unique_org(), db, firestore_people_stores(db).persons


def _seed_person(db, org, uid="u_nina", email="nina@example.com", version=1):
    """A person document and (optionally) its reservation, written directly (the state an earlier build, or another
    concurrency mode, could have left)."""
    db.put(record_path(org, "person", uid), {"version": version, "record": person(uid, org, email=email)})


def _loud(caught: pytest.ExceptionInfo) -> None:
    assert not isinstance(caught.value, SPECIFIC), f"a failed holder check is not {type(caught.value).__name__}"
    said = everything_said(caught.value)
    assert "nina@example.com" not in said and "old@example.com" not in said and "new@example.com" not in said


# --- the fake models Firestore for the sequential flows (guards) --------


def test_PPL_11c_FS_16_guard_the_fake_models_the_sequential_flows():
    org, db, persons = _org_stores()
    persons.create(person("u_a", org, email="a@example.com"))
    persons.create(person("u_b", org, email="b@example.com"))
    assert db.raw(email_path(org, "A@Example.com")) == {"person_id": "u_a"}
    with pytest.raises(errors.EmailTaken):
        persons.create(person("u_c", org, email="B@example.com"))
    assert db.raw(record_path(org, "person", "u_c")) is None
    persons.replace(person("u_a", org, email="c@example.com"), expected_version=1)
    assert db.raw(email_path(org, "a@example.com")) is None and db.raw(email_path(org, "c@example.com")) == {
        "person_id": "u_a"
    }
    persons.delete(org, "u_b", expected_version=1)
    assert db.raw(email_path(org, "b@example.com")) is None
    founder_org = unique_org()
    persons.create_founder(person("u_f", founder_org, role="owner", email="f@example.com"))
    assert db.raw(founder_path(founder_org)) is not None and persons.founded(founder_org) is True


# --- the reservation is created, never overwritten --------


def test_PPL_11c_FS_16_create_that_loses_the_address_to_a_rival_after_its_read_is_email_taken_and_writes_nothing():
    org, db, persons = _org_stores()
    db.rival_after_read(email_path(org, "nina@example.com"), RIVAL)
    with pytest.raises(errors.EmailTaken):
        persons.create(person("u_nina", org, email="nina@example.com"))
    assert db.raw(email_path(org, "nina@example.com")) == RIVAL, "the rival's reservation was overwritten"
    assert db.raw(record_path(org, "person", "u_nina")) is None, "the person was written without its address"


def test_PPL_11c_FS_16_replace_to_an_address_a_rival_takes_after_its_read_is_email_taken_and_changes_nothing():
    org, db, persons = _org_stores()
    persons.create(person("u_nina", org, email="old@example.com"))
    db.rival_after_read(email_path(org, "new@example.com"), RIVAL)
    with pytest.raises(errors.EmailTaken):
        persons.replace(person("u_nina", org, email="new@example.com"), expected_version=1)
    assert db.raw(email_path(org, "new@example.com")) == RIVAL, "the rival's reservation was overwritten"
    assert db.raw(email_path(org, "old@example.com")) == {"person_id": "u_nina"}, "the old address was released"
    stored = db.raw(record_path(org, "person", "u_nina"))
    assert stored["version"] == 1 and stored["record"]["email"] == "old@example.com"


def test_PPL_11c_FS_16_create_founder_that_loses_the_address_to_a_rival_after_its_read_is_email_taken():
    """The rival holds only the address (no founder marker, no person): the honest refusal is `EmailTaken`, not
    `OrgAlreadyFounded` (today every commit-time `AlreadyExists` is reported as the latter)."""
    org, db, persons = _org_stores()
    db.rival_after_read(email_path(org, "f@example.com"), RIVAL)
    with pytest.raises(errors.EmailTaken):
        persons.create_founder(person("u_f", org, role="owner", email="f@example.com"))
    assert db.raw(email_path(org, "f@example.com")) == RIVAL, "the rival's reservation was overwritten"
    assert db.raw(founder_path(org)) is None and db.raw(record_path(org, "person", "u_f")) is None


def test_PPL_11c_FS_16_guard_create_founder_that_loses_to_a_rival_founder_is_org_already_founded():
    org, db, persons = _org_stores()
    rival_person = {"version": 1, "record": person("u_rival", org, role="owner", email="r@example.com")}
    db.rival_after_read(
        founder_path(org),
        docs={
            founder_path(org): {"uid": "u_rival"},
            record_path(org, "person", "u_rival"): rival_person,
            email_path(org, "r@example.com"): RIVAL,
        },
    )
    with pytest.raises(errors.OrgAlreadyFounded):
        persons.create_founder(person("u_f", org, role="owner", email="f@example.com"))
    assert db.raw(founder_path(org)) == {"uid": "u_rival"} and db.raw(record_path(org, "person", "u_f")) is None


@pytest.mark.parametrize("flow", ["create", "create_founder", "replace_moves_the_address"])
def test_PPL_11c_FS_16_a_reservation_is_only_ever_created_or_deleted_never_set_or_updated(flow):
    """Spy on the writes each flow commits: a reservation (`people_directory/email_*`) is a `create` or a `delete`;
    an unconditional `set` or an `update` is what let a rival's reservation be overwritten."""
    org, db, persons = _org_stores()
    if flow == "create":
        persons.create(person("u_nina", org, email="nina@example.com"))
    elif flow == "create_founder":
        persons.create_founder(person("u_nina", org, role="owner", email="nina@example.com"))
    else:
        persons.create(person("u_nina", org, email="old@example.com"))
        persons.replace(person("u_nina", org, email="new@example.com"), expected_version=1)
    reservations = [(kind, path) for kind, path in db.attempted_ops if "/people_directory/email_" in path]
    assert reservations, flow
    assert {kind for kind, _ in reservations} <= {"create", "delete"}, reservations


# --- a reservation is deleted only by its holder --------


def test_PPL_11c_FS_16_delete_of_a_person_whose_address_is_held_by_another_fails_loudly_and_changes_nothing():
    org, db, persons = _org_stores()
    _seed_person(db, org)
    db.put(email_path(org, "nina@example.com"), OTHER)
    with pytest.raises(errors.PeopleError) as caught:
        persons.delete(org, "u_nina", expected_version=1)
    _loud(caught)
    assert db.raw(email_path(org, "nina@example.com")) == OTHER, "another person's reservation was deleted"
    assert db.raw(record_path(org, "person", "u_nina")) is not None, "the delete went ahead on an inconsistent store"


def test_PPL_11c_FS_16_replace_that_moves_an_address_it_does_not_hold_fails_loudly_and_changes_nothing():
    org, db, persons = _org_stores()
    _seed_person(db, org, email="old@example.com")
    db.put(email_path(org, "old@example.com"), OTHER)
    # built outside the `with`: the traceback shows the call line
    moved = person("u_nina", org, email="new@example.com")
    with pytest.raises(errors.PeopleError) as caught:
        persons.replace(moved, expected_version=1)
    _loud(caught)
    assert db.raw(email_path(org, "old@example.com")) == OTHER, "another person's reservation was deleted"
    assert db.raw(email_path(org, "new@example.com")) is None, "the new address was reserved on an inconsistent store"
    stored = db.raw(record_path(org, "person", "u_nina"))
    assert stored["version"] == 1 and stored["record"]["email"] == "old@example.com"


def test_PPL_11c_FS_16_guard_a_person_with_no_reservation_is_still_deleted_and_moved():
    """No holder, nothing to protect: an absent reservation (a person written before reservations existed) is not an
    error (the check is `held by someone else`, not `held by me`)."""
    org, db, persons = _org_stores()
    _seed_person(db, org, "u_a", email="a@example.com")
    _seed_person(db, org, "u_b", email="b@example.com")
    persons.replace(person("u_a", org, email="moved@example.com"), expected_version=1)
    assert db.raw(email_path(org, "moved@example.com")) == {"person_id": "u_a"}
    persons.delete(org, "u_b", expected_version=1)
    assert db.raw(record_path(org, "person", "u_b")) is None


def test_PPL_11c_FS_16_guard_a_holder_that_is_the_person_is_deleted_with_it():
    org, db, persons = _org_stores()
    persons.create(person("u_nina", org, email="nina@example.com"))
    persons.delete(org, "u_nina", expected_version=1)
    assert db.raw(email_path(org, "nina@example.com")) is None and db.raw(record_path(org, "person", "u_nina")) is None


# --- the same checks with the real SDK, on the emulator --------


@emulator
def test_PPL_11c_FS_16_on_the_emulator_delete_of_a_person_whose_address_is_held_by_another_fails_loudly(fs_backend):
    org, client = unique_org(), fs_backend.client
    stores = fs_backend.stores()
    stores.persons.create(person("u_nina", org, email="nina@example.com"))
    client.document(email_path(org, "nina@example.com")).set(OTHER)  # an inconsistent reservation
    with pytest.raises(errors.PeopleError) as caught:
        stores.persons.delete(org, "u_nina", expected_version=1)
    _loud(caught)
    assert raw(client, email_path(org, "nina@example.com")) == OTHER
    assert stores.persons.get(org, "u_nina") is not None


@emulator
def test_PPL_11c_FS_16_on_the_emulator_replace_that_moves_an_address_it_does_not_hold_fails_loudly(fs_backend):
    org, client = unique_org(), fs_backend.client
    stores = fs_backend.stores()
    stores.persons.create(person("u_nina", org, email="old@example.com"))
    client.document(email_path(org, "old@example.com")).set(OTHER)
    # built outside the `with`: the traceback shows the call line
    moved = person("u_nina", org, email="new@example.com")
    with pytest.raises(errors.PeopleError) as caught:
        stores.persons.replace(moved, expected_version=1)
    _loud(caught)
    assert raw(client, email_path(org, "old@example.com")) == OTHER
    assert raw(client, email_path(org, "new@example.com")) is None
    assert stores.persons.get(org, "u_nina").record["email"] == "old@example.com"
