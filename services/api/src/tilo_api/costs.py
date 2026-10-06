"""Cost report routes (FR-MTR-10, API half; services/api/tests/API_FR_MTR_10.md). Two reads, owner only:
`GET /worlds/{world_id}/costs` and `GET /costs`. Each is `tilo_metering.costs.cost_report` over the Treasury ledger
(the `get_ledger` seam) and the world's recorded events, narrowed to the runs of the worlds asked for. Nothing is
written, so `replay_only` (NFR-24) does not close them; the body is the report alone (profiles, never a model id)."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from tilo_metering import LedgerEntry, MeteringConfigError
from tilo_metering.costs import cost_report, load_credit_usd
from tilo_metering.savings import InconsistentMemoryHit

from tilo_api import deps
from tilo_api.deps import Principal, Store, WorldRecord, get_current_principal, get_ledger, get_store

router = APIRouter()


def _unit_types(store: Store, world_id: str) -> dict[str, str]:
    """Plan unit id -> unit_type from the world's stored run; nothing if it has no usable plan (BQ-MTR10-2)."""
    plan = getattr(store.runs.get(world_id), "plan", None)
    units = plan.get("units") if isinstance(plan, dict) else None
    pairs = ((u.get("id"), u.get("unit_type")) for u in units if isinstance(u, dict)) if isinstance(units, list) else ()
    return {unit_id: kind for unit_id, kind in pairs if isinstance(unit_id, str) and isinstance(kind, str)}


_credit_usd_cache: float | None = None


def reset_credit_usd_cache() -> None:
    """Forget the price sheet read so far (tests; a changed prices.yaml needs a restart otherwise)."""
    global _credit_usd_cache
    _credit_usd_cache = None


def _credit_usd() -> float:
    """US$ per credit from config/prices.yaml (FR-MTR-01), read once; an unreadable file closes the routes (503).
    Only a good read is kept, so an unreadable file is tried again on the next request."""
    global _credit_usd_cache
    if _credit_usd_cache is None:
        try:
            _credit_usd_cache = load_credit_usd(deps.prices_path())
        except MeteringConfigError as exc:
            raise HTTPException(status_code=503, detail="not_configured") from exc
    return _credit_usd_cache


def _report(store: Store, ledger: Sequence[LedgerEntry], worlds: Iterable[tuple[str, WorldRecord]]) -> dict[str, Any]:
    """The report for these worlds: their runs (the world's own run id plus any on its events) and no others."""
    events: list[dict] = []
    unit_types: dict[str, dict[str, str]] = {}
    runs: set[str] = set()
    for world_id, world in worlds:
        world_events = store.events.get(world_id, [])
        events += world_events
        runs |= {world.run_id} | {e["run_id"] for e in world_events if isinstance(e.get("run_id"), str)}
        unit_types[world.run_id] = _unit_types(store, world_id)
    credit_usd = _credit_usd()
    try:
        return cost_report([e for e in ledger if e.run in runs], events, unit_types=unit_types, credit_usd=credit_usd)
    except InconsistentMemoryHit as exc:  # a hit that disagrees with its own costs (BQ-MTR10-5): refuse, never a 500
        raise HTTPException(status_code=422, detail="inconsistent_ledger") from exc


@router.get("/worlds/{world_id}/costs")
def get_world_costs(
    world_id: str,
    principal: Principal = Depends(get_current_principal),
    store: Store = Depends(get_store),
    ledger: Sequence[LedgerEntry] = Depends(get_ledger),
) -> JSONResponse:
    """A non-member and an unknown world get the same bare 404; a member who is not the owner gets 403."""
    world = store.worlds.get(world_id)
    if principal.world_id != world_id or world is None:
        raise HTTPException(status_code=404)
    if principal.role != "owner" or principal.user_id != world.owner:
        raise HTTPException(status_code=403)
    return JSONResponse(content={"world_id": world_id, **_report(store, ledger, [(world_id, world)])})


@router.get("/costs")
def get_costs(
    principal: Principal = Depends(get_current_principal),
    store: Store = Depends(get_store),
    ledger: Sequence[LedgerEntry] = Depends(get_ledger),
) -> JSONResponse:
    """Every world the signed-in owner owns, whatever world their principal names."""
    if principal.role != "owner":
        raise HTTPException(status_code=403)
    mine = sorted((w, rec) for w, rec in store.worlds.items() if rec.owner == principal.user_id)
    return JSONResponse(content=_report(store, ledger, mine))
