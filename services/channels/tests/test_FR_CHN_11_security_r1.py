"""FR-CHN-11 security round 1 (PR #249). (1) A bare carriage return, or any other line break, between two words is a
line break for the T3 signal and the preview, as the MIME text encoder sends it, never a join that hides "contract".
(2) A card's tier, level and outbox entry are one record written before any enqueue: a replay, a restart, a policy
change or a concurrent preview adopts it, and Cancel or Edit stops whatever entry the card scheduled, so "cancelled"
always means nothing is sent (PRD 11.6). Fake clock, fake outbox, scripted model; no real send."""

from __future__ import annotations

import email.message

import pytest
from _chn10_lib import answer
from _chn11_lib import (
    BENIGN,
    POLICY_ID,
    RUN,
    USER,
    WORLD,
    FakePolicy,
    OutboxRefused,
    autopilot_module,
    drafted,
    make_bench,
    pair,
    scripted_thread,
)

CR_BODY = (
    "Hi David,\n\nFriday 2pm works for us. Please sign the\rcontract and send the\rinvoice by\rwire to our\rIBAN."
    " We\rwill meet the\rdeadline.\n\nBest,\nSarah"
)
BREAKS = ["\r", "\r\n", "\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x85", " ", " "]


class FailingReader:
    def get_thread(self, user_id: str, thread_id: str) -> dict:
        raise TimeoutError("transient")


def instance(bench, *, reader=None, policy=None):
    return autopilot_module().Autopilot(
        drafter=bench.rig.svc,
        reader=reader or bench.rig.reader,
        contacts=bench.contacts,
        policy=policy or bench.policy,
        outbox=bench.outbox,
        cards=bench.cards,
        clock=bench.rig.clock,
        world_id=WORLD,
        run_id=RUN,
    )


def never_sent(bench) -> None:
    for _ in range(3):
        bench.rig.clock.advance(600)
        bench.outbox.dispatch_due()
    assert bench.outbox.sent == [], "an entry was sent after Cancel or Edit succeeded"


def stop(ap, card_id: str, op: str) -> None:
    if op == "cancel":
        assert ap.cancel(USER, card_id).status == "cancelled"
    else:
        assert ap.edit(USER, card_id, "add a thank you", instruction_id="ins-sec-edit") is not None


def test_FR_CHN_11_bare_cr_body_through_the_real_drafter_is_t3_and_never_scheduled() -> None:
    bench = make_bench("L2")
    thread, _ = bench.rig.thread(answers=(answer(CR_BODY),))
    card = bench.ap.preview(USER, *drafted(bench, thread))
    assert card.tier == "T3" and "money_or_legal" in card.modifiers
    assert (card.level, card.outbox_id) == ("L1", None)
    assert "\r" not in card.body and "the\ncontract" in card.body and "We\nwill" in card.body
    bench.rig.clock.advance(3600)
    bench.outbox.dispatch_due()
    assert bench.outbox.entries == {}


@pytest.mark.parametrize("brk", BREAKS)
@pytest.mark.parametrize(
    ("category", "text"),
    [
        ("legal", "Please sign the{}contract."),
        ("legal", "These{}terms apply."),
        ("money", "Send it by{}wire to our{}IBAN."),
        ("money", "We can offer a{}refund."),
        ("commitment", "We{}will deliver it."),
        ("commitment", "We meet the{}deadline."),
    ],
)
def test_FR_CHN_11_line_breaks_between_words_never_hide_a_t3_term(brk: str, category: str, text: str) -> None:
    assert category in autopilot_module().t3_content_signal(text.replace("{}", brk))


@pytest.mark.parametrize("brk", ["\r", "\r\n", "\r\r\n"])
def test_FR_CHN_11_preview_body_equals_the_mime_body_sent(brk: str) -> None:
    bench = make_bench("L2")
    thread = scripted_thread(bench)
    raw = f"Hi David,{brk}{brk}Friday 2pm works{brk}for us.{brk}Best,{brk}Sarah"
    card = bench.ap.preview(USER, *pair(thread, raw))
    message = email.message.EmailMessage()
    message.set_content(raw)
    assert message.get_content() == card.body + "\n", "the card shows exactly what the connector sends"
    assert card.tier == "T2", "a CR line break alone is not T3"


@pytest.mark.parametrize("brk", BREAKS[2:])
def test_FR_CHN_11_other_line_breaks_fail_closed_and_never_join_words(brk: str) -> None:
    bench = make_bench("L2")
    thread = scripted_thread(bench)
    card = bench.ap.preview(USER, *pair(thread, f"Hi David,\n\nFriday 2pm works{brk}for us.\n\nBest,\nSarah"))
    assert "works\nfor us." in card.body
    assert card.tier == "T3" and (card.level, card.outbox_id) == ("L1", None)
    assert "obfuscated" in autopilot_module().t3_content_signal(brk)


def _crash_on_first_enqueue(bench, monkeypatch, *, stored: bool) -> None:
    real, crashed = bench.outbox.enqueue, []

    def enqueue(entry, evidence):
        if crashed:
            return real(entry, evidence)
        crashed.append(entry["id"])
        if stored:
            real(entry, evidence)
        raise RuntimeError("instance died")

    monkeypatch.setattr(bench.outbox, "enqueue", enqueue)


@pytest.mark.parametrize("op", ["cancel", "edit"])
@pytest.mark.parametrize("stored", [True, False])
def test_FR_CHN_11_crash_around_enqueue_then_replay_with_a_failing_thread_read(monkeypatch, stored, op) -> None:
    bench = make_bench("L2")
    thread = scripted_thread(bench)
    ctx, result = pair(thread, BENIGN)
    _crash_on_first_enqueue(bench, monkeypatch, stored=stored)
    with pytest.raises(RuntimeError):
        bench.ap.preview(USER, ctx, result)
    replay = instance(bench, reader=FailingReader())
    card = replay.preview(USER, ctx, result)
    assert (card.level, card.tier) == ("L2", "T2"), "the replay adopts the recorded decision"
    assert list(bench.outbox.entries) == [card.outbox_id]
    stop(replay, card.card_id, op)
    never_sent(bench)


@pytest.mark.parametrize("op", ["cancel", "edit"])
@pytest.mark.parametrize("crash", [False, True])
def test_FR_CHN_11_replay_after_the_policy_flipped_to_l1_adopts_the_card(monkeypatch, crash, op) -> None:
    bench = make_bench("L2")
    thread = scripted_thread(bench)
    ctx, result = pair(thread, BENIGN)
    if crash:
        _crash_on_first_enqueue(bench, monkeypatch, stored=True)
        with pytest.raises(RuntimeError):
            bench.ap.preview(USER, ctx, result)
    else:
        bench.ap.preview(USER, ctx, result)
    replay = instance(bench, policy=FakePolicy("L1"))
    card = replay.preview(USER, ctx, result)
    assert card.level == "L2" and list(bench.outbox.entries) == [card.outbox_id]
    assert bench.outbox.entries[card.outbox_id]["authz"]["ref"] == POLICY_ID
    stop(replay, card.card_id, op)
    never_sent(bench)


@pytest.mark.parametrize("failing_first", [True, False])
def test_FR_CHN_11_concurrent_previews_with_a_transient_read_failure_agree(failing_first: bool) -> None:
    bench = make_bench("L2")
    thread = scripted_thread(bench)
    ctx, result = pair(thread, BENIGN)
    good, failing = bench.ap, instance(bench, reader=FailingReader())
    first, second = (failing, good) if failing_first else (good, failing)
    real_create, inner = bench.cards.create, []

    def create(user_id, key, value):  # `second` has worked out its card; `first` stores its own before it
        if not inner:
            inner.append(None)
            inner[0] = first.preview(USER, ctx, result)
        return real_create(user_id, key, value)

    bench.cards.create = create
    late = second.preview(USER, ctx, result)
    bench.cards.create = real_create
    early = inner[0]
    assert early is not None
    assert early == late, "every call adopts the first stored record"
    assert len(bench.outbox.entries) == (0 if failing_first else 1)
    assert (early.level, early.outbox_id is None) == (("L1", True) if failing_first else ("L2", False))
    assert good.cancel(USER, early.card_id).status == "cancelled"
    never_sent(bench)


def test_FR_CHN_11_cancel_replayed_after_a_crash_reports_cancelled_and_send_is_refused(monkeypatch) -> None:
    bench = make_bench("L2")
    thread = scripted_thread(bench)
    card = bench.ap.preview(USER, *pair(thread, BENIGN))

    def put(*args):
        raise RuntimeError("instance died")

    monkeypatch.setattr(bench.cards, "put", put)
    with pytest.raises(RuntimeError):
        bench.ap.cancel(USER, card.card_id)
    monkeypatch.undo()
    assert bench.outbox.state(card.outbox_id) == "cancelled"
    assert bench.new_autopilot().cancel(USER, card.card_id).status == "cancelled"
    assert bench.ap.send(USER, card.card_id).status == "refused"
    never_sent(bench)


def test_FR_CHN_11_cancel_never_reports_cancelled_when_the_outbox_cannot_cancel() -> None:
    bench = make_bench("L2")
    thread = scripted_thread(bench)
    card = bench.ap.preview(USER, *pair(thread, BENIGN))

    def refuse(outbox_id):
        raise OutboxRefused("halted")

    bench.outbox.cancel = refuse
    with pytest.raises(autopilot_module().CancelPending):  # round 2: retryable, never "cancelled" or "too_late"
        bench.ap.cancel(USER, card.card_id)
    assert bench.outbox.state(card.outbox_id) == "scheduled"
