"""`GET /v1/people`: the signed-in person's team list (LIVE-GAPS-1a, FR-TEAM-01; people.rules.md PE-17, PE-20, PE-26).

The caller is `Principal.user_id` and the org is `deps.ORG_ID`; nothing in the request names a person or an org (query
parameters are ignored). Every row goes through the PE-20 projection (`tilo_people.access.read`) and nothing is
filtered by hand: the caller reads their own record in full, an org owner reads `id`, `display_name`, `org_role` and
`memberships` of the others, a member reads `id` and `display_name` of a teammate and nothing of anyone else (not even
a name). Email, aliases, time zone and preferred channel of another person never leave `tilo-api`. Read only: no store
write, no event, no model. The answer is sorted by (display_name, id).
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from tilo_people.access import AccessRequest, read
from tilo_people.directory import Directory
from tilo_people.stores import PeopleStores

from tilo_api import deps
from tilo_api.people import _PeopleRoute

router = APIRouter(route_class=_PeopleRoute)

# Most permissive first: the person's own record, then the owner's view, then the teammate's (PE-20).
_ACTIONS = ("read_full", "read_membership", "read_directory")


def list_people(stores: PeopleStores, org: str, actor: str, now: str) -> list[dict[str, Any]] | None:
    """The persons of `org` that `actor` may read, each as the projection PE-20 allows; None when `actor` has no
    record in `org`."""
    directory = Directory.of(s.record for s in stores.persons.list(org))
    if directory.record(actor) is None:
        return None
    rows: list[dict[str, Any]] = []
    for stored in stores.persons.list(org):
        for action in _ACTIONS:
            got = read(AccessRequest(actor, action, "person", stored.record, now), directory)
            if got is not None:
                rows.append(got)
                break
    rows.sort(key=lambda row: (row["display_name"], row["id"]))
    return rows


@router.get("/v1/people")
def people_route(
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    stores: Annotated[PeopleStores, Depends(deps.get_people_stores)],
    clock: Annotated[Any, Depends(deps.get_clock)],
) -> dict[str, Any]:
    """The team list; no person record for the caller is the one 404, a store that fails a fixed 503."""
    try:
        rows = list_people(stores, deps.ORG_ID, principal.user_id, clock())
    except NotImplementedError:
        raise  # the route class answers 503 not_configured
    except Exception:
        raise HTTPException(status_code=503, detail="unavailable") from None
    if rows is None:
        raise HTTPException(status_code=404, detail="not_found")
    return {"people": rows, "you": principal.user_id}
