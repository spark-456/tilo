"""FR-HIL-02 (PRD 10.3, 10.6; docs/open-questions.md BQ-04;
docs/security/p4-policy-invariants.md PI-03): "Every card has a timeout and a safe default; the
Director applies the default and posts a Nudge saying so... Gates default to hold and never time
out to 'go'." Acceptance test named in 10.6: "a timed-out card applies its default and posts a
Nudge". See API_ST3b.md ambiguity 5 for the reading of PI-03 this suite tests to (a
question.answered/default/nudge part for every kind; only approval.resolved is withheld for
gate/consent, whose record stays open).
"""

from __future__ import annotations

from _cards_lib import FakeClock, FakeEventWriter, load_valid_card, new_ulid
from tilo_api.cards import CardStore

OWNER = "u_owner"
START = "2026-09-29T09:30:00.000Z"


def _store(world_id: str) -> tuple[CardStore, FakeClock, FakeEventWriter]:
    clock = FakeClock(START)
    writer = FakeEventWriter()
    store = CardStore(clock=clock, writer=writer, world_owners={world_id: OWNER})
    return store, clock, writer


def test_FR_HIL_02_timed_out_card_applies_its_default_and_posts_a_nudge():
    card = load_valid_card("needs_you_blocked")
    store, clock, writer = _store(card["world_id"])
    store.submit(card, outbox_id=None)
    assert card["timeout"] == 3600

    clock.advance(3600)  # exactly at the timeout boundary
    results = store.tick()

    assert len(results) == 1
    result = results[0]
    assert result.card_id == card["id"]
    assert result.held is False

    nudges = writer.of_type("question.answered")
    assert len(nudges) == 1
    assert nudges[0]["data"] == {"answered_by": "default"}
    assert nudges[0].get("severity") == "nudge", "BQ-04: the timeout default's severity is nudge"
    assert nudges[0].get("authz") is None, "question.answered is not a side-effect type (BQ-23)"


def test_FR_HIL_02_a_card_not_yet_timed_out_is_left_alone():
    card = load_valid_card("needs_you_blocked")
    store, clock, writer = _store(card["world_id"])
    store.submit(card, outbox_id=None)

    clock.advance(card["timeout"] - 1)
    results = store.tick()

    assert results == []
    assert writer.parts == []
    cards = store.list_for_world(card["world_id"], as_user=OWNER)
    assert cards[0]["id"] == card["id"], "an untimed-out card stays open and answerable"


def test_FR_HIL_02_a_timed_out_card_can_no_longer_be_answered_by_a_person():
    card = load_valid_card("needs_you_blocked")
    store, clock, _writer = _store(card["world_id"])
    store.submit(card, outbox_id=None)
    clock.advance(card["timeout"])
    store.tick()

    result = store.answer(card["world_id"], card["id"], option=card["options"][0]["id"], channel="web", actor=OWNER)

    assert result.outcome == "rejected"
    assert result.reason == "already_resolved"


def test_FR_HIL_02_PI_03_gate_never_times_out_to_go():
    """A gate never times out to "go": no approval.resolved is emitted, and the card stays held
    (open), so a person can still answer it after the deadline passes."""
    card = load_valid_card("gate_send_reply")
    store, clock, writer = _store(card["world_id"])
    store.submit(card, outbox_id=new_ulid("ob-timeout-1"))

    clock.advance(card["timeout"])
    results = store.tick()

    assert len(results) == 1
    assert results[0].held is True, "a gate must stay held (open), never resolved, at timeout"
    assert writer.of_type("approval.resolved") == [], "PI-03: a timed-out gate emits no approval.resolved"

    # Still answerable after the timeout, because it stayed held rather than closing.
    answered = store.answer(card["world_id"], card["id"], option="approve", channel="web", actor=OWNER)
    assert answered.outcome == "answered"


def test_FR_HIL_02_PI_03_consent_never_times_out_to_connect():
    card = load_valid_card("consent_drive_folder")
    store, clock, writer = _store(card["world_id"])
    store.submit(card, outbox_id=None)

    clock.advance(card["timeout"])
    results = store.tick()

    assert len(results) == 1
    assert results[0].held is True
    assert writer.of_type("connection.consented") == []

    answered = store.answer(card["world_id"], card["id"], option="connect", channel="web", actor=OWNER)
    assert answered.outcome == "answered"


def test_FR_HIL_02_PI_03_a_held_gate_is_nudged_only_once():
    """tick() may be called repeatedly (a scheduler polling); a still-open gate must not post a
    fresh Nudge on every call once it has already been nudged for this timeout."""
    card = load_valid_card("gate_send_reply")
    store, clock, writer = _store(card["world_id"])
    store.submit(card, outbox_id=new_ulid("ob-timeout-2"))

    clock.advance(card["timeout"])
    store.tick()
    clock.advance(10)
    second_results = store.tick()

    assert second_results == []
    assert len(writer.of_type("question.answered")) == 1
