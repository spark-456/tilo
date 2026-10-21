"""WORLDS-MANAGE (owner ask, 21 Oct 2026: "add an option to delete worlds from the worlds section since it is getting
cluttered"): `DELETE /worlds/{world_id}` takes a world off its owner's Worlds list.

Owner only, on their own full web or mobile-web sign-in bound to no world (the same rule as an owner's team-share
change, ADR-0040); every other caller, a missing world and a teammate's shared world get the one unknown-world 404, so
the route is no membership oracle. A world still at work (its latest world state is `world.started`, or a run is
planning it) is a 409: there is no single-world stop event (`world.paused` is Pause all or the kill switch), so the
person pauses it first. Otherwise the record's `hidden` flag is set and committed; answering again is the same 204.

Nothing is erased and no event is written (an owner decision, docs/open-questions.md BQ-WORLDS-MANAGE-1): the record,
its events, artifacts, ledger and archive stay, and `/costs` keeps counting what it spent. Only the lists stop showing
it: `GET /worlds`, a teammate's team read (`deps.team_reader`) and the cards feed. The recorded sample is never a
stored world; the sample router answers its id with 409 `sample_is_a_replay` before this route is reached.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response

from tilo_api import deps
from tilo_api.deps import EventWriter, Principal, Store, get_current_principal, get_event_writer, get_store
from tilo_api.worlds_list import world_status

router = APIRouter()

_UNKNOWN = "Tilo could not find that."
_WORKING = "This world is still working. Pause it first, then delete it."


def _own_world(principal: Principal, store: Store, world_id: str) -> deps.WorldRecord:
    world = store.load_world(world_id)
    if (
        world is None
        or principal.role != "owner"
        or principal.world_id is not None
        or not deps.full_world_session(principal)
        or principal.user_id != world.owner
    ):
        raise HTTPException(status_code=404, detail=_UNKNOWN)
    return world


@router.delete("/worlds/{world_id}", status_code=204)
def delete_world(
    world_id: str,
    principal: Principal = Depends(get_current_principal),
    store: Store = Depends(get_store),
    writer: EventWriter = Depends(get_event_writer),
) -> Response:
    world = _own_world(principal, store, world_id)
    if world.hidden:
        return Response(status_code=204)  # already off the list: deleting again changes nothing
    store.settle(world_id, writer)  # a run a restart ended gets its world.failed first, so it is not "working"
    status = world_status(store.events.get(world_id, []))
    if status == "started" or (status == "idle" and world_id in store.runs):
        raise HTTPException(status_code=409, detail=_WORKING)
    world.hidden = True
    try:
        store.commit(worlds={world_id: world}, evict=False)
    except Exception:
        world.hidden = False  # the store refused (stale, unavailable): the world stays listed, the error says why
        raise
    return Response(status_code=204)
