"""The team view of a shared world's work items (BQ-CTX-TEAMWORLD, ADR-0040 decision 6, FR-TEAM-05, PE-33):
`GET /worlds/{world_id}/work-items`, a list read model. Security-flagged: it shows people's items to their teammates.

The caller is the world's owner or a team reader (`deps.readable_world`), on a full web or mobile-web sign-in
session; every other case is the one unknown-world 404. A row is the oracle's answer, `tilo_people.decide` for
`read_team` against each share in force for the world: an item that names this world, made and owned by a person who
is a member of the share's team with the reader, `open` or `done`, not flagged. The row has six keys (`id`, `title`,
`status`, `due`, `owner`, `world_id`) and never `source`, `evidence`, `history`, `assigned_by`, `snoozed_until` or
`flagged`. Items made before the world was shared have no `world_id` and are never listed (migration). The list reads
records, never another person's event stream (PE-12), and takes nothing from the request but the world in the path.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Response
from tilo_people.access import AccessRequest, read
from tilo_people.directory import Directory
from tilo_people.stores import PeopleStores
from tilo_people.world_share import in_force

from tilo_api import deps

logger = logging.getLogger("tilo_api.team_items")
router = APIRouter()

LIST_MAX = 200


@router.get("/worlds/{world_id}/work-items")
def list_team_items(
    world_id: str,
    response: Response,
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    store: Annotated[deps.Store, Depends(deps.get_store)],
    people: Annotated[Callable[[], PeopleStores | None], Depends(deps.get_people_provider)],
    clock: Annotated[Callable[[], str], Depends(deps.get_clock)],
) -> dict[str, Any]:
    if not (
        principal.full_session is True and not principal.demo_session and principal.channel in ("web", "mobile_web")
    ):
        raise HTTPException(status_code=404)
    world, viewer = deps.readable_world(principal, store, people, clock, world_id)
    stores = people()
    if stores is None:
        raise HTTPException(status_code=503, detail="not_configured")
    now = clock()
    try:
        directory = Directory.of(s.record for s in stores.persons.list(deps.ORG_ID))
        shares = [
            s.record
            for s in stores.world_shares.list(deps.ORG_ID, "world_id", world_id)
            if in_force(s.record, world.owner, directory, now)
        ]
        items = stores.work_items.list(deps.ORG_ID, "world_id", world_id) if shares else ()
    except Exception as exc:
        logger.warning("team items not read (%s) world=%s", type(exc).__name__, world_id)
        raise HTTPException(status_code=503, detail="unavailable") from None
    rows: list[dict[str, Any]] = []
    for stored in items:
        for share in shares:
            request = AccessRequest(
                viewer.user_id, "read_team", "work_item", stored.record, now, world_share=share, world_owner=world.owner
            )
            if (row := read(request, directory)) is not None:
                rows.append(row)
                break
    response.headers["Cache-Control"] = "no-store"
    return {"world_id": world_id, "items": rows[:LIST_MAX], "truncated": len(rows) > LIST_MAX}
