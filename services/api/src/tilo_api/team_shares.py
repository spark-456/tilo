"""Team-shared worlds, the write half (BQ-CTX-TEAMWORLD, ADR-0040 decisions 2 and 9, FR-TEAM-01/02, PE-31, PE-35):
`PUT` and `DELETE /worlds/{world_id}/team-shares/{team}`. Security-flagged: these two routes are the only way a world
is opened to a team. `GET /worlds/{world_id}/team-shares` (TSW-2a) is the owner's read of the same records, with the
same guard: each share's `in_force` and, when it is not, a fixed reason word.

Only the world's record owner, on a full web or mobile-web sign-in session bound to no world, may call them; every
other caller, an unknown world and a malformed team are the one unknown-world 404 (no membership oracle). To grant,
the owner must also be a member of `{team}` now (PE-04's rule for sharing). `granted_by` and `revoked` are the
verified principal and the server clock, never a body, header or query; the routes read no body at all. No model,
agent, assistant `ui_action` or Approver reaches them, and an org owner has no revoke right: removing the world
owner from the team lapses their shares (`tilo_people.world_share.in_force`).

Order: the record is written first, then the `world.share_changed` event in the shared world (`vis: []`, ids only).
If a grant's event cannot be written the record is removed again and the answer is 503; a revoke's stays (fail
closed) and the identical retry writes the missing event, whose id is derived from the record's own stamp.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Mapping
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Response
from tilo_people.directory import Directory
from tilo_people.errors import AlreadyExists, NotFound, VersionConflict
from tilo_people.stores import PeopleStores, Stored
from tilo_people.world_share import in_force, share_id

from tilo_api import deps, events
from tilo_api.people_limits import write_limit

logger = logging.getLogger("tilo_api.team_shares")
router = APIRouter()

_TEAM = re.compile(r"tm_[0-9a-z_]{1,48}")
_ATTEMPTS = 3  # compare-and-set tries and event appends per request


def _unavailable() -> HTTPException:
    return HTTPException(status_code=503, detail="unavailable")


def _owner_world(principal: deps.Principal, store: deps.Store, world_id: str, team: str | None) -> deps.WorldRecord:
    """The world, for its record owner's full web or mobile-web session bound to no world; else the unknown 404.
    `team` is None for the listing, which names none."""
    world = store.worlds.get(world_id)
    if (
        world is None
        or (team is not None and _TEAM.fullmatch(team) is None)
        or principal.world_id is not None
        or principal.role != "owner"
        or principal.channel not in ("web", "mobile_web")
        or principal.full_session is not True
        or principal.demo_session
        or principal.user_id != world.owner
    ):
        raise HTTPException(status_code=404, detail="Tilo could not find that.")
    return world


def _directory(people: PeopleStores) -> Directory:
    return Directory.of(s.record for s in people.persons.list(deps.ORG_ID))


def _log(writer: deps.EventWriter, world_id: str, actor: str, team: str, state: str, record: dict[str, Any]) -> None:
    """The one event of the change, appended to the shared world; any failure raises. The id comes from the record's
    own stamp, so a retry of the same change is the same part and commits once (EV-10)."""
    stamp = record["granted_by"] if state == "on" else record["revoked"]
    part: dict[str, Any] = {
        "id": events.stable_part_id("world.share_changed", record["id"], state, stamp["at"]),
        "type": "world.share_changed",
        "actor": actor,
        "target": world_id,
        "district": None,
        "summary": f"Team sharing was turned {state} for this world.",
        "vis": [],
        "authz": None,
        "data": {"team": team, "state": state},
    }
    for attempt in range(_ATTEMPTS):
        try:
            writer.append(world_id, part)
            return
        except Exception as exc:
            reopen = getattr(writer, "reopen", None)
            if type(exc).__name__ == "WriterBusy" and callable(reopen):
                try:
                    reopen()
                except Exception:
                    pass  # the original failure and the bounded retries stand
            if attempt == _ATTEMPTS - 1:
                raise


def _grant(shares: Any, wanted: dict[str, Any], owner: str, directory: Directory, now: str) -> tuple[Stored, bool]:
    """Creates the record, keeps the owner's own standing grant (a retry never restamps it), or replaces a revoked
    one, one a previous owner granted, or one that has lapsed (the owner left the team and came back, F1). The flag
    is True when this request wrote the record: only then may a failed event take it back (F2)."""
    for _ in range(_ATTEMPTS):
        held = shares.get(deps.ORG_ID, wanted["id"])
        try:
            if held is None:
                return shares.create(wanted), True
            if in_force(held.record, owner, directory, now):
                return held, False
            return shares.replace(wanted, expected_version=held.version), True
        except (AlreadyExists, VersionConflict, NotFound):
            continue  # a racing writer: read again
    raise _unavailable()


def _take_back(shares: Any, stored: Stored, owner: str, now: str) -> None:
    """Nothing is shared without its event (F3): delete the record this request wrote, retried; if the delete keeps
    failing, stamp the revocation by compare-and-set (fail closed, the share is withdrawn, no event); if that too
    fails the share stays and the case is the residual listed in BQ-TEAMWORLD-3."""
    share_key = stored.record["id"]
    version = stored.version
    for _ in range(_ATTEMPTS):
        try:
            shares.delete(deps.ORG_ID, share_key, expected_version=version)
            return
        except (NotFound, VersionConflict):
            return  # gone, or someone else already replaced it: not this request's to remove
        except Exception:
            continue
    try:
        shares.replace({**stored.record, "revoked": {"by": owner, "at": now}}, expected_version=version)
    except Exception:
        logger.error("world share not removed or revoked after a failed event share=%s", share_key)


def _answer(response: Response, world_id: str, team: str, state: str, now_in_force: bool) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    return {"world_id": world_id, "team": team, "state": state, "in_force": now_in_force}


def _withdraw(shares: Any, world_id: str, team: str, owner: str, now: str) -> dict[str, Any]:
    """Stamps the revocation (compare-and-set), or finds the one a first attempt already stamped; 404 for no share."""
    for _ in range(_ATTEMPTS):
        held = shares.get(deps.ORG_ID, share_id(world_id, team))
        if held is None:
            raise HTTPException(status_code=404, detail="Tilo could not find that.")
        if held.record["revoked"] is not None:
            return dict(held.record)  # a retry: the first revocation stands
        try:
            return dict(
                shares.replace(
                    {**held.record, "revoked": {"by": owner, "at": now}}, expected_version=held.version
                ).record
            )
        except VersionConflict:
            continue
        except NotFound:
            raise HTTPException(status_code=404, detail="Tilo could not find that.") from None
    raise _unavailable()


def _reason(record: Mapping[str, Any], world_owner: str, now: str) -> str:
    """The fixed word for a share that is not in force (PE-31), checked in the order the rule states it."""
    if record["revoked"] is not None:
        return "revoked"
    if record["granted_by"]["by"] != world_owner:
        return "owner_changed"
    if record["granted_by"]["at"] > now:
        return "not_yet"
    return "owner_left_team"


@router.get("/worlds/{world_id}/team-shares")
def list_team_shares(
    world_id: str,
    response: Response,
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    store: Annotated[deps.Store, Depends(deps.get_store)],
    people: Annotated[PeopleStores, Depends(deps.get_people_stores)],
    clock: Annotated[Callable[[], str], Depends(deps.get_clock)],
) -> dict[str, Any]:
    """The owner's view of the world's shares: team, `in_force`, and why not (a fixed word: revoked, owner_left_team,
    owner_changed, not_yet). Same guard as the writes; a team reader, who may read the world, gets the 404."""
    world = _owner_world(principal, store, world_id, None)
    now = clock()
    try:
        directory = _directory(people)
        stored = people.world_shares.list(deps.ORG_ID, "world_id", world_id)
    except Exception:
        raise _unavailable() from None
    rows = []
    for item in sorted(stored, key=lambda s: s.record["team"]):
        record = item.record
        live = in_force(record, world.owner, directory, now)
        rows.append(
            {
                "team": record["team"],
                "in_force": live,
                "reason": None if live else _reason(record, world.owner, now),
                "granted_at": record["granted_by"]["at"],
            }
        )
    response.headers["Cache-Control"] = "no-store"
    return {"world_id": world_id, "shares": rows}


@router.put("/worlds/{world_id}/team-shares/{team}", dependencies=[Depends(write_limit)])
def put_team_share(
    world_id: str,
    team: str,
    response: Response,
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    store: Annotated[deps.Store, Depends(deps.get_store)],
    writer: Annotated[deps.EventWriter, Depends(deps.get_event_writer)],
    people: Annotated[PeopleStores, Depends(deps.get_people_stores)],
    clock: Annotated[Callable[[], str], Depends(deps.get_clock)],
) -> dict[str, Any]:
    """The owner shares the world with `team`: the world's whole Story, Trace, runs and artifacts (not its
    `vis: []` lines), past and future, become readable by every member (ADR-0040 decision 10)."""
    world = _owner_world(principal, store, world_id, team)
    now, owner = clock(), principal.user_id
    wanted = {
        "id": share_id(world_id, team),
        "org_id": deps.ORG_ID,
        "world_id": world_id,
        "team": team,
        "granted_by": {"by": owner, "at": now},
        "revoked": None,
    }
    try:
        directory = _directory(people)
        if not directory.is_member(owner, team, now):
            raise HTTPException(status_code=403, detail="forbidden")
        stored, created = _grant(people.world_shares, wanted, owner, directory, now)
    except HTTPException:
        raise
    except Exception:
        raise _unavailable() from None  # a store that cannot answer: nothing was shared
    try:
        _log(writer, world_id, owner, team, "on", dict(stored.record))
    except Exception as exc:
        logger.warning("world share event not written (%s) world=%s team=%s", type(exc).__name__, world_id, team)
        if created:  # a standing share keeps standing: the retry writes the event only (F2)
            _take_back(people.world_shares, stored, owner, now)
        raise _unavailable() from None
    logger.info("world_share state=on world=%s team=%s by=%s", world_id, team, owner)
    return _answer(response, world_id, team, "on", in_force(stored.record, world.owner, directory, now))


@router.delete("/worlds/{world_id}/team-shares/{team}", dependencies=[Depends(write_limit)])
def delete_team_share(
    world_id: str,
    team: str,
    response: Response,
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    store: Annotated[deps.Store, Depends(deps.get_store)],
    writer: Annotated[deps.EventWriter, Depends(deps.get_event_writer)],
    people: Annotated[PeopleStores, Depends(deps.get_people_stores)],
    clock: Annotated[Callable[[], str], Depends(deps.get_clock)],
) -> dict[str, Any]:
    """The owner withdraws the share, effective on the next request. The revocation is not undone if its event
    fails: the retry writes the event and never restamps the revocation."""
    _owner_world(principal, store, world_id, team)
    owner = principal.user_id
    try:
        record = _withdraw(people.world_shares, world_id, team, owner, clock())
    except HTTPException:
        raise
    except Exception:
        raise _unavailable() from None
    try:
        _log(writer, world_id, owner, team, "off", record)
    except Exception as exc:
        logger.warning("world share event not written (%s) world=%s team=%s", type(exc).__name__, world_id, team)
        raise _unavailable() from None
    logger.info("world_share state=off world=%s team=%s by=%s", world_id, team, owner)
    return _answer(response, world_id, team, "off", False)
