"""PlanGraph validator (FR-INT-09, PRD 7.1 and 10.4). Deterministic code, no model: a plan is checked
against contracts/plan.schema.json and then against every computable rule in contracts/plan.rules.md
(PG-01..PG-11; PG-12 is the schema's). A plan with any violation is rejected before it reaches a
person. Each violation names its rule id; a shape failure is reported as `schema` and stops the
cross-reference checks, since they assume the shape.

PG-06 can only check "never lower" at plan time: units carry no per-action facts, so no context
modifier can be shown to apply. The tier a gate may not go below is the higher of the risk table's
(`tilo_policy.RiskTable`) and the one each guarded unit's connectors declare for the action."""

from __future__ import annotations

import functools
import itertools
import json
import math
from collections.abc import Iterator, Mapping
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import jsonschema
from tilo_policy import RiskTable
from tilo_policy.coverage import in_force, level_at, stamped_by, ts
from tilo_policy.schemas import conforms
from tilo_providers.schema_guard import MAX_ERRORS, describe, guarded

CONTRACTS = Path(__file__).resolve().parents[4] / "contracts"
SCHEMA_RULE = "schema"
TIER_ORDER = ("T1", "T2", "T3")
POLICY_LEVELS = ("L2", "L3")  # PG-10: only a policy that acts without a person may open a gate
DIMENSIONS = ("depth", "sources", "parallelism", "verification", "output_format")
MIN_DIFFERING = 2  # PG-08
MAX_PLAN_BYTES = 64 * 1024  # BQ-107: the PRD and contracts set none; checked before any walk


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
def _contract(name: str) -> dict[str, Any]:
    contract: dict[str, Any] = json.loads((CONTRACTS / name).read_text("utf-8"))
    return contract


def _inlined(node: Any, doc: str, seen: tuple[str, ...] = ()) -> Any:
    """`node` (in contract `doc`) with every `$ref` replaced by a copy of its target. Each `$ref`
    lookup cost about 150 us per id: 4.4 s for a plan at its array caps (#173). A cyclic `$ref`, or one
    beside anything but a description, fails start-up."""
    if isinstance(node, list):
        return [_inlined(item, doc, seen) for item in node]
    if not isinstance(node, dict):
        return node
    out = {key: _inlined(value, doc, seen) for key, value in node.items() if key not in ("$ref", "$defs", "$schema")}
    if not isinstance(ref := node.get("$ref"), str):
        return out
    target_doc, _, pointer = ref.partition("#")
    target_doc = target_doc or doc
    if f"{target_doc}#{pointer}" in seen or set(out) - {"description"}:
        raise ValueError(f"cannot inline $ref {ref} in {doc}")
    target: Any = _contract(target_doc)
    for part in filter(None, pointer.split("/")):
        target = target[part]
    resolved = _inlined(target, target_doc, (*seen, f"{target_doc}#{pointer}"))
    return {**out, **resolved}


@functools.cache
def _plan_validator() -> Any:
    """Validates against plan.schema.json with every `$ref` inlined, a linear `uniqueItems` and the
    `pattern` above; no `$schema` is left to swap in a stock validator class."""
    cls = guarded(jsonschema.validators.extend(jsonschema.Draft202012Validator, {"pattern": _pattern}))
    return cls(_inlined(_contract("plan.schema.json"), "plan.schema.json"))


def _too_big(plan: Any) -> list[Violation]:
    """A plan over MAX_PLAN_BYTES as compact UTF-8 JSON, measured before any walk and stopping at the cap."""
    size = 0
    try:
        for chunk in json.JSONEncoder(ensure_ascii=False, separators=(",", ":")).iterencode(plan):
            size += len(chunk.encode("utf-8", "surrogatepass"))
            if size > MAX_PLAN_BYTES:
                return [Violation(SCHEMA_RULE, f"/: the plan is larger than {MAX_PLAN_BYTES} bytes")]
    except (TypeError, ValueError, RecursionError):  # not JSON, a number too long to print, too deep
        return [Violation(SCHEMA_RULE, "/: the plan could not be validated")]
    return []


def _numbers(value: Any, path: str = "") -> Iterator[tuple[str, int | float]]:
    if isinstance(value, bool):
        return
    if isinstance(value, int | float):
        yield path or "/", value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _numbers(item, f"{path}/{key}")
    elif isinstance(value, list):
        for i, item in enumerate(value):
            yield from _numbers(item, f"{path}/{i}")


def _finite(number: int | float) -> bool:
    """A finite float, so arithmetic on it never overflows: NaN, infinity and 10**400 are not."""
    try:
        return math.isfinite(number)
    except OverflowError:
        return False


def _schema_violations(plan: Any) -> list[Violation]:
    found = _too_big(plan)
    if found:
        return found
    try:
        errors = sorted(
            itertools.islice(_plan_validator().iter_errors(plan), MAX_ERRORS),
            key=lambda e: list(map(str, e.absolute_path)),
        )
        found = [Violation(SCHEMA_RULE, describe(e)) for e in errors]
    except Exception:  # too deep to walk, or a number too long to print: fail closed
        return [Violation(SCHEMA_RULE, "/: the plan could not be validated")]
    if not found:
        found = [
            Violation(SCHEMA_RULE, f"{path}: must be a finite number") for path, n in _numbers(plan) if not _finite(n)
        ]
    return found


def _utc_now() -> str:
    now = datetime.now(UTC)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _duplicates(ids: list[str]) -> list[str]:
    return sorted({i for i in ids if ids.count(i) > 1})


def _declared(connector: Any, action: str) -> list[Mapping[str, Any]]:
    """The connector's declarations of `action` (a missing or malformed connector declares none)."""
    declared = connector.get("actions") if isinstance(connector, Mapping) else None
    if not isinstance(declared, list):
        return []
    return [d for d in declared if isinstance(d, Mapping) and d.get("id") == action]


def _approves(connector: Any, action: str) -> bool:
    """The connector declares `action` as a side effect (gate_type: approval)."""
    return any(d.get("gate_type") == "approval" for d in _declared(connector, action))


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


def _floor_tier(
    gate: dict[str, Any], units: dict[str, Any], risk_table: RiskTable, connectors: Mapping[str, Any]
) -> str:
    """The higher of the table's tier and every tier the guarded units' connectors declare for the
    action; a declared tier that is not T1..T3 counts as T3."""
    action = gate["action_type"]
    tiers = [risk_table.tier_of(action, [])]
    for uid in gate["guards"]:
        for conn in units[uid]["connectors"] if uid in units else []:
            declared = [d.get("risk_tier") for d in _declared(connectors.get(conn), action)]
            tiers += [t if isinstance(t, str) and t in TIER_ORDER else "T3" for t in declared]
    return max(tiers, key=TIER_ORDER.index)


def _pg06(plan: dict[str, Any], risk_table: RiskTable, connectors: Mapping[str, Any]) -> Iterator[Violation]:
    units = {u["id"]: u for u in plan["units"]}
    for gate in plan["gates"]:
        floor = _floor_tier(gate, units, risk_table, connectors)
        if TIER_ORDER.index(gate["risk_tier"]) < TIER_ORDER.index(floor):
            yield Violation(
                "PG-06",
                f"gate {gate['id']} is {gate['risk_tier']}, below the {floor} that {gate['action_type']} has "
                "in the risk table or its connectors",
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
    """`not (min <= max)`, so a NaN that reached here is out of order too."""
    for a in plan["approaches"]:
        for key, low, high in (("time", "min_s", "max_s"), ("credits", "min", "max")):
            pair = (a[key][low], a[key][high])
            if not (all(map(_finite, pair)) and pair[0] <= pair[1]):
                yield Violation("PG-09", f"approach {a['id']}: {key} {low} is not a finite number at or below {high}")


def _policy_scope(
    policy: Any, gate: dict[str, Any], owner: str | None, now: str, risk_table: RiskTable
) -> tuple[list[str], list[str]] | None:
    """(connectors, districts) of a policy that may open `gate` at `now`, else None: a record that
    conforms to policy.schema.json, is the owner's and in force (tilo_policy.coverage), and is at
    L2 or L3 at `now` by its history, capped by the table's max_level for the gate's tier."""
    try:
        if not (
            conforms("policy.schema.json", policy)
            and policy["id"] == gate["policy_ref"]
            and policy["action_type"] == gate["action_type"]
            and all(v is None or _finite(v) for v in policy["limits"].values())
            and in_force(policy, policy["owner"] if owner is None else owner, now)
            and stamped_by(policy, now)
        ):
            return None
        level = level_at(policy, now)
        if level is None or min(level, risk_table.max_level.get(gate["risk_tier"], "L1")) not in POLICY_LEVELS:
            return None
        return list(policy["scope"]["connectors"]), list(policy["scope"]["districts"])
    except Exception:  # a malformed record is unusable, not an error
        return None


def _pg10(
    plan: dict[str, Any],
    policies: Mapping[str, Any],
    connectors: Mapping[str, Any],
    owner: str | None,
    now: str,
    risk_table: RiskTable,
) -> Iterator[Violation]:
    units = {u["id"]: u for u in plan["units"]}
    try:
        ts(now)
        clock_ok = True
    except ValueError:
        clock_ok = False
    for gate in plan["gates"]:
        ref, action = gate["policy_ref"], gate["action_type"]
        if ref is None:
            continue
        scope = _policy_scope(policies.get(ref), gate, owner, now, risk_table) if clock_ok else None
        if scope is None:
            yield Violation("PG-10", f"gate {gate['id']}: {ref} is not the owner's L2/L3 policy for {action} now")
            continue
        scope_connectors, scope_districts = scope
        for uid in gate["guards"]:
            unit = units.get(uid)
            if unit is None:
                continue  # PG-05 reports a guard that names no unit
            outside = [
                c for c in unit["connectors"] if _approves(connectors.get(c), action) and c not in scope_connectors
            ]
            if scope_districts and unit["district"] not in scope_districts:  # empty districts: no restriction
                outside.append(unit["district"])
            if outside:
                yield Violation("PG-10", f"gate {gate['id']}: {ref} does not cover {', '.join(outside)} for {uid}")


def _pg11(plan: dict[str, Any], skills: AbstractSet[str], connectors: Mapping[str, Any]) -> Iterator[Violation]:
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
    skills: AbstractSet[str],
    policies: Mapping[str, Any],
    owner: str | None = None,
    now: str | None = None,
) -> list[Violation]:
    """Every violation the plan has, in rule order; an empty list means valid.

    `connectors` maps connector id to its connector.schema.json record, `skills` is the set (or
    frozenset) of skill ids, `policies` maps policy id to its policy.schema.json record. `owner` is
    the world owner whose policies may open gates; None binds each policy to its own recorded owner
    (every stamp still by that owner). `now` (a common.schema.json timestamp; anything else fails
    every policy gate) decides which policy level is in force; it defaults to the clock.

    BQ-72: `owner=None` trusts each policy's own recorded owner, so the first caller that passes
    client-supplied plan JSON (FR-INT-10) must pass the world owner, with a test (issue #124).
    """
    if not isinstance(skills, set | frozenset):  # a str would match substrings
        raise TypeError("skills must be a set or frozenset of skill ids")
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
        _pg06(plan, risk_table, connectors),
        _pg07(plan),
        _pg08(plan),
        _pg09(plan),
        _pg10(plan, policies, connectors, owner, _utc_now() if now is None else now, risk_table),
        _pg11(plan, skills, connectors),
    )
    return [v for check in checks for v in check]
