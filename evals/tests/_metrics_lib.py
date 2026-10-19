"""Helpers for the EV metrics tests (PRD 3.5 EV-01..EV-15, PRD 19.3 "honest reporting").

Not a conftest (see _evals_lib.py). The module under test, `tilo_evals.metrics`, is imported lazily through
`metrics()` so that, until it exists, every test fails on its own with ModuleNotFoundError rather than the whole
directory failing at collection.

Pinned shapes (design in the EV-metrics ticket):
- `RunRecord(run_id, source, basis, case_id, group, measures, events, outputs, passed, expected_completed)`, frozen.
- `MetricRow(id, name, target, basis, status, value, n, of, method, note)`, frozen. `value` of a share is a
  fraction in 0..1 (the report prints counts first, then the percent).
- `compute_metrics(runs, *, credit_usd, coverage)` returns rows ordered EV-01..EV-15.
"""

import importlib
import itertools
import re
from collections.abc import Iterable, Mapping
from typing import Any

from _evals_lib import make_event

EV_IDS = tuple(f"EV-{n:02d}" for n in range(1, 16))
COMPUTABLE = ("EV-01", "EV-03", "EV-04", "EV-06", "EV-07", "EV-08", "EV-09", "EV-10")
NEEDS_LIVE_OR_PILOT = ("EV-02", "EV-05", "EV-11", "EV-12", "EV-13", "EV-14", "EV-15")
MODEL_ID = re.compile(r"claude-|gemini-|gpt-", re.IGNORECASE)
CLAIM_SENTENCE = "scripted_fakes rows test pipeline mechanics, not model quality"

_SEQ = itertools.count(1)
_RUN = itertools.count(1)


def metrics() -> Any:
    return importlib.import_module("tilo_evals.metrics")


def metrics_report() -> Any:
    return importlib.import_module("tilo_evals.metrics_report")


# ---- events (shapes from contracts/events/data/*.schema.json) -------------------------------------------------


def event(type_: str, **data: Any) -> dict[str, Any]:
    """A TiloEvent-shaped dict with a process-unique seq and id (memory.hit is de-duplicated by id)."""
    return make_event(next(_SEQ), type_, data=data)


def planned(low: float, high: float, tier: str = "town") -> dict[str, Any]:
    return event("world.planned", tier=tier, approach="standard", unit_count=3, credits={"min": low, "max": high})


def completed(used: float) -> dict[str, Any]:
    return event("world.completed", credits_used=used, deliverable_count=1)


def blocked(unit: str | None = "U1") -> dict[str, Any]:
    return event("agent.blocked", unit=unit, reason="tool failed")


def recovered(unit: str = "U1", attempt: int = 1) -> dict[str, Any]:
    return event("agent.recovered", unit=unit, attempt=attempt)


def escalated(reason: str = "repeated_failure") -> dict[str, Any]:
    return event("agent.escalated", reason=reason)


def budget_requested() -> dict[str, Any]:
    estimate = {"min": 5.0, "max": 9.0}
    return event("budget.requested", requested=2.0, spent=4.0, cap=5.0, remaining_units=[], estimate=estimate)


def approval_requested() -> dict[str, Any]:
    return event("approval.requested", gate_id="g_send", action_type="email.send", risk_tier="T3", irreversible=True)


def alert_raised() -> dict[str, Any]:
    return event("alert.raised", reason="flagged")


def handoff(verified: bool) -> dict[str, Any]:
    note = {"id": "art_note", "kind": "handoff_note"}
    return event("agent.context_handoff_completed", predecessor="A_1", note=note, verification_passed=verified)


def memory_hit(origin: float, lookup: float, saved: float | None = None) -> dict[str, Any]:
    saved = origin - lookup if saved is None else saved
    return event("memory.hit", origin_cost=origin, lookup_cost=lookup, saved=saved)


# ---- records and rows -----------------------------------------------------------------------------------------


def rec(*events: dict[str, Any], basis: str = "recorded", **over: Any) -> Any:
    """A RunRecord. Defaults: a recorded replay of E-PLAN-01 that passed and was expected to complete."""
    fields: dict[str, Any] = {
        "run_id": f"r_{next(_RUN)}",
        "source": "bank" if basis == "scripted_fakes" else "replay",
        "basis": basis,
        "case_id": "B-001" if basis == "scripted_fakes" else "E-PLAN-01",
        "group": None if basis == "scripted_fakes" else "E-PLAN",
        "measures": (),
        "outputs": {},
        "passed": True,
        "expected_completed": True,
    }
    fields |= over
    fields["measures"] = tuple(fields["measures"])
    return metrics().RunRecord(events=tuple(events), **fields)


def full_coverage(value: tuple[int, int] = (0, 0)) -> dict[str, tuple[int, int]]:
    return dict.fromkeys(EV_IDS, value)


def compute(
    runs: Iterable[Any], *, credit_usd: float = 0.005, coverage: Mapping[str, tuple[int, int]] | None = None
) -> list[Any]:
    return metrics().compute_metrics(
        list(runs), credit_usd=credit_usd, coverage=full_coverage() if coverage is None else coverage
    )


def rows_for(rows: list[Any], ev_id: str) -> list[Any]:
    return [r for r in rows if r.id == ev_id]


def only(rows: list[Any], ev_id: str, basis: str | None) -> Any:
    """The single row of `ev_id` on `basis` (None: the basis-less no_data / needs_live_or_pilot row)."""
    found = [r for r in rows if r.id == ev_id and r.basis == basis]
    assert len(found) == 1, f"expected one {ev_id} row on basis {basis!r}, got {[(r.id, r.basis) for r in rows]}"
    return found[0]


def metric_row(**over: Any) -> Any:
    """A MetricRow built by hand, for the rendering tests (independent of compute_metrics)."""
    fields: dict[str, Any] = {
        "id": "EV-01",
        "name": "Task success",
        "target": ">= 85% seeded; >= 60% open",
        "basis": "recorded",
        "status": "computed",
        "value": 0.75,
        "n": 3,
        "of": 4,
        "method": "Share of runs that passed with no human redo.",
        "note": "3 of 4 runs passed. 12 cases measure this, 4 recorded.",
    }
    fields |= over
    return metrics().MetricRow(**fields)
