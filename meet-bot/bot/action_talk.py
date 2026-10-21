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
    '{"title", optional "body", "board": "personal" or "team"} (the board they named, now or in recent_exchanges, '
    'e.g. your own question "what should I pin to the team board?"; "personal" only if no board was named), '
    'add_agenda_item {"title", optional "minutes"} to this '
    'meeting\'s agenda, and create_meeting {"title", "start" (ISO 8601 with time zone, resolved from now_local), '
    '"minutes"}. To do one, reply {"reply": null, "action": {"name": ..., "args": {...}}} and nothing else; Tilo reads '
    "it back and acts only after the person says yes. Never say you have done anything, and you cannot send messages, "
    "emails or invites. To find a free time for a meeting, reply with the action find_times "
    '{"minutes", optional "days" (1-14), "with_team": true when their teammates should be free too}; Tilo checks the '
    'calendars and offers times. offered_times, when given, are the times Tilo offered last, in order: "the second '
    'one" is offered_times[1]; to book one, propose create_meeting with that start. '
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
        # Live 21 Oct the model wrote "Team"/"team board" and Tilo read back "your personal board": its value, normalised.
        board = " ".join(str(args.get("board") or "").lower().split()).removeprefix("the ").removesuffix(" board")
        clean["board"] = "team" if board == "team" else "personal"
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


def _when(start: str, zone_name: str | None = None) -> str:
    try:
        tz = ZoneInfo(zone_name) if zone_name else zone()
    except Exception:
        tz = zone()
    when = datetime.fromisoformat(start.replace("Z", "+00:00")).astimezone(tz)
    return when.strftime("%a %d %b at %I:%M %p").replace(" 0", " ")


# -- free times (find_times: a read, so no read-back; the booking is an ordinary create_meeting) ----------------------
CHECKING_LINE = "Let me check the calendars."


def times_request(raw: Any) -> dict[str, Any] | None:
    """The model's find_times as tilo-api's arguments (30 minutes over the next 7 days unless it said otherwise)."""
    if not isinstance(raw, dict) or raw.get("name") != "find_times":
        return None
    args = raw.get("args") if isinstance(raw.get("args"), dict) else {}

    def number(key: str, low: int, high: int, default: int) -> int:
        value = args.get(key)
        return value if isinstance(value, int) and not isinstance(value, bool) and low <= value <= high else default

    return {
        "minutes": number("minutes", 15, 240, 30),
        "days": number("days", 1, 14, 7),
        "with_team": args.get("with_team") is True,
    }


def time_label(start: str, zone_name: str | None) -> str:
    return _when(start, zone_name)


def times_line(result: dict[str, Any] | None, request: dict[str, Any]) -> str:
    """What Tilo says with tilo-api's answer: the offered starts, and plainly what it could not check."""
    if result is None:
        return "I couldn't check calendars just now."
    slots = [s for s in result.get("slots") or [] if isinstance(s, str)]
    if not slots:
        return f"I couldn't find a free {request['minutes']}-minute slot in the next {request['days']} days."
    labels = [_when(s, result.get("zone")) for s in slots]
    text = "I can do " + (", ".join(labels[:-1]) + " or " + labels[-1] if len(labels) > 1 else labels[0]) + "."
    if result.get("google") == "not_connected":
        text += " Your Google Calendar isn't connected to Tilo, so I only checked your Tilo calendar."
    elif result.get("google") != "ok":
        text += " I couldn't read your Google Calendar just now, so I only checked your Tilo calendar."
    if request.get("with_team"):
        text += (
            " For your teammates I can only see their Tilo calendars."
            if result.get("teammates")
            else " You're not on a team in Tilo, so I only checked yours."
        )
    return text + " Which one should I schedule?"


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


def done_line(action: PendingAction) -> str:
    """An action tilo-api confirmed this call, in fixed words: the only way Tilo ever says it did something."""
    title = action.args["title"]
    if action.name == "create_pin":
        return f'Yes, "{title}" is pinned to your {action.args["board"]} board.'
    if action.name == "add_agenda_item":
        return f'Yes, "{title}" is on this meeting\'s agenda.'
    return f'Yes, "{title}" is on your Agenda for {_when(action.args["start"])}.'


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
        "no_team": "You're not on a team in Tilo yet, so there's no team board. I can pin it to your personal board.",
        "agenda_full": "This meeting's agenda is full, so I didn't add it.",
    }.get(outcome, "I couldn't do that just now, so nothing was changed.")
