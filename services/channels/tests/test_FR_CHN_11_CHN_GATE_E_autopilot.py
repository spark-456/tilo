"""CHN-GATE-E (FR-CHN-11; ADR-0025 decisions 2, 3, 5, 6; PRD 10.4 T3 "money, contract or legal terms"): through the
public `Autopilot.preview` / `edit`, a name in a draft rides the L2 undo window only if the thread vouches for it, and
only the names of the draft's own To and Cc and of the mailbox owner count. The Autopilot reads the participants
itself (a caller's value is thrown away) from its own quarantined reader.

Given a thread, a ready draft and an L2 policy; When the card is previewed; Then the tier is T2 and the card rides L2
(60 s window), or it is T3 with the "money_or_legal" modifier, level L1, nothing scheduled.

Defaults applied (ADR-0025):
 - The draft goes to Dana (the inbound sender, always a known recipient) unless a test says otherwise. Dana's names are
   her address local part ("dana", "fox"); the mailbox's are "ops" plus the From name on SENT mail ("Sarah Chen").
 - A card that waits for a person (T3, L1) is the held outcome; the old #525 position rules are not tested here.
 - Where the ADR's own example display name ("Fifty Thousand") would be dropped by the name filter anyway, a second
   case uses a display name that PASSES the filter ("Marcus Reed", "Zebra Pelican"), so the test proves the trust rule
   and not the filter.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import time

import pytest
from _chn11_lib import answer, drafted
from _chn_contracts_lib import CONTRACTS
from _chn_gate_e_lib import (
    MAILBOX,
    OWN,
    USER,
    Mail,
    RaisingReader,
    RecordingHandler,
    autopilot_module,
    card,
    inbound,
    is_t3_unlisted,
    listed_words,
    make_bench,
    pair,
    participants_module,
    rides_l2,
    sent,
    thread_of,
    with_participants,
)
from hypothesis import given, settings
from hypothesis import strategies as st

DANA = "dana.fox@harriercharters.example"
HI_DANA = "Hi Dana, works for us."


def held(c) -> None:
    assert is_t3_unlisted(c), f"expected a held T3 card, got {(c.tier, c.modifiers, c.level)}"
    assert c.scheduled_at is None


# ---- 1. a name the thread vouches for rides L2 (ADR: "A recipient rides L2") ----


def test_FR_CHN_11_CHN_GATE_E_a_recipients_address_local_part_words_ride_l2() -> None:
    bench = make_bench("L2")
    thread = thread_of(bench, sent(to=("David Lee <david.lee@example.com>",)))
    to = ("david.lee@example.com",)
    assert rides_l2(card(bench, thread, "Hi David, works for us.", to=to))
    assert rides_l2(card(bench, thread, "Hi David Lee, works for us.", to=to))
    assert rides_l2(card(bench, thread, "Hi Lee, works for us.", to=to))


def test_FR_CHN_11_CHN_GATE_E_a_recipients_sent_display_name_vouches_nothing() -> None:
    # 8 Oct amendment: the SENT To name may be a sender's choice that Gmail copied into the user's reply
    bench = make_bench("L2")
    thread = thread_of(bench, sent(to=("Prepaid Approved <mallory@example.com>",)))
    to = ("mallory@example.com",)
    held(card(bench, thread, "Hi Prepaid Approved, works for us.", to=to))
    held(card(bench, thread, "Hi Prepaid, works for us.", to=to))
    assert rides_l2(card(bench, thread, "Hi Mallory, works for us.", to=to)), "its address local part still names it"


def test_FR_CHN_11_CHN_GATE_E_a_recipients_address_local_part_rides_l2() -> None:
    bench = make_bench("L2")
    thread = thread_of(bench, sent(to=("david@example.com",)))  # only the address, no display name
    assert rides_l2(card(bench, thread, "Hi David, works for us.", to=("david@example.com",)))


def test_FR_CHN_11_CHN_GATE_E_the_replied_to_sender_is_named_by_its_address_local_part() -> None:
    bench = make_bench("L2")
    thread = thread_of(bench)  # Dana Fox <dana.fox@...> wrote the message the draft answers
    assert rides_l2(card(bench, thread, "Hi Dana,\n\nFriday 2pm works for us.", to=(DANA,)))
    assert rides_l2(card(bench, thread, "Hi Dana Fox, works for us.", to=(DANA,)))
    assert rides_l2(card(bench, thread, "Thanks Fox, see you Tuesday.", to=(DANA,)))


def test_FR_CHN_11_CHN_GATE_E_only_the_mailbox_local_part_names_the_owner() -> None:
    bench = make_bench("L2")
    thread = thread_of(bench, sent(to=(DANA,)))  # the SENT From name "Sarah Chen" vouches nothing (8 Oct amendment)
    assert rides_l2(card(bench, thread, "Hi Dana,\n\nFriday 2pm works for us.\n\nBest,\nOps", to=(DANA,)))
    for body in (
        "Hi Dana,\n\nFriday 2pm works for us.\n\nBest,\nSarah",
        "Hi Dana,\n\nFriday 2pm works for us.\n\nBest,\nSarah Chen",
    ):
        held(card(bench, thread, body, to=(DANA,)))


def test_FR_CHN_11_CHN_GATE_E_a_recipient_cc_d_on_the_users_sent_mail_rides_l2() -> None:
    bench = make_bench("L2")
    thread = thread_of(bench, sent(to=(DANA,), cc=("Priya Shah <priya@example.com>",)))
    c = card(bench, thread, "Hi Dana and Priya, works for us.", to=(DANA,), cc=("priya@example.com",))
    assert rides_l2(c)


# ---- 2. a name the thread does not vouch for is T3 (ADR: "Not in the thread is T3") ----


@pytest.mark.parametrize(
    "body",
    [
        "Hi Fifty Thousand, works for us.",
        "Hi Zebra Pelican, works for us.",
        "Hi Marcus, works for us.",  # a name in the thread's text (the inbound body), not a participant
        "Hi Dana,\n\nFriday 2pm works for us.\n\nBest,\nZebra",
        "Hi Dana,\n\nSounds good Zebra.",
        "Hi Dana, works for us.\n\nBest,\nSarah",  # the thread has no SENT mail: nothing names the mailbox's owner
    ],
)
def test_FR_CHN_11_CHN_GATE_E_a_name_nobody_vouched_for_is_held_as_t3(body: str) -> None:
    bench = make_bench("L2")
    held(card(bench, thread_of(bench), body, to=(DANA,)))
    bench.rig.clock.advance(3600)
    bench.outbox.dispatch_due()
    assert bench.outbox.entries == {}, "T3 is never scheduled without a person"


def test_FR_CHN_11_CHN_GATE_E_the_default_bench_thread_vouches_only_for_david_in_a_greeting() -> None:
    # The default rig thread: David Miller wrote, ops@ is addressed and sarah.chen@ is Cc'd. The draft answers David.
    bench = make_bench("L2")
    thread, _ = bench.rig.thread()
    david = "david.miller@harriercharters.example"
    assert card(bench, thread, "Hi David, works for us.", to=(david,)).tier == "T2"
    held(card(bench, thread, "Hi Sarah, works for us.", to=(david,)))  # a Cc'd thread member who is not a recipient
    held(card(bench, thread, "Hi David Zebra, works for us.", to=(david,)))


@settings(max_examples=60, deadline=None)
@given(word=st.text("abcdefghijklmnopqrstuvwxyz", min_size=3, max_size=12))
def test_FR_CHN_11_CHN_GATE_E_property_a_word_the_thread_does_not_name_is_never_l2(word: str) -> None:
    if word in listed_words() or word in {"dana", "fox", "ops"}:
        return
    bench = make_bench("L2")
    thread = thread_of(bench)
    for body in (f"Hi {word}, works for us.", f"Hi Dana,\n\nWorks for us.\n\nBest,\n{word}"):
        c = card(bench, thread, body, to=(DANA,))
        assert c.level == "L1" and c.outbox_id is None and c.tier == "T3", f"{body!r} rode L2"


# ---- 3. trust: only the draft's recipients and the mailbox owner name anybody (decision 3) ----


@pytest.mark.parametrize("display", ["Marcus Reed", "Zebra Pelican", "Fifty Thousand"])
def test_FR_CHN_11_CHN_GATE_E_an_inbound_cc_display_name_does_not_name_the_recipient(display: str) -> None:
    bench = make_bench("L2")
    mail = inbound("Sam <sam@example.com>", cc=(f"{display} <david@example.com>",))
    thread = thread_of(
        bench, mail, sent(to=("david@example.com",))
    )  # David is a known recipient by the user's own mail
    to = ("david@example.com",)
    assert rides_l2(card(bench, thread, "Hi David, works for us.", to=to))
    held(card(bench, thread, f"Hi {display}, works for us.", to=to))
    held(card(bench, thread, f"Hi David,\n\nWorks for us.\n\nBest,\n{display.split()[0]}", to=to))


@pytest.mark.parametrize("display", ["Marcus Reed", "Zebra Pelican", "Fifty Thousand"])
def test_FR_CHN_11_CHN_GATE_E_an_inbound_from_display_name_does_not_name_that_sender(display: str) -> None:
    bench = make_bench("L2")
    thread = thread_of(bench, sender=f"{display} <sender@example.com>")  # the message the draft answers
    to = ("sender@example.com",)
    assert rides_l2(card(bench, thread, "Hi Sender, works for us.", to=to)), "its address local part still names it"
    held(card(bench, thread, f"Hi {display}, works for us.", to=to))
    held(card(bench, thread, f"Hi {display.split()[0]}, works for us.", to=to))


@pytest.mark.parametrize("display", ["Marcus", "Sarah Chen", "Zebra Pelican", "Tenk"])
def test_FR_CHN_11_CHN_GATE_E_an_inbound_to_display_name_does_not_name_the_user(display: str) -> None:
    bench = make_bench("L2")
    thread = thread_of(bench, to=(f"{display} <{MAILBOX}>",))  # the sender wrote this name for the mailbox
    assert rides_l2(card(bench, thread, "Hi Dana,\n\nWorks for us.\n\nBest,\nOps", to=(DANA,)))
    held(card(bench, thread, f"Hi Dana,\n\nWorks for us.\n\nBest,\n{display.split()[0]}", to=(DANA,)))


def test_FR_CHN_11_CHN_GATE_E_a_thread_member_who_is_not_a_recipient_is_held_as_t3() -> None:
    bench = make_bench("L2")
    thread = thread_of(bench, sent(to=(DANA, "Priya Shah <priya@example.com>")))
    assert rides_l2(card(bench, thread, "Hi Dana, works for us.", to=(DANA,)))
    held(card(bench, thread, "Hi Priya, works for us.", to=(DANA,)))
    held(card(bench, thread, "Hi Dana and Priya, works for us.", to=(DANA,)))
    held(card(bench, thread, "Hi Dana,\n\nWorks for us.\n\nBest,\nShah", to=(DANA,)))


def test_FR_CHN_11_CHN_GATE_E_a_sent_cc_name_belongs_to_that_recipient_only() -> None:
    bench = make_bench("L2")
    thread = thread_of(bench, sent(to=(DANA,), cc=("Priya Shah <priya@example.com>",)))
    held(card(bench, thread, "Hi Priya, works for us.", to=(DANA,)))  # not on this draft's To or Cc
    assert rides_l2(card(bench, thread, "Hi Priya, works for us.", to=(DANA,), cc=("priya@example.com",)))


def test_FR_CHN_11_CHN_GATE_E_the_mailbox_from_name_vouches_nothing_on_any_message() -> None:
    bench = make_bench("L2")
    body = "Hi Dana,\n\nFriday 2pm works for us.\n\nBest,\nSarah"
    spoof = Mail("m-spoof", OWN, "Engine tune-up", "x", to=[DANA], labels=["INBOX"])  # From the mailbox, no SENT label
    nolabel = Mail("m-nolabel", OWN, "Engine tune-up", "x", to=[DANA])
    inbound_from_owner = inbound("Sarah Chen <ops@harborview.example>", to=(DANA,))
    for earlier in (spoof, nolabel, inbound_from_owner, sent(to=(DANA,))):
        held(card(bench, thread_of(bench, earlier), body, to=(DANA,)))


@pytest.mark.parametrize("display", ["Marcus Reed", "Zebra Pelican"])
def test_FR_CHN_11_CHN_GATE_E_a_display_name_vouches_nothing_on_a_spoofed_or_a_sent_message(display: str) -> None:
    bench = make_bench("L2")
    spoof = Mail("m-spoof", OWN, "Engine tune-up", "x", to=[f"{display} <{DANA}>"], labels=["INBOX"])
    held(card(bench, thread_of(bench, spoof), f"Hi {display.split()[0]}, works for us.", to=(DANA,)))
    own = sent(to=(f"{display} <{DANA}>",))  # the user's own SENT mail: its display name vouches nothing either
    held(card(bench, thread_of(bench, own), f"Hi {display.split()[0]}, works for us.", to=(DANA,)))


# ---- 4. the name filter reaches the card (ADR: "Filter: ... name nobody") ----


@pytest.mark.parametrize("display", ["Fifty Thousand", "Refunds Team", "Tenk", "Legal Dept", "Re Fund", "Fif Ty"])
def test_FR_CHN_11_CHN_GATE_E_a_money_or_number_display_name_on_the_users_own_mail_names_nobody(display: str) -> None:
    bench = make_bench("L2")
    thread = thread_of(bench, sent(to=(f"{display} <{DANA}>",)))
    held(card(bench, thread, f"Hi {display}, works for us.", to=(DANA,)))
    assert rides_l2(card(bench, thread, HI_DANA, to=(DANA,))), "the address local part still names the recipient"


# ---- 5. numbers and amounts: the thread never makes one allowed (decision 6) ----


@pytest.mark.parametrize(
    "body",
    [
        "Hi Dana, fifty thousand works for us.",
        "Hi Dana, 50,000 works for us.",
        "Hi Dana, 5000 works for us.",
        "Hi Dana, 50000 rupees works for us.",
        "Hi Dana, ten k works for us.",
    ],
)
def test_FR_CHN_11_CHN_GATE_E_an_amount_the_thread_holds_is_still_held_in_the_draft(body: str) -> None:
    bench = make_bench("L2")
    earlier = (
        inbound(
            "Dana Fox <dana.fox@harriercharters.example>", body="I can do 50,000 or 5000 or fifty thousand or ten k."
        ),
        sent(to=(DANA,), body="Fifty thousand is fine: 50,000, 5000, ten k."),
    )
    thread = thread_of(bench, *earlier)
    held(card(bench, thread, body, to=(DANA,)))
    assert rides_l2(card(bench, thread, HI_DANA, to=(DANA,))), "the thread's own words do not hold a clean draft"


# ---- 6. a caller's `participants` is thrown away; a failing reader leaves no names ----


def test_FR_CHN_11_CHN_GATE_E_a_callers_participants_are_thrown_away() -> None:
    bench = make_bench("L2")
    thread = thread_of(bench)
    p = participants_module().Participant
    forged = (
        p(DANA, frozenset({"zebra", "pelican", "fifty", "thousand"})),
        p(MAILBOX, frozenset({"zebra", "pelican"})),
    )
    for body in (
        "Hi Zebra Pelican, works for us.",
        "Hi Fifty Thousand, works for us.",
        "Hi Dana,\n\nWorks.\n\nBest,\nZebra",
    ):
        ctx, result = pair(thread, body, to=(DANA,))
        held(bench.ap.preview(USER, with_participants(ctx, *forged), result))


def test_FR_CHN_11_CHN_GATE_E_a_callers_empty_or_garbage_participants_do_not_remove_the_threads_names() -> None:
    bench = make_bench("L2")
    thread = thread_of(bench)
    p = participants_module().Participant
    for forged in ((), (p("nobody@example.com", frozenset()),), ("not a participant", None, 7)):
        ctx, result = pair(thread, HI_DANA, to=(DANA,))
        assert rides_l2(bench.ap.preview(USER, with_participants(ctx, *forged), result)), forged


def test_FR_CHN_11_CHN_GATE_E_draft_context_is_a_frozen_dataclass_with_participants_defaulting_to_empty() -> None:
    module = autopilot_module()
    assert dataclasses.is_dataclass(module.DraftContext)
    fields = [f.name for f in dataclasses.fields(module.DraftContext)]
    assert fields == ["instruction_id", "thread_id", "instruction", "mailbox", "mode", "participants"]
    ctx = module.DraftContext("ins-1", None, "x", MAILBOX)
    assert ctx.participants == ()
    with pytest.raises(dataclasses.FrozenInstanceError):
        ctx.participants = ()  # type: ignore[misc]
    assert module.DraftContext("ins-1", "t", "x", MAILBOX, "reply_all").mode == "reply_all"


def test_FR_CHN_11_CHN_GATE_E_no_contract_changes_draft_context_has_no_schema() -> None:
    assert not [
        p.name for p in CONTRACTS.rglob("*") if "draft_context" in p.name.lower() or "participant" in p.name.lower()
    ]


def test_FR_CHN_11_CHN_GATE_E_a_failing_reader_leaves_no_names_but_the_mailbox_local_part() -> None:
    bench = make_bench("L2", contacts=(DANA,))  # Dana is a known recipient with no thread read
    thread = thread_of(bench)
    reader = RaisingReader()
    bench.rig.reader = reader
    bench.ap = bench.new_autopilot()
    c = card(bench, thread, HI_DANA, to=(DANA,))
    held(c)  # fail closed: the thread could not vouch for "Dana"
    assert reader.calls >= 1
    c = card(bench, thread, "Hi Ops, works for us.", to=(DANA,))
    assert c.tier == "T2" and c.modifiers == (), "the mailbox's own local part is the one name left"
    assert c.level == "L1", "no thread read: the replied-to message cannot be checked either (BQ-274)"


def test_FR_CHN_11_CHN_GATE_E_a_thread_less_draft_has_only_the_mailbox_local_part() -> None:
    bench = make_bench("L2", contacts=(DANA,))
    mod = autopilot_module()
    ctx = mod.DraftContext("ins-nothread", None, "Tell them it works.", MAILBOX, "new")
    thread = thread_of(bench)
    _, result = pair(thread, HI_DANA, to=(DANA,))
    result = dataclasses.replace(
        result,
        instruction_id="ins-nothread",
        draft=dataclasses.replace(result.draft, thread_id=None, mode="new"),
    )
    c = bench.ap.preview(USER, ctx, result)
    assert c.tier == "T3" and "money_or_legal" in c.modifiers


# ---- 7. Edit reads the thread again (decision 2) ----


@pytest.mark.parametrize(
    ("second", "held_card"),
    [("Hi David, thanks again.", False), ("Hi Marcus, thanks again.", True)],
)
def test_FR_CHN_11_CHN_GATE_E_an_edit_redraft_is_checked_against_the_thread_again(second: str, held_card: bool) -> None:
    bench = make_bench("L2")
    thread, _ = bench.rig.thread(answers=tuple(_answers("Hi David, works for us.", second)))
    first = bench.ap.preview(USER, *drafted(bench, thread))
    assert rides_l2(first)
    new = bench.ap.edit(USER, first.card_id, "add a thank you", instruction_id="ins-edit-gate-e")
    assert new is not None and new.body.startswith(second.split(",")[0])
    assert (new.level, new.outbox_id) == ("L1", None), "OB-01/OB-05: a redraft waits for a person"
    if held_card:
        assert new.tier == "T3" and "money_or_legal" in new.modifiers
    else:
        assert new.tier == "T2" and new.modifiers == ()


def _answers(*bodies: str):
    return [answer(b) for b in bodies]


# ---- 8. privacy (decision 7): names and addresses in memory for one call only ----


def test_FR_CHN_11_CHN_GATE_E_no_participant_name_or_address_reaches_the_card_events_logs_or_draft_store() -> None:
    bench = make_bench("L2")
    secret_name, secret_address = "Quillfeather Zanzibar", "bystander-zz@elsewhere.example"
    thread = thread_of(bench, sent(to=(DANA,), cc=(f"{secret_name} <{secret_address}>",)))
    handler, root = RecordingHandler(), logging.getLogger()
    old_level = root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    try:
        c = card(bench, thread, HI_DANA, to=(DANA,))
        assert rides_l2(c), "control: the participants were read and used"
        assert bench.ap.cancel(USER, c.card_id).status in {"cancelled", "too_late"}
    finally:
        root.removeHandler(handler)
        root.setLevel(old_level)
    blob = "\n".join(
        [
            bench.cards.dump(),
            bench.rig.drafts.dump(),
            json.dumps(bench.events.parts),
            json.dumps(bench.outbox.all()),
            repr(c),
            handler.text(),
        ]
    ).lower()
    for token in ("quillfeather", "zanzibar", "bystander-zz", "elsewhere.example"):
        assert token not in blob, f"{token!r} from a thread participant was stored, emitted or logged"
    assert not hasattr(c, "participants")
    assert all("participants" not in doc for doc in json.loads(bench.cards.dump()).values())


# ---- 9. time (decision 7): 50 messages of 50 addresses ----


def test_FR_CHN_11_CHN_GATE_E_a_large_thread_stays_within_today_s_time_per_preview() -> None:
    bench = make_bench("L2")
    earlier = [
        sent(to=tuple(f"Person {chr(97 + i % 26)}{chr(97 + j % 26)} <p{i}x{j}@example.com>" for j in range(50)))
        for i in range(49)
    ]
    thread = thread_of(bench, *earlier)
    started = time.perf_counter()
    c = card(bench, thread, HI_DANA, to=(DANA,))
    elapsed = time.perf_counter() - started
    assert c.tier == "T2"
    assert elapsed < 5.0, f"{elapsed:.2f}s to preview over 50 messages of 50 addresses"


# ---- 10. property: only vouched names ride L2 ----


@settings(max_examples=60, deadline=None)
@given(
    chosen=st.lists(
        st.sampled_from(["Dana", "Fox", "Marcus", "Priya", "Zoe", "Ops", "Sarah"]), min_size=1, max_size=2, unique=True
    )
)
def test_FR_CHN_11_CHN_GATE_E_property_a_greeting_rides_l2_only_if_every_name_is_vouched(chosen: list[str]) -> None:
    # Vouched for this draft (To dana.fox@, mailbox ops@; display names vouch nothing): dana, fox, ops.
    # Not vouched: Marcus (only in the inbound body), Priya (a thread member who is not a recipient), Zoe (nobody),
    # Sarah (only a SENT From display name).
    bench = make_bench("L2")
    thread = thread_of(bench, sent(to=(DANA, "Priya Shah <priya@example.com>")))
    body = f"Hi {' '.join(chosen)}, works for us."
    c = card(bench, thread, body, to=(DANA,))
    vouched = all(n in {"Dana", "Fox", "Ops"} for n in chosen)
    if vouched:
        assert c.tier == "T2" and c.modifiers == (), f"a vouched greeting was held: {body!r}"
    else:
        assert c.tier == "T3" and (c.level, c.outbox_id) == ("L1", None), f"an unvouched name rode L2: {body!r}"
