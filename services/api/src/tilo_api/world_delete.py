"""WORLDS-MANAGE (owner ask, 21 Oct 2026: "add an option to delete worlds from the worlds section since it is getting
cluttered"): `DELETE /worlds/{world_id}` takes a world off its owner's Worlds list.

Owner only, on their own full web or mobile-web sign-in bound to no world (the same rule as an owner's team-share
change, ADR-0040); every other caller, a missing world and a teammate's shared world get the one unknown-world 404, so
the route is no membership oracle. Refused with a 409:
- while the world is at work (its latest world state is `world.started`, or a run is planning it): there is no
  single-world stop event (`world.paused` is Pause all or the kill switch), so the person pauses it first, and Pause all
  is final for its run (BQ-90);
- while a meeting of the person's names the world and is still `scheduled`, `joining` or `live` (its bot would attend
  for a world nobody can open); a people store that cannot be read is a 503, never a guess.
The status is read again, and the copy committed, under the world's own lock (the one Pause all takes) and the lock a
run start takes (`Store.runs_guard`), so neither lands between the check and the commit; the shared record is never
changed in place. Otherwise the record's `hidden` flag is set and committed.

Nothing is erased and no event is written (an owner decision, docs/open-questions.md BQ-WORLDS-MANAGE-1): the record,
its events, artifacts, ledger and archive stay, and `/costs` keeps counting what it spent, each such task marked
`world_deleted`. A hidden world is then gone everywhere (security review, 21 Oct):
- every route whose path names it answers its signed-in callers the unknown-world 404 (`deps.refuse_hidden_world`), as
  do `deps.member_world`, `deps.team_reader` and the task routes (`tasks._owned`), so a world-bound session and an old
  link read nothing, and a second delete is that 404 too;
- share links into it are revoked (`sharing.WorldView.hidden`: 410);
- it is stopped like a paused world: no run starts in it (`runs.start_run`), a run still holding it writes nothing more
  and its browser step ends (`Run.paused`), and the Scheduler's outbox sweep holds its unsent entries; the plate and a
  routine's next run never offer it. Routines belong to the person, not the world: deleting one result leaves the
  routine as it is.
The lists skip it: `GET /worlds`, the cards feed and team reads. The recorded sample is never a stored world; the
sample router answers its id with 409 `sample_is_a_replay` before this route is reached.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException, Response
from tilo_people.stores import PeopleStores

from tilo_api import deps, dispatch
from tilo_api.deps import (
    EventWriter,
    Principal,
    Store,
    get_current_principal,
    get_event_writer,
    get_people_provider,
    get_store,
)
from tilo_api.worlds_list import world_status

router = APIRouter()

_UNKNOWN = "Tilo could not find that."
_WORKING = "This world is still working. Pause it first, then delete it."
_MEETING = "A meeting for this world is still booked or under way. Cancel or end it first, then delete the world."
_UNCHECKED = "Tilo could not check this world's meetings. Try again."
_CHANGED = "This world changed while it was being deleted. Try again."
_BOOKED = frozenset({"scheduled", "joining", "live"})  # meeting.schema.json states whose bot may still attend


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


def _meeting_booked(people: PeopleStores | None, owner: str, world_id: str) -> bool:
    """Whether a meeting of the owner's names this world and may still have a bot attend it. No people stores (not
    configured or not readable) is a 503: a booked meeting cannot be ruled out."""
    if people is None:
        raise HTTPException(status_code=503, detail=_UNCHECKED)
    try:
        rows = people.meetings.list(deps.ORG_ID, "owner", owner)
    except Exception:
        raise HTTPException(status_code=503, detail=_UNCHECKED) from None
    return any(r.record.get("world_id") == world_id and r.record.get("status") in _BOOKED for r in rows)


def _working(store: Store, world_id: str) -> bool:
    status = world_status(store.events.get(world_id, []))
    return status == "started" or (status == "idle" and world_id in store.runs)


@router.delete("/worlds/{world_id}", status_code=204)
def delete_world(
    world_id: str,
    principal: Principal = Depends(get_current_principal),
    store: Store = Depends(get_store),
    writer: EventWriter = Depends(get_event_writer),
    people: Callable[[], PeopleStores | None] = Depends(get_people_provider),
) -> Response:
    world = _own_world(principal, store, world_id)
    store.settle(world_id, writer)  # a run a restart ended gets its world.failed first, so it is not "working"
    if _working(store, world_id):  # the cheap answer first; read again below, under the locks
        raise HTTPException(status_code=409, detail=_WORKING)
    if _meeting_booked(people(), world.owner, world_id):
        raise HTTPException(status_code=409, detail=_MEETING)
    with dispatch.locked_worlds(store, [world_id]), store.runs_guard:
        current = store.worlds.get(world_id, world)
        if current.hidden:  # a delete that landed while this one waited: the world is off the list either way
            return Response(status_code=204)
        if _working(store, world_id):
            raise HTTPException(status_code=409, detail=_WORKING)
        store.commit(worlds={world_id: dataclasses.replace(current, hidden=True)}, evict=False)  # 409 stale, 503
        # a kill switch's unsaved change is written from the cached record, never a caller's copy: then the flag did
        # not land, and the person tries again rather than being told it is gone
        if not getattr(store.worlds.get(world_id), "hidden", False):
            raise HTTPException(status_code=409, detail=_CHANGED)
    return Response(status_code=204)
