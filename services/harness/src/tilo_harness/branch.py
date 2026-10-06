"""Restart a run from a checkpoint as a branch (FR-MEM-11; PRD 13.4, 13.5, 8.5).

A `Checkpoint` lists the units a parent run finished: the unit handed over (`agent.handoff` from its worker) and the
Verifier passed every artifact it handed over (`artifact.reviewed` "passed", caused by that handoff; FR-MEM-02). It is
read from the parent's recorded events, so it is pure and deterministic. `run_plan(reuse=)` then reuses a unit instead
of running it, and records the reuse as one `memory.hit` (`saved = origin_cost - lookup_cost`, EV-09).

A unit is reused only when the cut stays closed: it is in the checkpoint, its spec digest still matches the plan, every
artifact version it handed over is one the branch's world recorded (EV-15, fail closed), and every unit it depends on is
reused too (a unit downstream of one that runs would have an input about to change).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

SUMMARY_LIMIT = 140  # the event envelope's summary cap


@dataclass(frozen=True)
class FinishedUnit:
    unit_id: str
    spec_digest: str  # unit_digest(plan unit) at the time of the parent run
    artifact_refs: tuple[dict[str, Any], ...]  # the refs the unit handed over
    origin_cost: float  # the credits on the unit's events in the parent run
    handoff_event_id: str  # the parent's agent.handoff of this unit (the hit's `cause`)


@dataclass(frozen=True)
class Checkpoint:
    parent_run_id: str
    units: Mapping[str, FinishedUnit]  # finished units only; may be empty


def unit_digest(unit: Mapping[str, Any]) -> str:
    """SHA-256 hex of the unit's canonical JSON (sorted keys, no spaces): any change to the spec changes it."""
    canonical = json.dumps(unit, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _same_ref(a: Any, b: Any) -> bool:
    return (
        isinstance(a, Mapping)
        and isinstance(b, Mapping)
        and all(a.get(k) == b.get(k) for k in ("artifact_id", "version"))
    )


def checkpoint_from_events(
    events: Sequence[dict[str, Any]], plan: dict[str, Any], *, run_id: str | None = None
) -> Checkpoint:
    """The finished units of one run in `events`, for the units of `plan`. `ValueError`: an empty stream, a `run_id`
    with no events, or several runs without `run_id`."""
    runs = {event["run_id"] for event in events}
    if not runs:
        raise ValueError("checkpoint: the event stream is empty")
    if run_id is None:
        if len(runs) != 1:
            raise ValueError("checkpoint: the stream holds several runs; say which one with run_id")
        run_id = next(iter(runs))
    elif run_id not in runs:
        raise ValueError(f"checkpoint: the stream has no events of run {run_id}")
    mine = [event for event in events if event["run_id"] == run_id]
    planned = {unit["id"]: unit for unit in plan["units"]}
    worker_of = {
        e["data"]["unit"]: e["target"] for e in mine if e["type"] == "agent.assigned" and e["data"]["unit"] in planned
    }
    passed = [e for e in mine if e["type"] == "artifact.reviewed" and e["data"].get("result") == "passed"]
    units: dict[str, FinishedUnit] = {}
    for unit_id, worker in worker_of.items():
        handoffs = [e for e in mine if e["type"] == "agent.handoff" and e["actor"] == worker]
        if not handoffs:
            continue
        handoff = handoffs[-1]
        refs = tuple(dict(ref) for ref in handoff["data"]["envelope"]["artifact_refs"])
        reviews = [e for e in passed if e["cause"] == handoff["id"]]
        if not refs or not all(any(_same_ref(r["data"]["artifact"], ref) for r in reviews) for ref in refs):
            continue
        cost = sum(e["credits"] for e in mine if worker in (e["actor"], e["target"]))
        units[unit_id] = FinishedUnit(unit_id, unit_digest(planned[unit_id]), refs, cost, handoff["id"])
    return Checkpoint(run_id, units)


def reusable_units(
    checkpoint: Checkpoint, order: Sequence[Mapping[str, Any]], recorded_version: Callable[[str], int] | None
) -> list[str]:
    """Unit ids to reuse, in dependency order: finished, unchanged, recorded by the world, dependencies all reused."""
    reused: list[str] = []
    for unit in order:
        finished = checkpoint.units.get(unit["id"])
        if finished is None or finished.spec_digest != unit_digest(unit):
            continue
        if not all(dep in reused for dep in unit["depends_on"]):
            continue
        if recorded_version is None or not all(
            isinstance(ref.get("version"), int) and recorded_version(ref["artifact_id"]) >= ref["version"]
            for ref in finished.artifact_refs
        ):
            continue
        reused.append(unit["id"])
    return reused


def hit_summary(saved: float) -> str:
    return f"The agent reused a finished unit from the earlier run and saved {saved:g} credits."[:SUMMARY_LIMIT]
