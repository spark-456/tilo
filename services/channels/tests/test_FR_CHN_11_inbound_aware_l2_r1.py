"""FR-CHN-11, security review round 1 of PR #389 (ADR-0013; issue #298 "CHN-GATE-C", first bullet; BQ-265; PRD 10.4: T3
"money, contract or legal terms" always needs a person, L2 "the instruction is the approval" is for plain replies;
OB-01: an L2 send is queued only on a policy decision). The first review failed the inbound-aware L2 check on four
counts; these tests pin the fix (the amount-shape and ASCII-split signals are in the `_unit` file).

  1. The replied-to message's SUBJECT is read like its body. A clean body under "Confirm the $5,000 wire transfer
     today" keeps a clean draft ("Yes, confirmed.") off L2, on the legacy level hint, on the policy port and through
     the real Drafter. A subject that is not text, or is obfuscated, fails closed. Only the replied-to message's
     subject counts, never an earlier one's.
  2. A spoofed sender: L2 only when the replied-to message carries an `Authentication-Results` header with
     "dmarc=pass" (case-insensitive). Any dmarc=fail / softfail / none / temperror / permerror, an ambiguous value (no
     dmarc verdict, or a pass beside a failure), a missing header or a value that is not text fails closed. Per the
     user's decision of 5 Oct for #298 (BQ-265) such a reply is T3; these tests only pin that the card stays off L2
     (level L1, window 0, no policy.applied, no outbox entry) and leave the tier to the code.
  3. More than one message sharing the replied-to Message-ID fails closed (it replaces "all duplicates must be
     clean"): the id does not name one message, so no one message can be called clean. Also pinned, to kill mutants:
     a first-only or last-only duplicate check, a removed empty-`in_reply_to` guard (a message with no Message-ID must
     not match an empty `in_reply_to`), and a missing, `None` or non-text body turned into a string.

Fake clock, fake outbox, no network, no paid call. Helpers: _chn11_inbound_lib.py (`tamper` hands a test the
replied-to message as the plain dict the reader returns). Invisible characters are built with chr()."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from _chn10_lib import AUTH_PASS, USER, Msg, answer
from _chn11_inbound_lib import (
    CLEAN_DRAFTS,
    KINDS,
    NUMBER_INBOUND,
    SCHEDULING_INBOUND,
    SIGNAL_INBOUND,
    SUBJECT_SIGNAL,
    answering,
    assert_rides_l2,
    assert_waits_for_a_person,
    earlier_message,
    make_l2,
)
from _chn11_lib import INSTRUCTION, MAILBOX, context
from _chn_wire4_lib import fresh_ulid
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

TRANSFER = "Can you confirm the transfer of $5,000 to our bank account today?"
ZWSP = chr(0x200B)
AUTH = "Authentication-Results"
YES = "Yes, confirmed."


def _card(
    kind: str, inbound: str = SCHEDULING_INBOUND, body: str = YES, edit: Callable[[dict], None] | None = None, **kw: Any
):
    """(rig, thread, preview, context) of a ready `body` draft answering the thread's last message."""
    h = make_l2(kind)
    thread = h.thread(inbound, **kw)
    if edit is not None:
        h.tamper(edit)
    p, ctx, _ = h.preview(thread, body)
    return h, thread, p, ctx


def _set(key: str, value: Any) -> Callable[[dict], None]:
    def edit(message: dict) -> None:
        message[key] = value

    return edit


def _drop(key: str) -> Callable[[dict], None]:
    def edit(message: dict) -> None:
        message.pop(key, None)

    return edit


def _header(name: str, value: Any = None, *, drop: bool = False) -> Callable[[dict], None]:
    def edit(message: dict) -> None:
        if drop:
            message["headers"].pop(name, None)
        else:
            message["headers"][name] = value

    return edit


# ---------------------------------------------------------------------------
# (1) The replied-to message's Subject


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("family", list(SUBJECT_SIGNAL))
@pytest.mark.parametrize("body", CLEAN_DRAFTS)
def test_FR_CHN_11_inbound_aware_l2_a_signal_in_the_subject_keeps_a_clean_draft_off_l2(
    kind: str, family: str, body: str
) -> None:
    # The motivating probe: subject "Confirm the $5,000 wire transfer today", a clean scheduling body, "Yes, confirmed."
    h, _, p, ctx = _card(kind, SCHEDULING_INBOUND, body, subject=SUBJECT_SIGNAL[family])
    assert_waits_for_a_person(h, p, ctx)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("family", list(SUBJECT_SIGNAL))
def test_FR_CHN_11_inbound_aware_l2_through_the_real_drafter_a_signal_in_the_subject_waits_for_a_person(
    kind: str, family: str
) -> None:
    h = make_l2(kind)
    thread, _ = h.rig.thread(subject=SUBJECT_SIGNAL[family], answers=(answer(YES),))
    ctx = context(thread, instruction=INSTRUCTION, instruction_id=fresh_ulid())
    result = h.rig.svc.draft(
        USER, instruction_id=ctx.instruction_id, thread_id=thread.thread_id, instruction=INSTRUCTION, mailbox=MAILBOX
    )
    assert result.status == "ready" and result.draft.body == YES, "test setup: the clean reply passes FR-CHN-10"
    p = h.ap.preview(USER, ctx, result)
    assert_waits_for_a_person(h, p, ctx)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("subject", ["Re: Confirm the $5,000 wire transfer today", "RE: CONFIRM THE REFUND"])
def test_FR_CHN_11_inbound_aware_l2_a_re_prefixed_or_upper_case_subject_signal_still_counts(
    kind: str, subject: str
) -> None:
    h, _, p, ctx = _card(kind, subject=subject)
    assert_waits_for_a_person(h, p, ctx)


@pytest.mark.parametrize("kind", KINDS)
def test_FR_CHN_11_inbound_aware_l2_an_amount_in_the_subject_counts_like_one_in_the_body(kind: str) -> None:
    h, _, p, ctx = _card(kind, subject="Can you confirm the 5,000 today?")
    assert_waits_for_a_person(h, p, ctx)


@pytest.mark.parametrize("kind", KINDS)
def test_FR_CHN_11_inbound_aware_l2_an_obfuscated_subject_fails_closed(kind: str) -> None:
    h, _, p, ctx = _card(kind, subject=f"Engine tune-up{ZWSP} scheduling")
    assert_waits_for_a_person(h, p, ctx)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize(
    "edit",
    [
        _set("subject", None),
        _set("subject", 7),
        _set("subject", ["Friday"]),
        _set("subject", b"Friday"),
        _drop("subject"),
    ],
    ids=["none", "int", "list", "bytes", "missing"],
)
def test_FR_CHN_11_inbound_aware_l2_a_subject_that_is_not_text_fails_closed(kind: str, edit: Callable) -> None:
    h, _, p, ctx = _card(kind, edit=edit)
    assert_waits_for_a_person(h, p, ctx)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize(
    "subject", ["Engine tune-up scheduling", "Re: Engine tune-up scheduling", "Re: Dock 14 on Thursday at 3pm"]
)
def test_FR_CHN_11_inbound_aware_l2_a_clean_subject_still_rides_l2(kind: str, subject: str) -> None:
    h, _, p, _ = _card(kind, subject=subject)
    assert_rides_l2(h, p)


@pytest.mark.parametrize("kind", KINDS)
def test_FR_CHN_11_inbound_aware_l2_the_default_test_subject_is_clean(kind: str) -> None:
    # "estimate" is a money word: the shared test benches must not use it as the subject of a clean thread.
    h = make_l2(kind)
    thread = h.thread()
    assert "estimate" not in thread.messages[-1].subject.lower()
    p, _, _ = h.preview(thread, YES)
    assert_rides_l2(h, p)


@pytest.mark.parametrize("kind", KINDS)
def test_FR_CHN_11_inbound_aware_l2_an_earlier_messages_risky_subject_does_not_matter(kind: str) -> None:
    h = make_l2(kind)
    earlier = Msg(
        message_id="m-earlier-subject",
        sender="David Miller <david.miller@harriercharters.example>",
        subject="Confirm the $5,000 wire transfer today",
        body="Hi Sarah, are you free on Friday?",
        headers={AUTH: AUTH_PASS},
    )
    thread = h.thread(SCHEDULING_INBOUND, earlier=(earlier,))
    p, _, _ = h.preview(thread, YES)
    assert_rides_l2(h, p)


# ---------------------------------------------------------------------------
# (2) A spoofed sender: L2 needs dmarc=pass on the replied-to message

FAILING_RESULTS = {
    "dmarc_fail": "mx.example; spf=pass; dkim=pass; dmarc=fail header.from=harriercharters.example",
    "dmarc_softfail": "mx.example; dmarc=softfail header.from=harriercharters.example",
    "dmarc_none": "mx.example; dmarc=none header.from=harriercharters.example",
    "dmarc_temperror": "mx.example; dmarc=temperror header.from=harriercharters.example",
    "dmarc_permerror": "mx.example; dmarc=permerror header.from=harriercharters.example",
    "upper_case_fail": "MX.EXAMPLE; DMARC=FAIL HEADER.FROM=HARRIERCHARTERS.EXAMPLE",
    "pass_then_fail": "mx.example; dmarc=pass header.from=a.example; dmarc=fail header.from=harriercharters.example",
    "fail_then_pass": "mx.example; dmarc=fail header.from=harriercharters.example; dmarc=pass header.from=a.example",
    "spf_and_dkim_pass_but_no_dmarc": "mx.example; spf=pass; dkim=pass",
    "no_verdict": "mx.example; dmarc",
    "empty_verdict": "mx.example; dmarc=",
    "empty": "",
    "blank": "   ",
}


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("value", list(FAILING_RESULTS.values()), ids=list(FAILING_RESULTS))
def test_FR_CHN_11_inbound_aware_l2_anything_but_dmarc_pass_keeps_the_reply_off_l2(kind: str, value: str) -> None:
    h, _, p, ctx = _card(kind, headers={AUTH: value})
    assert_waits_for_a_person(h, p, ctx)


@pytest.mark.parametrize("kind", KINDS)
def test_FR_CHN_11_inbound_aware_l2_a_message_with_no_authentication_results_header_fails_closed(kind: str) -> None:
    h, _, p, ctx = _card(kind, edit=_header(AUTH, drop=True))
    assert_waits_for_a_person(h, p, ctx)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize(
    "value",
    [None, 5, True, ["mx.example; dmarc=pass"], {"v": "dmarc=pass"}, b"mx.example; dmarc=pass"],
    ids=["none", "int", "bool", "list", "dict", "bytes"],
)
def test_FR_CHN_11_inbound_aware_l2_an_authentication_results_value_that_is_not_text_fails_closed(
    kind: str, value: Any
) -> None:
    h, _, p, ctx = _card(kind, edit=_header(AUTH, value))
    assert_waits_for_a_person(h, p, ctx)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize(
    "value",
    [
        AUTH_PASS,
        "mx.example; dmarc=pass header.from=harriercharters.example",
        "MX.EXAMPLE; DMARC=PASS HEADER.FROM=HARRIERCHARTERS.EXAMPLE",
        "mx.example; spf=pass smtp.mailfrom=x.example; dkim=pass; dmarc=pass (p=reject) header.from=x.example",
    ],
    ids=["default", "plain", "upper_case", "with_spf_dkim_and_policy"],
)
def test_FR_CHN_11_inbound_aware_l2_dmarc_pass_in_any_case_still_rides_l2(kind: str, value: str) -> None:
    h, _, p, _ = _card(kind, headers={AUTH: value})
    assert_rides_l2(h, p)


@pytest.mark.parametrize("kind", KINDS)
def test_FR_CHN_11_inbound_aware_l2_an_earlier_messages_failing_authentication_does_not_matter(kind: str) -> None:
    h = make_l2(kind)
    earlier = earlier_message("Hi Sarah, are you free on Friday?")
    earlier.headers[AUTH] = FAILING_RESULTS["dmarc_fail"]
    thread = h.thread(SCHEDULING_INBOUND, earlier=(earlier,))
    p, _, _ = h.preview(thread, YES)
    assert_rides_l2(h, p)


def test_FR_CHN_11_inbound_aware_l2_the_owner_can_still_send_a_reply_to_an_unauthenticated_message() -> None:
    # Legacy bench (fake evidence), like the existing owner-send test; the policy port needs real OB-01 evidence.
    h, _, p, ctx = _card("legacy_level_hint", headers={AUTH: FAILING_RESULTS["dmarc_fail"]})
    assert_waits_for_a_person(h, p, ctx)
    out = h.ap.send(USER, p.card_id)
    assert out.status == "queued", "the owner's own Send still queues it, with no undo window"
    (entry,) = h.entries()
    assert entry["authz"]["by"] == "person" and entry["undo_window_s"] == 0


# ---------------------------------------------------------------------------
# (3) More than one message with the replied-to Message-ID fails closed


def _with_copies(kind: str, *copies: tuple[str, int], subject: str = "Engine tune-up scheduling"):
    """A clean, authenticated thread whose last message is the replied-to one, plus copies sharing its Message-ID:
    `(body, index)` inserts a copy at that index (negative: appended after the last message)."""
    h = make_l2(kind)
    thread = h.thread(SCHEDULING_INBOUND)
    shared = thread.messages[-1].message_id
    for body, index in copies:
        copy = Msg(
            message_id=shared,
            sender=thread.messages[-1].sender,
            subject=subject,
            body=body,
            headers={AUTH: AUTH_PASS},
        )
        if index < 0:
            thread.messages.append(copy)
        else:
            thread.messages.insert(index, copy)
    return h, thread


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize(
    "copies",
    [
        ((SCHEDULING_INBOUND, 0),),
        ((SCHEDULING_INBOUND, -1),),
        ((TRANSFER, 0),),
        ((TRANSFER, -1),),
        ((SCHEDULING_INBOUND, 0), (SCHEDULING_INBOUND, -1)),
        ((TRANSFER, 0), (SCHEDULING_INBOUND, -1)),
    ],
    ids=[
        "clean_before",
        "clean_after",
        "risky_before_clean_last",
        "risky_after_clean_first",
        "three_clean",
        "three_one_risky",
    ],
)
def test_FR_CHN_11_inbound_aware_l2_two_messages_with_the_replied_to_message_id_fail_closed(
    kind: str, copies: tuple[tuple[str, int], ...]
) -> None:
    # Every copy is clean in the cases named "clean": the old rule ("all duplicates must be clean") rode L2; the new one
    # does not, whichever copy a first-only or last-only check would have looked at.
    h, thread = _with_copies(kind, *copies)
    assert sum(m.message_id == thread.messages[-1].message_id for m in thread.messages) == len(copies) + 1
    p, ctx, _ = h.preview(thread, YES)
    assert_waits_for_a_person(h, p, ctx)


@pytest.mark.parametrize("kind", KINDS)
def test_FR_CHN_11_inbound_aware_l2_a_risky_copy_in_the_middle_of_clean_ones_fails_closed(kind: str) -> None:
    h, thread = _with_copies(kind, (SCHEDULING_INBOUND, 0), (TRANSFER, 1))
    p, ctx, _ = h.preview(thread, YES)
    assert_waits_for_a_person(h, p, ctx)


@pytest.mark.parametrize("kind", KINDS)
def test_FR_CHN_11_inbound_aware_l2_a_single_match_among_other_distinct_messages_still_rides_l2(kind: str) -> None:
    h = make_l2(kind)
    others = (earlier_message("Hi Sarah, are you free on Friday?", message_id="m-a"), earlier_message(TRANSFER))
    thread = h.thread(SCHEDULING_INBOUND, earlier=others)
    p, _, _ = h.preview(thread, YES)
    assert_rides_l2(h, p)


# ---------------------------------------------------------------------------
# Mutants: the empty in_reply_to guard, and a body that is not text


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize(
    "edit", [_header("Message-ID", drop=True), _header("Message-ID", "")], ids=["no_message_id", "empty_message_id"]
)
def test_FR_CHN_11_inbound_aware_l2_an_empty_in_reply_to_never_matches_a_message_with_no_message_id(
    kind: str, edit: Callable
) -> None:
    # Without the guard, "" == "" would pick the message that has no Message-ID and its clean body would ride L2.
    h = make_l2(kind)
    thread = h.thread(SCHEDULING_INBOUND)
    h.tamper(edit)
    ctx, result = answering(thread, YES, in_reply_to="")
    p = h.ap.preview(USER, ctx, result)
    assert_waits_for_a_person(h, p, ctx)


@pytest.mark.parametrize("kind", KINDS)
def test_FR_CHN_11_inbound_aware_l2_an_empty_in_reply_to_with_every_message_lacking_an_id_fails_closed(
    kind: str,
) -> None:
    h = make_l2(kind)
    thread = h.thread(SCHEDULING_INBOUND, earlier=(earlier_message("Hi Sarah, are you free on Friday?"),))
    original = h.rig.reader.get_thread

    def get_thread(user_id: str, thread_id: str) -> dict:
        doc = original(user_id, thread_id)
        for message in doc["messages"]:
            message["headers"].pop("Message-ID", None)
        return doc

    h.rig.reader.get_thread = get_thread  # type: ignore[method-assign]
    ctx, result = answering(thread, YES, in_reply_to="")
    p = h.ap.preview(USER, ctx, result)
    assert_waits_for_a_person(h, p, ctx)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize(
    "edit",
    [
        _set("body", None),
        _set("body", ["Hi Sarah, can Marcus come by this Friday afternoon?"]),
        _set("body", 1234),
        _set("body", b"Hi Sarah, can Marcus come by this Friday afternoon?"),
        _set("body", {"text": "Hi Sarah, can Marcus come by this Friday afternoon?"}),
        _drop("body"),
    ],
    ids=["none", "list", "int", "bytes", "dict", "missing"],
)
def test_FR_CHN_11_inbound_aware_l2_a_body_that_is_not_text_is_never_read_as_text_and_fails_closed(
    kind: str, edit: Callable
) -> None:
    # A mutant that turned the value into a string (str(body), or "" for a missing one) would read clean text.
    h, _, p, ctx = _card(kind, edit=edit)
    assert_waits_for_a_person(h, p, ctx)


# ---------------------------------------------------------------------------
# Invariant (Hypothesis): the window needs a clean body, a clean subject and a dmarc pass together

_SUBJECTS = ["Engine tune-up scheduling", "Re: Friday afternoon", *SUBJECT_SIGNAL.values()]
_RESULTS = [AUTH_PASS, FAILING_RESULTS["dmarc_fail"], FAILING_RESULTS["no_verdict"], FAILING_RESULTS["empty"]]
_BODIES = [SCHEDULING_INBOUND, TRANSFER, *SIGNAL_INBOUND[:3], *NUMBER_INBOUND]


@given(
    body=st.sampled_from(_BODIES),
    subject=st.sampled_from(_SUBJECTS),
    results=st.sampled_from(_RESULTS),
    kind=st.sampled_from(KINDS),
)
@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_FR_CHN_11_inbound_aware_l2_property_the_window_needs_a_clean_body_subject_and_authentication(
    body: str, subject: str, results: str, kind: str
) -> None:
    h = make_l2(kind)
    thread = h.thread(body, subject=subject, headers={AUTH: results})
    p, ctx, _ = h.preview(thread, YES)
    if body == SCHEDULING_INBOUND and subject in _SUBJECTS[:2] and results == AUTH_PASS:
        assert_rides_l2(h, p)
    else:
        assert_waits_for_a_person(h, p, ctx)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("inbound", NUMBER_INBOUND, ids=[f"number{i}" for i in range(len(NUMBER_INBOUND))])
def test_FR_CHN_11_inbound_aware_l2_an_amount_or_number_word_inbound_never_rides_l2(kind: str, inbound: str) -> None:
    # Round 1 finding 2 end to end: no money word in the sentence, but an amount or a number word.
    h, _, p, ctx = _card(kind, inbound)
    assert_waits_for_a_person(h, p, ctx)
