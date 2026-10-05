"""FR-CHN-11: no L2 undo window when the message a draft answers carries a money, legal or commitment signal
(ADR-0013; issue #298 "CHN-GATE-C", first bullet; BQ-265; PRD 10.4: T3 "money, contract or legal terms" always needs a
person, L2 "the instruction is the approval" is for plain replies; HR / OB-01: an L2 send is queued only on a policy
decision).

Why: the autopilot looked only at the draft's own body. An inbound "please confirm the transfer of $5,000" answered by
"Yes, confirmed." is a clean T2 body, so it rode L2 and was sent after the undo window with no person.

Decided behaviour (the caller's spec for this ticket):
  - The replied-to message is the thread message whose Message-ID is the draft's `in_reply_to` (what the Drafter's
    envelope sets, BQ-185). Only that message counts: earlier or quoted messages of the thread do not.
  - It carries a signal when `inbound_signal(its body)` is not empty: a word of the money, legal or commitment
    families, or obfuscated, or over SIGNAL_CAP (fail closed).
  - Then the card stays at L1: it waits for its owner's Send (level "L1", no undo window, no `policy.applied`, no
    outbox entry, nothing ever sent silently) and is still tiered by the draft's OWN body (T2, no modifier for a
    clean body; T3 `money_or_legal` for a risky one). The inbound signal is not a new tier modifier.
  - A clean inbound message (plain scheduling talk) still rides L2 exactly as before.
  - A replied-to message that cannot be found fails closed: no L2. That is an unreadable thread, a thread with no
    messages, and an `in_reply_to` (also an empty one) that names no message of the thread.

Both ways the level reaches the Autopilot are driven: the legacy `level()` hint and the policy port; both fakes answer
L2 for every send, so only the autopilot's own inbound check can stop it. Fake clock, fake outbox, no network, no
paid call. Helpers: _chn11_inbound_lib.py. Invisible characters are built with chr()."""

from __future__ import annotations

import secrets

import pytest
from _chn10_lib import USER, Msg, Thread, answer
from _chn11_inbound_lib import (
    CLEAN_DRAFTS,
    COMMITMENT_INBOUND,
    KINDS,
    LEGAL_INBOUND,
    MONEY_INBOUND,
    SCHEDULING_INBOUND,
    SIGNAL_INBOUND,
    answering,
    assert_waits_for_a_person,
    earlier_message,
    make_l2,
)
from _chn11_lib import BENIGN, INSTRUCTION, MAILBOX, context
from _chn_wire4_lib import fresh_ulid
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

TRANSFER = "Can you confirm the transfer of $5,000 to our bank account today?"  # the motivating inbound message
ZWSP, CYR_A, BIDI_OVERRIDE, SHY = chr(0x200B), chr(0x0430), chr(0x202E), chr(0x00AD)
CAP = 20_000  # autopilot_t3.SIGNAL_CAP: an inbound message over it is not read, it fails closed

# Inbound bodies that are clean of the three families but obfuscated, or too long to read.
OBFUSCATED_INBOUND = {
    "zero_width_space": f"Hi Sarah, can we meet Friday{ZWSP} afternoon? Thanks, David",
    "cyrillic_look_alike": f"Hi Sarah, can we meet on Fri{chr(0x0456)}day afternoon? Thanks, David",
    "bidi_override": f"Hi Sarah, can we meet {BIDI_OVERRIDE}on Friday afternoon? Thanks, David",
    "soft_hyphen": f"Hi Sarah, can we meet on Fri{SHY}day afternoon? Thanks, David",
    "obfuscated_signal_word": f"Hi Sarah, please send the ref{ZWSP}und today. Thanks, David",
    "over_the_cap": "Can we meet on Friday afternoon? " * (CAP // 33 + 20),
}


def _l2_card(kind: str, inbound: str, body: str = BENIGN, **thread_kw):
    h = make_l2(kind)
    thread = h.thread(inbound, **thread_kw)
    p, ctx, _ = h.preview(thread, body)
    return h, thread, p, ctx


# ---------------------------------------------------------------------------
# (1) The failing drafts against a money-transfer inbound message never reach L2


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("body", CLEAN_DRAFTS)
def test_FR_CHN_11_inbound_aware_l2_money_transfer_inbound_keeps_a_clean_draft_off_l2(kind: str, body: str) -> None:
    h, _, p, ctx = _l2_card(kind, TRANSFER, body)
    assert (p.status, p.tier, p.modifiers) == ("ready", "T2", ()), "tiered by its own body: clean, so T2"
    assert_waits_for_a_person(h, p, ctx)


@pytest.mark.parametrize("body", CLEAN_DRAFTS)
def test_FR_CHN_11_inbound_aware_l2_through_the_real_drafter_the_money_transfer_reply_waits_for_a_person(
    body: str,
) -> None:
    # The same thing end to end: the real FR-CHN-10 Drafter (scripted model) drafts the clean reply, whose
    # in_reply_to is the inbound message's Message-ID; the autopilot reads the thread through the same reader.
    h = make_l2("legacy_level_hint")
    thread, _ = h.rig.thread(body=TRANSFER, answers=(answer(body),))
    ctx = context(thread, instruction=INSTRUCTION, instruction_id=fresh_ulid())
    result = h.rig.svc.draft(
        USER, instruction_id=ctx.instruction_id, thread_id=thread.thread_id, instruction=INSTRUCTION, mailbox=MAILBOX
    )
    assert result.status == "ready" and result.draft.body == body, "test setup: the clean reply passes FR-CHN-10"
    p = h.ap.preview(USER, ctx, result)
    assert (p.tier, p.modifiers) == ("T2", ())
    assert_waits_for_a_person(h, p, ctx)


@pytest.mark.parametrize("kind", KINDS)
def test_FR_CHN_11_inbound_aware_l2_a_replayed_preview_and_a_second_instance_stay_at_l1(kind: str) -> None:
    h = make_l2(kind)
    thread = h.thread(TRANSFER)
    ctx, result = answering(thread, "Yes, confirmed.")
    first = h.ap.preview(USER, ctx, result)
    again = h.ap.preview(USER, ctx, result)
    other = h.new_ap().preview(USER, ctx, result)
    assert first.card_id == again.card_id == other.card_id
    for card in (first, again, other):
        assert (card.level, card.undo_window_s, card.scheduled_at) == ("L1", 0, None)
    assert_waits_for_a_person(h, first, ctx)


def test_FR_CHN_11_inbound_aware_l2_the_owner_can_still_send_it_and_it_goes_once_with_no_window() -> None:
    h, _, p, _ = _l2_card("legacy_level_hint", TRANSFER, "Yes, confirmed.")
    assert h.entries() == []
    out = h.ap.send(USER, p.card_id)
    assert out.status == "queued", "the owner's own Send queues it now (L1), not as a scheduled L2 entry"
    (entry,) = h.entries()
    assert entry["id"] == out.outbox_id
    assert entry["authz"]["by"] == "person" and entry["authz"]["ref"] == USER
    assert (entry["risk_tier"], entry["undo_window_s"]) == ("T2", 0)
    h.outbox.dispatch_due()
    assert len(h.outbox.sent) == 1
    assert h.ap.send(USER, p.card_id).status in ("queued", "refused")  # a repeated tap never adds an entry
    assert len(h.entries()) == 1


# ---------------------------------------------------------------------------
# (2) Money, legal and commitment signals in the inbound message, each family, both ways in


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize(
    "inbound",
    [*MONEY_INBOUND, *LEGAL_INBOUND, *COMMITMENT_INBOUND],
    ids=[f"{f}{i}" for f, n in (("money", 4), ("legal", 4), ("commitment", 4)) for i in range(n)],
)
def test_FR_CHN_11_inbound_aware_l2_money_legal_and_commitment_inbound_never_ride_l2(kind: str, inbound: str) -> None:
    body = CLEAN_DRAFTS[len(inbound) % len(CLEAN_DRAFTS)]  # a clean body whatever the inbound says
    h, _, p, ctx = _l2_card(kind, inbound, body)
    assert (p.tier, p.modifiers) == ("T2", ())
    assert_waits_for_a_person(h, p, ctx)


@pytest.mark.parametrize("kind", KINDS)
def test_FR_CHN_11_inbound_aware_l2_own_body_tiering_is_unchanged_a_risky_draft_is_still_t3(kind: str) -> None:
    body = "Hi David,\n\nThe invoice for the wire transfer is attached.\n\nBest,\nSarah"
    h, _, p, ctx = _l2_card(kind, TRANSFER, body)
    assert p.tier == "T3" and "money_or_legal" in p.modifiers
    assert_waits_for_a_person(h, p, ctx)


# ---------------------------------------------------------------------------
# (3) Obfuscated or over-the-cap inbound messages fail closed


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("inbound", list(OBFUSCATED_INBOUND.values()), ids=list(OBFUSCATED_INBOUND))
def test_FR_CHN_11_inbound_aware_l2_obfuscated_or_over_cap_inbound_fails_closed(kind: str, inbound: str) -> None:
    h, _, p, ctx = _l2_card(kind, inbound, "Yes, confirmed.")
    assert (p.tier, p.modifiers) == ("T2", ())
    assert_waits_for_a_person(h, p, ctx)


# ---------------------------------------------------------------------------
# (4) A scheduling-only inbound message still rides L2


def _assert_rides_l2(h, p) -> None:
    assert p.level == "L2" and p.undo_window_s == 60 and p.scheduled_at is not None
    (entry,) = h.entries()
    assert entry["state"] == "scheduled" and entry["undo_window_s"] == 60
    assert entry["authz"]["by"] == "policy"
    if h.kind == "policy_port":
        assert len(h.policy_events()) == 1


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("body", [BENIGN, *CLEAN_DRAFTS])
def test_FR_CHN_11_inbound_aware_l2_a_scheduling_only_inbound_still_rides_l2(kind: str, body: str) -> None:
    h, _, p, _ = _l2_card(kind, SCHEDULING_INBOUND, body)
    assert (p.tier, p.modifiers) == ("T2", ())
    _assert_rides_l2(h, p)


@pytest.mark.parametrize("kind", KINDS)
def test_FR_CHN_11_inbound_aware_l2_digits_a_link_and_unlisted_words_in_the_inbound_are_no_signal(kind: str) -> None:
    # The L2 allowlist is for the draft, not for the message it answers: only the three families, obfuscation and the
    # cap count there.
    inbound = "Hi Sarah, could Marcus bring the 2 tarps to dock 14 on Thursday at 3pm? Map: https://harriercharters.example/dock-14"
    h, _, p, _ = _l2_card(kind, inbound, BENIGN)
    _assert_rides_l2(h, p)


@pytest.mark.parametrize("kind", KINDS)
def test_FR_CHN_11_inbound_aware_l2_the_card_can_still_be_cancelled_inside_the_window_when_the_inbound_is_clean(
    kind: str,
) -> None:
    h, _, p, _ = _l2_card(kind, SCHEDULING_INBOUND, "Yes, confirmed.")
    _assert_rides_l2(h, p)
    assert h.ap.cancel(USER, p.card_id).status == "cancelled"
    h.clock.advance(120)
    h.outbox.dispatch_due()
    assert h.outbox.sent == []


# ---------------------------------------------------------------------------
# (5) Only the replied-to message matters, never an earlier one in the thread


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize(
    "earlier_body",
    [
        "Our invoice for $1,200 is overdue, please wire it to the bank account.",
        "Please sign the contract and the NDA, we accept no liability.",
        "We guarantee the repair and promise to meet the Friday deadline.",
    ],
    ids=["money", "legal", "commitment"],
)
def test_FR_CHN_11_inbound_aware_l2_an_earlier_risky_message_does_not_matter_only_the_replied_to_one(
    kind: str, earlier_body: str
) -> None:
    h = make_l2(kind)
    thread = h.thread(SCHEDULING_INBOUND, earlier=(earlier_message(earlier_body),))
    assert len(thread.messages) == 2
    p, _, _ = h.preview(thread, "Yes, confirmed.")
    assert (p.tier, p.modifiers) == ("T2", ())
    _assert_rides_l2(h, p)


@pytest.mark.parametrize("kind", KINDS)
def test_FR_CHN_11_inbound_aware_l2_an_earlier_risky_message_of_our_own_does_not_matter_either(kind: str) -> None:
    h = make_l2(kind)
    mine = earlier_message("We will send the invoice and wire the refund.", sender=MAILBOX, message_id="m-mine")
    thread = h.thread(SCHEDULING_INBOUND, earlier=(mine,))
    p, _, _ = h.preview(thread, "Yes, confirmed.")
    _assert_rides_l2(h, p)


@pytest.mark.parametrize("kind", KINDS)
def test_FR_CHN_11_inbound_aware_l2_a_risky_replied_to_message_counts_even_after_clean_earlier_ones(kind: str) -> None:
    h = make_l2(kind)
    thread = h.thread(TRANSFER, earlier=(earlier_message("Hi Sarah, are you free on Friday afternoon?"),))
    p, ctx, _ = h.preview(thread, "Yes, confirmed.")
    assert_waits_for_a_person(h, p, ctx)


# ---------------------------------------------------------------------------
# (6) A missing replied-to message fails closed


def _unreadable_thread() -> Thread:
    """A thread the reader does not hold (its read raises LookupError)."""
    ghost = Msg(
        message_id="m-ghost", sender="David Miller <david.miller@harriercharters.example>", subject="Hi", body="Hi"
    )
    return Thread(thread_id="t-ghost-" + secrets.token_hex(4), messages=[ghost])


@pytest.mark.parametrize("kind", KINDS)
def test_FR_CHN_11_inbound_aware_l2_an_unreadable_thread_fails_closed(kind: str) -> None:
    h = make_l2(kind)
    thread = _unreadable_thread()
    ctx, result = answering(thread, "Yes, confirmed.")
    p = h.ap.preview(USER, ctx, result)
    assert_waits_for_a_person(h, p, ctx)


@pytest.mark.parametrize("kind", KINDS)
def test_FR_CHN_11_inbound_aware_l2_a_thread_without_messages_fails_closed(kind: str) -> None:
    h = make_l2(kind)
    thread = h.rig.reader.add(USER, Thread(thread_id="t-empty-" + secrets.token_hex(4), messages=[]))
    ctx, result = answering(thread, "Yes, confirmed.", in_reply_to="<m-gone@mail.example>")
    p = h.ap.preview(USER, ctx, result)
    assert_waits_for_a_person(h, p, ctx)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("in_reply_to", ["<nobody@mail.example>", ""], ids=["names_no_message", "empty"])
def test_FR_CHN_11_inbound_aware_l2_an_in_reply_to_that_matches_no_message_fails_closed(
    kind: str, in_reply_to: str
) -> None:
    # The thread is readable and clean, but the draft does not say which message it answers.
    h = make_l2(kind)
    thread = h.thread(SCHEDULING_INBOUND)
    ctx, result = answering(thread, "Yes, confirmed.", in_reply_to=in_reply_to)
    p = h.ap.preview(USER, ctx, result)
    assert_waits_for_a_person(h, p, ctx)


@pytest.mark.parametrize("kind", KINDS)
def test_FR_CHN_11_inbound_aware_l2_a_thread_read_that_raises_never_raises_out_of_preview_and_fails_closed(
    kind: str,
) -> None:
    h = make_l2(kind)
    thread = h.thread(SCHEDULING_INBOUND)
    ctx, result = answering(thread, "Yes, confirmed.")

    def boom(user_id: str, thread_id: str) -> dict:
        raise ConnectionError("the mail reader is down")

    h.rig.reader.get_thread = boom  # type: ignore[method-assign]
    p = h.ap.preview(USER, ctx, result)
    assert_waits_for_a_person(h, p, ctx)


# ---------------------------------------------------------------------------
# Invariants (Hypothesis): the undo window is only ever for a clean replied-to message


@given(
    inbound=st.sampled_from([SCHEDULING_INBOUND, TRANSFER, *SIGNAL_INBOUND, *OBFUSCATED_INBOUND.values()]),
    body=st.sampled_from([BENIGN, *CLEAN_DRAFTS]),
    kind=st.sampled_from(KINDS),
    earlier=st.sampled_from([None, "Hi Sarah, are you free on Friday?", "Please wire the refund for the invoice."]),
)
@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_FR_CHN_11_inbound_aware_l2_property_the_window_is_only_for_a_clean_replied_to_message(
    inbound: str, body: str, kind: str, earlier: str | None
) -> None:
    h = make_l2(kind)
    thread = h.thread(inbound, earlier=(earlier_message(earlier),) if earlier else ())
    p, ctx, _ = h.preview(thread, body)
    if inbound == SCHEDULING_INBOUND:  # the earlier message never matters
        _assert_rides_l2(h, p)
    else:
        assert_waits_for_a_person(h, p, ctx)
