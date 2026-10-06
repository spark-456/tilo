"""FR-HIL-13 (PRD 10.6): Quiet hours on tilo-api CardStore."""

from __future__ import annotations

from _cards_lib import OWNER_P, FakeClock, FakeEventWriter, answer_client, clone_card, load_valid_card, new_ulid
from tilo_api.cards import CardStore

OWNER, W = "u_owner", "w_01"


def _setup(
    now: str = "2026-09-29T18:00:00.000Z", quiet_hours: dict | None = None
) -> tuple[CardStore, FakeClock, list[dict], dict[str, dict]]:
    clock, writer = FakeClock(now), FakeEventWriter()
    prefs: dict[str, dict] = {OWNER: {"quiet_hours": quiet_hours}} if quiet_hours is not None else {}
    notified: list[dict] = []
    store = CardStore(clock=clock, writer=writer, world_owners={W: OWNER}, preferences=prefs, notifier=notified.append)
    return store, clock, notified, prefs


def test_FR_HIL_13_inside_quiet_hours_only_gate_and_blocked_notify_and_suppressed_still_appear_in_app() -> None:
    store, _clock, notified, _prefs = _setup(
        now="2026-09-29T18:00:00.000Z",
        quiet_hours={"start": "22:00", "end": "07:00", "timezone": "Asia/Kolkata"},
    )
    gate_card = clone_card(load_valid_card("gate_send_reply"), id_=new_ulid("gate1"))
    blocked_card = clone_card(load_valid_card("needs_you_blocked"), id_=new_ulid("blk1"), building="B1")
    needs_you_card = clone_card(load_valid_card("needs_you_compare_basis"), id_=new_ulid("ny1"), building="B2")
    meeting_card = clone_card(load_valid_card("meeting_budget_split"), id_=new_ulid("mtg1"), building="B3")
    consent_card = clone_card(load_valid_card("consent_drive_folder"), id_=new_ulid("con1"))

    assert store.submit(gate_card, outbox_id=new_ulid("ob1")).outcome == "accepted"
    for card in (blocked_card, needs_you_card, meeting_card, consent_card):
        assert store.submit(card).outcome == "accepted"

    assert [c["id"] for c in notified] == [gate_card["id"], blocked_card["id"]]
    assert store.should_notify(gate_card) is True and store.should_notify(blocked_card) is True
    assert not any(store.should_notify(c) for c in (needs_you_card, meeting_card, consent_card))

    in_app_ids = {c["id"] for c in store.list_for_world(W, principal=OWNER_P)}
    assert in_app_ids == {c["id"] for c in (gate_card, blocked_card, needs_you_card, meeting_card, consent_card)}
    resp = answer_client(store, OWNER_P).get(f"/worlds/{W}/cards")
    assert resp.status_code == 200 and {c["id"] for c in resp.json()} == in_app_ids


def test_FR_HIL_13_outside_quiet_hours_needs_you_and_meeting_notify() -> None:
    store, _clock, notified, _prefs = _setup(
        now="2026-09-29T06:00:00.000Z",
        quiet_hours={"start": "22:00", "end": "07:00", "timezone": "Asia/Kolkata"},
    )
    needs_you_card = clone_card(load_valid_card("needs_you_compare_basis"), id_=new_ulid("ny2"), building="B2")
    meeting_card = clone_card(load_valid_card("meeting_budget_split"), id_=new_ulid("mtg2"), building="B3")
    gate_card = clone_card(load_valid_card("gate_send_reply"), id_=new_ulid("gate2"))
    store.submit(needs_you_card)
    store.submit(meeting_card)
    store.submit(gate_card, outbox_id=new_ulid("ob2"))
    assert [c["id"] for c in notified] == [needs_you_card["id"], meeting_card["id"], gate_card["id"]]


def test_FR_HIL_13_midnight_crossing_and_timezone_boundaries_on_card_store() -> None:
    store, clock, notified, _prefs = _setup(
        now="2026-09-29T21:59:00.000Z",
        quiet_hours={"start": "22:00", "end": "07:00", "timezone": "UTC"},
    )
    ny_before = clone_card(load_valid_card("needs_you_compare_basis"), id_=new_ulid("ny_before"), building="B1")
    store.submit(ny_before)
    assert [c["id"] for c in notified] == [ny_before["id"]]

    clock.set("2026-09-29T22:00:00.000Z")
    store.submit(clone_card(load_valid_card("needs_you_compare_basis"), id_=new_ulid("ny_start"), building="B2"))
    assert [c["id"] for c in notified] == [ny_before["id"]]

    clock.set("2026-09-30T02:30:00.000Z")
    blk_mid = clone_card(load_valid_card("needs_you_blocked"), id_=new_ulid("blk_mid"), building="B4")
    store.submit(clone_card(load_valid_card("needs_you_compare_basis"), id_=new_ulid("ny_mid"), building="B3"))
    store.submit(blk_mid)
    assert [c["id"] for c in notified] == [ny_before["id"], blk_mid["id"]]

    clock.set("2026-09-30T07:00:00.000Z")
    ny_end = clone_card(load_valid_card("needs_you_compare_basis"), id_=new_ulid("ny_end"), building="B5")
    store.submit(ny_end)
    assert [c["id"] for c in notified] == [ny_before["id"], blk_mid["id"], ny_end["id"]]
