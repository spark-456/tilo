"""PPL-11c-FS FS-17 (issue #577 item 3): the sole-person check of `erase_person` is atomic with the delete. Spec:
`API_PPL_11c_FS1c.md` section 2.

`_refuse_last_person` lists the org's people and decides on a snapshot; two erases of the last two people of an
UNFOUNDED (seeded) org both pass it and both delete, so the org is empty and then foundable by the bootstrap uid, who
joins the old team's pins. With the check inside the delete (under the lock of `MemoryStore`, inside the transaction on
Firestore) one erase of the two gets `LastPerson` and exactly one person is left. A FOUNDED org may still be emptied by
racing erases (BQ-PPL11C-16: the marker keeps `/first` closed).

The people store handed to `erase_person` takes a snapshot on `get` and `list` and then sleeps 100 ms (`SlowPersons`),
so a check made on a snapshot is certain to be stale; every other call goes straight to the store. Real threads. The
Firestore variants run only on the emulator, with three callers (`_ppl11c_fs_lib.racers`).
"""

from __future__ import annotations

import dataclasses

import pytest
from _ppl11c_fs_fake import SlowPersons
from _ppl11c_fs_lib import errs, oks, person, race, racers, unique_org
from tilo_people import errors
from tilo_people.stores import PeopleStores, erase_person

ROUNDS = range(2)


def _seeded(stores, org, count):
    """`count` ordinary people of an org nobody founded (a seeded org)."""
    for i in range(count):
        stores.persons.create(person(f"u_e{i}", org, role="owner" if i == 0 else "member"))
    assert stores.persons.founded(org) is False


def _race_erases(stores, org, count):
    slow = dataclasses.replace(stores, persons=SlowPersons(stores.persons))
    return race([lambda i=i: erase_person(slow, org, f"u_e{i}") for i in range(count)])


def _one_person_is_left(stores, org, results, count):
    refused = errs(results)
    assert len(refused) == 1 and isinstance(refused[0], errors.LastPerson), results
    assert len(oks(results)) == count - 1, results
    left = [s.record["id"] for s in stores.persons.list(org)]
    assert len(left) == 1, f"{left}: the org was emptied by racing erases"
    assert stores.persons.founded(org) is False


@pytest.mark.parametrize("round_", ROUNDS)
def test_PPL_11c_FS_17_racing_erases_of_an_unfounded_org_leave_one_person(backend, round_):
    count = racers(backend)  # eight in memory, three on the emulator
    org, stores = unique_org(), backend.stores()
    _seeded(stores, org, count)
    results = _race_erases(stores, org, count)
    _one_person_is_left(stores, org, results, count)


@pytest.mark.parametrize("round_", ROUNDS)
def test_PPL_11c_FS_17_two_racing_erases_of_the_last_two_people_of_an_unfounded_org_leave_one(round_):
    """The probe from the security review of FS-1: both erases succeeded and the org was empty."""
    org, stores = unique_org(), PeopleStores.in_memory()
    _seeded(stores, org, 2)
    results = _race_erases(stores, org, 2)
    _one_person_is_left(stores, org, results, 2)


def test_PPL_11c_FS_17_the_refused_erase_keeps_its_person_record_and_the_survivor_is_unchanged():
    org, stores = unique_org(), PeopleStores.in_memory()
    _seeded(stores, org, 2)
    before = {s.record["id"]: s for s in stores.persons.list(org)}
    results = _race_erases(stores, org, 2)
    (survivor,) = stores.persons.list(org)
    assert survivor == before[survivor.record["id"]], "the survivor's record and version are untouched"
    assert len(oks(results)) == 1 and len(errs(results)) == 1


def test_PPL_11c_FS_17_guard_a_founded_org_may_be_emptied_by_racing_erases(backend):
    org, stores = unique_org(), backend.stores()
    stores.persons.create_founder(person("u_e0", org, role="owner"))
    stores.persons.create(person("u_e1", org))
    assert stores.persons.founded(org) is True
    results = _race_erases(stores, org, 2)
    assert not errs(results), errs(results)
    assert stores.persons.list(org) == () and stores.persons.founded(org) is True


def test_PPL_11c_FS_17_guard_erasing_one_after_the_other_still_refuses_the_last(backend):
    org, stores = unique_org(), backend.stores()
    _seeded(stores, org, 2)
    assert erase_person(stores, org, "u_e0")["person"] == 1
    with pytest.raises(errors.LastPerson):
        erase_person(stores, org, "u_e1")
    assert [s.record["id"] for s in stores.persons.list(org)] == ["u_e1"]
    assert erase_person(stores, org, "u_e0")["person"] == 0, "erasing an absent person is still a no-op"
