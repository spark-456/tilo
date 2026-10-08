"""tilo_channels.reschedule_intent — rules-first "move this meeting" detector on inbound mail (FR-CAL-07 b, ticket 2).

Pure and deterministic: no model, no network, no clock, no logging, no I/O except reading `config/move_request.yaml`
once. Mail is untrusted data. The function never executes or follows anything in it and returns only closed,
bounded fields: a kind, a few hints computed by code (a resolved day, clock times, a duration) and cleaned ids.
It does not read the sender and decides nothing about who may reschedule; that is the draft and send tickets, and T3.
Undecided mail is `None` (there is no model fallback in this ticket).

Cost on hostile mail: the subject is cut to 500 and the body to 8,000 raw characters before one NFKC pass; quoted and
forwarded lines are dropped, then only the first 4,096 characters are scanned. Every regex here is linear.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from functools import cache
from pathlib import Path
from typing import Any

import yaml
from tilo_people.dates import resolve_due
from tilo_people.errors import PeopleInputError
from tilo_people.text import clean_line

CONFIG_PATH = Path(__file__).resolve().parents[4] / "config" / "move_request.yaml"
KINDS = ("move", "cancel_and_rebook", "ask_availability")
RAW_HEADING, RAW_MESSAGE, SCAN_CHARS, HINT_HEADING = 500, 8_000, 4_096, 120
MAX_PHRASES, MAX_PHRASE_CHARS, SUPPRESS_WINDOW, DAY_TRIES, SENTENCES_AHEAD = 200, 60, 4, 40, 4

_TOKEN = re.compile(r"[0-9]+(?:-[0-9]+)+|[a-z0-9']+(?:[.:][0-9]+)*")
_SPLIT = re.compile(r"(?<=[.!?;:,])\s+|\n\s*\n")
_REPLY = re.compile(r"\s*([A-Za-z]{1,3})\s*:\s*")
_ID = re.compile(r"[A-Za-z0-9@._=+-]{1,128}")
_CLOCK = r" (?:(noon)|([0-9]{1,2})(?::([0-9]{2}))?(?: ?(am|pm))?)(?= |$)"
_UNITS = {"minute": 1, "minutes": 1, "min": 1, "mins": 1, "hour": 60, "hours": 60, "hr": 60, "hrs": 60}
_LISTS = (
    "move_phrases",
    "cancel_and_rebook_phrases",
    "availability_phrases",
    "suppress_before",
    "reply_prefixes",
    "day_lead_ins",
    "earliest_markers",
    "latest_markers",
    "shift_words",
)
_RAW_LISTS = ("quote_markers", "quote_line_starts", "quote_line_ends")


def _fold(value: Any, cap: int) -> str:
    """The first `cap` characters, NFKC and case-folded, apostrophes unified, format characters removed."""
    raw = value[:cap] if isinstance(value, str) else ""
    folded = unicodedata.normalize("NFKC", raw).casefold().translate({0x2019: "'", 0x2018: "'", 0x2BC: "'"})
    return "".join(c for c in folded if unicodedata.category(c) != "Cf")


def _words(value: str) -> str:
    return " ".join(_TOKEN.findall(value))


def _strings(raw: Any, key: str) -> list[str]:
    found = raw.get(key) if isinstance(raw, Mapping) else None
    ok = isinstance(found, list) and len(found) <= MAX_PHRASES
    return [s for s in found if isinstance(s, str) and 0 < len(s) <= MAX_PHRASE_CHARS] if ok and found else []


def _marker_re(markers: tuple[str, ...]) -> re.Pattern[str] | None:
    return re.compile("(?:^| )(?:" + "|".join(map(re.escape, markers)) + ")" + _CLOCK) if markers else None


@dataclass(frozen=True)
class MoveConfig:
    """Word lists, normalised once. Phrase lists are space-padded token strings; a bad list is an empty list."""

    move_phrases: tuple[str, ...] = ()
    cancel_and_rebook_phrases: tuple[str, ...] = ()
    availability_phrases: tuple[str, ...] = ()
    suppress_before: tuple[str, ...] = ()
    reply_prefixes: tuple[str, ...] = ()
    day_lead_ins: tuple[str, ...] = ()
    earliest_markers: tuple[str, ...] = ()
    latest_markers: tuple[str, ...] = ()
    shift_words: tuple[str, ...] = ()
    quote_markers: tuple[str, ...] = ()
    quote_line_starts: tuple[str, ...] = ()
    quote_line_ends: tuple[str, ...] = ()
    earliest_re: re.Pattern[str] | None = field(default=None, compare=False, repr=False)
    latest_re: re.Pattern[str] | None = field(default=None, compare=False, repr=False)

    @classmethod
    def from_mapping(cls, raw: Any) -> MoveConfig:
        lists = {k: tuple(w for s in _strings(raw, k) if (w := _words(_fold(s, MAX_PHRASE_CHARS)))) for k in _LISTS}
        lists.update({k: tuple(_fold(s, MAX_PHRASE_CHARS) for s in _strings(raw, k)) for k in _RAW_LISTS})
        padded = {k: tuple(f" {w} " for w in lists[k]) for k in _LISTS[:4]}
        both = {**lists, **padded}
        return cls(
            **both, earliest_re=_marker_re(lists["earliest_markers"]), latest_re=_marker_re(lists["latest_markers"])
        )


def load_config(path: Path = CONFIG_PATH) -> MoveConfig:
    """The word lists in `path`; a missing or unreadable file is an empty config (no mail is a move request)."""
    try:
        return MoveConfig.from_mapping(yaml.safe_load(path.read_text(encoding="utf-8")))
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return MoveConfig()


@cache
def _default() -> MoveConfig:
    return load_config()


@dataclass(frozen=True)
class MoveRequest:
    kind: str  # one of KINDS
    constraint: dict[str, Any]  # day (YYYY-MM-DD), earliest_time / latest_time (HH:MM), duration_min: all from code
    ref_hints: dict[str, str | None]  # subject (cleaned, bounded), ics_uid, thread_id (strict alphabet)

    def as_dict(self) -> dict[str, Any]:
        return {
            "intent": "move_meeting",
            "kind": self.kind,
            "constraint": dict(self.constraint),
            "ref_hints": dict(self.ref_hints),
        }


def _unquoted(message: str, cfg: MoveConfig) -> str:
    """The lines before the first quote marker or attribution line, without `>` lines, cut to SCAN_CHARS."""
    kept = []
    for raw_line in message.splitlines():
        line = raw_line.strip()
        if line.startswith(">"):
            continue
        attribution = any(line.startswith(a) for a in cfg.quote_line_starts) and any(
            line.endswith(e) for e in cfg.quote_line_ends
        )
        if attribution or any(line.startswith(m) for m in cfg.quote_markers):
            break
        kept.append(raw_line)
    return "\n".join(kept)[:SCAN_CHARS]


def _strip_reply(heading: str, cfg: MoveConfig) -> tuple[str, bool]:
    replied = False
    for _ in range(5):
        found = _REPLY.match(heading)
        if not found or _words(found[1].casefold()) not in cfg.reply_prefixes:
            break
        heading, replied = heading[found.end() :], True
    return heading, replied


def _asks(flat: str, phrases: tuple[str, ...], suppress: tuple[str, ...]) -> bool:
    """A phrase in the padded sentence `flat` with no suppressing word in the four words before it."""
    for phrase in phrases:
        at = flat.find(phrase)
        while at != -1:
            before = " " + " ".join(flat[:at].split()[-SUPPRESS_WINDOW:]) + " "
            if not any(s in before for s in suppress):
                return True
            at = flat.find(phrase, at + 1)
    return False


def _mail_time(value: Any) -> str | None:
    """The mail's Date header as the contracts' UTC timestamp, or None."""
    if not isinstance(value, str) or len(value) > 64:
        return None
    try:
        when = datetime.fromisoformat(value)
    except ValueError:
        try:
            when = parsedate_to_datetime(value)
        except (TypeError, ValueError, IndexError, OverflowError):
            return None
    try:
        return when.replace(tzinfo=when.tzinfo or UTC).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    except (OverflowError, ValueError):
        return None


def _day(window: list[list[str]], cfg: MoveConfig, sent_at: str | None, zone: str) -> str | None:
    """The first phrase after a lead-in word (or opening a sentence) that `resolve_due` resolves; at most DAY_TRIES."""
    tries = 0
    for sentence in window if sent_at else ():
        for i in range(len(sentence)):
            if i and sentence[i - 1] not in cfg.day_lead_ins:
                continue
            for n in range(min(4, len(sentence) - i), 0, -1):
                tries += 1
                if tries > DAY_TRIES:
                    return None
                try:
                    found = resolve_due(" ".join(sentence[i : i + n]), meeting_at=sent_at, time_zone=zone)
                except PeopleInputError:
                    return None
                if found.reason == "resolved":
                    return found.due
    return None


def _clock(pattern: re.Pattern[str] | None, flat: str) -> str | None:
    found = pattern.search(flat) if pattern else None
    if not found:
        return None
    if found[1]:
        return "12:00"
    hour, minute, meridiem = int(found[2]), int(found[3] or 0), found[4]
    if meridiem is None and found[3] is None:
        return None  # a bare number is not a time
    if meridiem:
        if not 1 <= hour <= 12:
            return None
        hour = hour % 12 + (12 if meridiem == "pm" else 0)
    return f"{hour:02d}:{minute:02d}" if hour < 24 and minute < 60 else None


def _duration(window: list[list[str]], cfg: MoveConfig) -> int | None:
    for sentence in window:
        for i, word in enumerate(sentence[:-1]):
            around = sentence[i - 1 : i] + sentence[i + 2 : i + 3]
            if (
                word.isdigit()
                and len(word) <= 3
                and sentence[i + 1] in _UNITS
                and not set(around) & set(cfg.shift_words)
            ):
                minutes = int(word) * _UNITS[sentence[i + 1]]
                if 5 <= minutes <= 480:
                    return minutes
    return None


def _constraint(window: list[list[str]], cfg: MoveConfig, sent_at: str | None, zone: str) -> dict[str, Any]:
    flat = " " + " ".join(" ".join(s) for s in window) + " "
    earliest, latest = _clock(cfg.earliest_re, flat), _clock(cfg.latest_re, flat)
    if earliest and latest and earliest >= latest:
        earliest = latest = None
    found = {
        "day": _day(window, cfg, sent_at, zone),
        "earliest_time": earliest,
        "latest_time": latest,
        "duration_min": _duration(window, cfg),
    }
    return {k: v for k, v in found.items() if v is not None}


def _ref_hints(mail: Mapping[str, Any], heading: str) -> dict[str, str | None]:
    def ident(value: Any) -> str | None:
        return value if isinstance(value, str) and _ID.fullmatch(value) else None

    cleaned = " ".join(clean_line(heading).split())[:HINT_HEADING]
    return {
        "subject": cleaned or None,
        "ics_uid": ident(mail.get("ics_uid")),
        "thread_id": ident(mail.get("thread_id")),
    }


def detect_move_request(mail: Any, *, config: MoveConfig | None = None, time_zone: str = "UTC") -> MoveRequest | None:
    """A MoveRequest when the mail asks to move a meeting, else None. `mail` is the triage module's mail mapping
    (subject, body, date, thread_id; optional ics_uid). `time_zone` is the person's zone for relative days."""
    if not isinstance(mail, Mapping):
        return None
    cfg = config if config is not None else _default()
    heading_raw = mail.get("subject")
    heading, replied = _strip_reply(heading_raw[:RAW_HEADING] if isinstance(heading_raw, str) else "", cfg)
    pieces = ([] if replied else [_fold(heading, RAW_HEADING)]) + [_unquoted(_fold(mail.get("body"), RAW_MESSAGE), cfg)]
    sentences = [t for piece in pieces for part in _SPLIT.split(piece) if (t := _TOKEN.findall(part))]
    first, kinds, available = None, set(), False
    for i, sentence in enumerate(sentences):
        flat = " " + " ".join(sentence) + " "
        for kind, phrases in (("cancel_and_rebook", cfg.cancel_and_rebook_phrases), ("move", cfg.move_phrases)):
            if _asks(flat, phrases, cfg.suppress_before):
                kinds.add(kind)
                first = i if first is None else first
        available = available or _asks(flat, cfg.availability_phrases, cfg.suppress_before)
    if first is None:
        return None
    kind = "cancel_and_rebook" if "cancel_and_rebook" in kinds else "ask_availability" if available else "move"
    window = sentences[first : first + SENTENCES_AHEAD]
    constraint = _constraint(window, cfg, _mail_time(mail.get("date")), time_zone)
    return MoveRequest(kind, constraint, _ref_hints(mail, heading))
