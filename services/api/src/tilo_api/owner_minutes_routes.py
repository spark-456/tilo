"""Explicit owner minutes requests (FR-MTG-03/08); one default-off FlagStore activation."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, FastAPI, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from tilo_metering.flags import FlagStore

from tilo_api import deps
from tilo_api.owner_followup_caller import OwnerFollowupCaller, get_owner_followup_caller
from tilo_api.owner_minutes_caller import OwnerMinutesCaller, get_owner_minutes_caller
from tilo_api.people import _PeopleRoute
from tilo_api.people_writes import Empty, Refusal, json_body

MINUTES_FLAG = "meeting.minutes.enabled"
PersonId = Annotated[str, Field(pattern=r"^u_[0-9A-Za-z_]{1,48}$", max_length=50)]


class FollowupIn(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    recipients: Annotated[list[PersonId] | None, Field(min_length=1, max_length=50)] = None

    @field_validator("recipients")
    @classmethod
    def unique(cls, recipients: list[str] | None) -> list[str] | None:
        if recipients is not None and len(set(recipients)) != len(recipients):
            raise ValueError("duplicate recipients")
        return recipients


def _enabled(flags: FlagStore) -> bool:
    try:
        return flags.get(MINUTES_FLAG) is True
    except Exception:
        return False


def _owner_request(
    request: Request,
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    flags: Annotated[FlagStore, Depends(deps.get_flag_store)],
) -> None:
    if not _enabled(flags):
        raise Refusal(404, "not_found")
    if principal.demo_session or getattr(request.state, "demo_session", False) is True:
        raise Refusal(403, "demo_read_only")
    # The adopted callers authorize the current meeting/world owner; the session world role is not authority.


router = APIRouter(route_class=_PeopleRoute, dependencies=[Depends(_owner_request)])


@router.post("/v1/meetings/{meeting_id}/analyze-minutes")
def analyze(
    meeting_id: str,
    body: Annotated[Empty, Depends(json_body(Empty))],
    caller: Annotated[OwnerMinutesCaller, Depends(get_owner_minutes_caller)],
) -> dict[str, Any]:
    return caller.analyze(meeting_id)


@router.post("/v1/meetings/{meeting_id}/draft-followup")
def followup(
    meeting_id: str,
    body: Annotated[FollowupIn, Depends(json_body(FollowupIn))],
    caller: Annotated[OwnerFollowupCaller, Depends(get_owner_followup_caller)],
) -> Any:
    return caller.draft(meeting_id, recipients=body.recipients)


def install_owner_minutes_routes(app: FastAPI, flags: FlagStore) -> bool:
    """Called at app construction only. Unset/unreadable flag means no routes or OpenAPI entries.

    Activation still requires the integrated dependency factory and whole-chain review. Registered routes also
    recheck the same flag per request, so revocation refuses work without restarting the process.
    """
    if not _enabled(flags):
        return False
    app.include_router(router)
    app.openapi_schema = None
    return True
