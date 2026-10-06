"""Builders for the FR-MTR-10 cost-route tests (services/api): a real `Treasury` fed by hand with fake price sheets
(its ledger is the ledger the route reads), plus worlds, plans and events seeded into the in-memory `Store`. Kept out of
conftest.py under a package-unique module name (see _api_lib.py). Fake data only: no network, no provider.

Scenario (credits worked out by hand; 1 credit = US$0.005; sheet v1 effective 2026-01-01, sheet v2 effective
2026-06-01; flash-38 100k in + 50k out costs 40 credits under v1 and 120 under v2; lite-31 200k in + 100k out costs 40):

    world  owner     run    tier     done  spend
    w_a1   u_owner   r_a1   village  yes   U1 flash-38 40 (v1), U2 flash-38 120 (v2, from 2026-06-01), U3 lite-31 40;
                                          one accepted memory hit, origin 6, lookup 0.5, delivered twice
    w_a2   u_owner   r_a2   outpost  yes   U1 lite-31 40 + U9 plain commit 2 (no usage, not in the plan)
    w_b    u_other   r_b1   village  yes   U1 flash-38 120 (v2) and a memory hit, origin 10, lookup 1
"""

from __future__ import annotations

import copy
import json
import pathlib
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import yaml
from _api_lib import REPO_ROOT, make_world, validate_event
from tilo_api import app, deps
from tilo_metering import InMemoryFlagStore, MeteringConfig, PriceBook, Reservation, Treasury, Usage

CREDIT_USD = 0.005
OWNER, OTHER = "u_owner", "u_other"
A1, A2, B = "w_a1", "w_a2", "w_b"
RUN = {A1: "r_a1", A2: "r_a2", B: "r_b1"}
FLASH, LITE = "flash-38", "lite-31"  # profile names (config/models.yaml); never model ids
PLANS = {
    A1: {"units": [{"id": "U1", "unit_type": "research"}, {"id": "U2", "unit_type": "draft"},
                   {"id": "U3", "unit_type": "research"}]},
    A2: {"units": [{"id": "U1", "unit_type": "research"}]},
    B: {"units": [{"id": "U1", "unit_type": "draft"}]},
}  # fmt: skip
TIER = {A1: "village", A2: "outpost", B: "village"}
_ID_BASE = {A1: 0, A2: 100, B: 200}  # event ids are unique across worlds


def at(day: str, time: str = "12:00:00") -> datetime:
    return datetime.fromisoformat(f"{day}T{time}+00:00").astimezone(UTC)


def _sheet(effective_date: str, source: str, flash_in: float, flash_out: float) -> dict:
    return {
        "status": "set", "effective_date": effective_date, "source": source, "currency": "USD",
        "credit_usd": CREDIT_USD,
        "profiles": {FLASH: {"input": flash_in, "output": flash_out}, LITE: {"input": 0.5, "output": 1.0}},
    }  # fmt: skip


def _write(tmp_path: pathlib.Path, name: str, doc: dict) -> pathlib.Path:
    (path := tmp_path / name).write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return path


def treasury(tmp_path: pathlib.Path) -> Treasury:
    v1 = _write(tmp_path, "prices_v1.yaml", _sheet("2026-01-01", "Fake price sheet v1 for tests.", 1.0, 2.0))
    v2 = _write(tmp_path, "prices_v2.yaml", _sheet("2026-06-01", "Fake price sheet v2 for tests.", 3.0, 6.0))
    config = {  # the PRD 14.1 demo defaults, as packages/metering/tests/data/metering.stub.yaml
        "treasury": {"reserve_margin": 0.15, "request_at": 0.80},
        "caps": {"run_credits": 300, "user_day_credits": 1500, "org_day_credits": None},
        "spend": {"daily_usd_soft": 15, "daily_usd_hard": 25},
        "reconciliation": {"tolerance": 0.10, "billing_services": []},
    }
    return Treasury(
        config=MeteringConfig.load(_write(tmp_path, "metering.yaml", config)),
        prices=PriceBook.load(v1, v2),
        flags=InMemoryFlagStore(),
    )


def _reserve(t: Treasury, run: str, step: str, estimate: float, when: datetime) -> Reservation:
    reservation = t.reserve(run, step, estimate, at=when)
    assert isinstance(reservation, Reservation), f"the fake budget should never make {run}/{step} wait"
    return reservation


def _spend(t, run, step, profile, tokens_in, tokens_out, when, estimate=40.0) -> None:
    t.commit_usage(_reserve(t, run, step, estimate, when), Usage(profile, tokens_in, tokens_out), at=when)


def build_ledger(tmp_path: pathlib.Path) -> Treasury:
    t = treasury(tmp_path)
    for world, owner in ((A1, OWNER), (A2, OWNER), (B, OTHER)):
        t.open_run(RUN[world], user_id=owner, org_id="org_test", approved=300)
    _spend(t, "r_a1", "U1", FLASH, 100_000, 50_000, at("2026-05-31", "23:59:00"))  # sheet v1: 40
    _spend(t, "r_a1", "U2", FLASH, 100_000, 50_000, at("2026-06-01", "00:00:00"), 120.0)  # sheet v2: 120
    _spend(t, "r_a1", "U3", LITE, 200_000, 100_000, at("2026-06-02"))  # 40
    _spend(t, "r_a2", "U1", LITE, 200_000, 100_000, at("2026-06-03"))  # 40
    t.commit(_reserve(t, "r_a2", "U9", 10.0, at("2026-06-03")), 2.0, at=at("2026-06-03"))  # no usage, not in the plan
    _spend(t, "r_b1", "U1", FLASH, 100_000, 50_000, at("2026-06-02"), 120.0)  # sheet v2: 120
    return t


def commits(ledger, run: str | None = None) -> list:
    return [e for e in ledger if e.kind == "commit" and (run is None or e.run == run)]


# --- events and store ---------------------------------------------------------------------------------------


def _fixture(name: str) -> dict:
    return json.loads((REPO_ROOT / "contracts" / "fixtures" / "events" / "valid" / f"{name}.json").read_text("utf-8"))


def event(type_: str, world: str, seq: int, data: dict | None = None, **overrides: Any) -> dict:
    """A valid event (checked against event.schema.json and its data schema) copied from the registry fixture."""
    ev = copy.deepcopy(_fixture(type_))
    ev.update(
        id=f"01JB5VQ{_ID_BASE[world] + seq:019d}", seq=seq, world_id=world, run_id=RUN[world], target=world, vis="all"
    )
    ev.update(district=None, level=None)
    if data is not None:
        ev["data"] = data
    ev.update(overrides)
    validate_event(ev)
    return ev


def world_events(world: str, *, done: bool = True, hit: tuple[float, float] | None = None) -> list[dict]:
    planned = {"tier": TIER[world], "approach": "standard", "unit_count": 3, "credits": {"min": 20, "max": 35}}
    events = [event("world.planned", world, 1, planned)]
    if done:
        events.append(event("world.completed", world, 2, {"credits_used": 1.0, "deliverable_count": 1}))
    if hit:
        origin, lookup = hit
        data = {"origin_cost": origin, "lookup_cost": lookup, "saved": origin - lookup}
        delivered = event("memory.hit", world, 3, data)
        events += [delivered, copy.deepcopy(delivered)]  # the same event, delivered twice
    return events


def seed(store: deps.Store, *, with_plans: bool = True) -> None:
    """The three worlds of the scenario above, each with its events, and (by default) the plan its run holds."""
    for world, owner in ((A1, OWNER), (A2, OWNER), (B, OTHER)):
        store.worlds[world] = make_world(owner=owner, run_id=RUN[world])
    store.events[A1] = world_events(A1, hit=(6, 0.5))
    store.events[A2] = world_events(A2)
    store.events[B] = world_events(B, hit=(10, 1))
    if with_plans:
        for world, plan in PLANS.items():
            store.runs[world] = SimpleNamespace(plan=copy.deepcopy(plan))


def serve_ledger(ledger) -> None:
    """The route's one new seam: `tilo_api.deps.get_ledger()` returns the Treasury's ledger (a sequence of
    LedgerEntry). The `client` fixture clears dependency_overrides at teardown."""
    assert hasattr(deps, "get_ledger"), (
        "tilo_api.deps.get_ledger (the ledger seam, API_FR_MTR_10.md) does not exist yet"
    )
    app.dependency_overrides[deps.get_ledger] = lambda: ledger


def row(body_rows: list[dict], **match: Any) -> dict:
    found = [r for r in body_rows if all(r.get(k) == v for k, v in match.items())]
    assert len(found) == 1, f"expected one row for {match}, found {len(found)} in {body_rows}"
    return found[0]


def model_ids() -> set[str]:
    """Every model id written in config/models*.yaml (PL-01), read at run time so this file names none."""
    ids: set[str] = set()
    for path in sorted((REPO_ROOT / "config").glob("models*.yaml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        ids |= {p["model"] for p in (doc.get("profiles") or {}).values() if isinstance(p, dict) and p.get("model")}
    return ids
