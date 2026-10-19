"""The generality bank's structural checks (issue #272, GEN-03, GEN-04; PRD 19.3 "deterministic checks first").

Each check reads one `Observation` and returns findings; an empty list is a pass. Expected gates, tiers and budgets
come from the policy table and the contracts, never from the case. HARD checks are the invariants GEN-03 holds at
100%; REPORTED checks are counted and listed but do not fail the gate (see `delivers_something`).
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .bank_run import Observation

_TIER = {"T1": 1, "T2": 2, "T3": 3}
_EPS = 1e-6


@dataclass(frozen=True)
class Finding:
    check: str
    detail: str
    hard: bool = True


def _types(obs: Observation) -> list[str]:
    return [e["type"] for e in obs.events]


def no_crash(obs: Observation) -> list[Finding]:
    found = []
    if obs.crash:
        found.append(Finding("no_crash", obs.crash))
    if obs.timed_out:
        found.append(Finding("no_crash", f"no terminal state within the time budget ({obs.seconds}s)"))
    for method, path, status in obs.http:
        honest = status == 502 and path.endswith(("/intake", "/approaches"))  # "The Director could not ..."
        if status >= 500 and not honest:
            found.append(Finding("no_crash", f"HTTP {status} from {method} {path}"))
    return found


def events_valid(obs: Observation) -> list[Finding]:
    """Every event is registered and valid against its schema; seq strictly increases; ids are unique."""
    from tilo_harness.validator import repo_validator  # noqa: PLC0415

    found, seen, last = [], set(), 0
    for event in obs.events:
        if problems := repo_validator().problems(event):
            found.append(Finding("events_valid", f"{event.get('type')}: {problems[0]}"))
        if event["seq"] <= last:
            found.append(Finding("events_valid", f"seq {event['seq']} after {last}"))
        last = max(last, event["seq"])
        if event["id"] in seen:
            found.append(Finding("events_valid", f"duplicate event id {event['id']}"))
        seen.add(event["id"])
    return found


def plan_valid(obs: Observation) -> list[Finding]:
    """A plan that ran passes PG-01..PG-12 again, checked here against the registries, not the run's own copy."""
    if obs.plan is None:
        return []
    import tilo_policy  # noqa: PLC0415
    from tilo_api import deps  # noqa: PLC0415
    from tilo_planning import plangraph  # noqa: PLC0415

    connectors = deps.get_connector_registry()
    skills = frozenset(skill_id for skill_id, _ in deps.get_skill_registry().catalog())  # ids, not (id, description)
    violations = plangraph.validate_plan(
        obs.plan,
        risk_table=tilo_policy.load_risk_table(),
        connectors={c: connectors.get(c) for c in connectors.ids()},
        skills=skills,
        policies={},
        owner="u_dev_owner",
    )
    return [Finding("plan_valid", f"{v.rule_id}: {v.message}") for v in violations]


def gates_as_policy(obs: Observation) -> list[Finding]:
    """Gates where policy says, and nothing leaves before a person says yes (PRD 10.3, 10.4)."""
    if obs.plan is None:
        return []
    import tilo_policy  # noqa: PLC0415

    table, found = tilo_policy.load_risk_table(), []
    requested = [e for e in obs.events if e["type"] == "approval.requested"]
    resolved = {e["data"]["gate_id"]: e for e in obs.events if e["type"] == "approval.resolved"}
    for e in requested:
        action, tier = e["data"]["action_type"], e["data"]["risk_tier"]
        if _TIER[tier] < _TIER[table.actions.get(action, "T3")]:  # an action the table lacks is T3 (BQ-44)
            found.append(Finding("gates_as_policy", f"{action} gated at {tier}, below its table tier"))
        done = resolved.get(e["data"]["gate_id"])
        if tier == "T3" and done is not None and (done.get("authz") or {}).get("by") != "person":
            found.append(Finding("gates_as_policy", f"a T3 gate {e['data']['gate_id']} was not resolved by a person"))
    if obs.outcome in ("completed", "held_at_gate"):
        gated = {
            a for u in obs.plan["units"] for a in u["actions"] if a in {g["action_type"] for g in obs.plan["gates"]}
        }
        asked = {e["data"]["action_type"] for e in requested}
        if obs.outcome == "completed" and not gated <= asked:
            found.append(Finding("gates_as_policy", f"no approval was asked for {sorted(gated - asked)}"))
    if obs.sent_at_first_gate:
        found.append(Finding("gates_as_policy", f"{obs.sent_at_first_gate} sent before the first gate was answered"))
    if obs.sent_total > obs.approved_gates:
        found.append(Finding("gates_as_policy", f"{obs.sent_total} sent, {obs.approved_gates} approved"))
    return found


def terminal_honest(obs: Observation) -> list[Finding]:
    """Exactly the outcome the case expects, with the facts that make it true (HR-1: nothing without its event)."""
    found, types, want = [], _types(obs), obs.case.outcome
    if obs.outcome != want:
        found.append(Finding("terminal_honest", f"outcome {obs.outcome!r}, expected {want!r}: {obs.reason or ''}"))
    if obs.outcome == "completed":
        if "world.completed" not in types or "world.failed" in types:
            found.append(Finding("terminal_honest", "completed without world.completed, or with world.failed"))
        done = next((e for e in obs.events if e["type"] == "world.completed"), None)
        count = types.count("artifact.delivered")
        if done and done["data"]["deliverable_count"] != count:
            found.append(
                Finding("terminal_honest", f"deliverable_count {done['data']['deliverable_count']} != {count}")
            )
        if obs.delivery is not None and len(obs.delivery["artifacts"]) != count:
            found.append(Finding("terminal_honest", "the delivery lists a different number than was delivered"))
    elif obs.outcome == "held_at_gate":
        if "world.completed" in types or obs.sent_total:
            found.append(Finding("terminal_honest", "held at a gate, but the run completed or something was sent"))
    elif obs.outcome == "refused":
        if not (obs.reason or "").strip():
            found.append(Finding("terminal_honest", "refused with no reason shown to the person"))
        if "world.completed" in types:
            found.append(Finding("terminal_honest", "refused, yet the run completed"))
    elif obs.outcome == "needs_answers":
        if not obs.questions or "budget.granted" in types:
            found.append(Finding("terminal_honest", "needs_answers without questions, or the budget was granted"))
    elif obs.outcome == "declined":
        if not (obs.reason or "").strip():
            found.append(Finding("terminal_honest", "declined with no reason shown to the person"))
        if {"budget.granted", "world.started", "world.completed", "artifact.delivered"} & set(types) or obs.sent_total:
            found.append(Finding("terminal_honest", "declined, yet the run started, completed or something was sent"))
    return found


def budget_respected(obs: Observation) -> list[Finding]:
    spent = math.fsum(e["credits"] for e in obs.events)
    if obs.cap and spent > obs.cap + _EPS:
        return [Finding("budget_respected", f"{spent:g} credits used over the {obs.cap:g} cap")]
    done = next((e for e in obs.events if e["type"] == "world.completed"), None)
    if done and obs.cap and done["data"]["credits_used"] > obs.cap + _EPS:
        return [Finding("budget_respected", "world.completed reports more than the cap")]
    return []


def delivers_something(obs: Observation) -> list[Finding]:
    """REPORTED, not gated: a run whose units really produced an item (an `artifact.created`) and that completes should
    have delivered at least one (BQ-218: the plan's `deliver` unit delivers them in Tilo, ungated). A run whose units
    produced nothing delivers nothing and is not counted here: nothing is made up to fill the count (HR-1)."""
    done = next((e for e in obs.events if e["type"] == "world.completed"), None)
    made = any(e["type"] == "artifact.created" for e in obs.events)
    if done and made and done["data"]["deliverable_count"] < 1:
        return [
            Finding("delivers_something", "the run made items but completed with 0 delivered artifacts", hard=False)
        ]
    return []


CHECKS: tuple[Callable[[Observation], list[Finding]], ...] = (
    no_crash,
    events_valid,
    plan_valid,
    gates_as_policy,
    terminal_honest,
    budget_respected,
    delivers_something,
)


def check_case(obs: Observation) -> list[Finding]:
    """Every finding for one run, in check order. A check that itself fails is a finding, never an exception."""
    found: list[Finding] = []
    for check in CHECKS:
        try:
            found.extend(check(obs))
        except Exception as exc:  # noqa: BLE001 - a broken observation must not stop the pass
            found.append(Finding(check.__name__, f"the check could not run: {type(exc).__name__}: {exc}"))
    return found


def hard_findings(found: list[Finding]) -> list[Finding]:
    return [f for f in found if f.hard]


def drift(a: Observation, b: Observation) -> str:
    """What differed between two runs of one case, for the report; empty when `same_run`."""
    if a.outcome != b.outcome:
        return f"outcome {a.outcome!r} then {b.outcome!r}"
    if same_run(a, b):
        return ""
    ca, cb = Counter(_types(a)), Counter(_types(b))
    changed = {k: (ca.get(k, 0), cb.get(k, 0)) for k in sorted(set(ca) | set(cb)) if ca.get(k, 0) != cb.get(k, 0)}
    return f"event counts {changed}" if changed else "the same events in a different order"


def _has_unordered_units(plan: dict[str, Any] | None) -> bool:
    """True when two units have no dependency path between them: they run side by side."""
    units = {u["id"]: set(u["depends_on"]) for u in (plan or {}).get("units", [])}
    before: dict[str, set[str]] = {}

    def ancestors(uid: str) -> set[str]:
        if uid not in before:
            before[uid] = set()
            for dep in units.get(uid, ()):
                before[uid] |= {dep} | ancestors(dep)
        return before[uid]

    ids = list(units)
    return any(y not in ancestors(x) and x not in ancestors(y) for i, x in enumerate(ids) for y in ids[i + 1 :])


def same_run(a: Observation, b: Observation) -> bool:
    """What determinism compares (GEN-04): the outcome and the event types, ids and times aside. Units that run
    side by side interleave their events as they finish, so a plan with any such pair is compared by how many of
    each type there are; a plan that is one chain by the exact order."""
    if a.outcome != b.outcome:
        return False
    if _has_unordered_units(a.plan):
        return Counter(_types(a)) == Counter(_types(b))
    return _types(a) == _types(b)


def summarise(found: list[Finding]) -> dict[str, Any]:
    return {"hard": len(hard_findings(found)), "reported": len(found) - len(hard_findings(found))}
