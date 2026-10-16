"""`GET /v1/skills/catalog`: the skills the caller may use (SKILL-ROUTE, see `skills_route`). No model call."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends

from tilo_api import deps
from tilo_api.people import _PeopleRoute
from tilo_api.skills_route import CATALOG_MAX, library_entries, taught_entries
from tilo_api.skills_routes import _guarded, _readable

router = APIRouter(route_class=_PeopleRoute)


@router.get("/v1/skills/catalog")
def catalog_route(
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    store: Annotated[Any, Depends(deps.get_skill_store)],
    stores: Annotated[Any, Depends(deps.get_people_stores)],
    clock: Annotated[Callable[[], str], Depends(deps.get_clock)],
    registry: Annotated[Any, Depends(deps.get_skill_registry)],
) -> dict[str, Any]:
    """The skills the caller may use: name, one-line purpose, inputs and tools. No model call."""

    def read() -> dict[str, Any]:
        taught = _readable(store, stores, principal, clock, allow_unfounded=True)
        return {"skills": [*library_entries(registry), *taught_entries(taught, principal.user_id)][:CATALOG_MAX]}

    return _guarded(read)
