"""Helpers for the FR-MTG-09 host-route tests (ticket MTG09-b, the tilo-api half; the interface is pinned in
`API_MTG09_b.md`, the connector half in services/connectors/tests/API_FR_MTG_09.md).

Named `_mtg09b_lib` for the same global-bare-module-name reason as `_ppl11a_lib.py`. Nothing here is business logic:
it builds schema-valid records, fakes the two Google seams (the token broker and the HTTP transport behind
`MeetingHostAdapter`), and drives the real `tilo_api.app` through `TestClient`. A seam production does not have yet
resolves to a placeholder key (`_clint1_lib.seam`), so a missing seam shows up as a failed request, never as an
`AttributeError` in set-up.

What the doubles keep out of production code: `FakeHostCalendar` answers EVERY call with a full event (a planted Meet
link, a planted `htmlLink`, an entry point and the attendee list) whatever the request's `fields` mask says, so only the
adapter and the API can keep them out of what Tilo stores, logs and emits (FR-MTG-09 (c)).

No network (create_connection and getaddrinfo raise), no paid call, no model id, no LIVE; every token is assembled at
run time; every address is at example.com, example.net or example.org.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import re
import secrets
import socket
import threading
import time
from collections.abc import Callable
from typing import Any

from _clint1_lib import registered_event_types, seam
from _clint2_lib import SKILLS_ROOT, ArtifactRig, ClearModel, StreamWriter, layout_for, wait_for
from _ppl11a_lib import DEV, MEERA, ORG, OWNER, PRIYA, SAM, Rig
from tilo_connectors import InMemoryOutboxStore
from tilo_connectors.registry import load_registry

# --- names the pinned interface fixes ---

R_HOST = ("POST", "/v1/meetings/{meeting_id}/host")
CONNECTOR_ID = "meeting_host"
ACTION_TYPE = "create_meeting_event"
CALENDAR_EVENTS_OWNED = "https://www.googleapis.com/auth/calendar.events.owned"
EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
EVENT_FIELDS = "id,status,conferenceData(createRequest(status(statusCode)))"
INSERT_PARAMS = {"conferenceDataVersion": 1, "sendUpdates": "all", "fields": EVENT_FIELDS}
HOST_CALENDAR = "primary"

MEETING = "mt_host1"
WORLD = "w_meeting_host1"
RUN = "r_meeting_host1_1"
TITLE = "Q4 planning"
IST = "Asia/Kolkata"
T_START = "2030-01-15T09:00:00.000Z"  # far enough ahead that no wall clock a builder might use is past it
T_END = "2030-01-15T10:00:00.000Z"
WHEN_IST = "Tue 15 Jan 2030, 14:30 to 15:30"  # 09:00 to 10:00 UTC shown in Asia/Kolkata

ASHA, PRIYA_MAIL, SAM_MAIL, DEV_MAIL = "asha@example.com", "priya@example.com", "sam@example.com", "dev@example.com"
ATTACKER = "eve@example.org"
PLANTED_LINK = "https://" + "meet.google.com/" + "zzz-yyyy-xxx"
PLANTED_HTML = "https://www.google.com/calendar/event?eid=" + "PLANTEDEID0123"
DRAFT_KEY = re.compile(rf"{RUN}:U[0-9]{{1,4}}:[0-9]{{1,4}}:0")  # AR-05, output index 0
ULID = re.compile(r"[0-7][0-9A-HJKMNP-TV-Z]{25}")


def block_network(monkeypatch: Any) -> None:
    """EFF-01: no FR-MTG-09 test reaches a network. Only the two calls that leave the machine raise; a loopback
    socket pair (the event loop's own) stays usable."""

    def refuse(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("a FR-MTG-09 test tried to use the network")

    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.delenv("LIVE", raising=False)


# --- records ---


def attendees_of(*users: str | None, unresolved: tuple[str, ...] = ()) -> list[dict[str, Any]]:
    names = {OWNER: "Asha Rao", PRIYA: "Priya", SAM: "Sam", DEV: "Dev", MEERA: "Meera"}
    out = [{"name": names.get(u, u), "user": u} for u in users]
    return out + [{"name": name, "user": None} for name in unresolved]


def meeting(**over: Any) -> dict[str, Any]:
    """A `scheduled`, `bot`-sourced meeting of u_owner in the world `w_meeting_host1`, as the store holds it. By
    default: the owner, Priya, Sam and one attendee with no Tilo account (so three recipients and one not invited)."""
    record: dict[str, Any] = {
        "id": MEETING,
        "org_id": ORG,
        "owner": OWNER,
        "title": TITLE,
        "series": None,
        "scheduled": {"start": T_START, "end": T_END},
        "agenda": [{"title": "Launch date", "minutes": 15}],
        "attendees": attendees_of(OWNER, PRIYA, SAM, unresolved=("Dev from Acme",)),
        "attestation": {"by": OWNER, "at": "2026-10-05T09:00:00.000Z", "notice_version": "1.0.0"},
        "source": "bot",
        "status": "scheduled",
        "ended_reason": None,
        "minutes_confirmed_by": None,
        "transcript": None,
        "minutes": None,
        "delete_transcript_after": None,
        "delete_minutes_after": None,
        "created_at": "2026-10-05T09:00:00.000Z",
        "world_id": WORLD,
    }
    record.update(over)
    return record


def person(user: str, email: str, *, org: str = ORG, zone: str = IST, name: str | None = None) -> dict[str, Any]:
    return {
        "id": user,
        "org_id": org,
        "display_name": name or user.removeprefix("u_").title(),
        "aliases": [],
        "email": email,
        "time_zone": zone,
        "preferred_channel": "email",
        "org_role": "member",
        "memberships": [],
        "created_by": {"by": OWNER, "at": "2026-10-05T09:00:00.000Z"},
    }


# --- oracles, written from the API doc's text (API_FR_MTG_09.md), never from the code under test ---


def expected_exact(title: str, when: str, zone: str, recipients: int, not_invited: int) -> str:
    skipped = ""
    if not_invited > 0:
        plural = not_invited != 1
        skipped = (
            f"{not_invited} attendee{'s' if plural else ''} without a Tilo account "
            f"{'are' if plural else 'is'} not invited. "
        )
    return (
        f'Creates "{title}" on the Tilo meeting host\'s Google Calendar, {when} ({zone}), with a new Google Meet '
        f"link. Google emails an invitation from the meeting host account to the {recipients} people listed, you "
        f"included. {skipped}Guests cannot add people or see each other's addresses. An invitation cannot be unsent."
    )


def expected_draft(recipients: list[str], *, title: str = TITLE, zone: str = IST) -> dict[str, Any]:
    return {
        "v": "1.0",
        "kind": "meeting_event",
        "meeting_id": MEETING,
        "owner": OWNER,
        "title": title,
        "start": T_START,
        "end": T_END,
        "time_zone": zone,
        "attendees": list(recipients),
        "conference": "hangoutsMeet",
        "send_updates": "all",
        "guests_can_invite_others": False,
        "guests_can_modify": False,
        "guests_can_see_other_guests": False,
    }


def canonical(doc: dict[str, Any]) -> bytes:
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def marker_of(entry: dict[str, Any]) -> str:
    """The event id the adapter asks Google for: 32 lower-case hex characters of sha256(world_id NUL key)."""
    return hashlib.sha256(f"{entry['world_id']}\x00{entry['idempotency_key']}".encode()).hexdigest()[:32]


def expected_insert_body(entry: dict[str, Any], draft: dict[str, Any]) -> dict[str, Any]:
    marker = marker_of(entry)
    return {
        "id": marker,
        "summary": draft["title"],
        "start": {"dateTime": draft["start"], "timeZone": draft["time_zone"]},
        "end": {"dateTime": draft["end"], "timeZone": draft["time_zone"]},
        "attendees": [{"email": a} for a in draft["attendees"]],
        "conferenceData": {"createRequest": {"requestId": marker, "conferenceSolutionKey": {"type": "hangoutsMeet"}}},
        "guestsCanInviteOthers": False,
        "guestsCanModify": False,
        "guestsCanSeeOtherGuests": False,
    }


# --- the two Google seams, faked ---


class FakeApiResponse:
    def __init__(self, status: int, body: Any = None) -> None:
        self.status_code = status
        self.headers: dict[str, str] = {}
        self._body = body
        self.content = b"" if body is None else json.dumps(body).encode()

    def json(self) -> Any:
        if self._body is None:
            raise ValueError("no body")
        return copy.deepcopy(self._body)


class FakeHostCalendar:
    """`Transport` for `POST .../calendars/primary/events` and `GET .../events/{id}`. Keeps events by id, answers 409
    for a known id, counts one invitation per attendee on the first successful insert that carries
    `sendUpdates=all`, and never applies the `fields` mask. `conference` is the status it reports."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.events: dict[str, dict[str, Any]] = {}
        self.invitations: dict[str, int] = {}
        self.conference = "success"
        self._lock = threading.Lock()

    def _answer(self, event_id: str, attendees: list[str]) -> dict[str, Any]:
        return {
            "id": event_id,
            "status": "confirmed",
            "hangoutLink": PLANTED_LINK,
            "htmlLink": PLANTED_HTML,
            "attendees": [{"email": a} for a in attendees],
            "conferenceData": {
                "createRequest": {"status": {"statusCode": self.conference}},
                "entryPoints": [{"entryPointType": "video", "uri": PLANTED_LINK}],
            },
        }

    def request(
        self,
        method: str,
        url: str,
        *,
        params: Any = None,
        headers: Any = None,
        json: Any = None,  # noqa: A002 - the Transport protocol's own name
        content: bytes | None = None,
    ) -> FakeApiResponse:
        with self._lock:
            self.requests.append(
                {
                    "method": method,
                    "url": url,
                    "params": copy.deepcopy(dict(params or {})),
                    "headers": {k.lower(): v for k, v in dict(headers or {}).items()},
                    "json": copy.deepcopy(json),
                }
            )
            if method == "POST" and url == EVENTS_URL:
                event_id = json["id"]
                if event_id in self.events:
                    return FakeApiResponse(409, {"error": {"code": 409}})
                attendees = [a["email"] for a in json["attendees"]]
                self.events[event_id] = self._answer(event_id, attendees)
                if (params or {}).get("sendUpdates") == "all":
                    self.invitations[event_id] = len(attendees)
                return FakeApiResponse(200, self.events[event_id])
            if method == "GET" and url.startswith(EVENTS_URL + "/"):
                found = self.events.get(url.rsplit("/", 1)[1])
                return FakeApiResponse(200, found) if found else FakeApiResponse(404, {"error": {"code": 404}})
            return FakeApiResponse(404, {"error": {"code": 404}})


class FakeBroker:
    """The token broker's adapter-facing half. `connected` False makes a call raise `NotConnected` (the outbox then
    waits for a person and spends no attempt). `disconnect` flips it and hands `connection.revoked` to `emit`,
    in the shape `TokenBroker._emit_part` uses."""

    def __init__(self) -> None:
        self.connected = True
        self.calls: list[tuple[str, str, tuple[str, ...], bool]] = []
        self.token = "ya29." + secrets.token_hex(24)  # assembled at run time
        self.emit: Callable[[dict[str, Any]], None] | None = None

    def access_token_for_adapter(
        self, user_id: str, connector: str, *, required_scopes: Any, force_refresh: bool = False
    ) -> str:
        from tilo_connectors.tokens import NotConnected  # noqa: PLC0415

        self.calls.append((user_id, connector, tuple(required_scopes), force_refresh))
        if not self.connected:
            raise NotConnected("no connection for this user and connector")
        return self.token

    def connection_state(self, user_id: str, connector: str) -> str | None:
        return "connected" if self.connected else None

    def revoked_part(self, user_id: str, connector: str = CONNECTOR_ID) -> dict[str, Any]:
        return {"type": "connection.revoked", "authz": None, "data": {"connector": connector}, "user_id": user_id}

    def disconnect(self, user_id: str, connector: str) -> None:
        self.connected = False
        if self.emit is not None:
            self.emit(self.revoked_part(user_id, connector))


class _RefusingRunner:
    """A unit runner the host path must never ask: the plan is fixed, no Director and no worker model is called."""

    def __init__(self, calls: list[str]) -> None:
        self._calls = calls

    async def run(self, unit: Any, context: Any) -> Any:
        from tilo_harness.executor import UnitOutcome  # noqa: PLC0415

        self._calls.append(unit["id"])
        return UnitOutcome(success=False, summary="the host path never runs a worker model")


# --- the rig ---


class HostRig:
    """A PPL-11a `Rig` (people stores, principal, clock) plus everything a hosted run needs behind its seams: the
    event writer and `deps.Store` the run reads, one artifact store, an outbox store, the shipped connector registry,
    the fake broker and the fake calendar. `rig.event_store` is the one `deps.Store` (worlds, events, runs)."""

    def __init__(self, rig: Rig, *, with_meeting: bool = True) -> None:
        from tilo_api import deps  # noqa: PLC0415

        self.rig, self.deps = rig, deps
        self.timeline: list[str] = []
        self.art = ArtifactRig()
        self.writer = StreamWriter(rig.event_store, self.timeline)
        self.outbox_store = InMemoryOutboxStore()
        self.calendar = FakeHostCalendar()
        self.broker = FakeBroker()
        self.registry = load_registry(rig.deps._REPO_ROOT / "config" / "connectors.yaml")
        self.compile_calls: list[dict[str, Any]] = []
        self.runner_calls: list[str] = []
        self.resolver_calls: list[dict[str, Any]] = []
        self.store = rig.event_store
        self.store.worlds[WORLD] = deps.WorldRecord(owner=OWNER, districts={}, run_id=RUN)
        rig.add_people()
        if with_meeting:
            rig.add("meetings", meeting())
        rig.as_user(OWNER)
        ov = rig.app.dependency_overrides
        ov[deps.get_store] = lambda: self.store
        ov[deps.get_event_writer] = lambda: self.writer
        ov[seam(deps, "get_artifact_store")] = lambda: self.art.store
        ov[seam(deps, "get_redactor")] = lambda: self.art.redactor
        ov[seam(deps, "get_run_archive")] = lambda: self.art.open_archive
        ov[seam(deps, "get_outbox_store")] = lambda: self.outbox_store
        ov[seam(deps, "get_connector_registry")] = lambda: self.registry
        ov[seam(deps, "get_connector_adapters")] = lambda: {}  # the host path builds its own adapter (API_MTG09_b.md)
        ov[seam(deps, "get_token_broker")] = lambda: self.broker
        ov[seam(deps, "get_meeting_host_transport")] = lambda: self.calendar
        ov[seam(deps, "get_plan_compiler")] = lambda: self._compile
        ov[seam(deps, "get_layout_builder")] = lambda: self._layout
        ov[seam(deps, "get_unit_runner")] = lambda: _RefusingRunner(self.runner_calls)
        ov[seam(deps, "get_action_resolver")] = lambda: self._resolve
        ov[seam(deps, "get_skill_registry")] = lambda: _no_skills()
        clear = {role: ClearModel() for role in ("director", "lead", "specialist", "verifier", "writer", "narrator")}
        ov[seam(deps, "get_must_ask_providers")] = lambda: clear

    # seam callables --------------------------------------------------------------------------------------------------

    def _compile(self, **kw: Any) -> dict:
        self.compile_calls.append(kw)
        raise AssertionError("a hosted meeting is a fixed plan: the Director is never asked")

    @staticmethod
    def _layout(plan: dict, *, world_id: str) -> dict:
        return layout_for(plan, world_id=world_id)

    def _resolve(self, *, unit: dict, action_type: str, item: dict, brief: dict) -> dict:
        """The generic address-book resolver. A host run must never take its recipients from it: it answers a
        stranger, so any use shows up as that address on a card, an entry or a request."""
        self.resolver_calls.append({"unit": unit["id"], "action_type": action_type})
        return {"destination": "thread-elsewhere", "recipients": [ATTACKER], "known_recipients": []}

    # driving ---------------------------------------------------------------------------------------------------------

    def host(self, actor: str = OWNER, meeting_id: str = MEETING, body: Any = None) -> Any:
        self.rig.as_user(actor)
        return self.rig.client.post(f"/v1/meetings/{meeting_id}/host", json={} if body is None else body)

    def sign_in_world(self, user: str = OWNER, role: str = "owner") -> None:
        self.rig.as_user(user, role=role, world_id=WORLD)

    def cards(self) -> list[dict[str, Any]]:
        self.sign_in_world()
        response = self.rig.client.get(f"/worlds/{WORLD}/cards")
        assert response.status_code == 200, response.text[:200]
        return response.json()

    def gate_cards(self) -> list[dict[str, Any]]:
        return [c for c in self.cards() if c["kind"] == "gate"]

    def wait_gate(self) -> dict[str, Any]:
        found = wait_for(lambda: self.gate_cards() or None, what="the host gate card")
        assert len(found) == 1, found
        return found[0]

    def answer(self, card_id: str, option: str, channel: str = "web") -> Any:
        self.sign_in_world()
        return self.rig.client.post(
            f"/worlds/{WORLD}/cards/{card_id}/answer", json={"option": option, "channel": channel}
        )

    def host_and_wait_gate(self) -> dict[str, Any]:
        response = self.host()
        assert response.status_code == 200, response.text[:300]
        return self.wait_gate()

    def approve_and_wait_sent(self) -> dict[str, Any]:
        card = self.host_and_wait_gate()
        answered = self.answer(card["id"], "approve")
        assert answered.status_code == 200, answered.text[:200]
        wait_for(lambda: self.events("data.transfer"), what="data.transfer")
        return card

    def events(self, type_: str | None = None) -> list[dict[str, Any]]:
        stream = list(self.store.events.get(WORLD, []))
        return stream if type_ is None else [e for e in stream if e["type"] == type_]

    def entries(self) -> list[dict[str, Any]]:
        return [dict(e) for e in self.outbox_store.all_entries()]

    def quiet(self, seconds: float = 0.6) -> None:
        """Lets a run that would act, act: nothing here is sent in the time a run needs for its first dispatch."""
        time.sleep(seconds)

    def nothing_happened(self) -> dict[str, Any]:
        """Everything a refused host request must leave alone."""
        return {
            "people": self.rig.snapshot(),
            "events": {w: len(e) for w, e in self.store.events.items()},
            "runs": sorted(self.store.runs),
            "entries": self.entries(),
            "calendar": list(self.calendar.requests),
            "broker": list(self.broker.calls),
            "artifacts": sorted(self.art.meta.paths("")),
            "compile": list(self.compile_calls),
            "runner": list(self.runner_calls),
        }

    def scope(self) -> Any:
        return self.art.scope(WORLD, OWNER)

    def requested(self) -> dict[str, Any]:
        found = self.events("approval.requested")
        assert len(found) == 1, [e["type"] for e in self.events()]
        return found[0]

    def draft(self) -> tuple[dict[str, Any], dict[str, Any], bytes]:
        """(ref, stored record, bytes) of the draft the one gate holds, read back from the artifact store."""
        ref = dict(self.requested()["data"]["item"])
        stored = self.art.store.head(self.scope(), ref)
        assert stored is not None, ref
        return ref, stored.record, self.art.store.read(self.scope(), ref)

    def receipt_refs(self) -> list[dict[str, Any]]:
        draft = self.requested()["data"]["item"]
        made = [dict(e["data"]["artifact"]) for e in self.events("artifact.created")]
        same = (draft["artifact_id"], draft["version"])
        return [
            {"artifact_id": r["artifact_id"], "version": r["version"]}
            for r in made
            if (r["artifact_id"], r["version"]) != same and self.art.store.head(self.scope(), r) is not None
        ]

    def principal_as(self, principal: Any) -> None:
        """Answers as exactly this principal (another person, another channel) until `rig.as_user` is called."""
        self.rig.app.dependency_overrides[self.deps.get_current_principal] = lambda: principal

    def restore_principal(self) -> None:
        self.rig.app.dependency_overrides[self.deps.get_current_principal] = self.rig._principal


def _no_skills() -> Any:
    from tilo_harness.skills import SkillRegistry  # noqa: PLC0415

    return SkillRegistry(SKILLS_ROOT)


# --- scans ---


def stored_text(hr: HostRig) -> dict[str, str]:
    """Every place Tilo kept something, as text, by place: the event stream, the outbox rows, every artifact record
    and blob, the people store (a record the route must not have written to)."""
    places: dict[str, str] = {
        "events": json.dumps(hr.store.events, sort_keys=True, default=str),
        "outbox": json.dumps(hr.entries(), sort_keys=True, default=str),
        "people": hr.rig.snapshot(),
    }
    for path in hr.art.meta.paths(""):
        places[f"artifact-record:{path}"] = json.dumps(hr.art.meta.get(path), sort_keys=True, default=str)
    for key in hr.art.blobs.keys(""):
        places[f"artifact-blob:{key}"] = hr.art.blobs.read(key).decode("utf-8", "replace")
    return places


class LogCatcher:
    """Every record of every logger at DEBUG, as text (pytest's caplog does the capturing)."""

    def __init__(self, caplog: Any) -> None:
        caplog.set_level(logging.DEBUG)
        self._caplog = caplog

    def text(self) -> str:
        return "\n".join(f"{r.name} {r.getMessage()}" for r in self._caplog.records)


def assert_registered_and_valid(registry: Any, repo_root: Any, stream: list[dict[str, Any]]) -> None:
    """Every event the host run wrote: schema-valid with its type's data schema (EV-02) and registered."""
    from _api_contracts_lib import assert_valid_event  # noqa: PLC0415

    registered = registered_event_types(repo_root)
    assert {e["type"] for e in stream} <= registered, {e["type"] for e in stream} - registered
    for event in stream:
        assert_valid_event(repo_root, registry, event)
