"""Test doubles and helpers for CHN-GATE-E (FR-CHN-11, ADR-0025 "DraftContext thread participants"). The API they
drive is pinned in API_CHN_GATE_E.md. Nothing here is production logic.

Threads are built with the real `Rig.thread` of `_chn10_lib`: `earlier` messages first, then the inbound message the
draft answers (its Message-ID is the draft's `in_reply_to`). `Mail` adds Gmail's `labelIds` to a message: "SENT" is the
only label that makes a message the user's own (BQ-223); a From header alone is sender-controlled. All addresses are
fictional `.example` domains; the display names are made up.
"""

from __future__ import annotations

import importlib
import logging
import secrets
from dataclasses import replace
from typing import Any

from _chn10_lib import Msg, Thread
from _chn11_lib import MAILBOX, USER, Bench, Mail, autopilot_module, pair
from _chn11_lib import make_bench as _make_bench

__all__ = ["MAILBOX", "USER", "Mail", "autopilot_module", "make_bench", "pair"]

OWN = f"Sarah Chen <{MAILBOX}>"  # the mailbox owner's From header on mail the user's client wrote
LOGGER_NAMES = ("", "tilo_channels", "tilo_channels.autopilot", "tilo_channels.participants")


def make_bench(level: str = "L2", contacts: tuple[str, ...] = ()) -> Bench:
    """The FR-CHN-11 bench without the owner's own SENT note the other benches start every thread with: here a
    thread holds only what a test puts in it, so nothing vouches for a name by accident."""
    bench = _make_bench(level, contacts)
    bench.rig.own_mail = ()
    return bench


def participants_module() -> Any:
    """Imported at call time so a missing module fails the test, not collection."""
    return importlib.import_module("tilo_channels.participants")


def t3_module() -> Any:
    return importlib.import_module("tilo_channels.autopilot_t3")


def sent(
    to: tuple[str, ...] = (),
    cc: tuple[str, ...] = (),
    *,
    sender: str = OWN,
    labels: tuple[str, ...] = ("SENT",),
    body: str = "Looping them in.",
) -> Mail:
    """A message the user's own client wrote: From the mailbox, with Gmail's SENT label (unless `labels` says so)."""
    return Mail(
        "m-" + secrets.token_hex(5), sender, "Engine tune-up", body, to=list(to), cc=list(cc), labels=list(labels)
    )


def inbound(
    sender: str, *, to: tuple[str, ...] = (MAILBOX,), cc: tuple[str, ...] = (), body: str = "Adding a colleague."
) -> Mail:
    return Mail("m-" + secrets.token_hex(5), sender, "Engine tune-up", body, to=list(to), cc=list(cc), labels=["INBOX"])


def thread_of(
    bench: Bench, *earlier: Msg, sender: str = "Dana Fox <dana.fox@harriercharters.example>", **kw: Any
) -> Thread:
    """A thread whose answered (last, inbound, clean, DMARC-passing) message is from `sender`, after `earlier`."""
    kw.setdefault("to", (MAILBOX,))
    kw.setdefault("cc", ())
    thread, _ = bench.rig.thread(earlier=earlier, sender=sender, **kw)
    return thread


def card(bench: Bench, thread: Thread, body: str, to: tuple[str, ...], cc: tuple[str, ...] = (), **kw: Any) -> Any:
    return bench.ap.preview(USER, *pair(thread, body, to=to, cc=cc, **kw))


def is_t3_unlisted(card_: Any) -> bool:
    """Held for a person: T3 because of the content gate, no window, nothing scheduled."""
    return (
        card_.tier == "T3"
        and "money_or_legal" in card_.modifiers
        and (card_.level, card_.undo_window_s, card_.outbox_id) == ("L1", 0, None)
    )


def rides_l2(card_: Any) -> bool:
    return card_.tier == "T2" and card_.modifiers == () and (card_.level, card_.undo_window_s) == ("L2", 60)


def listed_words() -> frozenset[str]:
    """The allowlist words: `_WORDS` with the greeting and sign-off words (ADR-0025 decision 5)."""
    module = t3_module()
    return frozenset(module._WORDS) | frozenset(module._GREETING) | frozenset(module._SIGN_OFF)


def names_by_address(participants: Any) -> dict[str, frozenset[str]]:
    return {p.address: p.names for p in participants}


def with_participants(ctx: Any, *participants: Any) -> Any:
    return replace(ctx, participants=tuple(participants))


class RaisingReader:
    """A thread reader that always fails (the Gmail read is down)."""

    def __init__(self) -> None:
        self.calls = 0

    def get_thread(self, user_id: str, thread_id: str) -> dict:
        self.calls += 1
        raise ConnectionError("gmail read is down")


class RecordingHandler(logging.Handler):
    """Every record of every logger at every level, formatted with its arguments."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(record.getMessage() + " " + " ".join(str(a) for a in (record.args or ())))
        if record.exc_info:
            self.lines.append(str(record.exc_info[1]))

    def text(self) -> str:
        return "\n".join(self.lines)
