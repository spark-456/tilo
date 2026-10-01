"""FR-HIL-02 (PRD 10.3, 10.6): "Same-type cards from one district within 60 s merge ... Gates
default to hold and never time out to 'go'." Acceptance test named in 10.6: "Three cards from
one district in 60 s merge". See API_ST3b.md ambiguities 1-3 for what "district", "same-type"
and the merge window's anchor mean at this layer (header.building, card kind, anchored on the
group's first card).
"""

from __future__ import annotations

from _cards_lib import OWNER_P, FakeClock, FakeEventWriter, add_seconds, clone_card, load_valid_card, new_ulid
from tilo_api.cards import CardStore

OWNER = "u_owner"
START = "2026-09-29T09:30:00.000Z"


def _store(world_id: str) -> tuple[CardStore, FakeClock, FakeEventWriter]:
    clock = FakeClock(START)
    writer = FakeEventWriter()
    store = CardStore(clock=clock, writer=writer, world_owners={world_id: OWNER})
    return store, clock, writer


def test_FR_HIL_02_three_cards_from_one_district_in_60s_merge():
    base = load_valid_card("needs_you_compare_basis")
    store, _clock, _writer = _store(base["world_id"])

    first = clone_card(base, id_="01J8Z3K4M5N6P7Q8R9S0T1V001", created_at=START)
    second = clone_card(base, id_="01J8Z3K4M5N6P7Q8R9S0T1V002", created_at=add_seconds(START, 10))
    third = clone_card(base, id_="01J8Z3K4M5N6P7Q8R9S0T1V003", created_at=add_seconds(START, 55))
    assert first["header"]["building"] == second["header"]["building"] == third["header"]["building"]
    assert first["kind"] == second["kind"] == third["kind"]

    r1 = store.submit(first, outbox_id=None)
    r2 = store.submit(second, outbox_id=None)
    r3 = store.submit(third, outbox_id=None)

    assert r1.outcome == "accepted"
    assert r1.card_id == first["id"]
    assert r2.outcome == "merged"
    assert r2.card_id == first["id"]
    assert r3.outcome == "merged"
    assert r3.card_id == first["id"]

    cards = store.list_for_world(base["world_id"], principal=OWNER_P)
    assert [c["id"] for c in cards] == [first["id"]], "three merged cards must show as exactly one"


def test_FR_HIL_02_cards_61s_apart_do_not_merge():
    base = load_valid_card("needs_you_compare_basis")
    store, _clock, _writer = _store(base["world_id"])

    first = clone_card(base, id_="01J8Z3K4M5N6P7Q8R9S0T1V011", created_at=START)
    later = clone_card(base, id_="01J8Z3K4M5N6P7Q8R9S0T1V012", created_at=add_seconds(START, 61))

    r1 = store.submit(first, outbox_id=None)
    r2 = store.submit(later, outbox_id=None)

    assert r1.outcome == "accepted"
    assert r2.outcome == "accepted", "61 s apart is outside the 60 s merge window"
    assert r2.card_id == later["id"]

    cards = store.list_for_world(base["world_id"], principal=OWNER_P)
    assert {c["id"] for c in cards} == {first["id"], later["id"]}


def test_FR_HIL_02_cards_from_different_districts_do_not_merge():
    base = load_valid_card("needs_you_compare_basis")
    store, _clock, _writer = _store(base["world_id"])

    d1 = clone_card(base, id_="01J8Z3K4M5N6P7Q8R9S0T1V021", created_at=START, building="B2")
    d2 = clone_card(base, id_="01J8Z3K4M5N6P7Q8R9S0T1V022", created_at=add_seconds(START, 5), building="B4")

    r1 = store.submit(d1, outbox_id=None)
    r2 = store.submit(d2, outbox_id=None)

    assert r1.outcome == "accepted"
    assert r2.outcome == "accepted"
    cards = store.list_for_world(base["world_id"], principal=OWNER_P)
    assert {c["id"] for c in cards} == {d1["id"], d2["id"]}


def test_FR_HIL_02_gate_cards_never_merge():
    """card.rules.md CR-06 / PI-03: a gate is its own authorisation and must never merge into
    another, even from the same building within the window -- both valid gate fixtures share
    building B2."""
    first = load_valid_card("gate_send_reply")
    second = clone_card(load_valid_card("gate_save_file_reversible"), id_="01J8Z3K4M5N6P7Q8R9S0T1V2W9")
    assert first["header"]["building"] == second["header"]["building"]
    assert first["kind"] == second["kind"] == "gate"
    store, _clock, _writer = _store(first["world_id"])

    r1 = store.submit(first, outbox_id=new_ulid("ob-1"))
    r2 = store.submit(second, outbox_id=new_ulid("ob-2"))

    assert r1.outcome == "accepted"
    assert r2.outcome == "accepted", "gate cards never merge, whatever their building or timing"
    cards = store.list_for_world(first["world_id"], principal=OWNER_P)
    assert {c["id"] for c in cards} == {first["id"], second["id"]}


def test_FR_HIL_02_consent_cards_never_merge():
    base = load_valid_card("consent_drive_folder")
    store, _clock, _writer = _store(base["world_id"])

    first = clone_card(base, id_="01J8Z3K4M5N6P7Q8R9S0T1V031", created_at=START)
    second = clone_card(base, id_="01J8Z3K4M5N6P7Q8R9S0T1V032", created_at=add_seconds(START, 1))

    r1 = store.submit(first, outbox_id=None)
    r2 = store.submit(second, outbox_id=None)

    assert r1.outcome == "accepted"
    assert r2.outcome == "accepted", "consent cards never merge -- each is its own authorisation"
