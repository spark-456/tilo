"""The people API (PPL-11a; docs/prd-addendum-people-agents.md, ADR-0020/0021, services/api/tests/API_PPL_11a.md).
Slice A: the two evidence-quote routes. Every route sits behind the SEC-15 gate (none is public), takes the person from
the verified `deps.Principal` (the session's world role neither grants nor takes away), and reads one org only
(`deps.ORG_ID`, at call time). It makes no model call and builds no router. One 404 body for every refusal; 422 for a
bad shape before any lookup; 503 `not_configured` for an unwired seam and 503 for a store that cannot be read.
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

from tilo_api import deps
from tilo_api.people_quotes import Reader, item_quote, meeting_quotes

_MEETING_ID = re.compile(r"mt_[0-9A-Za-z_]{1,48}")
_ITEM_ID = re.compile(r"wi_[0-9A-Za-z_]{1,48}")
_IDS = r"^u[0-9]{4,6}(,u[0-9]{4,6}){0,19}$"  # 1 to 20 utterance ids, comma separated


class _PeopleRoute(APIRoute):
    """A seam with no production wiring raises `NotImplementedError` (T4's artifact store and redactor): 503
    `not_configured`, like the seams that raise it as an HTTP error."""

    def get_route_handler(self) -> Callable[[Request], Any]:
        handler = super().get_route_handler()

        async def guarded(request: Request) -> Response:
            try:
                return await handler(request)
            except NotImplementedError:
                return JSONResponse(status_code=503, content={"detail": "not_configured"})

        return guarded


router = APIRouter(route_class=_PeopleRoute)


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="not_found")  # one body whatever the cause: no oracle


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
