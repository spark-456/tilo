"""Test doubles, oracles and data factories for the FR-MTG-09 tests (bot-hosted meetings, connector side).
Pinned API: API_FR_MTG_09.md (ADR-0024). Ticket MTG09-a.

No production code lives here (root CLAUDE.md test-writer rule). What is here:

- FakeHostCalendar: an in-process stand-in for `POST /calendar/v3/calendars/primary/events` and
  `GET .../events/{id}` behind the adapter's injected Transport seam. It keeps events by id, answers 409 for a
  known id, counts invitations per event (one per attendee, only on the first successful insert that carries
  `sendUpdates=all`), accepts only bearer tokens the FakeGoogle token double issued, and fails on demand (a lost
  answer after creating, a rejected token once, 400, 403, 404, 429, 500, a conference status). It does NOT apply
  the `fields` mask: every answer holds a planted Meet link, a planted `htmlLink`, an entry point and the whole
  attendee list, so only the adapter can keep them out of what Tilo stores, logs and emits. It never opens a
  socket (an autouse fixture also makes every socket call raise).
- DraftArtifacts: the artifact store's hash-checked read (AR-01) for the draft, as the adapter's `ArtifactSource`:
  `get(artifact_id, version)` returns the stored JSON object, and raises when the bytes were replaced.
- ByteReceiptStore / FlakyReceipts: `ReceiptStore` doubles that keep the receipt as the canonical JSON the spec
  pins, so a test can scan the bytes.
- RecordingAdapter: wraps the adapter the outbox calls, so a test sees what it returned and what it raised.
- HostEnv / make_host_env(): broker (with a TokenSpy), consent service, fake calendar, artifact doubles,
  adapter and an Outbox wired together; `HostEnv.prepare()` runs steps 3 to 5 of the ordered flow (draft, store,
  gate) and builds the gate-authorised outbox case and the gate card.
- Oracles: the `exact` sentence, the draft `content` bytes, the insert body, the receipt bytes, written from the
  API doc's text so a test compares the builder's output with the document, not with the builder's own helper.

`tilo_connectors.meeting_host` and `tilo_connectors.adapters.meeting_host` do not exist yet; the tests import
them lazily through `mh()` and `mha()`, so a missing module fails the test that needs it with
ModuleNotFoundError, never a collection error in this file.

Every token is assembled at runtime (FakeGoogle, `secrets`); every address is at example.com, example.net or
example.org; nothing opens a socket, calls a model or reads LIVE.
"""

from __future__ import annotations

import ast
import copy
import hashlib
import importlib
import itertools
import json
import pathlib
import re
import secrets
import socket
import threading
import traceback
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest
import yaml
from _calendar_lib import AUTONOMY_YAML, CALENDAR_READONLY, CONNECTORS_YAML, PERSONAL_YAML, TokenSpy
from _connectors_lib import ManualClock, add_seconds, parse_ts
from _gapi_lib import FakeApiResponse, Req
from _oauth_lib import (
    CARD_ID,
    OWNER,
    REPO_ROOT,
    RUN,
    WORLD,
    Env,
    declarations,
    make_env,
)
from conftest import gate_case

__all__ = [
    "AUTONOMY_YAML",
    "CALENDAR_READONLY",
    "CONNECTORS_YAML",
    "PERSONAL_YAML",
    "OWNER",
    "RUN",
    "WORLD",
]

SRC = REPO_ROOT / "services" / "connectors" / "src" / "tilo_connectors"
SCRIPT = REPO_ROOT / "services" / "connectors" / "scripts" / "live_meeting_host_smoke.py"

# Names the API doc pins (redeclared on purpose: a test double must not import the module under test;
# test_FR_MTG_09_config asserts they equal the module's constants).
CONNECTOR_ID = "meeting_host"
ACTION_TYPE = "create_meeting_event"
CALENDAR_EVENTS_OWNED = "https://www.googleapis.com/auth/calendar.events.owned"
EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
EVENT_FIELDS = "id,status,conferenceData(createRequest(status(statusCode)))"
HOST_CALENDAR = "primary"
DRAFT_KIND = "meeting_event"
EXACT_MAX = 500
GMAIL_READONLY = "https://www.googleapis.com/auth/gmail.readonly"
DRIVE_FILE = "https://www.googleapis.com/auth/drive.file"

ORG = "org_example"
OTHER_ORG = "org_other"
MEETING_ID = "mt_q4_plan"
UNIT = "U1"
AGENT = "A_host1"
ATTEMPT = 1
APPROVER = "u_approver"

T_NOW = "2026-10-06T07:00:00.000Z"  # the server clock when the Owner asks to host
T_START = "2026-10-06T09:00:00.000Z"
T_END = "2026-10-06T10:00:00.000Z"
T_UPDATED = "2026-10-06T06:00:00.000Z"
IST = "Asia/Kolkata"

ASHA = "asha@example.com"
PRIYA_MAIL = "priya@example.com"
SAM_MAIL = "sam@example.net"
EXTRA_MAIL = "extra@example.com"
ATTACKER = "eve@example.org"


def mh():
    return importlib.import_module("tilo_connectors.meeting_host")


def mha():
    return importlib.import_module("tilo_connectors.adapters.meeting_host")


def errs():
    return importlib.import_module("tilo_connectors.errors")


# ---------------------------------------------------------------------------
# Guards: no network, no LIVE


@pytest.fixture(autouse=True)
def no_network_and_no_live(monkeypatch):
    """EFF-01: nothing here reaches a network or reads LIVE. Every socket call raises; LIVE is unset."""
    monkeypatch.delenv("LIVE", raising=False)

    def refuse(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("a FR-MTG-09 test tried to use the network")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)


# ---------------------------------------------------------------------------
# Config, declaration, registry


def host_decl() -> dict:
    """The `meeting_host` entry as the API doc's "Shipped config" block spells it."""
    return {
        "id": CONNECTOR_ID,
        "name": "Tilo meeting host",
        "icon": "calendar",
        "auth": "oauth2",
        "scopes": {"send": [CALENDAR_EVENTS_OWNED]},
        "capabilities": ["send"],
        "actions": [
            {
                "id": ACTION_TYPE,
                "capability": "send",
                "description": (
                    "On the meeting bot's own Google account (sign in as the bot, not as yourself): "
                    "create a meeting with a Meet link and invite the people you approve."
                ),
                "risk_tier": "T3",
                "gate_type": "approval",
                "irreversible": True,
            }
        ],
        "limits": {"per_minute": 30, "batch_size": 50},
        "data_class": {"returns": ["business"], "redact": []},
    }


def shipped_decl() -> dict:
    """The declaration the shipped config/connectors.yaml holds (the assertion fails today: not added yet)."""
    entries = yaml.safe_load(CONNECTORS_YAML.read_text(encoding="utf-8"))
    found = [e for e in entries if e["id"] == CONNECTOR_ID]
    assert len(found) == 1, "config/connectors.yaml declares meeting_host exactly once (MTG09-a adds it)"
    return copy.deepcopy(found[0])


def write_registry(tmp_path: pathlib.Path, decl: dict | None = None, name: str = "connectors.yaml"):
    """A registry over `decl` (default: the pinned meeting_host entry) written into tmp_path, never into config/."""
    from tilo_connectors.registry import load_registry

    path = tmp_path / name
    path.write_text(yaml.safe_dump([decl if decl is not None else host_decl()], sort_keys=False), encoding="utf-8")
    return load_registry(path)


def write_personal(tmp_path: pathlib.Path, block: Any = None, *, drop: bool = False, name: str = "personal.yaml"):
    """The shipped personal.yaml with the `meeting_host` block set to `block` (or removed with `drop`)."""
    raw = yaml.safe_load(PERSONAL_YAML.read_text(encoding="utf-8"))
    raw.pop("meeting_host", None)
    if not drop:
        raw["meeting_host"] = {"max_duration_min": 60} if block is None else block
    path = tmp_path / name
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return path


def host_config(max_duration_min: int = 60):
    return mh().MeetingHostConfig(max_duration_min=max_duration_min)


# ---------------------------------------------------------------------------
# Meetings and persons (contract-valid: test_FR_MTG_09_the_test_fixtures_validate...)


def person(
    user: str,
    email: str,
    *,
    org: str = ORG,
    zone: str = IST,
    name: str | None = None,
    role: str = "member",
) -> dict:
    return {
        "id": user,
        "org_id": org,
        "display_name": name or user.removeprefix("u_").title(),
        "aliases": [],
        "email": email,
        "time_zone": zone,
        "preferred_channel": "email",
        "org_role": role,
        "memberships": [],
        "created_by": {"by": OWNER, "at": T_UPDATED},
    }


def default_persons() -> dict[str, dict]:
    return {
        OWNER: person(OWNER, ASHA, name="Asha Rao", role="owner"),
        "u_priya": person("u_priya", PRIYA_MAIL, name="Priya Nair"),
        "u_sam": person("u_sam", SAM_MAIL, name="Sam Lee"),
        "u_extra": person("u_extra", EXTRA_MAIL, name="Extra Person"),  # of the org, on no meeting
    }


def attendee(name: str, user: str | None) -> dict:
    return {"name": name, "user": user}


def default_attendees() -> list[dict]:
    return [
        attendee("Asha Rao", OWNER),
        attendee("Priya", "u_priya"),
        attendee("Sam", "u_sam"),
        attendee("Dev from Acme", None),
    ]


def meeting(
    *,
    title: str = "Q4 planning",
    attendees: list[dict] | None = None,
    start: str | None = T_START,
    end: str | None = T_END,
    **over: Any,
) -> dict:
    """A `scheduled`, `bot`-sourced meeting record that passes meeting.schema.json (the stored record)."""
    record: dict[str, Any] = {
        "id": MEETING_ID,
        "org_id": ORG,
        "owner": OWNER,
        "title": title,
        "series": None,
        "scheduled": None if start is None else {"start": start, "end": end},
        "agenda": [{"title": "Launch date", "minutes": 15}],
        "attendees": default_attendees() if attendees is None else attendees,
        "attestation": {"by": OWNER, "at": T_UPDATED, "notice_version": "1.0.0"},
        "source": "bot",
        "status": "scheduled",
        "ended_reason": None,
        "minutes_confirmed_by": None,
        "transcript": None,
        "minutes": None,
        "delete_transcript_after": None,
        "delete_minutes_after": None,
        "created_at": T_UPDATED,
    }
    record.update(over)
    return record


def many_users(n: int, *, org: str = ORG) -> tuple[list[dict], dict[str, dict]]:
    """n attendee entries and their person records: u_p01.. with p01@example.com.."""
    attendees, persons = [], {}
    for i in range(1, n + 1):
        user = f"u_p{i:02d}"
        attendees.append(attendee(f"Person {i:02d}", user))
        persons[user] = person(user, f"p{i:02d}@example.com", org=org)
    return attendees, persons


def minutes_after(start: str, minutes: int) -> str:
    return add_seconds(start, minutes * 60)


def draft_of(
    meeting_: dict | None = None,
    persons_: dict | None = None,
    *,
    actor: str = OWNER,
    now: str = T_NOW,
    max_duration_min: int = 60,
):
    persons_ = default_persons() if persons_ is None else persons_
    return mh().draft_meeting_event(
        meeting=meeting() if meeting_ is None else meeting_,
        persons=persons_,
        actor=actor,
        now=now,
        config=host_config(max_duration_min),
    )


def refusal_rule(call: Callable[[], Any]) -> str:
    """The rule id a call raises MeetingHostRefused with (the test fails when it raises nothing else)."""
    try:
        call()
    except mh_refused() as exc:
        return exc.rule
    raise AssertionError("expected MeetingHostRefused, nothing was raised")


def mh_refused() -> type[BaseException]:
    return errs().MeetingHostRefused


# ---------------------------------------------------------------------------
# Oracles: the formulas the API doc pins


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def local_when(start: str, end: str, zone: str) -> str:
    s = parse_ts(start).astimezone(ZoneInfo(zone))
    e = parse_ts(end).astimezone(ZoneInfo(zone))
    return f"{s:%a %d %b %Y, %H:%M} to {e:%H:%M}"


def oracle_exact(title: str, start: str, end: str, zone: str, n: int, k: int) -> str:
    plural = "s" if k != 1 else ""
    skipped = f"{k} attendee{plural} without a Tilo account {'are' if k != 1 else 'is'} not invited. " if k > 0 else ""
    return (
        f'Creates "{title}" on the Tilo meeting host\'s Google Calendar, {local_when(start, end, zone)} ({zone}), '
        f"with a new Google Meet link. Google emails an invitation from the meeting host account to the {n} "
        f"people listed, you included. {skipped}Guests cannot add people or see each other's addresses. "
        "Tilo notetaker joins at the start time and posts a recording notice. "
        "An invitation cannot be unsent."
    )


def oracle_content(meeting_: dict, recipients: Iterable[str], zone: str = IST) -> bytes:
    return canonical(
        {
            "v": "1.0",
            "kind": DRAFT_KIND,
            "meeting_id": meeting_["id"],
            "owner": meeting_["owner"],
            "title": meeting_["title"],
            "start": meeting_["scheduled"]["start"],
            "end": meeting_["scheduled"]["end"],
            "time_zone": zone,
            "attendees": list(recipients),
            "conference": "hangoutsMeet",
            "send_updates": "all",
            "guests_can_invite_others": False,
            "guests_can_modify": False,
            "guests_can_see_other_guests": False,
        }
    )


def marker_of(entry: dict) -> str:
    """side_effect_marker(entry): sha256 of world_id NUL idempotency_key, first 32 hex characters."""
    return hashlib.sha256(f"{entry['world_id']}\x00{entry['idempotency_key']}".encode()).hexdigest()[:32]


def oracle_insert_body(entry: dict, draft: dict) -> dict:
    marker = marker_of(entry)
    return {
        "id": marker,
        "summary": draft["title"],
        "start": {"dateTime": draft["start"], "timeZone": draft["time_zone"]},
        "end": {"dateTime": draft["end"], "timeZone": draft["time_zone"]},
        "attendees": [{"email": a} for a in entry["recipients"]],
        "conferenceData": {"createRequest": {"requestId": marker, "conferenceSolutionKey": {"type": "hangoutsMeet"}}},
        "guestsCanInviteOthers": False,
        "guestsCanModify": False,
        "guestsCanSeeOtherGuests": False,
    }


def oracle_params() -> dict:
    return {"conferenceDataVersion": 1, "sendUpdates": "all", "fields": EVENT_FIELDS}


def receipt_bytes(receipt: Any) -> bytes:
    """The receipt's stored bytes as the API doc pins them: no link, no address, no title, no time."""
    return canonical(
        {
            "v": "1.0",
            "kind": "meeting_event_receipt",
            "connector": CONNECTOR_ID,
            "calendar": HOST_CALENDAR,
            "event_ref": receipt.event_ref,
            "meeting_id": receipt.meeting_id,
            "draft": dict(receipt.draft),
            "outbox_id": receipt.outbox_id,
            "conference": receipt.conference,
        }
    )


# ---------------------------------------------------------------------------
# The Google Calendar double


@dataclass
class _Ev:
    id: str
    summary: str
    start: Any
    end: Any
    attendees: list[str]
    status: str = "confirmed"
    conference: str | None = "success"
    invitations: list[str] = field(default_factory=list)


@dataclass
class Plant:
    """What Google may put in an answer whatever the `fields` mask says: none of it may travel."""

    link: str
    html_link: str
    organizer: str
    conference_id: str

    @classmethod
    def make(cls) -> Plant:
        def word(n: int) -> str:
            return "".join(secrets.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(n))

        return cls(
            link=f"https://meet.google.com/{word(3)}-{word(4)}-{word(3)}",
            html_link=f"https://www.google.com/calendar/event?eid={secrets.token_hex(12)}",
            organizer=f"bot{secrets.token_hex(3)}@example.org",
            conference_id=f"{word(3)}-{word(4)}-{word(3)}",
        )

    def needles(self) -> list[str]:
        slug = self.link.rsplit("/", 1)[1]
        return [self.link, self.html_link, slug, self.html_link.split("eid=")[1], self.organizer]


@dataclass
class _Failure:
    status: int
    headers: dict
    times: int
    predicate: Callable[[Req], bool]


class FakeHostCalendar:
    """`request` is the whole Transport surface. See the module docstring."""

    def __init__(self, google: Any, *, conference: str | None = "success") -> None:
        self._google = google
        self.conference = conference  # the createRequest statusCode of new events (None: no conferenceData)
        self.plant = Plant.make()
        self.requests: list[Req] = []
        self.events: dict[str, _Ev] = {}
        self.rejected_tokens: set[str] = set()
        self.on_insert: Callable[[], None] | None = None  # runs after creating, before answering (a race)
        self.get_hides_events = False  # GET answers 404 even for a known id
        self.answer_id: str | None = None  # the id an insert answer carries instead of the real one
        self._failures: list[_Failure] = []
        self._lose_after_create = 0
        self._lock = threading.RLock()

    # -- provisioning --------------------------------------------------------------------------
    def fail_next(
        self,
        status: int,
        *,
        times: int = 1,
        headers: dict | None = None,
        when: Callable[[Req], bool] = lambda r: True,
    ) -> None:
        with self._lock:
            self._failures.append(_Failure(status, dict(headers or {}), times, when))

    def clear_failures(self) -> None:
        with self._lock:
            self._failures.clear()

    def lose_answer_after_create(self, times: int = 1) -> None:
        """The next insert(s) are carried out (event created, invitations counted), then the caller sees a
        TransportError."""
        with self._lock:
            self._lose_after_create += times

    def reject_token(self, token: str) -> None:
        with self._lock:
            self.rejected_tokens.add(token)

    def seed_event(self, event_id: str, *, status: str = "confirmed", attendees: Iterable[str] = ()) -> None:
        """An event that already exists under `event_id` (an earlier attempt, or a cancelled one): no invitation."""
        with self._lock:
            self.events[event_id] = _Ev(event_id, "seeded", {}, {}, list(attendees), status, self.conference)

    # -- inspection ----------------------------------------------------------------------------
    def posts(self) -> list[Req]:
        with self._lock:
            return [r for r in self.requests if r.method == "POST"]

    def gets(self) -> list[Req]:
        with self._lock:
            return [r for r in self.requests if r.method == "GET"]

    def invitations(self) -> list[tuple[str, str]]:
        """(event id, address) for every invitation Google sent, in order."""
        with self._lock:
            return [(ev.id, a) for ev in self.events.values() for a in ev.invitations]

    def created(self) -> list[_Ev]:
        with self._lock:
            return [ev for ev in self.events.values() if ev.summary != "seeded"]

    def tokens_used(self) -> set[str]:
        return {r.token for r in self.requests if r.token}

    # -- the Transport seam --------------------------------------------------------------------
    def request(
        self,
        method: str,
        url: str,
        *,
        params: Any = None,
        headers: Any = None,
        json: Any = None,
        content: bytes | None = None,
        timeout: Any = None,
    ) -> FakeApiResponse:
        from tilo_connectors.adapters import TransportError

        req = Req(
            method.upper(),
            url,
            {k: v for k, v in dict(params or {}).items() if v is not None},
            {str(k).lower(): str(v) for k, v in dict(headers or {}).items()},
            copy.deepcopy(json),
            bytes(content) if content is not None else None,
        )
        assert "?" not in url, f"query belongs in params, not the URL: {url}"
        with self._lock:
            self.requests.append(req)
            failure = next((f for f in self._failures if f.times > 0 and f.predicate(req)), None)
            if failure is not None:
                failure.times -= 1
        if failure is not None:
            return self._error(failure.status, failure.headers)
        token = req.token
        if not token or token not in self._google.issued_access or token in self.rejected_tokens:
            return self._error(401)
        if req.method == "POST" and url == EVENTS_URL:
            response, lose = self._insert(req)
            if self.on_insert is not None and response.status_code == 200:
                self.on_insert()
            if lose:
                raise TransportError("simulated: the answer was lost after Google created the event")
            return response
        if req.method == "GET" and url.startswith(EVENTS_URL + "/"):
            return self._get(url[len(EVENTS_URL) + 1 :])
        raise AssertionError(f"the fake has no endpoint {req.method} {url}")

    # -- internals -----------------------------------------------------------------------------
    def _error(self, status: int, headers: dict | None = None) -> FakeApiResponse:
        """An error body that echoes everything a careless Google might: link, address, organizer."""
        body = {
            "error": {
                "code": status,
                "message": f"failed for {self.plant.organizer} see {self.plant.link} {self.plant.html_link}",
                "status": "ERROR",
            }
        }
        return FakeApiResponse(status, body, headers=headers)

    def _insert(self, req: Req) -> tuple[FakeApiResponse, bool]:
        body = req.json or {}
        event_id = body.get("id")
        if not isinstance(event_id, str) or not re.fullmatch(r"[0-9a-v]{5,1024}", event_id):
            return self._error(400), False
        with self._lock:
            if event_id in self.events:
                return self._error(409), False
            conference = self.conference if req.params.get("conferenceDataVersion") == 1 else "failure"
            ev = _Ev(
                event_id,
                str(body.get("summary", "")),
                body.get("start"),
                body.get("end"),
                [str(a.get("email")) for a in body.get("attendees", [])],
                "confirmed",
                conference,
            )
            if req.params.get("sendUpdates") == "all":
                ev.invitations = list(ev.attendees)
            self.events[event_id] = ev
            lose = self._lose_after_create > 0
            if lose:
                self._lose_after_create -= 1
        answer = self._body(ev)
        if self.answer_id is not None:
            answer["id"] = self.answer_id
        return FakeApiResponse(200, answer), lose

    def _get(self, event_id: str) -> FakeApiResponse:
        with self._lock:
            ev = self.events.get(event_id)
        if ev is None or self.get_hides_events:
            return self._error(404)
        return FakeApiResponse(200, self._body(ev))

    def _body(self, ev: _Ev) -> dict:
        """The full event, hostile: the `fields` mask is not applied."""
        out: dict[str, Any] = {
            "kind": "calendar#event",
            "id": ev.id,
            "status": ev.status,
            "summary": ev.summary,
            "hangoutLink": self.plant.link,
            "htmlLink": self.plant.html_link,
            "organizer": {"email": self.plant.organizer, "self": True},
            "attendees": [{"email": a, "responseStatus": "needsAction"} for a in ev.attendees],
        }
        if ev.conference is not None:
            out["conferenceData"] = {
                "createRequest": {"requestId": ev.id, "status": {"statusCode": ev.conference}},
                "entryPoints": [{"entryPointType": "video", "uri": self.plant.link}],
                "conferenceId": self.plant.conference_id,
            }
        return out


# ---------------------------------------------------------------------------
# Artifact and receipt doubles


class FakeArtifactCorrupt(Exception):
    """What a hash-checked store read raises when the bytes differ from the record (AR-01). Deliberately not a
    ValueError: the real store's ArtifactCorrupt is not one either."""


class DraftArtifacts:
    """The artifact store, write side for the host unit and read side (`ArtifactSource`) for the adapter."""

    def __init__(self) -> None:
        self._records: dict[tuple[str, int], dict] = {}
        self._bytes: dict[tuple[str, int], bytes] = {}
        self._versions = itertools.count(1)
        self.reads: list[tuple[str, int]] = []
        self._lock = threading.Lock()

    def put_draft(
        self,
        content: bytes,
        *,
        world_id: str = WORLD,
        run_id: str = RUN,
        unit: str = UNIT,
        attempt: int = ATTEMPT,
        label: str | None = None,
        screening: str = "clean",
        media_type: str = "application/json",
        origin_kind: str = "unit",
        redacted_to: bytes | None = None,
    ) -> dict:
        """Store `content` (or `redacted_to`, a store whose redactor changed it) and return the artifact record."""
        stored_bytes = content if redacted_to is None else redacted_to
        version = next(self._versions)
        ref: dict[str, Any] = {"artifact_id": "art_meeting_event", "version": version}
        if label:
            ref["label"] = label
        record = {
            "v": "1.0",
            "artifact": ref,
            "org_id": ORG,
            "world_id": world_id,
            "run_id": run_id,
            "owner": OWNER,
            "media_type": media_type,
            "size_bytes": max(1, len(stored_bytes)),
            "content_sha256": hashlib.sha256(stored_bytes).hexdigest(),
            "parents": [],
            "origin": (
                {"kind": origin_kind, "unit": unit, "agent": AGENT}
                if origin_kind == "unit"
                else {"kind": origin_kind, "unit": None, "agent": None}
            ),
            "sources": [],
            "screening": screening,
            "screened_at": None if screening == "unscreened" else T_NOW,
            "redacted": redacted_to is not None,
            "idempotency_key": f"{run_id}:{unit}:{attempt}:0" if origin_kind in ("unit", "render") else None,
            "created_at": T_NOW,
        }
        with self._lock:
            self._records[("art_meeting_event", version)] = record
            self._bytes[("art_meeting_event", version)] = stored_bytes
        return copy.deepcopy(record)

    def get(self, artifact_id: str, version: int) -> dict:
        key = (artifact_id, int(version))
        with self._lock:
            self.reads.append(key)
            record, data = self._records[key], self._bytes[key]
        if hashlib.sha256(data).hexdigest() != record["content_sha256"]:
            raise FakeArtifactCorrupt("the stored bytes do not match the record")
        return json.loads(data.decode("utf-8"))

    def replace_bytes(self, ref: dict, data: bytes) -> None:
        """Different bytes under the same ref (a broken store or an attacker)."""
        with self._lock:
            self._bytes[(ref["artifact_id"], ref["version"])] = data

    def all_bytes(self) -> list[bytes]:
        with self._lock:
            return list(self._bytes.values())


class ByteReceiptStore:
    """A `ReceiptStore` that keeps each receipt as the canonical JSON the API doc pins."""

    def __init__(self) -> None:
        self._by_key: dict[tuple[str, str], tuple[Any, bytes, dict]] = {}
        self._versions = itertools.count(1)
        self.put_calls = 0
        self._lock = threading.Lock()

    def put(self, receipt: Any) -> dict:
        data = receipt_bytes(receipt)
        key = (receipt.world_id, receipt.outbox_id)
        with self._lock:
            self.put_calls += 1
            if key in self._by_key:
                if self._by_key[key][1] == data:
                    return dict(self._by_key[key][2])
                raise errs().SideEffectRefused("a different receipt is already stored for this send")
            ref = {"artifact_id": "art_meeting_receipt", "version": next(self._versions)}
            self._by_key[key] = (receipt, data, ref)
            return dict(ref)

    def get(self, world_id: str, meeting_id: str) -> Any:
        with self._lock:
            found = [
                r for (w, _), (r, _b, _ref) in self._by_key.items() if w == world_id and r.meeting_id == meeting_id
            ]
        return found[0] if found else None

    def all_bytes(self) -> list[bytes]:
        with self._lock:
            return [b for (_r, b, _ref) in self._by_key.values()]

    def receipts(self) -> list[Any]:
        with self._lock:
            return [r for (r, _b, _ref) in self._by_key.values()]


class FlakyReceipts(ByteReceiptStore):
    """The first `failures` puts raise `error` before anything is stored."""

    def __init__(self, error: Exception, failures: int = 1) -> None:
        super().__init__()
        self._error, self._failures = error, failures

    def put(self, receipt: Any) -> dict:
        with self._lock:
            if self._failures > 0:
                self._failures -= 1
                self.put_calls += 1
                raise self._error
        return super().put(receipt)


class RecordingAdapter:
    """What the outbox calls: delegates to the adapter and records what it returned and what it raised."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.results: list[Any] = []
        self.errors: list[BaseException] = []
        self.calls = 0

    def execute_side_effect(self, entry: Any, grant: Any) -> Any:
        self.calls += 1
        try:
            result = self.inner.execute_side_effect(entry, grant)
        except BaseException as exc:
            self.errors.append(exc)
            raise
        self.results.append(result)
        return result

    def error_text(self) -> str:
        return "\n".join(
            "".join(traceback.format_exception(e)) + str(e) + repr(e) + repr(getattr(e, "args", ()))
            for e in self.errors
        )

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)


# ---------------------------------------------------------------------------
# Wiring


@dataclass
class Flow:
    """Steps 3 to 5 of the ordered flow, done; nothing is enqueued."""

    meeting: dict
    persons: dict
    draft: Any
    stored: dict
    gate: dict
    case: dict
    card: dict

    @property
    def entry(self) -> dict:
        return self.case["entry"]

    @property
    def ref(self) -> dict:
        return self.gate["item"]


@dataclass
class HostEnv:
    env: Env
    spy: TokenSpy
    cal: FakeHostCalendar
    artifacts: DraftArtifacts
    receipts: Any
    adapter: Any  # the real MeetingHostAdapter
    recorder: RecordingAdapter
    outbox: Any
    store: Any
    sleeps: list[float]
    alerts: list[dict]
    host_response: dict | None
    decl: dict = field(default_factory=host_decl)
    owner_for_world: Callable[[str], str] = lambda world_id: OWNER  # noqa: E731 - the world's owner (PE-12)
    baseline: int = 0  # parts emitted while connecting accounts: not part of the flow under test

    @property
    def emitted(self) -> list[dict]:
        return self.env.emitted

    @property
    def clock(self) -> ManualClock:
        return self.env.clock

    @property
    def broker(self) -> Any:
        return self.env.broker

    def parts_of(self, event_type: str) -> list[dict]:
        return self.env.parts_of(event_type)

    def transfers(self) -> list[dict]:
        return self.parts_of("data.transfer")

    def stored_receipts(self) -> list[Any]:
        """What the receipt store holds, whichever double (a list attribute or a method) lists it."""
        listed = self.receipts.receipts
        return list(listed() if callable(listed) else listed)

    def flow_parts(self) -> list[dict]:
        """The parts the flow itself emitted, after the accounts were connected."""
        return self.env.emitted[self.baseline :]

    def new_outbox(self) -> tuple[Any, Any]:
        """A second tilo-connectors instance over the same store, calendar and receipts: a fresh adapter."""
        from tilo_connectors.outbox import Outbox

        adapter, recorder = self._adapter(self.cal, self.receipts)
        outbox = Outbox(
            self.store,
            {CONNECTOR_ID: recorder},
            emit=self.env.emitted.append,
            clock=self.env.clock,
            alert=self.alerts.append,
        )
        return outbox, recorder

    def _adapter(self, cal: Any, receipts: Any) -> tuple[Any, RecordingAdapter]:
        adapter = mha().MeetingHostAdapter(
            declaration=copy.deepcopy(self.decl),
            broker=self.spy,
            transport=cal,
            artifacts=self.artifacts,
            owner_of=lambda world_id: self.owner_for_world(world_id),
            receipts=receipts,
            clock=self.env.clock,
            emit=self.env.emitted.append,
            sleep=self.sleeps.append,
        )
        return adapter, RecordingAdapter(adapter)

    def prepare(
        self,
        meeting_: dict | None = None,
        persons_: dict | None = None,
        *,
        run_id: str = RUN,
        world_id: str = WORLD,
        approver: str = OWNER,
        option: str = "approve",
        channel: str = "web",
        label: str | None = None,
        idempotency_key: str | None = None,
        max_duration_min: int = 60,
    ) -> Flow:
        meeting_ = meeting() if meeting_ is None else copy.deepcopy(meeting_)
        persons_ = default_persons() if persons_ is None else copy.deepcopy(persons_)
        draft = draft_of(meeting_, persons_, max_duration_min=max_duration_min)
        stored = self.artifacts.put_draft(draft.content, world_id=world_id, run_id=run_id, label=label)
        gate = mh().host_gate(draft, stored, copy.deepcopy(self.decl))
        case = build_case(
            draft,
            gate,
            run_id=run_id,
            world_id=world_id,
            approver=approver,
            option=option,
            channel=channel,
            idempotency_key=idempotency_key,
        )
        return Flow(meeting_, persons_, draft, stored, gate, case, build_card(gate, run_id=run_id, world_id=world_id))

    def settle(self, flow: Flow, **kw: Any) -> list[dict]:
        """Enqueue and dispatch once; the entries that settled."""
        enqueue(self.outbox, flow.case, **kw)
        return self.outbox.dispatch_due()

    def everything_emitted(self) -> str:
        return json.dumps(self.emitted, sort_keys=True, default=str)

    def host_token(self) -> str:
        return self.env.broker.access_token_for_adapter(OWNER, CONNECTOR_ID, required_scopes=[CALENDAR_EVENTS_OWNED])


def make_host_env(
    *,
    receipts: Any = None,
    connect_host: bool = True,
    connect_gmail: bool = False,
    start: str = T_NOW,
    conference: str | None = "success",
    max_attempts: int | None = None,
) -> HostEnv:
    from tilo_connectors.consent import ConsentService
    from tilo_connectors.outbox import Outbox
    from tilo_connectors.store import InMemoryOutboxStore

    env = make_env()
    env.clock.set(start)
    env.service = ConsentService(
        connectors={**declarations(), CONNECTOR_ID: host_decl()},
        broker=env.broker,
        http=env.google,
        settings=env.settings,
        clock=env.clock,
        emit=env.emitted.append,
    )
    response = env.connect(OWNER, CONNECTOR_ID, [CALENDAR_EVENTS_OWNED]) if connect_host else None
    if connect_gmail:
        env.connect(OWNER, "gmail", [GMAIL_READONLY])
    spy = TokenSpy(env.broker)
    cal = FakeHostCalendar(env.google, conference=conference)
    host = HostEnv(
        env=env,
        spy=spy,
        cal=cal,
        artifacts=DraftArtifacts(),
        receipts=receipts if receipts is not None else mh().InMemoryReceiptStore(),
        adapter=None,
        recorder=None,  # type: ignore[arg-type]
        outbox=None,
        store=InMemoryOutboxStore(),
        sleeps=[],
        alerts=[],
        host_response=response,
    )
    host.baseline = len(env.emitted)
    host.adapter, host.recorder = host._adapter(cal, host.receipts)
    host.outbox = Outbox(
        host.store,
        {CONNECTOR_ID: host.recorder},
        emit=env.emitted.append,
        clock=env.clock,
        alert=host.alerts.append,
    )
    return host


# ---------------------------------------------------------------------------
# The gate-authorised outbox case and the gate card (steps 5 to 7)

_OUTBOX_IDS = itertools.count(9600)


def next_outbox_id() -> str:
    return f"01JB5VQ000000000000000{next(_OUTBOX_IDS):04d}"


def build_case(
    draft: Any,
    gate: dict,
    *,
    run_id: str = RUN,
    world_id: str = WORLD,
    approver: str = OWNER,
    option: str = "approve",
    channel: str = "web",
    idempotency_key: str | None = None,
    created_at: str = T_NOW,
) -> dict:
    """The case the harness writes after the Owner approves the card: exactly the values `host_gate` returned."""
    outbox_id = next_outbox_id()
    case = gate_case(
        outbox_id=outbox_id,
        idempotency_key=idempotency_key or f"{run_id}:{UNIT}:create_meeting_event:{outbox_id[-4:]}",
        connector=gate["connector"],
        action_type=gate["action_type"],
        recipients=tuple(gate["recipients"]),
        destination=gate["destination"],
        item=copy.deepcopy(gate["item"]),
        risk_tier=gate["risk_tier"],
        approver=approver,
        world_id=world_id,
        run_id=run_id,
        created_at=created_at,
    )
    case["entry"]["modifiers"] = list(gate["modifiers"])
    case["entry"]["attachments"] = list(gate["attachments"])
    case["entry"]["undo_window_s"] = gate["undo_window_s"]
    case["reserved_by"]["data"]["irreversible"] = gate["irreversible"]
    case["authorised_by"]["data"]["option"] = option
    case["authorised_by"]["data"]["channel"] = channel
    return case


def build_card(gate: dict, *, run_id: str = RUN, world_id: str = WORLD) -> dict:
    """The gate card the deterministic card builder makes (API doc, ordered flow step 5)."""
    return {
        "id": CARD_ID,
        "world_id": world_id,
        "run_id": run_id,
        "header": {"building": "B1", "agent": AGENT},
        "add_context": False,
        "created_at": T_NOW,
        "timeout": 3600,
        "gate": {
            "id": "G1",
            "action": {
                "type": gate["action_type"],
                "connector": gate["connector"],
                "exact": gate["exact"],
                "item": copy.deepcopy(gate["item"]),
                "destination": gate["destination"],
            },
            "recipients": list(gate["recipients"]),
            "irreversible": gate["irreversible"],
            "risk_tier": gate["risk_tier"],
        },
        "consent": None,
        "kind": "gate",
        "rung": "gate",
        "what_happened": "The meeting invitation is drafted and ready to send.",
        "why_it_matters": "Google emails an invitation to every person listed, and it cannot be unsent.",
        "options": [
            {"id": "approve", "label": "Approve", "suggested": False, "irreversible": True},
            {
                "id": "edit",
                "label": "Edit first",
                "suggested": True,
                "reason": "Every invitee is a new recipient, so check the list once.",
                "irreversible": False,
            },
            {"id": "hold", "label": "Hold", "suggested": False, "irreversible": False},
        ],
        "actions": ["show_me", "snooze"],
        "answer_channels": ["web", "mobile_web"],
        "safe_default": "hold",
    }


def enqueue(outbox: Any, case: dict, *, option: str | None = None, authorised_by: Any = "keep", entry: Any = None):
    from _connectors_lib import evidence_from_case

    evidence = evidence_from_case(copy.deepcopy(case))
    if option is not None:
        evidence["authorised_by"]["data"]["option"] = option
    if authorised_by != "keep":
        evidence["authorised_by"] = authorised_by
    return outbox.enqueue(copy.deepcopy(case["entry"] if entry is None else entry), evidence)


def literal_gate(recipients: tuple[str, ...] = (ASHA, PRIYA_MAIL), *, stored_label: str | None = None) -> dict:
    """What `host_gate` must return, written out from the API doc (not computed by the module)."""
    ref: dict[str, Any] = {"artifact_id": "art_meeting_event", "version": 1}
    return {
        "action_type": ACTION_TYPE,
        "connector": CONNECTOR_ID,
        "risk_tier": "T3",
        "irreversible": True,
        "modifiers": ["new_recipients"],
        "recipients": list(recipients),
        "attachments": [],
        "item": ref,
        "destination": "primary",
        "exact": oracle_exact("Q4 planning", T_START, T_END, IST, len(recipients), 0),
        "undo_window_s": 0,
    }


# ---------------------------------------------------------------------------
# Leak scanning


def planted_needles(host: HostEnv) -> list[str]:
    return host.cal.plant.needles()


def everything_text(
    host: HostEnv, caplog: Any, *extra: str, with_drafts: bool = True, with_recipients: bool = True
) -> str:
    """Every place a link or an address could land: parts, logs of every logger, exception text, receipts,
    stored artifacts, the outbox rows and the cards and reprs a test passes in. For the address check
    (`with_drafts=False`, `with_recipients=False`) the draft artifact and the outbox rows' `recipients` field,
    the two places an address may be (with the card's `gate.recipients`), are left out."""
    rows = []
    for row in host.store.all_entries():
        row = copy.deepcopy(row)
        if not with_recipients:
            row.pop("recipients", None)
        rows.append(row)
    pieces = [
        host.everything_emitted(),
        caplog_text(caplog),
        host.recorder.error_text(),
        json.dumps(rows, sort_keys=True, default=str),
        repr(host.adapter),
        repr(host.recorder.results),
        *extra,
    ]
    if with_drafts:
        pieces += [b.decode("utf-8", "replace") for b in host.artifacts.all_bytes()]
    receipts = host.receipts
    if hasattr(receipts, "all_bytes"):
        pieces += [b.decode("utf-8", "replace") for b in receipts.all_bytes()]
    else:
        pieces.append(repr(getattr(receipts, "receipts", "")))
    return "\n".join(pieces)


def caplog_text(caplog: Any) -> str:
    out = []
    for record in caplog.records:
        out.append(record.getMessage())
        out.append(repr(record.args))
        if record.exc_info:
            out.append("".join(traceback.format_exception(*record.exc_info)))
        if record.exc_text:
            out.append(record.exc_text)
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Static checks


def module_source(path: pathlib.Path) -> str:
    assert path.is_file(), f"{path} does not exist yet"
    return path.read_text(encoding="utf-8")


def import_roots(path: pathlib.Path) -> set[str]:
    """Every dotted module name the file imports (absolute, and relative ones with their dots)."""
    tree = ast.parse(module_source(path), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            names.add("." * node.level + (node.module or ""))
    return names


def string_constants(path: pathlib.Path) -> list[str]:
    tree = ast.parse(module_source(path), filename=str(path))
    return [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def instant(value: str) -> datetime:
    return parse_ts(value).astimezone(UTC)
