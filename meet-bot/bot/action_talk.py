"""ADR-0042 amendment 1 (owner decision 21 Oct, BQ-MTG-ACTIONS-1): what Tilo says around a meeting action.

Pure: the model proposes one of three actions; Tilo reads it back in its own fixed words; only the same speaker's "yes"
(within `CONFIRM_S`) sends it; and Tilo reports only what tilo-api confirmed. The model never writes the read-back or the
result, so it can never claim an action that did not happen. No I/O, no model."""

from __future__ import annotations

import os
import re
import secrets
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

ACTIONS = ("create_pin", "add_agenda_item", "create_meeting")
CONFIRM_S = 45.0  # a yes must follow the read-back this soon
ANSWER_ECHO_S = 8.0  # live 21 Oct: one spoken yes arrives as a partial caption, then its final one
FAILED_AGAIN_LINE = "That still didn't go through, so nothing was changed."  # a second failure in a row, reworded
_YES = re.compile(
    r"^\s*(yes|yeah|yep|yup|sure|ok|okay|go ahead|do it|please do|correct|confirm|that's right|right|yes please)\b",
    re.I,
)
_NO = re.compile(r"^\s*(no|nope|cancel|don't|do not|stop|never mind|nevermind|wait)\b", re.I)

ACTIONS_TEXT = (
    "You can do exactly three things for the person speaking, and only when they clearly ask: create_pin "
    '{"title", optional "body", "board": "personal" or "team"}, add_agenda_item {"title", optional "minutes"} to this '
    'meeting\'s agenda, and create_meeting {"title", "start" (ISO 8601 with time zone, resolved from now_local), '
    '"minutes"}. To do one, reply {"reply": null, "action": {"name": ..., "args": {...}}} and nothing else; Tilo reads '
    "it back and acts only after the person says yes. Never say you have done anything, and you cannot send messages, "
    "emails or invites. "
)


def zone() -> Any:
    """The time zone meetings are spoken in (`TILO_MEETING_TZ`, default Asia/Kolkata), or UTC if it cannot be read."""
    try:
        return ZoneInfo(os.environ.get("TILO_MEETING_TZ", "Asia/Kolkata"))
    except Exception:
        return UTC


def now_local() -> str:
    return datetime.now(zone()).isoformat(timespec="minutes")


@dataclass
class PendingAction:
    speaker: str  # as captioned (for matching the yes)
    api_speaker: str | None  # what tilo-api matches; None = the meeting owner (one-on-one)
    name: str
    args: dict[str, Any]
    at: float = field(default_factory=time.monotonic)
    key: str = field(default_factory=lambda: secrets.token_urlsafe(12))


def _title(value: Any) -> str | None:
    text = " ".join(str(value).split()) if isinstance(value, str) else ""
    return text[:120] if text else None


def proposal(raw: Any, speaker: str, *, one_on_one: bool) -> PendingAction | None:
    """The model's `action` object as a PendingAction, or None when it is not one of the three, well formed."""
    if not isinstance(raw, dict) or raw.get("name") not in ACTIONS or not isinstance(raw.get("args"), dict):
        return None
    name, args = raw["name"], raw["args"]
    title = _title(args.get("title"))
    if title is None:
        return None
    clean: dict[str, Any] = {"title": title}
    if name == "create_pin":
        clean["board"] = "team" if args.get("board") == "team" else "personal"
        body = _title(args.get("body"))
        if body:
            clean["body"] = body
    elif name == "add_agenda_item":
        if isinstance(args.get("minutes"), int) and 1 <= args["minutes"] <= 240:
            clean["minutes"] = args["minutes"]
    else:
        start, minutes = args.get("start"), args.get("minutes")
        try:
            when = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
        except ValueError:
            return None
        if when.tzinfo is None or not isinstance(minutes, int) or not 5 <= minutes <= 480:
            return None
        clean.update(start=when.isoformat(), minutes=minutes)
    who = speaker.removesuffix(" (chat)").strip()
    return PendingAction(speaker=who, api_speaker=None if one_on_one else who, name=name, args=clean)


def _when(start: str) -> str:
    when = datetime.fromisoformat(start.replace("Z", "+00:00")).astimezone(zone())
    return when.strftime("%a %d %b at %I:%M %p").replace(" 0", " ")


def readback(action: PendingAction) -> str:
    title = action.args["title"]
    if action.name == "create_pin":
        return f'Pin "{title}" to your {action.args["board"]} board?'
    if action.name == "add_agenda_item":
        return f'Add "{title}" to this meeting\'s agenda?'
    return (
        f'Schedule "{title}" on {_when(action.args["start"])} for {action.args["minutes"]} minutes? I would join and '
        "take notes, so say yes only if you have the right to record it."
    )


def _who(speaker: str) -> str:
    return speaker.removesuffix(" (chat)").strip().lower()


def answer(action: PendingAction | None, speaker: str, text: str, *, one_on_one: bool) -> str | None:
    """'yes', 'no' or None for one heard line: only the person Tilo asked (or anyone one-on-one), only in time."""
    if action is None or time.monotonic() - action.at > CONFIRM_S:
        return None
    if not one_on_one and _who(speaker) != action.speaker.lower():
        return None
    if _NO.match(text):
        return "no"
    return "yes" if _YES.match(text) else None


@dataclass(frozen=True)
class Answered:
    """A yes or no Tilo took, from whom and when."""

    speaker: str
    at: float = field(default_factory=time.monotonic)


def repeats_answer(last: Answered | None, speaker: str, text: str, *, one_on_one: bool) -> bool:
    """Another caption of a yes or no Tilo already took (the live partial, then the final): never a new question."""
    if last is None or time.monotonic() - last.at > ANSWER_ECHO_S or not (_YES.match(text) or _NO.match(text)):
        return False
    return one_on_one or _who(speaker) == last.speaker.lower()


def same_request(a: PendingAction | None, b: PendingAction) -> bool:
    """The same action and arguments, still waiting for its yes: one read-back, whichever caption asked first."""
    if a is None or time.monotonic() - a.at > CONFIRM_S or a.name != b.name:
        return False
    return {k: str(v).lower() for k, v in a.args.items()} == {k: str(v).lower() for k, v in b.args.items()}


def request_args(action: PendingAction) -> dict[str, Any]:
    """The args tilo-api takes. A meeting carries the spoken recording attestation: the yes to the read-back."""
    args = dict(action.args)
    if action.name == "create_meeting":
        args["recording_attested"] = True
    return args


def result_line(action: PendingAction, ok: bool, outcome: str, info: dict[str, Any]) -> str:
    """What Tilo says after tilo-api answered: success only on its confirmation."""
    if ok:
        if action.name == "create_pin":
            return f"Done, I pinned it to your {info.get('board', action.args['board'])} board."
        if action.name == "add_agenda_item":
            return "Done, it's on this meeting's agenda."
        start = info.get("start") or action.args["start"]
        return f"Done, it's on your Agenda for {_when(start)}."
    return {
        "unknown_person": "I can't find you in Tilo, so I didn't change anything.",
        "ambiguous_person": "More than one person in Tilo has that name, so I didn't change anything.",
        "cap_reached": "I've made the five changes I can in one call, so I didn't do that one.",
        "team_unclear": "I couldn't tell which team board to use, so I didn't add it.",
        "agenda_full": "This meeting's agenda is full, so I didn't add it.",
    }.get(outcome, "I couldn't do that just now, so nothing was changed.")
