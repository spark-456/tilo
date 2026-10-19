"""Builders for the FR-MTR-10 cost-report tests (packages/metering). Not conftest.py: prepend import mode needs
unique basenames. Fake data only: fake price sheets, a real `Treasury` fed by hand (its ledger is the ledger under
test), and events copied from `contracts/fixtures/events/valid/` with only ids and the fields a test names changed.

The scenario below is the one every number in test_FR_MTR_10_cost_report.py is checked against. Credits are worked out
by hand from the fake price sheets (1 credit = US$0.005):

    sheet v1 (effective 2026-01-01): flash-38 in 1.0 out 2.0, lite-31 in 0.5 out 1.0   (US$ per million tokens)
    sheet v2 (effective 2026-06-01): flash-38 in 3.0 out 6.0, lite-31 unchanged
    flash-38, 100k in + 50k out: v1 = 0.20 US$ = 40 credits;  v2 = 0.60 US$ = 120 credits
    lite-31,  200k in + 100k out: 0.10 + 0.10 US$ = 40 credits (either sheet)

    run   tier     done   entries (step, profile, credits, date)
    r_a1  village  yes    U1 flash-38 40 (2026-05-31, sheet v1) / U2 flash-38 120 (2026-06-01, sheet v2) / U3 lite-31 40
    r_a2  outpost  yes    U1 lite-31 40 / U9 no usage 2 (a plain commit)
    r_a3  (none)   no     U1 flash-38 40 (2026-05-01, sheet v1)
    r_a4  village  yes    U1 lite-31 40
"""

from __future__ import annotations

import copy
import json
import pathlib
from datetime import UTC, datetime

from _metering_testlib import REPO_ROOT, metering_config, write_yaml
from tilo_metering import InMemoryFlagStore, MeteringConfig, PriceBook, Reservation, Treasury, Usage

FIXTURES = REPO_ROOT / "contracts" / "fixtures" / "events"
CREDIT_USD = 0.005

OWNER, ORG = "u_owner", "org_test"
FLASH, LITE = "flash-38", "lite-31"  # profile names (config/models.yaml); never model ids

UNIT_TYPES = {  # run id -> plan unit id -> unit_type (plan.schema.json units[].unit_type)
    "r_a1": {"U1": "research", "U2": "draft", "U3": "research"},
    "r_a2": {"U1": "research"},
    "r_a3": {"U1": "draft"},
    "r_a4": {"U1": "research"},
}
WORLD_OF = {"r_a1": "w_a1", "r_a2": "w_a2", "r_a3": "w_a3", "r_a4": "w_a4"}
TIER_OF = {"r_a1": "village", "r_a2": "outpost", "r_a4": "village"}  # r_a3 never planned
COMPLETED = ("r_a1", "r_a2", "r_a4")  # r_a3 never completed


def at(day: str, time: str = "12:00:00") -> datetime:
    return datetime.fromisoformat(f"{day}T{time}+00:00").astimezone(UTC)


def prices_doc(effective_date: str, source: str, flash_in: float, flash_out: float) -> dict:
    """A contracts/providers.schema.json $defs.prices document with fake numbers for two profiles."""
    return {
        "status": "set", "effective_date": effective_date, "source": source, "currency": "USD",
        "credit_usd": CREDIT_USD,
        "profiles": {FLASH: {"input": flash_in, "output": flash_out}, LITE: {"input": 0.5, "output": 1.0}},
    }  # fmt: skip


SHEET_V1 = prices_doc("2026-01-01", "Fake price sheet v1 for tests.", 1.0, 2.0)
SHEET_V2 = prices_doc("2026-06-01", "Fake price sheet v2 for tests.", 3.0, 6.0)


def price_book(tmp_path: pathlib.Path) -> PriceBook:
    return PriceBook.load(
        write_yaml(tmp_path, "prices_v1.yaml", SHEET_V1), write_yaml(tmp_path, "prices_v2.yaml", SHEET_V2)
    )


def treasury(tmp_path: pathlib.Path) -> Treasury:
    config = MeteringConfig.load(write_yaml(tmp_path, "metering.yaml", metering_config()))
    return Treasury(config=config, prices=price_book(tmp_path), flags=InMemoryFlagStore())


def _reserve(t: Treasury, run: str, step: str, estimate: float, when: datetime) -> Reservation:
    reservation = t.reserve(run, step, estimate, at=when)
    assert isinstance(reservation, Reservation), f"the fake budget should never make {run}/{step} wait: {reservation}"
    return reservation


def spend(
    t: Treasury,
    run: str,
    step: str,
    profile: str,
    tokens_in: int,
    tokens_out: int,
    when: datetime,
    estimate: float = 40.0,
) -> None:
    """One priced commit through `commit_usage`: the Treasury prices it with the sheet in effect on `when`."""
    reservation = _reserve(t, run, step, estimate, when)
    t.commit_usage(reservation, Usage(profile, tokens_in, tokens_out), at=when)


def plain_commit(t: Treasury, run: str, step: str, credits: float, when: datetime) -> None:
    t.commit(_reserve(t, run, step, 10.0, when), credits, at=when)


def build_ledger(tmp_path: pathlib.Path, *, noise: bool = False) -> Treasury:
    """The scenario's ledger. `noise` adds what is not spend: a released reservation, a grant, a priced usage record
    and one unpriced usage record, none of which is a commit."""
    t = treasury(tmp_path)
    for run in ("r_a1", "r_a2", "r_a3", "r_a4"):
        t.open_run(run, user_id=OWNER, org_id=ORG, approved=300)
    spend(t, "r_a1", "U1", FLASH, 100_000, 50_000, at("2026-05-31", "23:59:00"))  # sheet v1: 40
    spend(t, "r_a1", "U2", FLASH, 100_000, 50_000, at("2026-06-01", "00:00:00"), 120.0)  # sheet v2: 120
    spend(t, "r_a1", "U3", LITE, 200_000, 100_000, at("2026-06-02"))  # 40
    spend(t, "r_a2", "U1", LITE, 200_000, 100_000, at("2026-06-03"))  # 40
    plain_commit(t, "r_a2", "U9", 2.0, at("2026-06-03"))  # no usage: no profile
    spend(t, "r_a3", "U1", FLASH, 100_000, 50_000, at("2026-05-01"))  # sheet v1: 40
    spend(t, "r_a4", "U1", LITE, 200_000, 100_000, at("2026-06-04"))  # 40
    if noise:
        t.release(_reserve(t, "r_a1", "U7", 20.0, at("2026-06-05")))
        t.grant("r_a1", 25.0)
        t.record_usage("r_a1", Usage(FLASH, 1_000_000, 1_000_000), at=at("2026-06-05"))
        t.record_usage("r_a4", Usage(LITE, 5, 5), at=at("2026-06-05"))
    return t


def commits(ledger) -> list:
    return [e for e in ledger if e.kind == "commit"]


# --- events ---------------------------------------------------------------------------------------------------


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / "valid" / f"{name}.json").read_text(encoding="utf-8"))


def event(type_: str, *, run: str, seq: int, data: dict | None = None, **overrides) -> dict:
    """A schema-shaped event copied from the registry fixture for `type_`; ids follow `seq` so builds are stable."""
    ev = copy.deepcopy(_fixture(type_))
    ev.update(id=f"01JB5VQ{seq:019d}", seq=seq, run_id=run, world_id=WORLD_OF.get(run, f"w_{run}"))
    if data is not None:
        ev["data"] = data
    ev.update(overrides)
    return ev


def planned(run: str, tier: str, seq: int) -> dict:
    data = {"tier": tier, "approach": "standard", "unit_count": 3, "credits": {"min": 20, "max": 35}}
    return event("world.planned", run=run, seq=seq, data=data)


def completed(run: str, seq: int) -> dict:
    return event("world.completed", run=run, seq=seq, data={"credits_used": 1.0, "deliverable_count": 1})


def hit(run: str, seq: int, origin: float, lookup: float) -> dict:
    data = {"origin_cost": origin, "lookup_cost": lookup, "saved": origin - lookup}
    return event("memory.hit", run=run, seq=seq, data=data)


H1 = hit("r_a1", 50, 6, 0.5)  # saves 5.5
H2 = hit("r_a4", 51, 10, 1)  # saves 9


def scenario_events(*, hits: bool = True) -> list[dict]:
    """Planned and completed events for the runs above, plus two accepted reuses; H1 arrives twice (a redelivery)."""
    events = [planned(run, tier, 10 + i) for i, (run, tier) in enumerate(TIER_OF.items())]
    events += [completed(run, 20 + i) for i, run in enumerate(COMPLETED)]
    if hits:
        events += [copy.deepcopy(H1), copy.deepcopy(H2), copy.deepcopy(H1)]
    return events


def row(rows: list[dict], **match) -> dict:
    """The one row whose keys equal `match`; fails the test with the rows listed if there is not exactly one."""
    found = [r for r in rows if all(r.get(k) == v for k, v in match.items())]
    assert len(found) == 1, f"expected one row for {match}, found {len(found)} in {rows}"
    return found[0]


def model_ids() -> set[str]:
    """Every model id written in config/models*.yaml (PL-01): read at run time so this file names none."""
    import yaml

    ids: set[str] = set()
    for path in sorted((REPO_ROOT / "config").glob("models*.yaml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        ids |= {p["model"] for p in (doc.get("profiles") or {}).values() if isinstance(p, dict) and p.get("model")}
    return ids
