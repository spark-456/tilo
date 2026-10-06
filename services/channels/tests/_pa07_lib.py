"""Test doubles for FR-PA-07 ("Draft reply" on a plate mail item). The API they drive is pinned in API_FR_PA_07.md.

Nothing here is production logic. The send line under test is the real one end to end (the FR-CHN-13 / CHN-WIRE-1
line): the real FR-CHN-10 `Drafter` over a scripted model, the real FR-CHN-11 `Autopilot` in production mode, the real
`tilo_connectors.Outbox` and `GmailAdapter`, the REAL `tilo_policy.check_entry`; Gmail itself is `FakeGmailApi`. Next to
it sits a real FR-CHN-09 `Triage` over its own fakes, which is what puts a message on the plate as "needs a reply".

The only thing these tests need from the ticket is `tilo_channels.plate_reply.PlateReply`, imported at call time so a
missing module fails the test that uses it, not the collection of the file.

No network, no paid call, no real mail. Addresses are fictional `.example` domains.
"""

from __future__ import annotations

import functools
import importlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import _chn09_lib as triage_lib
from _chn10_lib import INJECTION_MARKER, OTHER_USER, Msg, answer, message_id_header
from _chn11_lib import DAVID, MAILBOX
from _chn13_lib import USER, Line
from _chn_wire1_lib import make_wire_line

__all__ = ["DAVID", "INJECTION_MARKER", "MAILBOX", "OTHER_USER", "USER", "Plate", "make_plate", "needs_plate"]

# A reply that passes the FR-CHN-10 checker with NO instruction (it adds no number, date, link or commitment word that
# the thread, which says "this Friday afternoon", does not already hold) and is plain scheduling talk, so
# `t3_content_signal` finds nothing: a T2 draft. (Words off the scheduling list, even "Marcus", make a draft T3.)
PLAIN_REPLY = "Hi David,\n\nFriday afternoon works for us. See you then.\n\nBest,\nSarah"
PLAIN_REPLY_V2 = "Hi David,\n\nFriday works for us. See you then.\n\nBest,\nSarah"
# Passes the checker too, but `t3_content_signal` sees legal and commitment words: a T3 draft (PRD 10.4).
LEGAL_REPLY = "Hi David,\n\nThanks for your note. We will review the contract terms and reply soon.\n\nBest,\nSarah"
# Invents a number and a commitment the person never gave: FR-CHN-10 must refuse it ("needs_you").
INVENTED_REPLY = "Hi David,\n\nFriday afternoon works for us, and we will give you a 20% discount.\n\nBest,\nSarah"

CATEGORIES = triage_lib.triage_module().CATEGORIES


def plate_module() -> Any:
    """Imported at call time so a missing module fails the test, not collection."""
    return importlib.import_module("tilo_channels.plate_reply")


def needs_plate(test: Callable[..., Any]) -> Callable[..., Any]:
    """A missing `tilo_channels.plate_reply` fails once, before Hypothesis generates or shrinks anything."""

    @functools.wraps(test)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        plate_module()
        return test(*args, **kwargs)

    return wrapper


@dataclass
class Plate:
    """One person's plate wiring: the send `line` plus the triage rig `tr` that holds her mail as needing a reply.
    `build()` gives a `PlateReply` over the same stores (call it again for a restart or a second instance)."""

    line: Line
    tr: Any  # _chn09_lib.Rig
    mailbox: str | None = MAILBOX
    reply: Any = None

    def build(self, *, autopilot: Any = None, drafter: Any = None) -> Any:
        return plate_module().PlateReply(
            triage=self.tr.results,
            mail=self.tr.reader,
            drafter=drafter or self.line.bench.rig.svc,
            autopilot=autopilot or self.line.ap,
            mailbox=lambda user_id: self.mailbox,
        )

    def new_instance(self) -> Any:
        """Another instance over the same stores (a second Cloud Run instance): own Drafter, own Autopilot."""
        return self.build(autopilot=self.line.bench.new_autopilot(), drafter=self.line.bench.rig.new_drafter())

    def mail(
        self,
        category: str = "needs_reply",
        *,
        reply: str | None = PLAIN_REPLY,
        extra_answers: Sequence[str] = (),
        earlier: Sequence[Msg] = (),
        later: Sequence[Msg] = (),
        triage_user: str = USER,
        corrected: str | None = None,
        triage_body: str | None = None,
        **thread_kw: Any,
    ) -> tuple[Any, str]:
        """A mail the triage store holds for `triage_user` under `category`, answering the last message of a thread
        that the drafter's reader and Gmail hold for USER. `reply` is what the scripted model drafts (and
        `extra_answers` the redrafts after it). `later` messages arrive in the thread after the plate mail (the
        drafter's reader sees them; the triage store holds only the plate mail). The triage copy carries its own
        Message-ID header, as the thread's copy does. Returns (thread, mail id); the mail id is what a plate row's
        `ref` carries."""
        answers = [answer(reply), *map(answer, extra_answers)] if reply is not None else []
        thread = self.line.thread(answers=answers, earlier=earlier, **thread_kw)
        last = thread.messages[-1]
        thread.messages.extend(later)
        extra: dict[str, Any] = {"headers": {"Message-ID": message_id_header(last.message_id)}}
        extra |= {"body": triage_body} if triage_body is not None else {}
        mail, _ = self.tr.mail(
            sender=last.sender,
            message_id=last.message_id,
            user_id=triage_user,
            reply=triage_lib.answer(category),
            **extra,
        )
        mail.thread_id = thread.thread_id
        self.tr.svc.triage(triage_user, last.message_id)
        if corrected is not None:
            self.tr.svc.correct(triage_user, last.message_id, category=corrected)
        return thread, last.message_id

    # --- what happened, read from the doubles --------------------------------------------------------------------

    def model_calls(self) -> int:
        return len(self.line.bench.rig.model.requests)

    def events(self) -> list[dict[str, Any]]:
        """Everything the drafter and the autopilot emitted."""
        return [*self.line.bench.rig.events.parts, *self.line.bench.events.parts]

    def of_type(self, event_type: str) -> list[dict[str, Any]]:
        return [p for p in self.events() if p.get("type") == event_type]

    def untouched(self) -> bool:
        """Nothing was read, drafted, stored, emitted or queued."""
        rig = self.line.bench.rig
        return (
            rig.model.requests == []
            and rig.safety.texts == []
            and rig.reader.calls == []
            and rig.drafts.dump() == "{}"
            and self.line.bench.cards.dump() == "{}"
            and self.events() == []
            and self.line.entries() == []
            and self.line.api.sent == []
        )


def make_plate(level: str = "L1", contacts: Sequence[str] = ()) -> Plate:
    """`level` is what the autonomy policy port answers for `send_email`; it is deliberately permissive at "L2"."""
    line = make_wire_line(level, tuple(contacts))
    plate = Plate(line=line, tr=triage_lib.make_rig())
    plate.reply = plate.build()
    return plate
