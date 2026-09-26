"""PlanGraph validator (FR-INT-09, PRD 7.1 and 10.4). Deterministic code, no model: a plan is checked
against contracts/plan.schema.json and then against every computable rule in contracts/plan.rules.md
(PG-01..PG-11; PG-12 is the schema's). A plan with any violation is rejected before it reaches a
person. Each violation names its rule id; a shape failure is reported as `schema` and stops the
cross-reference checks, since they assume the shape.

PG-06 can only check "never lower" at plan time: units carry no per-action facts, so no context
modifier can be shown to apply. Risk tiers come from `tilo_policy.RiskTable`."""

from __future__ import annotations

import functools
import itertools
import json
import math
from collections.abc import Collection, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012
from tilo_policy import RiskTable

CONTRACTS = Path(__file__).resolve().parents[4] / "contracts"
SCHEMA_RULE = "schema"
TIER_ORDER = ("T1", "T2", "T3")
POLICY_LEVELS = ("L2", "L3")  # PG-10: only a policy that acts without a person may open a gate
DIMENSIONS = ("depth", "sources", "parallelism", "verification", "output_format")
MIN_DIFFERING = 2  # PG-08


@dataclass(frozen=True)
class Violation:
    rule_id: str  # a plan.rules.md id ("PG-04") or "schema"
    message: str


def _pattern(validator: Any, pattern: str, instance: Any, schema: dict[str, Any]) -> Iterator[Any]:
    """JSON Schema's `$` ends the string; Python's also matches before a final newline."""
    if pattern.endswith("$") and not pattern.endswith(r"\$"):
        pattern = pattern[:-1] + r"\Z"
    yield from jsonschema.Draft202012Validator.VALIDATORS["pattern"](validator, pattern, instance, schema)


@functools.cache
def _plan_validator() -> Any:
    schemas = [json.loads(p.read_text("utf-8")) for p in sorted(CONTRACTS.glob("**/*.schema.json"))]
    # Without `$schema`, a `$ref` into another contract keeps the extended class (its `pattern`).
    schemas = [{k: v for k, v in s.items() if k != "$schema"} for s in schemas]
    registry = Registry().with_resources(
        (s["$id"], Resource.from_contents(s, default_specification=DRAFT202012)) for s in schemas
    )
    cls = jsonschema.validators.extend(jsonschema.Draft202012Validator, {"pattern": _pattern})
    return cls(json.loads((CONTRACTS / "plan.schema.json").read_text("utf-8")), registry=registry)


def _schema_violations(plan: Any) -> list[Violation]:
    errors = sorted(_plan_validator().iter_errors(plan), key=lambda e: list(map(str, e.absolute_path)))
    found = [Violation(SCHEMA_RULE, f"/{'/'.join(map(str, e.absolute_path))}: {e.message}") for e in errors]
    if not found and not math.isfinite(plan["budget_cap"]):
        found.append(Violation(SCHEMA_RULE, "/budget_cap: must be a finite number"))
    return found


def _utc_now() -> str:
    now = datetime.now(UTC)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _duplicates(ids: list[str]) -> list[str]:
    return sorted({i for i in ids if ids.count(i) > 1})


def _pg01(plan: dict[str, Any]) -> Iterator[Violation]:
    for kind in ("units", "gates"):
        for dup in _duplicates([item["id"] for item in plan[kind]]):
            yield Violation("PG-01", f"{kind[:-1]} id {dup} is used more than once")


def _pg02(plan: dict[str, Any], unit_ids: set[str]) -> Iterator[Violation]:
    for unit in plan["units"]:
        for dep in unit["depends_on"]:
            if dep == unit["id"]:
                yield Violation("PG-02", f"unit {dep} depends on itself")
            elif dep not in unit_ids:
                yield Violation("PG-02", f"unit {unit['id']} depends on unknown unit {dep}")


def _pg03(plan: dict[str, Any], unit_ids: set[str]) -> Iterator[Violation]:
    """Kahn's algorithm over the known edges; self-dependencies are PG-02's."""
    deps: dict[str, set[str]] = {uid: set() for uid in unit_ids}
    for unit in plan["units"]:
        deps[unit["id"]] |= {d for d in unit["depends_on"] if d in unit_ids and d != unit["id"]}
    ready = [uid for uid, before in deps.items() if not before]
    while ready:
        done = ready.pop()
        del deps[done]
        for uid, before in deps.items():
            if done in before:
                before.discard(done)
                if not before:
                    ready.append(uid)
    if deps:
        yield Violation("PG-03", f"depends_on has a cycle through units {', '.join(sorted(deps))}")


def _pg04(plan: dict[str, Any]) -> Iterator[Violation]:
    guarded = {(g["action_type"], uid) for g in plan["gates"] for uid in g["guards"]}
    for unit in plan["units"]:
        for action in unit["actions"]:
            if (action, unit["id"]) not in guarded:
                yield Violation("PG-04", f"unit {unit['id']} performs {action} with no gate guarding it")


def _pg05(plan: dict[str, Any]) -> Iterator[Violation]:
    actions: dict[str, set[str]] = {}
    for unit in plan["units"]:
        actions.setdefault(unit["id"], set()).update(unit["actions"])
    for gate in plan["gates"]:
        for uid in gate["guards"]:
            if gate["action_type"] not in actions.get(uid, set()):
                yield Violation(
                    "PG-05", f"gate {gate['id']} guards {uid}, which does not perform {gate['action_type']}"
                )


def _pg06(plan: dict[str, Any], risk_table: RiskTable) -> Iterator[Violation]:
    for gate in plan["gates"]:
        base = risk_table.tier_of(gate["action_type"], [])
        if TIER_ORDER.index(gate["risk_tier"]) < TIER_ORDER.index(base):
            yield Violation(
                "PG-06",
                f"gate {gate['id']} is {gate['risk_tier']}, "
                f"below the {base} the risk table gives {gate['action_type']}",
            )


def _pg07(plan: dict[str, Any]) -> Iterator[Violation]:
    ids = [a["id"] for a in plan["approaches"]]
    for dup in _duplicates(ids):
        yield Violation("PG-07", f"approach id {dup} is used more than once")
    if plan["chosen_approach"] not in ids:
        yield Violation("PG-07", f"chosen approach {plan['chosen_approach']} is not one of the approaches")


def differing_dimensions(a: dict[str, Any], b: dict[str, Any]) -> int:
    return sum(1 for key in DIMENSIONS if a["dimensions"][key] != b["dimensions"][key])


def _pg08(plan: dict[str, Any]) -> Iterator[Violation]:
    for a, b in itertools.combinations(plan["approaches"], 2):
        if (n := differing_dimensions(a, b)) < MIN_DIFFERING:
            yield Violation("PG-08", f"approaches {a['id']} and {b['id']} differ on {n} of 5 dimensions, not 2")


def _pg09(plan: dict[str, Any]) -> Iterator[Violation]:
    for a in plan["approaches"]:
        if a["time"]["min_s"] > a["time"]["max_s"]:
            yield Violation("PG-09", f"approach {a['id']}: time min_s is above max_s")
        if a["credits"]["min"] > a["credits"]["max"]:
            yield Violation("PG-09", f"approach {a['id']}: credits min is above max")


def _approves(connector: Any, action: str) -> bool:
    """The connector declares `action` as a side effect (gate_type: approval)."""
    if not isinstance(connector, Mapping):
        return False
    declared = connector.get("actions") or []
    return any(isinstance(d, Mapping) and d.get("id") == action and d.get("gate_type") == "approval" for d in declared)


def _pg10(
    plan: dict[str, Any], policies: Mapping[str, Any], connectors: Mapping[str, Any], now: str
) -> Iterator[Violation]:
    units = {u["id"]: u for u in plan["units"]}
    for gate in plan["gates"]:
        ref, action = gate["policy_ref"], gate["action_type"]
        if ref is None:
            continue
        policy = policies.get(ref)
        try:
            scope, expiry = policy["scope"], policy["expiry"]
            usable = (
                policy["id"] == ref
                and policy["action_type"] == action
                and policy["level"] in POLICY_LEVELS
                and (expiry is None or now < expiry)
            )
        except (KeyError, TypeError):
            usable = False
        if not usable:
            yield Violation("PG-10", f"gate {gate['id']}: {ref} is not an unexpired L2/L3 policy for {action}")
            continue
        for uid in gate["guards"]:
            unit = units.get(uid)
            if unit is None:
                continue  # PG-05 reports a guard that names no unit
            acting = [c for c in unit["connectors"] if _approves(connectors.get(c), action)]
            outside = [c for c in acting if scope["connectors"] and c not in scope["connectors"]]
            if scope["districts"] and unit["district"] not in scope["districts"]:
                outside.append(unit["district"])
            if outside:
                yield Violation("PG-10", f"gate {gate['id']}: {ref} does not cover {', '.join(outside)} for {uid}")


def _pg11(plan: dict[str, Any], skills: Collection[str], connectors: Mapping[str, Any]) -> Iterator[Violation]:
    for unit in plan["units"]:
        uid = unit["id"]
        for skill in unit["skills"]:
            if skill not in skills:
                yield Violation("PG-11", f"unit {uid}: skill {skill} is not in the skill registry")
        for conn in unit["connectors"]:
            if conn not in connectors:
                yield Violation("PG-11", f"unit {uid}: connector {conn} is not in the connector registry")
        for action in unit["actions"]:
            if not any(_approves(connectors.get(c), action) for c in unit["connectors"]):
                yield Violation(
                    "PG-11", f"unit {uid}: no connector of the unit declares {action} with an approval gate"
                )


def validate_plan(
    plan: Any,
    *,
    risk_table: RiskTable,
    connectors: Mapping[str, Any],
    skills: Collection[str],
    policies: Mapping[str, Any],
    now: str | None = None,
) -> list[Violation]:
    """Every violation the plan has, in rule order; an empty list means valid.

    `connectors` maps connector id to its connector.schema.json record, `skills` is the set of
    skill ids, `policies` maps policy id to its policy.schema.json record. `now` (a
    common.schema.json timestamp) decides whether a policy has expired; it defaults to the clock.
    """
    found = _schema_violations(plan)
    if found:
        return found
    unit_ids = {u["id"] for u in plan["units"]}
    checks = (
        _pg01(plan),
        _pg02(plan, unit_ids),
        _pg03(plan, unit_ids),
        _pg04(plan),
        _pg05(plan),
        _pg06(plan, risk_table),
        _pg07(plan),
        _pg08(plan),
        _pg09(plan),
        _pg10(plan, policies, connectors, now or _utc_now()),
        _pg11(plan, skills, connectors),
    )
    return [v for check in checks for v in check]
