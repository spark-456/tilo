"""CHN-GATE-E security review r1 (FR-CHN-11; ADR-0025 decisions 3 and 5, and the 8 Oct amendment: display names vouch
nothing). Written after the implementation; every case below is a hole the review found or a rule it asked to pin.

 - A plus tag is free text: a To or Cc address on a message that is not the user's own SENT mail gives the words of its
   BASE local part only (here: no message gives any tag), so a third party cannot choose a recipient's name words by
   writing `david.miller+approved.prepaid@...` into a header (the review's end-to-end probe, through the real Drafter).
 - A display name vouches nothing, not even on the user's own SENT mail: Gmail copies an inbound From display name into
   the SENT To when the user replies by hand ("Prepaid Approved <mallory@...>", then "Hi Prepaid Approved,").
 - The CHN-GATE-D r1-r3 number words as local parts are dropped by the single-word `_numberish` check.
 - An attacker-shaped thread (480-character local parts, raw "<" spam) costs a bounded time per read.
 - An address is checked for ASCII before it is lower-cased (U+212A KELVIN SIGN folds to "k").
"""

from __future__ import annotations

import time
from typing import Any

import pytest
from _chn10_lib import FakeThreadReader, Msg, Thread, answer
from _chn11_lib import DAVID, drafted
from _chn_gate_e_lib import (
    MAILBOX,
    OWN,
    USER,
    Mail,
    card,
    inbound,
    is_t3_unlisted,
    make_bench,
    names_by_address,
    participants_module,
    rides_l2,
    sent,
    thread_of,
)

DAVID_TAG = DAVID.replace("@", "+approved.prepaid@")
SPOOF_CC = Mail("m-spoof-cc", OWN, "Re: Engine tune-up", "Looping in.", to=[MAILBOX], cc=[DAVID_TAG], labels=["INBOX"])
SPOOF_NO_LABEL = Mail("m-spoof-nolabel", OWN, "Re: Engine tune-up", "Looping in.", to=[MAILBOX], cc=[DAVID_TAG])
SPOOF_TAGGED_FROM = Msg(
    "m-spoof-tag", "Ops <ops+x@harborview.example>", "Re: Engine tune-up", "Looping in.", to=[DAVID_TAG]
)
SPOOF_TAGGED_MAILBOX = Msg(
    "m-spoof-mb", "Ops <ops+approved.prepaid@harborview.example>", "Re: Engine tune-up", "Looping in.", to=[MAILBOX]
)
SPOOFS = [SPOOF_CC, SPOOF_NO_LABEL, SPOOF_TAGGED_FROM, SPOOF_TAGGED_MAILBOX]
IDS = ["cc_from_mailbox_inbox", "cc_from_mailbox_no_label", "to_from_tagged_mailbox", "tagged_mailbox_from"]


def read(*messages: Msg) -> tuple[Any, ...]:
    reader = FakeThreadReader()
    reader.add("u_r1", Thread(thread_id="t-r1", messages=list(messages)))
    return tuple(participants_module().read_participants(reader, "u_r1", "t-r1", MAILBOX))


@pytest.mark.parametrize("spoof", SPOOFS, ids=IDS)
def test_FR_CHN_11_CHN_GATE_E_r1_a_plus_tag_on_a_header_only_message_names_nobody(spoof: Msg) -> None:
    names = names_by_address(read(inbound("David Miller <david.miller@harriercharters.example>"), spoof))
    assert not names[DAVID] & {"approved", "prepaid"}, "a third party chose a recipient's name words through a plus tag"
    assert names[DAVID] == {"david", "miller"}
    assert names[MAILBOX] == {"ops"}, "a tag on the mailbox address is free text too"
    assert all(not {"approved", "prepaid", "x"} & words for words in names.values())


@pytest.mark.parametrize("spoof", SPOOFS, ids=IDS)
def test_FR_CHN_11_CHN_GATE_E_r1_through_the_real_drafter_a_tagged_spoof_does_not_vouch_a_word(spoof: Msg) -> None:
    for body, rides in (("Hi David, works for us.", True), ("Hi David, Approved.", False)):
        bench = make_bench("L2")
        thread, _ = bench.rig.thread(answers=(answer(body),), cc=())
        thread.messages.append(spoof)  # newer than the answered message, From the mailbox (spoofable header)
        ctx, result = drafted(bench, thread)
        c = bench.ap.preview(USER, ctx, result)
        if rides:
            assert rides_l2(c), "control: the real recipient's own name rides"
        else:
            assert is_t3_unlisted(c) and c.scheduled_at is None, f"{body!r} rode L2 through a spoofed plus tag"
            bench.rig.clock.advance(3600)
            bench.outbox.dispatch_due()
            assert bench.outbox.entries == {}, "T3 is never scheduled without a person"


def test_FR_CHN_11_CHN_GATE_E_r1_a_name_gmail_copied_from_an_inbound_from_into_the_users_reply_names_nobody() -> None:
    # The user replies by hand once: Gmail puts the inbound From display name into the SENT To.
    bench = make_bench("L2")
    mallory = "Prepaid Approved <mallory@example.com>"
    thread = thread_of(bench, inbound(mallory), sent(to=(mallory,)), sender=mallory)
    to = ("mallory@example.com",)
    for body in ("Hi Prepaid Approved, works for us.", "Hi Prepaid, works for us.", "Hi Approved, works for us."):
        c = card(bench, thread, body, to=to)
        assert is_t3_unlisted(c) and c.scheduled_at is None, f"{body!r} rode L2 on a copied display name"
    assert rides_l2(card(bench, thread, "Hi Mallory, works for us.", to=to)), "control: the local part still names it"


@pytest.mark.parametrize("word", ["Fifty", "Fiftyk", "Tenrm", "Onemil", "Sixbucks", "Fivegrand"])
def test_FR_CHN_11_CHN_GATE_E_r1_a_number_word_local_part_or_display_name_names_nobody(word: str) -> None:
    # the GATE-D r1-r3 words: only the single-word `_numberish` check in the name filter keeps them out
    address = f"{word.lower()}@example.com"
    assert not any(address in p.address and p.names for p in read(sent(to=(f"{word} <{address}>",)), inbound(address)))
    bench = make_bench("L2")
    thread = thread_of(bench, sent(to=(f"{word} <{address}>",)), inbound(f"{word} <{address}>"), sender=address)
    c = card(bench, thread, f"Hi {word}, works for us.", to=(address,))
    assert is_t3_unlisted(c), f"{word!r} rode L2"


def test_FR_CHN_11_CHN_GATE_E_r1_the_kelvin_sign_is_not_lowered_into_a_letter() -> None:
    words = participants_module()._words
    assert words("tenK", {}) == (), "U+212A is not ASCII: dropped before it can fold to 'k'"
    assert words("pat", {}) == ("pat",)


def test_FR_CHN_11_CHN_GATE_E_r1_an_attacker_shaped_thread_costs_a_bounded_time_per_read() -> None:
    dotted = ".".join(["ab"] * 160) + "@example.com"  # 480-character local part
    spam = "<" * 480
    messages: list[Msg] = []
    for i in range(50):
        to = tuple([dotted] * 25 + [spam] * 25)  # the production shape (bare addr-specs) and raw "<" spam, in list form
        messages.append(inbound(f"Dana <dana{i}@example.com>", to=to, cc=to))
    started = time.perf_counter()
    result = read(*messages)
    elapsed = time.perf_counter() - started
    assert len(result) <= 100
    assert elapsed < 4.0, f"{elapsed:.2f}s for an attacker-shaped thread: the header parse needs a character budget"
