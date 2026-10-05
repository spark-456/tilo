"""Test doubles and builders for the inbound-aware L2 tests (FR-CHN-11; ADR-0013; issue #298 "CHN-GATE-C", first
bullet; BQ-223). Nothing here is production logic.

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

from _chn10_lib import USER, Msg, Thread, message_id_header
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


def t3_module() -> Any:
    """Imported at call time so a missing function fails the test, not collection."""
    return importlib.import_module("tilo_channels.autopilot_t3")


def inbound_signal(text: str) -> frozenset[str]:
    """The proposed pure function `tilo_channels.autopilot_t3.inbound_signal(text) -> frozenset[str]` (a subset of
    {"money", "legal", "commitment", "obfuscated"}; never "unlisted"). A missing name fails the test."""
    return t3_module().inbound_signal(text)


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

    def thread(self, inbound: str = SCHEDULING_INBOUND, *, earlier: tuple[Msg, ...] = ()) -> Thread:
        thread, _ = self.rig.thread(body=inbound, earlier=earlier)
        return thread

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
    return Msg(message_id=message_id, sender=sender, subject="Engine tune-up scheduling", body=body)


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
