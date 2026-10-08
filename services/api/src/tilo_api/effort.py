"""Effort tracker, API half (FR-PA-20; services/api/tests/API_FR_PA_20.md): `GET /v1/effort`, Tilo's own effort for the
signed-in person's own worlds, credits from the Treasury ledger (FR-MTR-10's reading, `costs._report`) and a time-saved
estimate (PRD 14.2) from the recorded `building.completed` events and the EV-G2 baselines (the `get_time_baselines`
seam). No human time, no person, no model call, no write. A source that is not wired is 503 `not_configured`; one that
fails is 503 `unavailable`; an honest figure is complete or absent (HR-1)."""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping, Sequence
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from tilo_metering import LedgerEntry
from tilo_people.stores import PeopleStores

from tilo_api import deps
from tilo_api.costs import _report
from tilo_api.people import _PeopleRoute

_METHOD_URL = re.compile(r"https://[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?(?::[0-9]{1,5})?(?:/[A-Za-z0-9._~/-]*)?")
Minutes = tuple[float, float, float]  # (minutes, low, high)


def _number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def _baselines(sheet: Any) -> tuple[str, dict[str, Minutes]]:
    """(method_url, unit_type -> (median, p25, p75)); a sheet that breaks its rules refuses the read (never a guess)."""
    refusal = HTTPException(status_code=503, detail="not_configured")
    if not isinstance(sheet, Mapping) or not isinstance(sheet.get("units"), Mapping):
        raise refusal
    url = sheet.get("method_url")
    if not isinstance(url, str) or _METHOD_URL.fullmatch(url) is None:
        raise refusal
    units: dict[str, Minutes] = {}
    for kind, base in sheet["units"].items():
        if not isinstance(kind, str) or not isinstance(base, Mapping):
            raise refusal
        p25, median, p75 = (base.get(k, -1) for k in ("p25", "median", "p75"))  # -1: missing, refused below
        if not (_number(p25) and _number(median) and _number(p75) and p25 <= median <= p75):
            raise refusal
        units[kind] = (float(median), float(p25), float(p75))
    return url, units


def _saved(events: Sequence[Mapping[str, Any]], units: Mapping[str, Minutes], url: str) -> dict[str, Any]:
    """PRD 14.2 gross: each `building.completed` id once, unit_count x median / p25 / p75; a unit type without a
    baseline counts zero. Steering is not measured (BQ-PA20-3), so nothing is subtracted."""
    seen: set[str] = set()
    parts: list[Minutes] = []
    for ev in events:
        data = ev.get("data")
        if ev.get("type") != "building.completed" or ev.get("id") in seen or not isinstance(data, Mapping):
            continue
        seen.add(ev["id"])
        base, count = units.get(data.get("unit_type")), data.get("unit_count")  # type: ignore[arg-type]
        if base is not None and isinstance(count, int) and not isinstance(count, bool):
            parts.append((count * base[0], count * base[1], count * base[2]))
    return _time_saved([p[0] for p in parts], [p[1] for p in parts], [p[2] for p in parts], url)


def _time_saved(minutes: list[float], low: list[float], high: list[float], url: str) -> dict[str, Any]:
    return {
        "minutes": math.fsum(minutes),
        "low": math.fsum(low),
        "high": math.fsum(high),
        "steering_measured": False,
        "method_url": url,
    }


def _sum_saved(rows: Sequence[Mapping[str, Any]], url: str) -> dict[str, Any]:
    cols = [[r["time_saved"][k] for r in rows] for k in ("minutes", "low", "high")]
    return _time_saved(cols[0], cols[1], cols[2], url)


def _effort(
    person: str,
    stores: PeopleStores,
    store: deps.Store,
    ledger: Sequence[LedgerEntry],
    sheet: Any,
) -> dict[str, Any] | None:
    if stores.persons.get(deps.ORG_ID, person) is None:
        return None
    url, units = _baselines(sheet)
    mine = sorted((w, rec) for w, rec in store.worlds.items() if rec.owner == person)
    try:
        report = _report(store, ledger, mine)
    except HTTPException as refusal:
        if refusal.status_code == 422:  # a ledger that disagrees with itself is a source that cannot be read
            raise HTTPException(status_code=503, detail="unavailable") from None
        raise
    run_world: dict[str, str] = {}
    events: dict[str, list[Mapping[str, Any]]] = {}
    for world_id, rec in mine:
        run_world.setdefault(rec.run_id, world_id)
        for ev in store.events.get(world_id, []):
            if isinstance(ev.get("run_id"), str):
                run_world.setdefault(ev["run_id"], world_id)
                events.setdefault(ev["run_id"], []).append(ev)
    by_run = {t["run_id"]: t for t in report["tasks"]}
    for run in run_world.keys() - by_run.keys():  # a run with no spend and no recorded plan is a task with 0
        by_run[run] = {"run_id": run, "completed": False, "credits": 0.0, "usd": 0.0}
    meetings = sorted(
        (m.record for m in stores.meetings.list(deps.ORG_ID, "owner", person) if m.record.get("status") != "deleted"),
        key=lambda m: m["id"],
    )
    linked: dict[str, str] = {}
    for m in reversed(meetings):  # the smallest meeting id wins when two name one world
        if m.get("world_id") in dict(mine):
            linked[m["world_id"]] = m["id"]
    tasks = [
        {
            "world_id": run_world[run],
            "run_id": run,
            "meeting_id": linked.get(run_world[run]),
            "completed": row["completed"],
            "credits": row["credits"],
            "usd": row["usd"],
            "time_saved": _saved(events.get(run, []), units, url),
        }
        for run, row in sorted(by_run.items())
    ]

    def meeting_row(m: Mapping[str, Any]) -> dict[str, Any]:
        world = m.get("world_id") if m.get("world_id") in dict(mine) else None
        rows = [t for t in tasks if world is not None and t["world_id"] == world]
        return {
            "meeting_id": m["id"],
            "world_id": world,
            "tasks": len(rows),
            "credits": math.fsum(t["credits"] for t in rows),
            "usd": math.fsum(t["usd"] for t in rows),
            "time_saved": _sum_saved(rows, url),
        }

    return {
        "credit_usd": report["credit_usd"],
        "totals": {
            "tasks": len(tasks),
            "completed_tasks": sum(1 for t in tasks if t["completed"]),
            "credits": math.fsum(t["credits"] for t in tasks),
            "usd": math.fsum(t["usd"] for t in tasks),
            "time_saved": _sum_saved(tasks, url),
        },
        "meetings": [meeting_row(m) for m in meetings],
        "tasks": tasks,
    }


class _EffortRoute(_PeopleRoute):
    """A wired source that raises (ledger, baselines, people stores) is the fixed 503 `unavailable`, never a 500."""

    def get_route_handler(self) -> Callable[[Request], Any]:
        inner = super().get_route_handler()

        async def guarded(request: Request) -> Response:
            try:
                return await inner(request)  # type: ignore[no-any-return]
            except Exception:
                response = JSONResponse(status_code=503, content={"detail": "unavailable"})
                response.headers["Cache-Control"] = "no-store"
                return response

        return guarded


router = APIRouter(route_class=_EffortRoute)


@router.get("/v1/effort")
def effort_route(
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    stores: Annotated[PeopleStores, Depends(deps.get_people_stores)],
    store: Annotated[deps.Store, Depends(deps.get_store)],
    ledger: Annotated[Sequence[LedgerEntry], Depends(deps.get_ledger)],
    sheet: Annotated[Any, Depends(deps.get_time_baselines)],
) -> dict[str, Any]:
    """The signed-in person's own effort (PE-26): nothing in the request names a person. No person record is the one
    404; a stranger and a person of another org look alike."""
    found = _effort(principal.user_id, stores, store, ledger, sheet)
    if found is None:
        raise HTTPException(status_code=404, detail="not_found")
    return found
