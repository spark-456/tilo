"""FR-CHN-11: Edit and the undo window under any interleaving. PRD 11.4 Preview ("Edit takes a free-text change and
redrafts"), 11.4 Undo, 11.6 acceptance ("no send after cancel"), FR-CHN-10's content rules (the redraft is checked
again), outbox.rules.md OB-01 and OB-05 (a redraft is a new proposal with a new gate, also during an undo window;
an Edit is never an instruction), issue #243 (the T3 signal runs on the final text after Edit). The FR-CHN-10
Drafter is real; its model is scripted. API: API_FR_CHN_11.md."""

from __future__ import annotations

from datetime import timedelta

from _chn11_lib import (
    BENIGN,
    BENIGN_V2,
    INSTRUCTION,
    USER,
    drafted,
    make_bench,
    needs_autopilot,
    parse_ts,
    scripted_thread,
)
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

RATE = "Hi David,\n\nFriday 2pm works for us. Our hourly rate is 95.\n\nBest,\nSarah"
REFUND = "Hi David,\n\nFriday 2pm works for us. We will refund the deposit.\n\nBest,\nSarah"


def _scheduled(*bodies: str):
    bench = make_bench("L2")
    thread = scripted_thread(bench, BENIGN, *bodies)
    card = bench.ap.preview(USER, *drafted(bench, thread))
    assert card.level == "L2" and bench.outbox.state(card.outbox_id) == "scheduled"
    return bench, thread, card


def test_FR_CHN_11_edit_cancels_the_pending_send_and_redrafts_with_the_change() -> None:
    bench, thread, card = _scheduled(BENIGN_V2)
    bench.rig.clock.advance(20)
    new = bench.ap.edit(USER, card.card_id, "add a thank you", instruction_id="ins-edit-1")
    assert bench.outbox.state(card.outbox_id) == "cancelled"
    assert new.card_id != card.card_id and new.body == BENIGN_V2 and new.options == ("send", "edit", "cancel")
    prompt = bench.rig.model.requests[-1].prompt
    assert INSTRUCTION in prompt and "add a thank you" in prompt, "the redraft gets the instruction and the change"
    assert (new.level, new.outbox_id) == ("L1", None), "OB-01/OB-05: a redraft waits for a person"
    bench.rig.clock.advance(3600)
    bench.outbox.dispatch_due()
    assert bench.outbox.sent == []
    assert bench.ap.send(USER, card.card_id).status == "refused", "the superseded card is closed"
    assert bench.ap.send(USER, new.card_id).status == "queued"
    (sent,) = bench.outbox.dispatch_due()
    assert sent["authz"]["by"] == "person"


def test_FR_CHN_11_edit_reruns_the_checker_and_an_invented_redraft_cannot_be_sent() -> None:
    bench, _, card = _scheduled(RATE)
    new = bench.ap.edit(USER, card.card_id, "also tell him our hourly rate", instruction_id="ins-edit-2")
    assert new.status == "needs_you" and "send" not in new.options
    assert any(line.startswith("number") for line in new.findings)
    assert bench.ap.send(USER, new.card_id).status == "refused"
    bench.rig.clock.advance(3600)
    bench.outbox.dispatch_due()
    assert bench.outbox.sent == [] and bench.outbox.state(card.outbox_id) == "cancelled"


def test_FR_CHN_11_editing_in_a_money_term_flips_the_redraft_to_t3() -> None:
    bench, _, card = _scheduled(REFUND)
    new = bench.ap.edit(USER, card.card_id, "say we will refund the deposit", instruction_id="ins-edit-3")
    assert new.status == "ready" and new.tier == "T3" and "money_or_legal" in new.modifiers
    assert new.outbox_id is None
    bench.ap.send(USER, new.card_id)
    (entry,) = [e for e in bench.outbox.all() if e["id"] != card.outbox_id]
    assert entry["risk_tier"] == "T3" and entry["authz"]["by"] == "person"


def test_FR_CHN_11_edit_after_the_send_does_not_pretend_to_undo() -> None:
    bench, _, card = _scheduled(BENIGN_V2)
    bench.rig.clock.advance(60)
    bench.outbox.dispatch_due()
    assert bench.ap.edit(USER, card.card_id, "add a thank you", instruction_id="ins-edit-4") is None
    assert bench.outbox.state(card.outbox_id) == "sent"


OPS = st.lists(
    st.one_of(
        st.tuples(st.just("advance"), st.integers(0, 45)),
        st.sampled_from([("dispatch", 0), ("cancel", 0), ("edit", 0), ("send", 0)]),
    ),
    max_size=12,
)


@needs_autopilot
@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(OPS)
def test_FR_CHN_11_no_send_after_cancel_or_edit_under_any_interleaving(ops) -> None:
    bench, _, card = _scheduled(BENIGN_V2)
    first_artifact = bench.outbox.entries[card.outbox_id]["item"]["artifact_id"]
    dead: set[str] = set()  # entries pending when a cancel or edit succeeded: these must never send
    for i, (op, n) in enumerate(ops):
        pending = {e["id"] for e in bench.outbox.all() if e["state"] in ("scheduled", "queued")}
        if op == "advance":
            bench.rig.clock.advance(n)
        elif op == "dispatch":
            bench.outbox.dispatch_due()
        elif op == "send":
            bench.ap.send(USER, card.card_id)
        elif op == "cancel":
            status = bench.ap.cancel(USER, card.card_id).status
            if status == "cancelled":
                dead |= pending
            elif status == "too_late":
                assert any(e["state"] in ("sent", "queued") for e in bench.outbox.all())
        elif (new := bench.ap.edit(USER, card.card_id, "add a thank you", instruction_id=f"ins-e{i}")) is not None:
            dead |= pending
            card = new
    bench.rig.clock.advance(3600)
    bench.outbox.dispatch_due()
    sent = bench.outbox.sent_entries()
    assert not dead & {e["id"] for e in sent}, "an entry sent after its cancel or edit succeeded"
    artifacts = [e["item"]["artifact_id"] for e in sent]
    assert len(artifacts) == len(set(artifacts)), "one card, one send"
    for entry in bench.outbox.all():
        if entry["authz"]["by"] == "policy":
            assert entry["item"]["artifact_id"] == first_artifact, "only the instructed draft rides the L2 window"
    for outbox_id, when in bench.outbox.sent:
        entry = bench.outbox.entries[outbox_id]
        if entry["authz"]["by"] == "policy":
            assert entry["undo_window_s"] == 60 and when >= parse_ts(entry["created_at"]) + timedelta(seconds=60)
