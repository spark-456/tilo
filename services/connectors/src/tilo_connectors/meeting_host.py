"""tilo_connectors.meeting_host: the bot-hosted meeting (FR-MTG-09, ADR-0024; API tests/API_FR_MTG_09.md).

The meeting bot's own Google account creates a Calendar event with a Meet link and Google invites the people the
Owner approved. This module is the deterministic half: the config loader, the draft (MH-01..MH-06), the gate
facts the card and the outbox entry copy (MH-07), and the receipt. No network, no model, no log line. The Meet
link is never stored (FR-MTG-01): the receipt keeps Google's event id only. The call itself is
`adapters/meeting_host.py`, reachable only from `Outbox.dispatch_due()` (SEC-03).
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import jsonschema
import tilo_policy
import yaml

from ._schema import _registry
from ._time import parse_ts
from .calendar_sync import DEFAULT_PERSONAL_CONFIG
from .errors import MeetingHostConfigError, MeetingHostRefused, SideEffectRefused
from .registry import ConnectorRegistry, load_strict_yaml

CONNECTOR_ID = "meeting_host"
ACTION_TYPE = "create_meeting_event"
CALENDAR_EVENTS_OWNED = "https://www.googleapis.com/auth/calendar.events.owned"
HOST_CALENDAR = "primary"  # the outbox destination: the host account's own primary calendar
DRAFT_KIND = "meeting_event"
EXACT_MAX = 500  # card.schema.json gate_action.exact
MAX_RECIPIENTS = 50  # outbox.schema.json and card.schema.json maxItems
_MAX_DURATION_BOUNDS = (1, 1440)
_CONTRACTS = "https://contracts.tilo.example/"


@dataclass(frozen=True)
class MeetingHostConfig:
    max_duration_min: int  # 1..1440


def _declaration_is_pinned(declaration: Mapping[str, Any]) -> bool:
    """MH-07: the `meeting_host` entry holds one scope and one action: send, T3, approval, irreversible."""
    if declaration.get("id") != CONNECTOR_ID or dict(declaration.get("scopes") or {}) != {
        "send": [CALENDAR_EVENTS_OWNED]
    }:
        return False
    action = next(
        (a for a in declaration.get("actions") or [] if isinstance(a, Mapping) and a.get("id") == ACTION_TYPE), None
    )
    return action is not None and (
        action.get("capability"),
        action.get("risk_tier"),
        action.get("gate_type"),
        action.get("irreversible"),
    ) == ("send", "T3", "approval", True)


def load_meeting_host_config(
    path: str | os.PathLike[str] = DEFAULT_PERSONAL_CONFIG, *, registry: ConnectorRegistry
) -> MeetingHostConfig:
    """Names a key, never a value. Refuses the whole file on any doubt."""
    try:
        raw = load_strict_yaml(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError, RecursionError, ValueError):
        raise MeetingHostConfigError("personal config: not a readable UTF-8 YAML file") from None
    block = raw.get("meeting_host") if isinstance(raw, dict) else None
    if not isinstance(block, dict) or set(block) != {"max_duration_min"}:
        raise MeetingHostConfigError("meeting_host: must be a mapping with exactly the key max_duration_min")
    value = block["max_duration_min"]
    low, high = _MAX_DURATION_BOUNDS
    if type(value) is not int or not low <= value <= high:
        raise MeetingHostConfigError("meeting_host.max_duration_min: must be an integer from 1 to 1440")
    if CONNECTOR_ID not in registry or not _declaration_is_pinned(registry.get(CONNECTOR_ID)):
        raise MeetingHostConfigError("meeting_host: the connector declaration is not the pinned one")
    return MeetingHostConfig(value)


@dataclass(frozen=True)
class MeetingEventDraft:
    meeting_id: str
    org_id: str
    owner: str  # the meeting owner's user id
    title: str = field(repr=False)
    start: str  # common timestamp (UTC), from meeting.scheduled.start
    end: str  # common timestamp (UTC), from meeting.scheduled.end
    time_zone: str  # the owner's person.time_zone
    recipients: tuple[str, ...] = field(repr=False)  # the owner's address first, then invitees in attendee order
    invited: tuple[str, ...]  # user ids, same order as recipients
    not_invited: int  # attendees with no Tilo account
    content: bytes = field(repr=False)  # the draft artifact, canonical JSON
    content_sha256: str  # sha256(content), lower-case hex
    exact: str = field(repr=False)  # gate.action.exact


def _check(ref: str, value: Any) -> bool:
    validator = jsonschema.Draft202012Validator({"$ref": f"{_CONTRACTS}{ref}"}, registry=_registry())
    return next(iter(validator.iter_errors(value)), None) is None


def _fold(address: str) -> str:
    return unicodedata.normalize("NFKC", address).casefold()


def _exact(title: str, when: str, zone: str, recipients: int, not_invited: int) -> str:
    plural = not_invited != 1
    skipped = (
        f"{not_invited} attendee{'s' if plural else ''} without a Tilo account {'are' if plural else 'is'} "
        "not invited. "
        if not_invited > 0
        else ""
    )
    return (
        f'Creates "{title}" on the Tilo meeting host\'s Google Calendar, {when} ({zone}), with a new Google Meet '
        f"link. Google emails an invitation from the meeting host account to the {recipients} people listed, "
        f"you included. {skipped}Guests cannot add people or see each other's addresses. "
        "Tilo notetaker joins at the start time and posts a recording notice. "
        "An invitation cannot be unsent."
    )


def draft_meeting_event(
    *,
    meeting: Mapping[str, Any],  # the stored meeting record; tilo-api reads it, never a request body
    persons: Mapping[str, Mapping[str, Any]],  # person records by id: the owner and every attendee user
    actor: str,  # the signed-in principal (tilo-api session, never input)
    now: str,  # server clock, common timestamp
    config: MeetingHostConfig,
) -> MeetingEventDraft:
    """No side effect. Nothing but `meeting` and `persons` reaches the draft: no address, free text, transcript or
    model output can be passed in, so none can be invited (PE-09 pattern). The first failing check raises."""
    # MH-01
    if not _check("meeting.schema.json", meeting):
        raise MeetingHostRefused("MH-01", "the meeting record breaks the meeting contract")
    owner = meeting["owner"]
    if actor != owner or meeting["status"] != "scheduled" or meeting["source"] != "bot":
        raise MeetingHostRefused("MH-01", "only the owner hosts a scheduled bot meeting")
    if meeting["attestation"]["by"] != owner:
        raise MeetingHostRefused("MH-01", "the attestation is not the owner's")
    # MH-02
    window = meeting["scheduled"]
    if window is None or window["end"] is None:
        raise MeetingHostRefused("MH-02", "the meeting has no scheduled window")
    start, end = parse_ts(window["start"]), parse_ts(window["end"])
    if not parse_ts(now) < start < end:
        raise MeetingHostRefused("MH-02", "the window is not in the future")
    if (end - start).total_seconds() > config.max_duration_min * 60:
        raise MeetingHostRefused("MH-02", "the meeting is longer than the configured cap")
    # MH-03: a missing record refuses (fail closed); an attendee with no Tilo account is counted, never invited
    recipients: list[str] = []
    invited: list[str] = []
    folded: set[str] = set()
    attendee_users = [a["user"] for a in meeting["attendees"] if a["user"] is not None]
    for user in dict.fromkeys([owner, *attendee_users]):
        record = persons.get(user)
        if record is None or record.get("id") != user or not _check("person.schema.json", record):
            raise MeetingHostRefused("MH-03", f"no usable person record for {user}")
        if record["org_id"] != meeting["org_id"]:
            raise MeetingHostRefused("MH-03", f"{user} is not of the meeting's org")
        key = _fold(record["email"])
        if key in folded:
            raise MeetingHostRefused("MH-03", "two users share an address")
        folded.add(key)
        invited.append(user)
        recipients.append(record["email"])
    if len(recipients) > MAX_RECIPIENTS:
        raise MeetingHostRefused("MH-03", f"more than {MAX_RECIPIENTS} recipients")
    not_invited = len(meeting["attendees"]) - len(attendee_users)
    # MH-04
    zone = persons[owner]["time_zone"]
    try:
        local = ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        raise MeetingHostRefused("MH-04", "the owner's time zone is unknown") from None
    # MH-05: the title is the meeting's own, unchanged (the meeting schema refuses links and control characters)
    title = meeting["title"]
    # MH-06
    when = f"{start.astimezone(local):%a %d %b %Y, %H:%M} to {end.astimezone(local):%H:%M}"
    exact = _exact(title, when, zone, len(recipients), not_invited)
    if len(exact) > EXACT_MAX:
        raise MeetingHostRefused("MH-06", "the card sentence is longer than the card allows")
    content = json.dumps(
        {
            "v": "1.0",
            "kind": DRAFT_KIND,
            "meeting_id": meeting["id"],
            "owner": owner,
            "title": title,
            "start": window["start"],
            "end": window["end"],
            "time_zone": zone,
            "attendees": recipients,
            "conference": "hangoutsMeet",
            "send_updates": "all",
            "guests_can_invite_others": False,
            "guests_can_modify": False,
            "guests_can_see_other_guests": False,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return MeetingEventDraft(
        meeting_id=meeting["id"],
        org_id=meeting["org_id"],
        owner=owner,
        title=title,
        start=window["start"],
        end=window["end"],
        time_zone=zone,
        recipients=tuple(recipients),
        invited=tuple(invited),
        not_invited=not_invited,
        content=content,
        content_sha256=hashlib.sha256(content).hexdigest(),
        exact=exact,
    )


def host_gate(draft: MeetingEventDraft, stored: Mapping[str, Any], declaration: Mapping[str, Any]) -> dict[str, Any]:
    """What the card builder, `approval.requested` and the outbox entry copy (CR-10..CR-12, OB-05). `stored` is the
    artifact record the store returned for `draft.content`. A flagged draft still gates (T3 with `safety_flag`)."""
    if not _declaration_is_pinned(declaration):
        raise MeetingHostRefused("MH-07", "the connector declaration is not the pinned one")
    origin = stored.get("origin")
    ref = stored.get("artifact")
    if (
        stored.get("media_type") != "application/json"
        or stored.get("content_sha256") != draft.content_sha256
        or not isinstance(origin, Mapping)
        or origin.get("kind") != "unit"
        or not isinstance(ref, Mapping)
        or "artifact_id" not in ref
        or "version" not in ref
    ):
        raise MeetingHostRefused("MH-07", "the stored record is not the draft as made")
    facts = tilo_policy.SideEffectFacts(
        recipients=draft.recipients, known_recipients=(), safety_flags=stored.get("screening") != "clean"
    )
    assessed = tilo_policy.load_risk_table().assess(ACTION_TYPE, facts)
    return {
        "action_type": ACTION_TYPE,
        "connector": CONNECTOR_ID,
        "risk_tier": "T3",
        "irreversible": True,
        "modifiers": list(assessed.modifiers),
        "recipients": list(draft.recipients),
        "attachments": [],
        "item": {"artifact_id": ref["artifact_id"], "version": ref["version"]},
        "destination": HOST_CALENDAR,
        "exact": draft.exact,
        "undo_window_s": 0,
    }


@dataclass(frozen=True)
class HostReceipt:
    world_id: str
    outbox_id: str
    meeting_id: str
    owner: str
    draft: Mapping[str, Any]  # artifact_ref of the draft, no label
    event_ref: str  # Google's event id: side_effect_marker(entry), [0-9a-f]{32}
    conference: str  # "pending" | "success" | "failure", Google's createRequest status


class ReceiptStore(Protocol):  # production: the artifact store bound to the world's Scope, origin unit
    def put(self, receipt: HostReceipt) -> dict[str, Any]:
        """The artifact_ref. The same (world_id, outbox_id) and the same receipt return the same ref; a different
        receipt under that key raises SideEffectRefused."""
        ...

    def get(self, world_id: str, meeting_id: str) -> HostReceipt | None: ...


class InMemoryReceiptStore:
    """Dev and tests: `.receipts` lists what it stored."""

    def __init__(self) -> None:
        self.receipts: list[HostReceipt] = []
        self._by_key: dict[tuple[str, str], tuple[HostReceipt, dict[str, Any]]] = {}
        self._lock = threading.Lock()

    def put(self, receipt: HostReceipt) -> dict[str, Any]:
        key = (receipt.world_id, receipt.outbox_id)
        with self._lock:
            known = self._by_key.get(key)
            if known is not None:
                if known[0] != receipt:
                    raise SideEffectRefused("a different receipt is already stored for this send")
                return dict(known[1])
            digest = hashlib.sha256("\x00".join(key).encode()).hexdigest()[:24]
            ref = {"artifact_id": f"art_mr_{digest}", "version": 1}
            self._by_key[key] = (receipt, ref)
            self.receipts.append(receipt)
            return dict(ref)

    def get(self, world_id: str, meeting_id: str) -> HostReceipt | None:
        with self._lock:
            for (world, _outbox), (receipt, _ref) in self._by_key.items():
                if world == world_id and receipt.meeting_id == meeting_id:
                    return receipt
        return None
