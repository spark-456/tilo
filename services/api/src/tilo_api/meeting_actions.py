"""ADR-0042 amendment 1 (owner decision 21 Oct, BQ-MTG-ACTIONS-1): what the meeting bot may write, and as whom.

`POST /internal/meeting-actions/run` is a public route of the access gate and of App Check that checks its own caller:
a Google ID token for `TILO_MEETING_ACTIONS_AUDIENCE` from `TILO_MEETING_ACTIONS_CALLER` (the meeting bot's account;
unset, the voice meter's pair is used, never the schedule tick's or the Tasks one). The body names the meeting, the
attend's ACTION nonce, an idempotency key, the speaker's caption name (or none: the owner, one-on-one), one of three
actions and its arguments, nothing else (closed schemas, 4 KiB). The owner comes from the claim; a named speaker must
match exactly one person the owner can see (`tilo_people.names.match_name`, no fuzzy match) and the write runs as that
person through the same people writes, access oracle and Desk events a signed-in request uses:

- `create_pin`: a pin on the speaker's own personal board, or on their team's board (they must be in exactly one team).
- `add_agenda_item`: appended to THIS meeting's agenda, as its owner (max 20 items).
- `create_meeting`: a Tilo meeting on the speaker's Agenda, owned by them, with no attendees; only with
  `recording_attested` (the person said yes to "you have the right to record it"). No Google Calendar event, no invite.

At most five writes per call (`MAX_ACTIONS`); a key already answered gets the same answer and writes nothing. The
accepted risk: a caption name is the identity, so a participant who renames themselves could act as someone else.

INERT until the owner sets `TILO_MEETING_ACTIONS=1`: after bearer syntax is checked, anything else is a plain 404."""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationError, field_validator, model_validator
from tilo_harness.schedule import tick_caller_ok
from tilo_people.names import match_name

from tilo_api import deps, ephemeral, meeting_action_claims, schedules
from tilo_api.meeting_action_claims import MAX_ACTIONS, ActionClaim, ActionClaims
from tilo_api.people_events import WorkEvents
from tilo_api.people_meetings import MeetingEditIn, edit_meeting
from tilo_api.people_pins import PinIn, create_pin
from tilo_api.people_writes import AgendaIn, MeetingIn, Refusal, WindowIn, Writer, create_meeting

logger = logging.getLogger("tilo_api.meeting_actions")
router = APIRouter()
ROUTE = "/internal/meeting-actions/run"
ENV_AUDIENCE, ENV_CALLER = "TILO_MEETING_ACTIONS_AUDIENCE", "TILO_MEETING_ACTIONS_CALLER"
_METER_AUDIENCE, _METER_CALLER = "TILO_VOICE_METER_AUDIENCE", "TILO_VOICE_METER_CALLER"
MAX_BODY = 4096
_AUDIENCE = re.compile(r"https://[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?(?::[0-9]{1,5})?")
Line = Annotated[str, Field(min_length=1, max_length=120)]


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PinArgs(_Closed):
    title: Line
    body: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    board: Literal["personal", "team"]


class AgendaArgs(_Closed):
    title: Line
    minutes: Annotated[int, Field(ge=1, le=240)] | None = None


class MeetingArgs(_Closed):
    title: Line
    start: Annotated[str, Field(min_length=10, max_length=40)]
    minutes: Annotated[int, Field(ge=5, le=480)]
    recording_attested: StrictBool = False

    @model_validator(mode="after")
    def _attested(self) -> MeetingArgs:
        if self.recording_attested is not True:  # the spoken "yes, I have the right to record it" (PE-18, by voice)
            raise ValueError("recording not attested")
        return self

    @field_validator("start")
    @classmethod
    def _aware(cls, value: str) -> str:
        when = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if when.tzinfo is None:
            raise ValueError("start needs a time zone")
        return value


class ActionRequest(_Closed):
    meeting_id: Annotated[str, Field(pattern=r"^mt_[A-Za-z0-9_]{1,64}$")]
    claim: Annotated[str, Field(min_length=1, max_length=64)]
    key: Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
    speaker: Annotated[str, Field(min_length=1, max_length=80)] | None = None
    action: Literal["create_pin", "add_agenda_item", "create_meeting"]
    args: dict[str, Any]


_ARGS: dict[str, type[_Closed]] = {"create_pin": PinArgs, "add_agenda_item": AgendaArgs, "create_meeting": MeetingArgs}


def _out(status: int, body: dict[str, Any], action: str, outcome: str) -> JSONResponse:
    logger.info("meeting action %s %s %s", action, status, outcome)  # the action, status and outcome only
    return JSONResponse(body, status_code=status, headers={"Cache-Control": "no-store"})


def _pins() -> tuple[str, str] | None:
    """(audience, caller) when both are set and valid and the caller is not the tick's or the Tasks account."""
    audience = os.environ.get(ENV_AUDIENCE) or os.environ.get(_METER_AUDIENCE) or ""
    caller = os.environ.get(ENV_CALLER) or os.environ.get(_METER_CALLER) or ""
    others = {os.environ.get(schedules.ENV_CALLER) or "", os.environ.get(schedules.ENV_TASKS_CALLER) or ""}
    if not _AUDIENCE.fullmatch(audience) or not caller or caller in others:
        return None
    return audience, caller


def _bearer(request: Request) -> str | None:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    token = token.strip()
    return token if scheme.lower() == "bearer" and token and not any(c.isspace() for c in token) else None


async def _read_body(request: Request) -> bytes | None:
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BODY:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


def _seam(request: Request, fn: Callable[..., Any], *, takes_request: bool = True) -> Any:
    override = request.app.dependency_overrides.get(fn)
    if override is not None:
        return override()
    return fn(request) if takes_request else fn()


@router.post(ROUTE)
async def run_action(request: Request) -> JSONResponse:
    if (token := _bearer(request)) is None:
        return _out(401, {"error": "unauthenticated"}, "-", "unauthenticated")
    if not meeting_action_claims.enabled():  # the default: as if the route did not exist
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    if (pins := _pins()) is None:
        return _out(503, {"error": "not_configured"}, "-", "not_configured")
    audience, caller = pins
    try:
        verifier = _seam(request, schedules.get_oidc_verifier, takes_request=False)
        claims = await run_in_threadpool(verifier.verify, token, audience)
    except Exception as exc:  # bad signature, expiry, audience or a verifier outage: the type only, never the text
        logger.warning("meeting action token refused (%s)", type(exc).__name__)
        return _out(401, {"error": "unauthenticated"}, "-", "unauthenticated")
    if not isinstance(claims, Mapping) or not tick_caller_ok(claims, audience=audience, caller=caller):
        return _out(403, {"error": "forbidden"}, "-", "forbidden")
    # The bot's call carries no Firebase sign-in: after the OIDC check above (and only then) the seams hand out the
    # durable stores without resolving a principal, the schedule tick's pattern. Without it every seam was a 401.
    ephemeral.mark_no_person(request)
    raw = await _read_body(request)
    try:
        if raw is None:
            raise ValueError("too large")
        body = ActionRequest.model_validate_json(raw)
        args = _ARGS[body.action].model_validate(body.args)
    except (ValidationError, ValueError):
        return _out(422, {"error": "invalid_request"}, "-", "invalid_request")
    return await run_in_threadpool(_decide, request, body, args)


def _decide(request: Request, body: ActionRequest, args: _Closed) -> JSONResponse:
    registry: ActionClaims | None = _seam(request, meeting_action_claims.get_action_claims, takes_request=False)
    claim = registry.find(body.meeting_id, body.claim) if registry is not None else None
    if claim is None:  # absent, wrong nonce, another attend's, expired: one answer
        return _out(409, {"outcome": "not_attending"}, body.action, "not_attending")
    with claim.lock:
        if body.key in claim.replies:  # the same request again: the same answer, nothing written twice
            status, answer = claim.replies[body.key]
            return _out(status, answer, body.action, "replay")
        if claim.done >= MAX_ACTIONS:
            return _out(409, {"outcome": "cap_reached"}, body.action, "cap_reached")
        try:
            status, answer = _act(request, claim, body, args)
        except Refusal as refusal:
            code = refusal.status_code
            status, answer = (code if code in (404, 409) else 409), {"outcome": "refused"}
        except Exception as exc:  # a store or seam failure: never the record's text or the cause
            seam = exc.status_code if isinstance(exc, HTTPException) else "-"
            logger.warning("meeting action failed (%s %s)", type(exc).__name__, seam)
            return _out(503, {"outcome": "unavailable"}, body.action, "unavailable")
        if status == 200:
            claim.done += 1
        claim.replies[body.key] = (status, answer)
        return _out(status, answer, body.action, str(answer.get("outcome")))


def _writer(request: Request, actor: str, org: str) -> Writer:
    stores = _seam(request, deps.get_people_stores)
    clock = _seam(request, deps.get_clock, takes_request=False)
    w = Writer(stores, org, actor, clock(), _seam(request, deps.get_redactor))
    w.events = WorkEvents(_seam(request, deps.get_event_writer), _seam(request, deps.get_desk_worlds))
    return w


def _act(request: Request, claim: ActionClaim, body: ActionRequest, args: _Closed) -> tuple[int, dict[str, Any]]:
    owner = _writer(request, claim.uid, claim.org_id)
    actor = claim.uid
    if body.speaker is not None:
        found = match_name(body.speaker, owner.org_directory(), viewer=claim.uid, now=owner.now)
        if found.status != "resolved" or found.user is None:
            outcome = "ambiguous_person" if found.status == "ambiguous" else "unknown_person"
            return 404, {"outcome": outcome}
        actor = found.user
    if isinstance(args, AgendaArgs):  # this meeting's agenda belongs to its owner, whoever asked
        return _add_agenda_item(owner, body.meeting_id, args)
    w = owner if actor == claim.uid else _writer(request, actor, claim.org_id)
    if isinstance(args, PinArgs):
        return _create_pin(w, args)
    return _create_meeting(w, args)  # type: ignore[arg-type]


def _create_pin(w: Writer, args: PinArgs) -> tuple[int, dict[str, Any]]:
    team = None
    if args.board == "team":
        me = w.stores.persons.get(w.org, w.actor)
        teams = sorted({m["team"] for m in (me.record["memberships"] if me is not None else [])})
        if not teams:  # live 21 Oct: the owner is on no team, and "which team board?" hid that
            return 409, {"outcome": "no_team"}
        if len(teams) != 1:
            return 409, {"outcome": "team_unclear"}
        team = teams[0]
    create_pin(w, PinIn(title=args.title, body=args.body, team=team))
    return 200, {"outcome": "done", "action": "create_pin", "board": args.board}


def _add_agenda_item(w: Writer, meeting_id: str, args: AgendaArgs) -> tuple[int, dict[str, Any]]:
    stored = w.stores.meetings.get(w.org, meeting_id)
    if stored is None:
        return 404, {"outcome": "refused"}
    current = [AgendaIn(title=a["title"], minutes=a["minutes"]) for a in stored.record["agenda"]]
    if len(current) >= 20:
        return 409, {"outcome": "agenda_full"}
    edit_meeting(w, meeting_id, MeetingEditIn(agenda=[*current, AgendaIn(title=args.title, minutes=args.minutes)]))
    return 200, {"outcome": "done", "action": "add_agenda_item"}


def _stamp(when: datetime) -> str:
    return when.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.") + f"{when.microsecond // 1000:03d}Z"


def _create_meeting(w: Writer, args: MeetingArgs) -> tuple[int, dict[str, Any]]:
    start = datetime.fromisoformat(args.start.replace("Z", "+00:00"))
    window = WindowIn(start=_stamp(start), end=_stamp(start + timedelta(minutes=args.minutes)))
    create_meeting(
        w,
        MeetingIn(
            attest=True,
            notice_version=deps.NOTICE_VERSION,
            title=args.title,
            source="bot",
            scheduled=window,
        ),
    )
    return 200, {"outcome": "done", "action": "create_meeting", "start": window.start}
