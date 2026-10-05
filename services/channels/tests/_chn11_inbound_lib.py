"""Test doubles and builders for the inbound-aware L2 tests (FR-CHN-11; ADR-0013; issue #298 "CHN-GATE-C", first
bullet; BQ-265). Nothing here is production logic.

The autopilot used to look only at the draft's own body. These helpers build a thread with a chosen replied-to
(inbound) message and a ready draft that answers exactly that message (`in_reply_to` is the replied-to message's
Message-ID header, as FR-CHN-10's Drafter sets it), then run it through the real `Autopilot` in the two ways the
level reaches it: the legacy `level()` hint (`make_bench`, a permissive fake that answers L2 for every send) and the
policy port (`make_w4`, a production-mode Autopilot whose fake engine answers `run_after_undo` for every proposal).
Either way the fake policy is deliberately permissive, so only the autopilot's own inbound check can keep a card off
the undo window. No network, no paid call, no real mail. Addresses are fictional `.example` domains.
"""

from __future__ import annotations

import dataclasses
import functools
import importlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from _chn10_lib import AUTH_PASS, CLEAN_SUBJECT, USER, Msg, Thread, message_id_header
from _chn11_lib import DAVID, INSTRUCTION, MAILBOX, SARAH, context, make_bench, ready
from _chn_wire4_lib import fresh_ulid, make_w4

KINDS = ("legacy_level_hint", "policy_port")

# The three decided failing drafts (their own body is clean scheduling talk: T2, and today L2) ...
CLEAN_DRAFTS = ["Yes, confirmed.", "Yes to all of that.", "We would be happy to."]
# ... and a clean inbound: plain scheduling talk, no money, legal or commitment word.
SCHEDULING_INBOUND = "Hi Sarah, can Marcus come by this Friday afternoon? Thanks, David"

# One inbound sentence per signal family (each is plain text with no hidden character).
MONEY_INBOUND = [
    "Please confirm the transfer of $5,000 to our bank account today.",
    "Can you confirm the refund goes out this week?",
    "Could you pay the invoice before Friday?",
    "Is the quote still what you told us on the phone?",
]
LEGAL_INBOUND = [
    "Please confirm that you accept the contract terms.",
    "Do you agree to the NDA that I sent last week?",
    "Can you sign the waiver before the boat leaves?",
    "Who takes the liability if something breaks?",
]
COMMITMENT_INBOUND = [
    "Can you promise the engine is ready by Friday?",
    "Do you guarantee the repair will hold?",
    "Will you commit to the Friday deadline?",
    "Please assure me that nothing else is needed.",
]
SIGNAL_INBOUND = MONEY_INBOUND + LEGAL_INBOUND + COMMITMENT_INBOUND

# Money by an amount or a number word, with no money word in the sentence (BQ-265 fix pass, security review round 1).
NUMBER_INBOUND = [
    "Can you confirm the 5,000 to our account today?",
    "Please confirm the five thousand for the boat by Friday.",
    "Can you confirm we're square at 12000?",
    "Please confirm you'll take care of the 3 lakh tomorrow.",
    "Can you confirm you're on board with the 10% cut?",
]

# The replied-to message's Subject carries the signal and its body is clean scheduling talk (round 1, finding 1).
SUBJECT_SIGNAL = {
    "money": "Confirm the $5,000 wire transfer today",
    "legal": "Please sign the contract and NDA",
    "commitment": "We guarantee the Friday repair",
}


# Redesign after security round 3 (decided 6 Oct under the user's standing delegation; stricter than the 5 Oct
# decision): L2 needs the replied-to body AND Subject to be PLAIN (`autopilot_t3.inbound_plain`) as well as free of any
# `inbound_signal`. A denylist cannot list every obfuscation, so only plain scheduling talk may ride L2.
PLAIN_INBOUND = [
    SCHEDULING_INBOUND,
    "Can Marcus come by this Friday afternoon to look the engine over? Thanks, David",
    "Hi Sarah, are you free at 3pm or 2:30pm tomorrow?",
    "Don't worry, we're fine.",
    "Hi Sarah,\n\nCan Marcus come by this Friday afternoon?\nLet us meet at 14:30 on Thursday.\n\nThanks,\nDavid",
]
PLAIN_SUBJECTS = [
    "Engine tuneup scheduling",
    "Re: Engine tuneup scheduling",
    "Re: Dock on Thursday at 3pm",
    "Friday afternoon",
    "Re: Are you free at 2:30pm tomorrow?",
]

# The exact failures of the round-3 review: each is NOT clean (`inbound_signal` non-empty OR not `inbound_plain`).
R3_BODY_FAILURES = [
    "Please confirm the _transfer_ today.",
    "Please _sign_ the _contract_ today.",
    "_refund_",
    "_wire_",
    "the_transfer",
    "Please confirm the/trans-fer today.",
    "ok/re-fund today",
    "1)trans-fer",
    "si-gn/return",
    "wi-re/send",
    "the.trans.fer",
    "5million",
    "10lakh",
    "10lakhs",
    "2crore",
    "50thousand",
    "5hundred",
    "5mil",
    "5_million",
    "50  K",
    "25-M",
    "10-L",
    "12-b",
    "10/L",
    "10_m",
]
R3_SUBJECT_FAILURES = ["Re: _contract_ by Friday", "Re:con-tract", "Re:contract"]


# Round 4 (security review of PR #389): a family word cut by line breaks (or a stop mark and a line break) with a
# neighbouring word glued by a line break. Each is NOT clean (a signal OR not plain), as a body and as a Subject.
R4_NEWLINE_GLUE = [
    "Please confirm the\ntrans\nfer today.",
    "Please confirm the.\ntrans.\nfer today.",
    "Please\nsi\ngn\nit today.",
    "Please confirm the\ncon\ntract today.",
    "Please confirm the\nwi\nre today.",
    "Please confirm the\nrefu\nnd today.",
    "Please\nguaran\ntee it today.",
    "Please confirm the?\ndepo\nsit today.",
]
R4_SUBJECT_NEWLINE_GLUE = ["Re:\ncon\ntract", *R4_NEWLINE_GLUE]
# Ordinary multi-line plain scheduling talk stays clean and rides L2.
R4_PLAIN_MULTILINE = [
    "Hi Sarah,\nare you free on Friday\nafternoon or on\nSaturday morning?\nThanks,\nDavid",
    "Hi Sarah,\n\nCan Marcus come by this Friday afternoon?\nLet us meet at 14:30 on Thursday.\n\nThanks,\nDavid",
]
# Raw non-ASCII text that NFKC would turn into plain ASCII: never plain ("reſund", "ſees", fullwidth letters, NBSP).
R4_RAW_NON_ASCII_BODIES = [
    "Please confirm the re" + chr(0x017F) + "und today.",
    "Please confirm the " + chr(0x017F) + "ees today.",
    "Hi Sarah, are you free on Friday" + chr(0x00AA) + " afternoon?",
    "Hi Sarah, are you free on " + chr(0xFF26) + "riday?",
    "Hi Sarah, are you free on Friday" + chr(0x00A0) + "afternoon?",
]
R4_RAW_NON_ASCII_SUBJECTS = [
    "Re: re" + chr(0x017F) + "und",
    chr(0x017F) + "ees",
    "Friday" + chr(0x00A0) + "afternoon",
    "Re: " + chr(0xFF26) + "riday afternoon",
]
# Single letters separated by times of day ("w 5pm i 5pm r 5pm e" is "wire"): not clean.
R4_LETTERS_BETWEEN_TIMES = [
    "w 5pm i 5pm r 5pm e it today",
    "Please confirm the t 3pm r 3pm a 3pm n 3pm s 3pm fer today.",
]


def t3_module() -> Any:
    """Imported at call time so a missing function fails the test, not collection."""
    return importlib.import_module("tilo_channels.autopilot_t3")


def inbound_signal(text: str) -> frozenset[str]:
    """The proposed pure function `tilo_channels.autopilot_t3.inbound_signal(text) -> frozenset[str]` (a subset of
    {"money", "legal", "commitment", "obfuscated"}; never "unlisted"). A missing name fails the test."""
    return t3_module().inbound_signal(text)


def inbound_plain(text: str) -> bool:
    """The proposed pure function `tilo_channels.autopilot_t3.inbound_plain(text) -> bool`. A missing name fails the
    test."""
    return t3_module().inbound_plain(text)


def is_clean(text: str) -> bool:
    """What `inbound_is_clean` requires of the body and of the Subject: no signal AND plain."""
    return not inbound_signal(text) and inbound_plain(text)


def needs_inbound_plain(test: Callable[..., Any]) -> Callable[..., Any]:
    """A missing `inbound_plain` fails once, before Hypothesis generates or shrinks anything."""

    @functools.wraps(test)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        inbound_plain("")
        return test(*args, **kwargs)

    return wrapper


def needs_inbound_signal(test: Callable[..., Any]) -> Callable[..., Any]:
    """A missing `inbound_signal` fails once, before Hypothesis generates or shrinks anything."""

    @functools.wraps(test)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        inbound_signal("")
        return test(*args, **kwargs)

    return wrapper


@dataclass
class L2Rig:
    """One Autopilot wiring, either kind. `thread()` adds a thread for USER whose last message is the inbound one."""

    kind: str
    rig: Any
    ap: Any
    outbox: Any
    events: Any
    clock: Any
    new_ap: Any  # another instance over the same stores (a restart or a second Cloud Run instance)

    def thread(
        self,
        inbound: str = SCHEDULING_INBOUND,
        *,
        earlier: tuple[Msg, ...] = (),
        subject: str = CLEAN_SUBJECT,
        headers: dict[str, str] | None = None,
    ) -> Thread:
        """`subject` and `headers` are the replied-to message's (`headers` is added to its default dmarc=pass
        Authentication-Results, so a test overrides that one key to change it)."""
        thread, _ = self.rig.thread(body=inbound, earlier=earlier, subject=subject, headers=headers)
        return thread

    def tamper(self, edit: Callable[[dict[str, Any]], None]) -> None:
        """Every later read of a thread through the reader hands `edit` the replied-to message (the thread's last
        one) as the plain dict the reader returns, so a test can make a field missing, `None` or not text, the way a
        malformed mail or a reader bug would."""
        original = self.rig.reader.get_thread

        def get_thread(user_id: str, thread_id: str) -> dict[str, Any]:
            doc = original(user_id, thread_id)
            edit(doc["messages"][-1])
            return doc

        self.rig.reader.get_thread = get_thread  # type: ignore[method-assign]

    def entries(self) -> list[dict]:
        return self.outbox.all()

    def policy_events(self) -> list[dict]:
        return [p for p in self.events.parts if p.get("type") == "policy.applied"]

    def preview(self, thread: Thread, body: str) -> tuple[Any, Any, Any]:
        """(Preview, DraftContext, DraftResult) of a ready draft of `body` that answers the thread's last inbound."""
        ctx, result = answering(thread, body)
        return self.ap.preview(USER, ctx, result), ctx, result


def make_l2(kind: str) -> L2Rig:
    assert kind in KINDS
    if kind == "legacy_level_hint":
        bench = make_bench("L2", contacts=(DAVID, SARAH))
        return L2Rig(kind, bench.rig, bench.ap, bench.outbox, bench.events, bench.rig.clock, bench.new_autopilot)
    w4 = make_w4()
    return L2Rig(kind, w4.rig, w4.ap, w4.outbox, w4.events, w4.clock, w4.new_ap)


def answering(thread: Thread, body: str, *, in_reply_to: str | None = None, **ready_kw: Any) -> tuple[Any, Any]:
    """(DraftContext, ready DraftResult) whose draft answers the thread's last inbound message: its `in_reply_to` and
    `references` are that message's Message-ID, as the Drafter's envelope sets them. `in_reply_to` overrides it."""
    ctx = context(thread, instruction=INSTRUCTION, instruction_id=fresh_ulid())  # policy.applied needs a ULID
    result = ready(thread, body, instruction_id=ctx.instruction_id, **ready_kw)
    target = message_id_header(thread.last_inbound(MAILBOX).message_id) if in_reply_to is None else in_reply_to
    draft = dataclasses.replace(result.draft, in_reply_to=target, references=target)
    return ctx, dataclasses.replace(result, draft=draft)


def earlier_message(body: str, *, sender: str = DAVID, message_id: str = "m-earlier") -> Msg:
    """A message that came before the thread's last one."""
    return Msg(
        message_id=message_id,
        sender=sender,
        subject=CLEAN_SUBJECT,
        body=body,
        headers={"Authentication-Results": AUTH_PASS},
    )


def assert_waits_for_a_person(h: L2Rig, p: Any, ctx: Any) -> None:
    """The card is not on the undo window and no send can ride it: level L1, no window, no policy.applied, no outbox
    entry now or later however long the clock runs. A person's Send is still offered."""
    assert p.level == "L1", f"the card rode {p.level}: a risky inbound message may never get the undo window"
    assert p.undo_window_s == 0 and p.scheduled_at is None
    assert "send" in p.options and "cancel" in p.options, "the card still waits for its owner's Send"
    assert h.entries() == [], "no outbox entry may exist before a person taps Send"
    assert h.policy_events() == [], "no L2 policy.applied for a card that waits for a person"
    assert h.ap.policy_applied(USER, p.card_id) is None
    h.clock.advance(10 * 60)
    h.outbox.dispatch_due()
    assert h.outbox.sent == [] and h.entries() == [], "nothing may be sent silently, however long the clock runs"
    assert h.new_ap().policy_applied(USER, p.card_id) is None  # a second instance agrees (card is recorded)
    if h.kind == "policy_port":  # production mode: the gate asks a person (OB-01)
        assert h.ap.approval_requested(USER, p.card_id) is not None, "the L1 card must request the owner's approval"


def assert_rides_l2(h: L2Rig, p: Any) -> None:
    """The card is on the 60 s undo window as a scheduled entry authorised by policy."""
    assert p.level == "L2" and p.undo_window_s == 60 and p.scheduled_at is not None
    (entry,) = h.entries()
    assert entry["state"] == "scheduled" and entry["undo_window_s"] == 60
    assert entry["authz"]["by"] == "policy"
    if h.kind == "policy_port":
        assert len(h.policy_events()) == 1
