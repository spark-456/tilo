"""CHN-GATE-B (FR-CHN-11; issue #256 "Remaining gates", issue #298): three gaps in `Autopilot.preview` that let a send
ride the L2 undo window, or carry another thread's reply headers, when it must not. Sources: PRD 10.4 (L2 acts only
on a person's own instruction; new recipients are T3), 11.4 Preview and Undo / Formats, FR-HIL-04 (no T3 without a
person), OB-01, BQ-152, BQ-154, BQ-174; defaults are logged as BQ-221 to BQ-223 in docs/open-questions.md.

1. The draft's `thread_id` must be the context's. A mismatch raises ValueError (as a draft of another instruction
   does) before anything is recorded: no card, no outbox entry, nothing to Send (BQ-221).
2. An empty, whitespace-only or invisible-only instruction is never L2: the card is L1 with no schedule and waits for
   its owner's Send (BQ-222).
3. A From that only names an earlier message's sender in the thread does not make an inbound Cc of that address known
   (BQ-223). Known stays: contacts (lower-case ASCII equality, BQ-174), the user's own SENT messages' To and Cc
   (BQ-154), and the sender of the message the reply answers (the last message not from the mailbox: the existing
   FR-CHN-11 / FR-CHN-12 tests pin that a reply to that sender rides L2 with no contact).

The policy port always answers L2 unless a test says L1, so only the autopilot's own checks can stop an auto-send.
API: API_FR_CHN_11.md (no new API). Fake clock and fake outbox only; addresses are fictional `.example` domains.
"""

from __future__ import annotations

import dataclasses
import secrets
from dataclasses import dataclass, field
from typing import Any

import pytest
from _chn10_lib import Msg
from _chn11_lib import (
    BENIGN,
    DAVID,
    INSTRUCTION,
    MAILBOX,
    SARAH,
    USER,
    autopilot_module,
    make_bench,
    needs_autopilot,
    pair,
    scripted_thread,
)
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

PAT = "events@partner.example"
MALLORY = "mallory@attacker.example"
STRANGER = "stranger@elsewhere.example"
WINDOW_S = 60


def waits_for_a_person(bench: Any, card: Any) -> None:
    """The card is L1 with no schedule and nothing reaches the outbox, however long the clock runs."""
    assert (card.level, card.undo_window_s, card.outbox_id, card.scheduled_at) == ("L1", 0, None, None)
    bench.rig.clock.advance(3600)
    bench.outbox.dispatch_due()
    assert bench.outbox.entries == {} and bench.outbox.sent == [], "never scheduled or sent without a person"


def rides_the_window(card: Any) -> None:
    assert (card.tier, card.level, card.undo_window_s) == ("T2", "L2", WINDOW_S) and card.outbox_id is not None


# ---------------------------------------------------------------------------
# 1. result.draft.thread_id is the context's thread


def other_thread_ids(real: str, other: str) -> dict[str, str]:
    return {"another_thread": other, "padded": real + " ", "upper": real.upper(), "empty": "", "prefix": real[:-1]}


@pytest.mark.parametrize("level", ["L1", "L2"])
@pytest.mark.parametrize("mode", ["reply", "reply_all"])
@pytest.mark.parametrize("which", ["another_thread", "padded", "upper", "empty", "prefix"])
def test_CHN_GATE_B_FR_CHN_11_draft_of_another_thread_is_refused_and_nothing_is_recorded(
    level: str, mode: str, which: str
) -> None:
    bench = make_bench(level)
    thread_a, thread_b = scripted_thread(bench), scripted_thread(bench)
    ctx, result = pair(thread_a, BENIGN, mode=mode)
    wrong_id = other_thread_ids(thread_a.thread_id, thread_b.thread_id)[which]
    assert wrong_id != ctx.thread_id, "test setup: the draft names another thread"
    wrong = dataclasses.replace(result, draft=dataclasses.replace(result.draft, thread_id=wrong_id))

    with pytest.raises(ValueError):  # fail closed, as the existing check of the instruction id does (BQ-221)
        bench.ap.preview(USER, ctx, wrong)

    assert bench.cards.dump() == "{}", "a refused draft leaves no card behind: no other thread's reply headers"
    bench.rig.clock.advance(3600)
    bench.outbox.dispatch_due()
    assert bench.outbox.enqueue_calls == 0 and bench.outbox.entries == {}
    card_id = autopilot_module()._card_id(USER, ctx.instruction_id)
    assert bench.ap.send(USER, card_id).status == "refused"
    # Non-vacuity: the draft of the right thread, for the same instruction, is accepted as normal afterwards.
    card = bench.ap.preview(USER, ctx, result)
    assert card.level == level
    assert card.undo_window_s == (WINDOW_S if level == "L2" else 0)


@pytest.mark.parametrize("level", ["L1", "L2"])
def test_CHN_GATE_B_FR_CHN_11_replayed_preview_with_a_draft_of_another_thread_changes_nothing(level: str) -> None:
    bench = make_bench(level)
    thread_a, thread_b = scripted_thread(bench), scripted_thread(bench)
    ctx, result = pair(thread_a, BENIGN)
    first = bench.ap.preview(USER, ctx, result)
    before, entries = bench.cards.dump(), bench.outbox.all()
    wrong = dataclasses.replace(result, draft=dataclasses.replace(result.draft, thread_id=thread_b.thread_id))

    with pytest.raises(ValueError):
        bench.ap.preview(USER, ctx, wrong)
    with pytest.raises(ValueError):  # another instance over the same stores refuses it too
        bench.new_autopilot().preview(USER, ctx, wrong)

    assert bench.cards.dump() == before and bench.outbox.all() == entries
    again = bench.ap.preview(USER, ctx, result)
    assert (again.card_id, again.level, again.outbox_id) == (first.card_id, first.level, first.outbox_id)


def test_CHN_GATE_B_FR_CHN_11_draft_of_the_same_thread_is_not_refused_control() -> None:
    bench = make_bench("L2")
    ctx, result = pair(scripted_thread(bench), BENIGN)
    assert result.draft.thread_id == ctx.thread_id
    rides_the_window(bench.ap.preview(USER, ctx, result))


@needs_autopilot
@settings(max_examples=30, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(wrong=st.one_of(st.none(), st.text(max_size=14)), mode=st.sampled_from(["reply", "reply_all"]))
def test_CHN_GATE_B_FR_CHN_11_property_a_card_exists_only_for_the_contexts_own_thread(wrong, mode) -> None:
    bench = make_bench("L2")
    thread = scripted_thread(bench)
    ctx, result = pair(thread, BENIGN, mode=mode)
    if wrong is not None:
        assume(wrong != thread.thread_id)
        result = dataclasses.replace(result, draft=dataclasses.replace(result.draft, thread_id=wrong))
    if wrong is None:
        assert bench.ap.preview(USER, ctx, result).level == "L2"
        return
    with pytest.raises(ValueError):
        bench.ap.preview(USER, ctx, result)
    assert bench.cards.dump() == "{}" and bench.outbox.entries == {}


# ---------------------------------------------------------------------------
# 2. an empty instruction never rides L2

WHITESPACE = ["", " ", "\n", "\t \r\n", " ", " 　", "   \n   \n"]
INVISIBLE = ["​", "⁠ ‍", "﻿", "‮"]  # format characters only: nothing a person wrote


@pytest.mark.parametrize("instruction", WHITESPACE + INVISIBLE)
def test_CHN_GATE_B_FR_CHN_11_empty_instruction_never_rides_l2_and_waits_for_a_person(instruction: str) -> None:
    bench = make_bench("L2")
    thread = scripted_thread(bench)
    card = bench.ap.preview(USER, *pair(thread, BENIGN, instruction=instruction))

    assert card.status == "ready" and "send" in card.options, "the owner can still read it and Send"
    waits_for_a_person(bench, card)

    out = bench.ap.send(USER, card.card_id)  # the person's tap is what sends it
    (entry,) = bench.outbox.all()
    assert out.status == "queued" and entry["undo_window_s"] == 0
    assert entry["authz"]["by"] == "person" and entry["authz"]["ref"] == USER


@pytest.mark.parametrize("instruction", [INSTRUCTION, "ok", " Tell David yes. ", " Friday "])
def test_CHN_GATE_B_FR_CHN_11_non_empty_instruction_still_rides_l2_control(instruction: str) -> None:
    # Non-vacuity: on the same bench a draft of a real instruction is scheduled, so the L1 above comes from the
    # empty instruction alone.
    bench = make_bench("L2")
    rides_the_window(bench.ap.preview(USER, *pair(scripted_thread(bench), BENIGN, instruction=instruction)))


@needs_autopilot
@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    instruction=st.text(alphabet=[" ", "\t", "\n", "\r", " ", " ", "　", "​", "﻿"], max_size=9),
    tap=st.booleans(),
)
def test_CHN_GATE_B_FR_CHN_11_property_no_blank_instruction_is_ever_scheduled(instruction, tap) -> None:
    bench = make_bench("L2")
    card = bench.ap.preview(USER, *pair(scripted_thread(bench), BENIGN, instruction=instruction))
    assert (card.level, card.outbox_id, card.scheduled_at) == ("L1", None, None)
    if tap:
        bench.ap.send(USER, card.card_id)
    bench.rig.clock.advance(3600)
    bench.outbox.dispatch_due()
    for entry in bench.outbox.sent_entries():
        assert entry["authz"]["by"] == "person" and entry["undo_window_s"] == 0
    assert tap or bench.outbox.sent == []


# ---------------------------------------------------------------------------
# 3. an earlier thread sender is not a known recipient for an inbound Cc


@dataclass
class SentMsg(Msg):
    labels: list[str] = field(default_factory=lambda: ["SENT"])

    def as_message(self) -> dict[str, Any]:
        return super().as_message() | {"labelIds": list(self.labels)}


def inbound(sender: str) -> Msg:
    return Msg("m-" + secrets.token_hex(5), sender, "Engine tune-up", "Adding a colleague.", to=[MAILBOX])


def own_sent(*to: str) -> SentMsg:
    return SentMsg("m-" + secrets.token_hex(5), f"Ops <{MAILBOX}>", "Engine tune-up", "Looping them in.", to=list(to))


def reply_all_card(bench: Any, *earlier: Msg, cc: tuple[str, ...]) -> Any:
    """The thread has these earlier messages, then David's (the one answered), which Cc's nobody."""
    thread, _ = bench.rig.thread(earlier=earlier, cc=())
    return bench.ap.preview(USER, *pair(thread, BENIGN, mode="reply_all", to=(DAVID,), cc=cc))


FORMS = [
    f"Pat Partner <{PAT}>",
    PAT,
    f"PAT PARTNER <{PAT.upper()}>",  # lower-casing alone makes it equal
    f'"Sarah Chen" <{PAT}>',  # a display name that names a contact
]


@pytest.mark.parametrize("sender", FORMS)
def test_CHN_GATE_B_FR_CHN_11_cc_to_an_earlier_thread_sender_is_a_new_recipient(sender: str) -> None:
    bench = make_bench("L2", contacts=(SARAH,))
    card = reply_all_card(bench, inbound(sender), cc=(PAT,))

    assert card.tier == "T3" and "new_recipients" in card.modifiers, (card.tier, card.modifiers)
    assert list(card.cc) == [PAT], "recipients are shown exactly as they would be sent"
    waits_for_a_person(bench, card)

    bench.ap.send(USER, card.card_id)
    (entry,) = bench.outbox.all()
    assert entry["authz"]["by"] == "person" and entry["risk_tier"] == "T3"
    assert "new_recipients" in entry["modifiers"] and set(entry["recipients"]) == {DAVID, PAT}


def test_CHN_GATE_B_FR_CHN_11_spoofed_from_naming_a_contact_does_not_vouch_for_a_stranger() -> None:
    # A message threaded in with a From that borrows a contact's display name but a stranger's address.
    bench = make_bench("L2", contacts=(SARAH,))
    spoof = inbound(f'"Sarah Chen" <{MALLORY}>')
    card = reply_all_card(bench, spoof, cc=(MALLORY,))
    assert card.tier == "T3" and "new_recipients" in card.modifiers
    waits_for_a_person(bench, card)


def test_CHN_GATE_B_FR_CHN_11_two_earlier_senders_in_cc_are_both_new() -> None:
    bench = make_bench("L2")
    card = reply_all_card(bench, inbound(PAT), inbound(STRANGER), cc=(PAT, STRANGER))
    assert card.tier == "T3" and "new_recipients" in card.modifiers
    waits_for_a_person(bench, card)


@pytest.mark.parametrize("known_by", ["contact", "own_sent_message", "reply_target_only"])
def test_CHN_GATE_B_FR_CHN_11_known_recipients_still_ride_l2_control(known_by: str) -> None:
    # Non-vacuity: the same thread with an earlier sender still schedules when the address is known the right way,
    # and a reply to the sender being answered needs no contact (pinned by FR-CHN-11 and FR-CHN-12).
    contacts = (PAT,) if known_by == "contact" else ()
    bench = make_bench("L2", contacts=contacts)
    earlier = [inbound(PAT)] + ([own_sent(PAT)] if known_by == "own_sent_message" else [])
    card = reply_all_card(bench, *earlier, cc=() if known_by == "reply_target_only" else (PAT,))
    rides_the_window(card)


def test_CHN_GATE_B_FR_CHN_11_own_message_without_the_sent_label_still_vouches_for_nothing() -> None:
    bench = make_bench("L2")
    unlabelled = dataclasses.replace(own_sent(PAT), labels=[])
    card = reply_all_card(bench, inbound(PAT), unlabelled, cc=(PAT,))
    assert card.tier == "T3" and "new_recipients" in card.modifiers
    waits_for_a_person(bench, card)


POOL = [PAT, MALLORY, STRANGER, SARAH, "billing@partner.example"]


@needs_autopilot
@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    senders=st.lists(st.sampled_from(POOL), max_size=3, unique=True),
    contacts=st.lists(st.sampled_from(POOL), max_size=2, unique=True),
    sent_to=st.lists(st.sampled_from(POOL), max_size=2, unique=True),
    cc=st.lists(st.sampled_from(POOL), max_size=3, unique=True),
    tap=st.booleans(),
)
def test_CHN_GATE_B_FR_CHN_11_property_only_contacts_and_own_sent_recipients_ride_l2(
    senders, contacts, sent_to, cc, tap
) -> None:
    bench = make_bench("L2", contacts=contacts)
    earlier = [inbound(s) for s in senders] + ([own_sent(*sent_to)] if sent_to else [])
    card = reply_all_card(bench, *earlier, cc=tuple(cc))
    known = {DAVID} | set(contacts) | set(sent_to)  # an earlier sender adds nothing; DAVID is the one answered
    if set(cc) - known:
        assert card.tier == "T3" and (card.level, card.outbox_id) == ("L1", None)
    if tap:
        bench.ap.send(USER, card.card_id)
    bench.rig.clock.advance(3600)
    bench.outbox.dispatch_due()
    for entry in bench.outbox.sent_entries():
        assert sorted(entry["recipients"]) == sorted([DAVID, *cc])
        if set(entry["recipients"]) - known:
            assert entry["authz"]["by"] == "person" and "new_recipients" in entry["modifiers"]
