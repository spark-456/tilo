"""tilo_channels.reschedule_reply — a reply draft that proposes free times for a "move this meeting" mail
(FR-CAL-07 b, ticket 3; BQ-CAL07B-5 to -9).

A triaged mail carries a `move_request` label (never authority). This module re-runs the rules-only detector with the
person's time zone, resolves THE person's own accepted calendar entry for it, checks that the sender is a participant
of that entry, and asks `tilo_people.find_free_slots` for up to three times that are free. The times are formatted with
fixed words from `config/reschedule_reply.yaml`; the whole reply body is made by code and handed to the FR-CHN-10
`Drafter` as `fixed_body`, so no model writes or sees a time and the mail text is never echoed. Anything that cannot be
proved (no synced calendar, no matching meeting, a sender who is not a participant) proposes no time; an empty cache is
"not synced", never "free". The card is the FR-CHN-11 card with no instruction, so it is L1 and waits for the person's
own Send through the existing gate and outbox (T3 policy unchanged); nothing is written to the calendar. No logging.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Protocol
from zoneinfo import ZoneInfo

import yaml
from tilo_people.errors import PeopleInputError
from tilo_people.free_slots import find_free_slots, parse_working_window

from .autopilot import DraftContext, Preview
from .drafting import ReplyTargetMoved
from .plate_reply import PlateReply
from .reschedule_intent import MoveRequest, detect_move_request
from .triage import _result as triage_result
from .triage import bare_address

CONFIG_PATH = Path(__file__).resolve().parents[4] / "config" / "reschedule_reply.yaml"
PERSONAL_PATH = Path(__file__).resolve().parents[4] / "config" / "personal.yaml"
MODE, PRESET = "reply", "reschedule"
STATUSES = ("proposed", "not_synced", "unreadable", "no_free_time", "no_meeting", "not_participant")
NOTES = (*STATUSES, "not_configured", "no_time_zone")
NO_DRAFT = ("no_meeting", "not_participant", "not_configured", "no_time_zone")
MAX_SLOTS, MAX_TEXT, MAX_PARTICIPANTS = 3, 2_000, 500
_TOKENS = re.compile(r"[a-z0-9]+")
_INTS = {"lead_minutes": (0, 10_080), "default_duration_min": (5, 480), "max_slots": (1, MAX_SLOTS)}
_INTS |= {"horizon_days": (1, 14), "step_min": (1, 60), "buffer_min": (0, 120)}


class CalendarPort(Protocol):
    """What the caller (tilo-api) provides. The cached entries hold no attendee addresses (PE-13), so participants
    come from a separate read; none exists in production yet."""

    def entries(self, user_id: str) -> Sequence[Mapping[str, Any]] | None: ...  # None or empty: not synced
    def time_zone(self, user_id: str) -> str | None: ...
    def participants(self, user_id: str, entry_id: str) -> Collection[str] | None: ...


@dataclass(frozen=True)
class RescheduleConfig:
    lead_minutes: int
    default_duration_min: int
    max_slots: int
    horizon_days: int
    step_min: int
    buffer_min: int
    working_days: tuple[int, ...]
    window: tuple[str, str]
    weekdays: tuple[str, ...]
    months: tuple[str, ...]
    slot_line: str
    proposal_body: str
    holding_body: str
    notes: Mapping[str, str]


def _text(value: Any) -> str:
    if not isinstance(value, str) or not 0 < len(value) <= MAX_TEXT:
        raise ValueError("bad text")
    return value


def _names(value: Any, count: int) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) != count:
        raise ValueError("bad names")
    return tuple(_text(v) for v in value)


def load_config(path: Path = CONFIG_PATH, personal: Path = PERSONAL_PATH) -> RescheduleConfig | None:
    """The words and limits; None for any missing or malformed file or value (fail closed: nothing is drafted)."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        window = parse_working_window(yaml.safe_load(personal.read_text(encoding="utf-8"))["working_window"])
        ints = {k: raw[k] for k in _INTS}
        if any(
            type(v) is not int or not lo <= v <= hi for v, (lo, hi) in zip(ints.values(), _INTS.values(), strict=True)
        ):
            return None
        days = raw["working_days"]
        if not isinstance(days, list) or not days or any(type(d) is not int or not 0 <= d <= 6 for d in days):
            return None
        notes = {k: _text(raw["notes"][k]) for k in NOTES}
        cfg = RescheduleConfig(
            **ints,
            working_days=tuple(days),
            window=window,
            weekdays=_names(raw["weekdays"], 7),
            months=_names(raw["months"], 12),
            slot_line=_text(raw["slot_line"]),
            proposal_body=_text(raw["proposal_body"]),
            holding_body=_text(raw["holding_body"]),
            notes=notes,
        )
        _slot_text("2026-10-08T06:00:00.000Z", "UTC", cfg)  # a bad format string fails here, not in front of a user
        return cfg if "{slots}" in cfg.proposal_body else None
    except (OSError, UnicodeDecodeError, yaml.YAMLError, KeyError, TypeError, ValueError, IndexError, PeopleInputError):
        return None


def _slot_text(slot: str, tz: str, cfg: RescheduleConfig) -> str:
    when = datetime.fromisoformat(slot).astimezone(ZoneInfo(tz))
    return cfg.slot_line.format(
        weekday=cfg.weekdays[when.weekday()],
        day=when.day,
        month=cfg.months[when.month - 1],
        year=when.year,
        hour=f"{when.hour:02d}",
        minute=f"{when.minute:02d}",
        zone=tz,
    )


@dataclass(frozen=True)
class Plan:
    status: str
    slots: tuple[str, ...] = ()  # UTC timestamps, earliest first
    entry_id: str | None = None


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _words(value: Any) -> tuple[str, ...]:
    return (
        tuple(_TOKENS.findall(unicodedata.normalize("NFKC", value[:500]).casefold())) if isinstance(value, str) else ()
    )


def _contains(hay: tuple[str, ...], needle: tuple[str, ...]) -> bool:
    return bool(needle) and any(hay[i : i + len(needle)] == needle for i in range(len(hay) - len(needle) + 1))


def _resolve(
    live: list[Mapping[str, Any]], hints: Mapping[str, str | None], thread_id: str
) -> Mapping[str, Any] | None:
    """Exactly one entry, by ics UID, then thread id, then title within the subject; two matches at a tier is None."""
    subject = _words(hints.get("subject"))

    def source(e: Mapping[str, Any]) -> Mapping[str, Any]:
        return e["source"] if isinstance(e.get("source"), Mapping) else {}

    uid, thread = hints.get("ics_uid"), hints.get("thread_id") or thread_id
    tiers = (
        [e for e in live if uid and source(e).get("kind") == "google" and source(e).get("ref") == uid],
        [
            e
            for e in live
            if source(e).get("kind") == "tilo" and source(e).get("from") == "mail" and source(e).get("ref") == thread
        ],
        [e for e in live if _contains(subject, _words(e.get("title")))],
    )
    for found in tiers:
        if found:
            return found[0] if len(found) == 1 else None
    return None


def plan(
    request: MoveRequest,
    *,
    thread_id: str,
    owner: str,
    sender: str | None,
    entries: Sequence[Mapping[str, Any]] | None,
    participants: Callable[[str], Collection[str] | None],
    tz: str,
    now: datetime,
    cfg: RescheduleConfig,
) -> Plan:
    """Pure: the times to propose for `request`, or why none. Never raises, never holds mail or calendar text."""
    if not entries:
        return Plan("not_synced")  # an empty cache is never "free"
    try:
        return _plan(request, thread_id, owner, sender, entries, participants, tz, now, cfg)
    except (PeopleInputError, ValueError, TypeError, KeyError, AttributeError, OverflowError):
        return Plan("unreadable")


def _plan(
    request: MoveRequest,
    thread_id: str,
    owner: str,
    sender: str | None,
    entries: Sequence[Mapping[str, Any]],
    participants: Callable[[str], Collection[str] | None],
    tz: str,
    now: datetime,
    cfg: RescheduleConfig,
) -> Plan:
    low = now + timedelta(minutes=cfg.lead_minutes)
    live = [
        e
        for e in entries
        if isinstance(e, Mapping)
        and e.get("owner") == owner
        and e.get("state") == "accepted"
        and isinstance(e.get("id"), str)
        and datetime.fromisoformat(e.get("end") or e["start"]) > now
    ]
    found = _resolve(live, request.ref_hints, thread_id)
    if found is None:
        return Plan("no_meeting")
    who = participants(found["id"])
    people = (
        {a.lower() for a in who if isinstance(a, str)} if who is not None and len(who) <= MAX_PARTICIPANTS else set()
    )
    if sender is None or sender not in people:
        return Plan("not_participant", entry_id=found["id"])
    minutes = None
    if found.get("end") and not found.get("all_day"):
        minutes = int(
            (datetime.fromisoformat(found["end"]) - datetime.fromisoformat(found["start"])).total_seconds() // 60
        )
    minutes = minutes if minutes and 5 <= minutes <= 480 else request.constraint.get("duration_min")
    high = None
    if day := request.constraint.get("day"):  # a day computed by code from the mail's own date
        zone, d = ZoneInfo(tz), date.fromisoformat(day)
        low = max(low, datetime.combine(d, time(0), tzinfo=zone))
        high = datetime.combine(d + timedelta(days=1), time(0), tzinfo=zone)
    try:
        slots = find_free_slots(
            entries,
            owner=owner,
            now=_iso(now),
            tz=tz,
            duration_min=minutes or cfg.default_duration_min,
            working_window=cfg.window,
            working_days=cfg.working_days,
            not_before=_iso(low),
            not_after=_iso(high) if high else None,
            count=cfg.max_slots,
            step_min=cfg.step_min,
            buffer_min=cfg.buffer_min,
            horizon_days=cfg.horizon_days,
            exclude=[found["id"]],
        )
    except PeopleInputError:
        return Plan("no_free_time", entry_id=found["id"])
    return Plan("proposed" if slots else "no_free_time", slots, found["id"])


@dataclass(frozen=True)
class Outcome:
    status: str  # one of STATUSES, "not_configured" or "no_time_zone"
    preview: Preview | None  # the FR-CHN-11 card, always L1; None when nothing is drafted
    slots: tuple[str, ...]
    note: str  # a fixed sentence from config, for the person


class RescheduleReply(PlateReply):
    def __init__(self, *, calendar: CalendarPort, clock: Callable[[], float], **ports: Any) -> None:
        super().__init__(**ports)
        self._calendar, self._clock = calendar, clock

    def draft_reschedule(self, user_id: str, mail_id: str, *, request_id: str) -> Outcome | None:
        """None (nothing read beyond the plate check, drafted, stored, emitted or queued) unless this is the world
        owner's own needs_reply mail that carries the move marker; otherwise an Outcome. Idempotent per request."""
        doc = self._triage.get(user_id, mail_id)
        if not isinstance(doc, dict) or "flagged" not in doc or "category" not in doc:
            return None
        if not self._autopilot.owns(user_id) or triage_result(mail_id, doc).move_request is None:
            return None
        found = self._answerable(user_id, mail_id, request_id)
        cfg = load_config()
        if found is None:
            return None
        mailbox, mail, thread_id, own_id = found
        if cfg is None:
            return Outcome("not_configured", None, (), "")
        tz = self._calendar.time_zone(user_id)
        if not isinstance(tz, str):
            return Outcome("no_time_zone", None, (), cfg.notes["no_time_zone"])
        try:
            request = detect_move_request(mail, time_zone=tz)
        except Exception:  # a hostile Date header or zone is the sender's; no request, no draft
            request = None
        if request is None:
            return None
        verdict = plan(
            request,
            thread_id=thread_id,
            owner=user_id,
            sender=bare_address(mail.get("from")),
            entries=self._calendar.entries(user_id),
            participants=lambda entry_id: self._calendar.participants(user_id, entry_id),
            tz=tz,
            now=datetime.fromtimestamp(self._clock(), UTC),
            cfg=cfg,
        )
        note = cfg.notes[verdict.status]
        if verdict.status in NO_DRAFT:
            return Outcome(verdict.status, None, (), note)
        lines = "\n".join(f"- {_slot_text(s, tz, cfg)}" for s in verdict.slots)
        body = cfg.proposal_body.replace("{slots}", lines) if verdict.slots else cfg.holding_body
        instruction_id = "resched-" + hashlib.sha256(json.dumps([request_id, mail_id]).encode()).hexdigest()[:32]
        try:
            result = self._drafter.draft(
                user_id,
                instruction_id=instruction_id,
                thread_id=thread_id,
                instruction="",
                mailbox=mailbox,
                mode=MODE,
                preset=PRESET,
                answers=mail_id,
                fixed_body=body,
            )
        except ReplyTargetMoved:
            return None
        if result.draft is None or result.draft.in_reply_to != own_id:
            return None
        card = self._autopilot.preview(user_id, DraftContext(instruction_id, thread_id, "", mailbox, MODE), result)
        return Outcome(verdict.status, card, verdict.slots, note)
