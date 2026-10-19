"""The reminder sweep and the nudge routes (FR-PA-15b; FR-PA-05, FR-PA-15, PE-12, PE-26, PRD 10.2).

The Scheduler's tick calls `sweep`: for each person inside their working window it first returns the nudges whose
snooze has ended, then reads the person's plate through the one PE-26 builder (`build_plate`, so owner filters, `decide`
and PE-21 flags hold as everywhere else) and offers a nudge for each work item due today (`due_24h`, a date is due at
the end of its day) or past due (`overdue`). `tilo_channels.nudges.NudgeGate` decides in code, with no model, whether it
is raised now (window, daily cap, once per item, rule and day); a raised nudge is one `alert.raised` of severity `nudge`
in the person's Desk world with a fixed template line and ids only. The gate's per-person state is one document at
`orgs/{org}/nudge_state/{user}` (optimistic, retried), shared by every instance. The person snoozes a nudge (an hour,
or until tomorrow) through `POST /v1/nudges/{alert_id}/snooze` as themselves. Off unless `TILO_NUDGES=1`; a seam that is
not wired or a person whose plate fails is logged by type and skipped; the tick's own answer is unchanged.
"""

from __future__ import annotations

import copy
import datetime as dt
import json
import logging
import os
import re
from collections.abc import Callable
from typing import Annotated, Any, Literal, TypeVar
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from google.api_core.exceptions import Aborted, AlreadyExists, FailedPrecondition
from pydantic import BaseModel, ConfigDict
from tilo_channels.nudges import MemoryNudgeStore, Nudge, NudgeGate, NudgeRules, NudgeStore
from tilo_people.stores import PeopleStores

from tilo_api import access, deps, store_door
from tilo_api.people import _PeopleRoute
from tilo_api.people_plate import build_plate
from tilo_api.people_writes import json_body

logger = logging.getLogger("tilo_api.nudge_sweep")
ENV_NUDGES = "TILO_NUDGES"
MAX_PEOPLE = 500
_ATTEMPTS = 5
_USER = re.compile(r"u_[0-9A-Za-z_]{1,48}\Z")
_ALERT = re.compile(r"[0-7][0-9A-HJKMNP-TV-Z]{25}\Z")
_DESK = re.compile(r"w_desk_[0-9A-Za-z_]{1,43}\Z")
T = TypeVar("T")


class NudgeBusy(Exception):
    """The person's nudge state kept changing under the writer for every attempt: nothing was recorded."""


class FirestoreNudgeStore:
    """`orgs/{org}/nudge_state/{user}` = `{state: <json text>}`. One read-modify-write per `update`, guarded by the
    document's last update time (`create` when absent), retried on a lost race; the state is a JSON string so no key
    of it is a field path. `fn` may run more than once, which is safe: its part id is derived, so a repeated
    emit is the same event (EV-10)."""

    def __init__(self, client: Any, *, org_id: str = deps.ORG_ID) -> None:
        self._client, self._org = client, org_id

    def update(self, user_id: str, fn: Callable[[dict[str, Any]], T]) -> T:
        if _USER.match(user_id) is None:
            raise ValueError("not a user id")
        path = f"orgs/{self._org}/nudge_state/{user_id}"
        for _ in range(_ATTEMPTS):
            ref = self._client.document(path)
            snap = ref.get()
            held = json.loads((snap.to_dict() or {})["state"]) if snap.exists else {}
            work = copy.deepcopy(held)
            out = fn(work)
            payload = {"state": json.dumps(work, sort_keys=True, separators=(",", ":"))}
            try:
                if snap.exists:
                    ref.update(payload, option=self._client.write_option(last_update_time=snap.update_time))
                else:
                    ref.create(payload)
            except (FailedPrecondition, AlreadyExists, Aborted):
                continue  # another instance wrote first: read again
            return out
        raise NudgeBusy


_memory = MemoryNudgeStore()  # dev and tests only


def get_nudge_store() -> NudgeStore:
    """Deployed: the Firestore store behind the API store door (503 `not_configured` when it does not open, never
    memory: a snooze must survive a restart and be seen by every instance). Off Cloud Run: in memory."""
    if not access.enforced():
        return _memory
    try:
        return FirestoreNudgeStore(store_door.open_api_store(firestore_client_factory=store_door.client_factory).client)
    except (store_door.ApiStoreNotConfigured, store_door.ApiStoreUnavailable):
        raise HTTPException(status_code=503, detail="not_configured") from None


def make_gate(store: NudgeStore, writer: deps.EventWriter, desks: deps.DeskWorlds, stores: PeopleStores) -> NudgeGate:
    """The gate over the person's Desk world: each part is appended to the Desk world of the person it names, and only
    when that world is theirs (the answer is checked before anything is written, as for the work-item events)."""

    def emit(user_id: str, part: dict[str, Any]) -> None:
        world = desks.desk_world(deps.ORG_ID, user_id)
        if type(world) is not str or _DESK.match(world) is None or desks.desk_owner(world) != user_id:
            raise ValueError("not the person's Desk world")
        writer.append(world, part)

    def zone_of(user_id: str) -> str | None:
        found = stores.persons.get(deps.ORG_ID, user_id)
        return None if found is None else found.record.get("time_zone")

    return NudgeGate(rules=NudgeRules.load(), store=store, emit=emit, zone_of=zone_of)


def candidates(plate: dict[str, Any], user_id: str) -> list[Nudge]:
    """The nudges a plate asks for, in a fixed order: past due (oldest first), then due today. Only the person's own
    work item rows that PE-21 has not flagged; nothing of a title is carried."""
    today = plate["today"]
    rows = [
        r
        for r in plate["rows"]
        if r["ref"]["kind"] == "work_item" and r["flagged"] is False and isinstance(r["due"], str)
    ]
    late = sorted((r for r in rows if r["due"] < today), key=lambda r: (r["due"], r["ref"]["id"]))
    now = sorted((r for r in rows if r["due"] == today), key=lambda r: r["ref"]["id"])
    return [Nudge(user_id, r["ref"]["id"], "overdue") for r in late] + [
        Nudge(user_id, r["ref"]["id"], "due_24h") for r in now
    ]


def _inside(now: dt.datetime, zone: str, rules: NudgeRules) -> bool:
    try:
        local = now.astimezone(ZoneInfo(zone))
    except Exception:
        return False
    return rules.window_start <= f"{local:%H:%M}" < rules.window_end


def sweep(request: Request, now: str) -> int:
    """One pass for every person inside their window; returns how many nudges were raised (new or returned)."""
    if os.environ.get(ENV_NUDGES) != "1":
        return 0
    ov = request.app.dependency_overrides
    try:
        stores = ov.get(deps.get_people_stores, deps.get_people_stores)()
        sources = ov.get(deps.get_plate_sources, deps.get_plate_sources)()
        owners = ov.get(deps.get_source_owners, deps.get_source_owners)()
        writer = ov.get(deps.get_event_writer, deps.get_event_writer)()
        desks = ov.get(deps.get_desk_worlds, deps.get_desk_worlds)()
        gate = make_gate(ov.get(get_nudge_store, get_nudge_store)(), writer, desks, stores)
        rules = NudgeRules.load()
        at = dt.datetime.fromisoformat(now.replace("Z", "+00:00"))
        people = [s.record for s in stores.persons.list(deps.ORG_ID)][:MAX_PEOPLE]
    except Exception as exc:
        logger.info("nudge sweep not run (%s)", type(exc).__name__)
        return 0
    raised = 0
    for person in people:
        user = person["id"]
        if not _inside(at, str(person.get("time_zone")), rules):
            continue
        try:
            raised += len(gate.release(user, now=at))
            plate = build_plate(stores, sources, owners, deps.ORG_ID, user, now)
            for nudge in candidates(plate, user) if plate is not None else ():
                raised += gate.offer(nudge, now=at).status == "raised"
        except Exception as exc:
            logger.warning("nudge sweep failed for one person (%s)", type(exc).__name__)
    return raised


# -- the person's own routes -----------------------------------------------------------------------------------------

router = APIRouter(route_class=_PeopleRoute)  # the people write stack: write limit, 413 cap, 415, no-store


class SnoozeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    choice: Literal["hour", "tomorrow"]


def _gate(
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    stores: Annotated[PeopleStores, Depends(deps.get_people_stores)],
    store: Annotated[NudgeStore, Depends(get_nudge_store)],
    writer: Annotated[deps.EventWriter, Depends(deps.get_event_writer)],
    desks: Annotated[deps.DeskWorlds, Depends(deps.get_desk_worlds)],
) -> NudgeGate:
    return make_gate(store, writer, desks, stores)


@router.get("/v1/nudges")
def list_nudges(
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    gate: Annotated[NudgeGate, Depends(_gate)],
    clock: Annotated[Callable[[], str], Depends(deps.get_clock)],
    response: Response,
) -> dict[str, Any]:
    """The signed-in person's own nudges of today (no query names a person)."""
    response.headers["Cache-Control"] = "no-store"
    at = dt.datetime.fromisoformat(clock().replace("Z", "+00:00"))
    return {"nudges": gate.active(principal.user_id, now=at)}


@router.post("/v1/nudges/{alert_id}/snooze")
def snooze_nudge(
    alert_id: str,
    body: Annotated[SnoozeIn, Depends(json_body(SnoozeIn))],
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    gate: Annotated[NudgeGate, Depends(_gate)],
    clock: Annotated[Callable[[], str], Depends(deps.get_clock)],
    response: Response,
) -> dict[str, Any]:
    """Snooze one of the person's own nudges for an hour or until tomorrow's window; it returns once."""
    response.headers["Cache-Control"] = "no-store"
    if _ALERT.match(alert_id) is None:
        raise HTTPException(status_code=404, detail="not_found")
    at = dt.datetime.fromisoformat(clock().replace("Z", "+00:00"))
    done = gate.snooze(principal.user_id, alert_id, body.choice, now=at)
    if done.status != "snoozed":
        raise HTTPException(status_code=404, detail="not_found")  # one body: unknown, another person's, gone
    return {"alert_id": alert_id, "snoozed_until": done.until}
