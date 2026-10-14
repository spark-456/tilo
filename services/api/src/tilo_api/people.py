"""The people API (PPL-11a; docs/prd-addendum-people-agents.md, ADR-0020/0021, services/api/tests/API_PPL_11a.md).
Slices A to C: the evidence-quote routes, the plate and the writes (`people_writes.py`). Every route sits behind the
SEC-15 gate (none is public), takes the person from the verified `deps.Principal` (the session's world role neither
grants nor takes away), and reads one org only (`deps.ORG_ID`, at call time). It makes no model call and builds no
router. One 404 body for every refusal; 422 for a bad shape before any lookup; 503 `not_configured` for an unwired seam
and 503 for a store that cannot be read.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from tilo_memory.artifacts import ArtifactStore
from tilo_people.stores import PeopleStores

from tilo_api import deps, people_items
from tilo_api.meeting_bot import attend_meeting
from tilo_api.meeting_bot_rpc import MeetingBotRpc, get_meeting_bot_client
from tilo_api.meeting_draft_cleanup import get_meeting_draft_cleanup
from tilo_api.meeting_host import HostSeams, get_host_seams, host_meeting
from tilo_api.meeting_host_rpc import MeetingHostRpc
from tilo_api.meeting_join import owner_join
from tilo_api.meeting_voice_claims import AttendClaims, get_attend_claims
from tilo_api.people_events import WorkEvents, get_work_events
from tilo_api.people_limits import idempotent, write_limit
from tilo_api.people_meetings import MeetingEditIn, edit_meeting, get_meeting, list_meetings, read_minutes, set_world
from tilo_api.people_pins import PinIn, create_pin, delete_pin, list_pins
from tilo_api.people_plate import build_plate
from tilo_api.people_quotes import Reader, item_quote, meeting_quotes
from tilo_api.people_writes import (
    Empty,
    ItemIn,
    MeetingIn,
    PersonIn,
    Refusal,
    RoleIn,
    TeamIn,
    Writer,
    add_team,
    confirm_item,
    confirm_minutes,
    create_first_person,
    create_item,
    create_judge_member,
    create_meeting,
    create_person,
    json_body,
    remove_meeting,
    remove_team,
    set_role,
)
from tilo_api.request_work import while_connected

_MEETING_ID = re.compile(r"mt_[0-9A-Za-z_]{1,48}")
_ITEM_ID = re.compile(r"wi_[0-9A-Za-z_]{1,48}")
_PERSON_ID = re.compile(r"u_[0-9A-Za-z_]{1,48}")
_FOUNDING_CHANNELS = frozenset({"web", "mobile_web"})  # an allow-list: `/first` needs a full web sign-in (FS-19)
_IDS = r"^u[0-9]{4,6}(,u[0-9]{4,6}){0,19}$"  # 1 to 20 utterance ids, comma separated


class _PeopleRoute(APIRoute):
    """A seam with no production wiring raises `NotImplementedError` (T4's artifact store and redactor): 503
    `not_configured`, like the seams that raise it as an HTTP error. Every POST route counts one write attempt first
    (SEC-10: `write_limit`, before the body is read)."""

    def __init__(self, path: str, endpoint: Callable[..., Any], *, dependencies: Any = None, **kwargs: Any) -> None:
        if "POST" in kwargs.get("methods", ()):
            dependencies = [*(dependencies or []), Depends(write_limit)]
        super().__init__(path, endpoint, dependencies=dependencies, **kwargs)

    def get_route_handler(self) -> Callable[[Request], Any]:
        handler = super().get_route_handler()

        async def guarded(request: Request) -> Response:
            """Every answer, refusals included, is `Cache-Control: no-store` (PE-22: no copy outlives the request)."""
            try:
                response = await handler(request)
            except NotImplementedError:
                response = JSONResponse(status_code=503, content={"detail": "not_configured"})
            except HTTPException as refusal:
                extra = refusal.extra if isinstance(refusal, Refusal) else {}
                response = JSONResponse(
                    status_code=refusal.status_code,
                    content={"detail": refusal.detail, **extra},
                    headers=refusal.headers,
                )
            response.headers["Cache-Control"] = "no-store"
            return response

        return guarded


router = APIRouter(route_class=_PeopleRoute)


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="not_found")  # one body whatever the cause: no oracle


def _person_id(person_id: str) -> str:
    if _PERSON_ID.fullmatch(person_id) is None:
        raise _not_found()
    return person_id


def _unreadable() -> HTTPException:
    return HTTPException(status_code=503, detail="unavailable")


def _answer(found: Callable[[], dict[str, Any] | None]) -> dict[str, Any]:
    """404 for a refusal, 503 for anything the stores or the artifact store cannot give (never a 500, never a
    partial answer; no record text in either body)."""
    try:
        answer = found()
    except HTTPException:
        raise
    except Exception:
        raise _unreadable() from None
    if answer is None:
        raise _not_found()
    return answer


@router.get("/v1/meetings/{meeting_id}/quotes")
def meeting_quotes_route(
    meeting_id: str,
    ids: Annotated[str, Query(pattern=_IDS)],
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    stores: Annotated[PeopleStores, Depends(deps.get_people_stores)],
    artifacts: Annotated[ArtifactStore, Depends(deps.get_artifact_store)],
    redact: Annotated[Callable[[str], str], Depends(deps.get_redactor)],
    clock: Annotated[Callable[[], str], Depends(deps.get_clock)],
) -> dict[str, Any]:
    """The meeting owner's quotes, one per id in the order asked (PE-23)."""
    if _MEETING_ID.fullmatch(meeting_id) is None:
        raise _not_found()
    reader = Reader(stores, artifacts, redact, deps.ORG_ID, principal.user_id, clock())
    return _answer(lambda: meeting_quotes(reader, meeting_id, ids.split(",")))


@router.get("/v1/work-items/{work_item_id}/quote")
def work_item_quote_route(
    work_item_id: str,
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    stores: Annotated[PeopleStores, Depends(deps.get_people_stores)],
    artifacts: Annotated[ArtifactStore, Depends(deps.get_artifact_store)],
    redact: Annotated[Callable[[str], str], Depends(deps.get_redactor)],
    clock: Annotated[Callable[[], str], Depends(deps.get_clock)],
) -> dict[str, Any]:
    """The one quote a work item's owner gets (PE-23). It takes no argument: nothing can ask for a second quote."""
    if _ITEM_ID.fullmatch(work_item_id) is None:
        raise _not_found()
    reader = Reader(stores, artifacts, redact, deps.ORG_ID, principal.user_id, clock())
    return _answer(lambda: item_quote(reader, work_item_id))


@router.get("/v1/plate")
def plate_route(
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    stores: Annotated[PeopleStores, Depends(deps.get_people_stores)],
    sources: Annotated[deps.PlateSources, Depends(deps.get_plate_sources)],
    owners: Annotated[deps.SourceOwners, Depends(deps.get_source_owners)],
    clock: Annotated[Callable[[], str], Depends(deps.get_clock)],
) -> dict[str, Any]:
    """The signed-in person's own plate (PE-26): nothing in the request names a person, so none can be asked for. A
    person with no record is a 404 (the sources are not asked); a source that fails is a 503, never a partial plate."""
    now = clock()
    return _answer(lambda: build_plate(stores, sources, owners, deps.ORG_ID, principal.user_id, now))


def _writer(
    principal: deps.Principal,
    stores: PeopleStores,
    clock: Callable[[], str],
    redact: Callable[[str], str] | None = None,
    events: WorkEvents | None = None,
) -> Writer:
    w = Writer(stores, deps.ORG_ID, principal.user_id, clock(), *(() if redact is None else (redact,)))
    w.events = events
    return w


@router.post("/v1/meetings/{meeting_id}/confirm")
def confirm_meeting_route(
    meeting_id: str,
    _: Annotated[Empty, Depends(json_body(Empty))],
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    stores: Annotated[PeopleStores, Depends(deps.get_people_stores)],
    clock: Annotated[Callable[[], str], Depends(deps.get_clock)],
) -> dict[str, Any]:
    """The meeting owner confirms the minutes: the stamp is the owner and the server clock (PE-05, PE-07)."""
    if _MEETING_ID.fullmatch(meeting_id) is None:
        raise _not_found()
    return _answer(lambda: confirm_minutes(_writer(principal, stores, clock), meeting_id))


@router.get("/v1/meetings")
def list_meetings_route(
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    stores: Annotated[PeopleStores, Depends(deps.get_people_stores)],
    clock: Annotated[Callable[[], str], Depends(deps.get_clock)],
) -> dict[str, Any]:
    return _answer(lambda: list_meetings(_writer(principal, stores, clock)))


@router.get("/v1/meetings/{meeting_id}")
def get_meeting_route(
    meeting_id: str,
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    stores: Annotated[PeopleStores, Depends(deps.get_people_stores)],
    clock: Annotated[Callable[[], str], Depends(deps.get_clock)],
) -> dict[str, Any]:
    """The owner reads their meeting (PE-05); everyone else, and a deleted meeting, is the one 404."""
    if _MEETING_ID.fullmatch(meeting_id) is None:
        raise _not_found()
    return _answer(lambda: get_meeting(_writer(principal, stores, clock), meeting_id))


@router.post("/v1/meetings/{meeting_id}/edit")
def edit_meeting_route(
    meeting_id: str,
    body: Annotated[MeetingEditIn, Depends(json_body(MeetingEditIn))],
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    stores: Annotated[PeopleStores, Depends(deps.get_people_stores)],
    redact: Annotated[Callable[[str], str], Depends(deps.get_redactor)],
    clock: Annotated[Callable[[], str], Depends(deps.get_clock)],
) -> dict[str, Any]:
    """The owner edits title, series, schedule, agenda and attendees, nothing else (PE-07, PE-19)."""
    if _MEETING_ID.fullmatch(meeting_id) is None:
        raise _not_found()
    return _answer(lambda: edit_meeting(_writer(principal, stores, clock, redact), meeting_id, body))


@router.get("/v1/meetings/{meeting_id}/minutes")
def meeting_minutes_route(
    meeting_id: str,
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    stores: Annotated[PeopleStores, Depends(deps.get_people_stores)],
    artifacts: Annotated[ArtifactStore, Depends(deps.get_artifact_store)],
    redact: Annotated[Callable[[str], str], Depends(deps.get_redactor)],
    clock: Annotated[Callable[[], str], Depends(deps.get_clock)],
) -> dict[str, Any]:
    """The owner reads the minutes document, cleaned and redacted (PE-05, PE-24); needs the store and the redactor."""
    if _MEETING_ID.fullmatch(meeting_id) is None:
        raise _not_found()
    return _answer(lambda: read_minutes(_writer(principal, stores, clock), artifacts, redact, meeting_id))


@router.post("/v1/meetings/{meeting_id}/world")
def meeting_world_route(
    meeting_id: str,
    _: Annotated[Empty, Depends(json_body(Empty))],
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    stores: Annotated[PeopleStores, Depends(deps.get_people_stores)],
    worlds: Annotated[deps.MeetingWorlds, Depends(deps.get_meeting_worlds)],
    clock: Annotated[Callable[[], str], Depends(deps.get_clock)],
) -> dict[str, Any]:
    """The owner gets the meeting's world written once; the id is the maker's, never the request's (BQ-273)."""
    if _MEETING_ID.fullmatch(meeting_id) is None:
        raise _not_found()
    return _answer(lambda: set_world(_writer(principal, stores, clock), worlds, meeting_id))


@router.get("/v1/meetings/{meeting_id}/join")
def join_meeting_route(
    meeting_id: str,
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    stores: Annotated[PeopleStores, Depends(deps.get_people_stores)],
    store: Annotated[deps.Store, Depends(deps.get_store)],
    artifacts: Annotated[ArtifactStore, Depends(deps.get_artifact_store)],
    client: Annotated[MeetingHostRpc, Depends(deps.get_meeting_host_client)],
    clock: Annotated[Callable[[], str], Depends(deps.get_clock)],
) -> dict[str, Any]:
    return _answer(lambda: owner_join(_writer(principal, stores, clock), store, artifacts, client, meeting_id))


@router.post("/v1/meetings/{meeting_id}/attend")
async def attend_meeting_route(
    meeting_id: str,
    request: Request,
    _: Annotated[Empty, Depends(json_body(Empty))],
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    stores: Annotated[PeopleStores, Depends(deps.get_people_stores)],
    _new_work: Annotated[deps.Mode, Depends(deps.get_work_mode)],  # a bot is new live work: refused at a cap
    store: Annotated[deps.Store, Depends(deps.get_store)],
    artifacts: Annotated[ArtifactStore, Depends(deps.get_artifact_store)],
    host: Annotated[MeetingHostRpc, Depends(deps.get_meeting_host_client)],
    bot: Annotated[MeetingBotRpc, Depends(get_meeting_bot_client)],
    clock: Annotated[Callable[[], str], Depends(deps.get_clock)],
    claims: Annotated[AttendClaims | None, Depends(get_attend_claims)],
) -> dict[str, Any]:
    work = attend_meeting(
        _writer(principal, stores, clock), store, artifacts, host, bot, meeting_id, clock, claims=claims
    )
    try:
        return await while_connected(request, work)
    except HTTPException:
        raise
    except Exception:
        raise _unreadable() from None


@router.post("/v1/meetings/{meeting_id}/host")
def host_meeting_route(
    meeting_id: str,
    _: Annotated[Empty, Depends(json_body(Empty))],
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    stores: Annotated[PeopleStores, Depends(deps.get_people_stores)],
    clock: Annotated[Callable[[], str], Depends(deps.get_clock)],
    _new_work: Annotated[deps.Mode, Depends(deps.get_work_mode)],  # hosting starts a bot: refused at a cap
    seams: Annotated[HostSeams, Depends(get_host_seams)],
) -> dict[str, Any]:
    """The owner hosts a scheduled bot meeting (FR-MTG-09): one gate card, then one invitation (BQ-MTG09-20)."""
    if _MEETING_ID.fullmatch(meeting_id) is None:
        raise _not_found()
    return _answer(lambda: host_meeting(_writer(principal, stores, clock), meeting_id, seams))


@router.post("/v1/meetings/{meeting_id}/delete")
def delete_meeting_route(
    meeting_id: str,
    _: Annotated[Empty, Depends(json_body(Empty))],
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    stores: Annotated[PeopleStores, Depends(deps.get_people_stores)],
    artifacts: Annotated[ArtifactStore, Depends(deps.get_artifact_store)],
    clock: Annotated[Callable[[], str], Depends(deps.get_clock)],
    cleanup: Annotated[Callable[[str, str], None] | None, Depends(get_meeting_draft_cleanup)],
) -> dict[str, Any]:
    """The meeting owner deletes it and everything made from it (FR-MTG-10); needs the artifact store (503 without)."""
    if _MEETING_ID.fullmatch(meeting_id) is None:
        raise _not_found()
    return _answer(lambda: remove_meeting(_writer(principal, stores, clock), artifacts, meeting_id, cleanup=cleanup))


@router.post("/v1/work-items/{work_item_id}/confirm")
def confirm_work_item_route(
    work_item_id: str,
    _: Annotated[Empty, Depends(json_body(Empty))],
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    stores: Annotated[PeopleStores, Depends(deps.get_people_stores)],
    clock: Annotated[Callable[[], str], Depends(deps.get_clock)],
    events: Annotated[WorkEvents, Depends(get_work_events)],
) -> dict[str, Any]:
    """The assigner confirms a proposed item; nobody else can see it exists (PE-03, PE-07)."""
    if _ITEM_ID.fullmatch(work_item_id) is None:
        raise _not_found()
    return _answer(lambda: confirm_item(_writer(principal, stores, clock, events=events), work_item_id))


@router.post("/v1/meetings", status_code=201)
def create_meeting_route(
    request: Request,
    body: Annotated[MeetingIn, Depends(json_body(MeetingIn))],
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    stores: Annotated[PeopleStores, Depends(deps.get_people_stores)],
    redact: Annotated[Callable[[str], str], Depends(deps.get_redactor)],
    clock: Annotated[Callable[[], str], Depends(deps.get_clock)],
) -> dict[str, Any]:
    """A person of the org adds a meeting; the server mints the id and stamps the attestation (PE-18)."""
    return _answer(
        lambda: idempotent(
            request, principal, stores, body, lambda: create_meeting(_writer(principal, stores, clock, redact), body)
        )
    )


@router.post("/v1/people", status_code=201)
def create_person_route(
    request: Request,
    body: Annotated[PersonIn, Depends(json_body(PersonIn))],
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    stores: Annotated[PeopleStores, Depends(deps.get_people_stores)],
    redact: Annotated[Callable[[str], str], Depends(deps.get_redactor)],
    clock: Annotated[Callable[[], str], Depends(deps.get_clock)],
) -> dict[str, Any]:
    """An org owner adds a person; the server mints the id and the org is `deps.ORG_ID` (PE-17)."""
    return _answer(
        lambda: idempotent(
            request, principal, stores, body, lambda: create_person(_writer(principal, stores, clock, redact), body)
        )
    )


@router.post("/v1/people/first", status_code=201)
def create_first_person_route(
    request: Request,
    body: Annotated[PersonIn, Depends(json_body(PersonIn))],
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    stores: Annotated[PeopleStores, Depends(deps.get_people_stores)],
    gate: Annotated[Callable[[str], bool], Depends(deps.get_founder_gate)],
    redact: Annotated[Callable[[str], str], Depends(deps.get_redactor)],
    clock: Annotated[Callable[[], str], Depends(deps.get_clock)],
    judge: Annotated[Callable[[str], bool], Depends(deps.get_judge_gate)],
) -> dict[str, Any]:
    """The configured bootstrap uid founds an empty org as its owner (PE-17, BQ-PPL11C-15). A person who declared
    `judge` (and only then) joins as a plain member of it instead, never as owner (JUDGE-FIRST-RUN F1). Every other
    principal, and any org that has a person or was founded, is the same 403. The session (a full web or mobile_web
    sign-in, FS-19, an allow-list) is checked before any store is read; the marker is never the request's."""
    if not (principal.full_session and principal.channel in _FOUNDING_CHANNELS):
        raise Refusal(403, "forbidden")
    if gate(principal.user_id):
        make = create_first_person
    elif not principal.demo_session and judge(principal.user_id):
        make = create_judge_member
    else:
        raise Refusal(403, "forbidden")
    return _answer(
        lambda: idempotent(
            request,
            principal,
            stores,
            body,
            lambda: make(_writer(principal, stores, clock, redact), body),
        )
    )


@router.post("/v1/people/{person_id}/memberships")
def add_team_route(
    person_id: str,
    body: Annotated[TeamIn, Depends(json_body(TeamIn))],
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    stores: Annotated[PeopleStores, Depends(deps.get_people_stores)],
    clock: Annotated[Callable[[], str], Depends(deps.get_clock)],
) -> dict[str, Any]:
    """An org owner puts a person in a team; the stamp is the owner and the clock (PE-17)."""
    return _answer(lambda: add_team(_writer(principal, stores, clock), _person_id(person_id), body.team))


@router.post("/v1/people/{person_id}/memberships/remove")
def remove_team_route(
    person_id: str,
    body: Annotated[TeamIn, Depends(json_body(TeamIn))],
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    stores: Annotated[PeopleStores, Depends(deps.get_people_stores)],
    clock: Annotated[Callable[[], str], Depends(deps.get_clock)],
) -> dict[str, Any]:
    """An org owner takes a person out of a team; an absent team is a 200 with nothing changed."""
    return _answer(lambda: remove_team(_writer(principal, stores, clock), _person_id(person_id), body.team))


@router.post("/v1/people/{person_id}/role")
def set_role_route(
    person_id: str,
    body: Annotated[RoleIn, Depends(json_body(RoleIn))],
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    stores: Annotated[PeopleStores, Depends(deps.get_people_stores)],
    clock: Annotated[Callable[[], str], Depends(deps.get_clock)],
) -> dict[str, Any]:
    """An org owner promotes a member; roles are only ever promoted (409 `transition` otherwise)."""
    return _answer(lambda: set_role(_writer(principal, stores, clock), _person_id(person_id), body.org_role))


@router.post("/v1/work-items", status_code=201)
def create_work_item_route(
    request: Request,
    body: Annotated[ItemIn, Depends(json_body(ItemIn))],
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    stores: Annotated[PeopleStores, Depends(deps.get_people_stores)],
    redact: Annotated[Callable[[str], str], Depends(deps.get_redactor)],
    clock: Annotated[Callable[[], str], Depends(deps.get_clock)],
    events: Annotated[WorkEvents, Depends(get_work_events)],
    lookup: Annotated[Callable[[str], deps.WorldRecord | None], Depends(deps.get_world_lookup)],
) -> dict[str, Any]:
    """A person adds their own item; a mail or request source is checked against its owner (PE-08). A `world_id`
    binds it to a world its creator owns or reads as a team reader (ADR-0040, PE-33): only a full web or mobile-web
    sign-in session bound to no world may name one, and the world and its shares come from the stores."""

    def owners() -> deps.SourceOwners:  # resolved only when the source is mail or a request
        seam = request.app.dependency_overrides.get(deps.get_source_owners)
        return seam() if seam is not None else deps.get_source_owners(request)  # an override takes no argument

    def worlds(world_id: str) -> deps.WorldRecord | None:  # a session of another shape reads no world (PE-32)
        full = principal.full_session is True and not principal.demo_session and principal.world_id is None
        return lookup(world_id) if full and principal.channel in ("web", "mobile_web") else None

    return _answer(
        lambda: idempotent(
            request,
            principal,
            stores,
            body,
            lambda: create_item(_writer(principal, stores, clock, redact, events), body, owners, worlds),
        )
    )


def _item_writer(
    item_id: str,
    principal: deps.Principal,
    stores: PeopleStores,
    clock: Callable[[], str],
    redact: Callable[[str], str] | None = None,
    events: WorkEvents | None = None,
) -> Writer:
    if _ITEM_ID.fullmatch(item_id) is None:
        raise _not_found()
    return _writer(principal, stores, clock, redact, events)


@router.get("/v1/pinboards")
def list_pinboards_route(
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    stores: Annotated[PeopleStores, Depends(deps.get_people_stores)],
    clock: Annotated[Callable[[], str], Depends(deps.get_clock)],
    owners: Annotated[deps.SourceOwners, Depends(deps.get_source_owners)],
) -> dict[str, Any]:
    return _answer(lambda: list_pins(_writer(principal, stores, clock), owners))


@router.post("/v1/pinboards", status_code=201)
def create_pin_route(
    request: Request,
    body: Annotated[PinIn, Depends(json_body(PinIn))],
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    stores: Annotated[PeopleStores, Depends(deps.get_people_stores)],
    redact: Annotated[Callable[[str], str], Depends(deps.get_redactor)],
    clock: Annotated[Callable[[], str], Depends(deps.get_clock)],
    events: Annotated[WorkEvents, Depends(get_work_events)],
) -> dict[str, Any]:
    return _answer(
        lambda: idempotent(
            request,
            principal,
            stores,
            body,
            lambda: create_pin(_writer(principal, stores, clock, redact, events), body),
        )
    )


@router.post("/v1/pinboards/{pin_id}/delete")
def delete_pin_route(
    pin_id: str,
    body: Annotated[Empty, Depends(json_body(Empty))],
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    stores: Annotated[PeopleStores, Depends(deps.get_people_stores)],
    clock: Annotated[Callable[[], str], Depends(deps.get_clock)],
    owners: Annotated[deps.SourceOwners, Depends(deps.get_source_owners)],
    events: Annotated[WorkEvents, Depends(get_work_events)],
) -> dict[str, Any]:
    if re.fullmatch(r"pb_[0-9A-Za-z_]{1,48}", pin_id) is None:
        raise _not_found()
    return _answer(lambda: delete_pin(_writer(principal, stores, clock, events=events), pin_id, owners))


@router.get("/v1/work-items")
def list_work_items_route(
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    stores: Annotated[PeopleStores, Depends(deps.get_people_stores)],
    clock: Annotated[Callable[[], str], Depends(deps.get_clock)],
    status: Annotated[str | None, Query()] = None,
) -> dict[str, Any]:
    """The caller's own open, done and dropped items (PE-03); `status` narrows it (checked here: a 422 is no-store)."""
    if status is not None and status not in people_items.LIST_STATUSES:
        raise Refusal(422, "invalid_query")
    return _answer(lambda: people_items.list_items(_writer(principal, stores, clock), status))


@router.get("/v1/work-items/{work_item_id}")
def get_work_item_route(
    work_item_id: str,
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    stores: Annotated[PeopleStores, Depends(deps.get_people_stores)],
    clock: Annotated[Callable[[], str], Depends(deps.get_clock)],
) -> dict[str, Any]:
    """The owner reads the full record, the assigner of a confirmed item its status view (PE-03)."""
    w = _item_writer(work_item_id, principal, stores, clock)
    return _answer(lambda: people_items.get_item(w, work_item_id))


@router.post("/v1/work-items/{work_item_id}/edit")
def edit_work_item_route(
    work_item_id: str,
    body: Annotated[people_items.EditIn, Depends(json_body(people_items.EditIn))],
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    stores: Annotated[PeopleStores, Depends(deps.get_people_stores)],
    redact: Annotated[Callable[[str], str], Depends(deps.get_redactor)],
    clock: Annotated[Callable[[], str], Depends(deps.get_clock)],
    events: Annotated[WorkEvents, Depends(get_work_events)],
) -> dict[str, Any]:
    """The owner changes the title and the due phrase; `source` and every stamp are immutable (PE-07)."""
    w = _item_writer(work_item_id, principal, stores, clock, redact, events)
    return _answer(lambda: people_items.edit_item(w, work_item_id, body))


@router.post("/v1/work-items/{work_item_id}/snooze")
def snooze_work_item_route(
    work_item_id: str,
    body: Annotated[people_items.SnoozeIn, Depends(json_body(people_items.SnoozeIn))],
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    stores: Annotated[PeopleStores, Depends(deps.get_people_stores)],
    clock: Annotated[Callable[[], str], Depends(deps.get_clock)],
    events: Annotated[WorkEvents, Depends(get_work_events)],
) -> dict[str, Any]:
    """The owner parks an open item until a time within the next 30 days (PE-19)."""
    w = _item_writer(work_item_id, principal, stores, clock, events=events)
    return _answer(lambda: people_items.snooze_item(w, work_item_id, body))


def _plain_action(name: str, act: Callable[[Writer, str], dict[str, Any]], summary: str) -> None:
    """One owner action that takes `{}` and nothing else (done, reopen, not-mine, put-back)."""

    def route(
        work_item_id: str,
        _: Annotated[Empty, Depends(json_body(Empty))],
        principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
        stores: Annotated[PeopleStores, Depends(deps.get_people_stores)],
        clock: Annotated[Callable[[], str], Depends(deps.get_clock)],
        events: Annotated[WorkEvents, Depends(get_work_events)],
    ) -> dict[str, Any]:
        w = _item_writer(work_item_id, principal, stores, clock, events=events)
        return _answer(lambda: act(w, work_item_id))

    route.__name__ = f"{name.replace('-', '_')}_work_item_route"
    route.__doc__ = summary
    router.post(f"/v1/work-items/{{work_item_id}}/{name}")(route)


_plain_action("done", people_items.done_item, "The owner marks an open item done (PE-30).")
_plain_action("reopen", people_items.reopen_item, "The owner reopens a done item (PE-30).")
_plain_action("not-mine", people_items.not_mine, "The owner asks the assigner to reassign an item (PE-29).")
_plain_action("put-back", people_items.put_back, "The owner puts a snoozed or asked item back on the plate (PE-29).")
