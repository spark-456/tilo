"""Fixture builders and fake registries for ticket FR-INT-09 acceptance tests (PRD 7.1 row
FR-INT-09; contracts/plan.schema.json and contracts/plan.rules.md are the source of truth for the
PlanGraph and its cross-reference rules PG-01..PG-12). Named `_plan_validator_lib` -- not
`_lib` -- for the same reason `_planning_contracts_lib.py`'s docstring gives: pytest's "prepend"
import mode makes every leading-underscore helper module's bare name global for the whole
`uv run pytest` session, so a name reused by a sibling test directory's own `_lib.py` would
collide. Test modules in this directory import helpers from here (or from
`_planning_contracts_lib`, a sibling module in the same directory -- not a collision), never
`from conftest import ...`.

`tilo_planning.plangraph` does not exist yet (this is the test-writer pass). Every test importing
`validate_plan` from it therefore fails at collection with `ModuleNotFoundError` until the builder
ships it -- failing for the right reason. The public interface under test is this pass's own
design, taken from the ticket brief: `validate_plan(plan, *, risk_table, connectors, skills,
policies) -> list[Violation]` (empty list means valid), where `Violation` exposes at least
`.rule_id` (a `plan.rules.md` id such as `"PG-04"`, or a generic non-PG id for a plain
`plan.schema.json` shape failure -- plan.rules.md marks PG-12 "(schema)" itself, so a schema
failure needs no dedicated PG id of its own).

Ambiguities resolved here (CLAUDE.md: PRD's stated default, logged in docs/open-questions.md):

1. `config/connectors.yaml` (the file `connector.schema.json` says every connector is "one entry
   of") does not exist in this repo yet, and `skills/` holds only `.gitkeep` -- no populated skill
   registry either. `validate_plan` is designed to take `connectors` and `skills` as explicit
   registries (dict-of-id and set-of-id respectively) rather than loading config paths itself, so
   PG-11 is testable now; the real loader is the builder's concern. `build_fake_connectors` below
   loads the two connectors that already exist as contract fixtures
   (`contracts/fixtures/connector/valid/*.json`: `gmail`, `web_search`); `build_fake_skills`
   hand-lists the four skill ids the committed plan fixtures use, since no real skill registry
   exists to read them from.
2. `contracts/fixtures/plan/valid/three_approaches_policy_gate.json`'s gate `G1` names
   `policy_ref: "pol_finance_updates"`, but no `contracts/fixtures/policy/valid/*.json` fixture
   has that id (only `pol_drive_saves`, `pol_autopilot_l2`, `pol_status_updates`). Needs contract
   change: a `contracts/fixtures/policy/valid/l2_finance_updates.json` fixture with id
   `pol_finance_updates` would let this plan fixture be exercised without a synthetic policy.
   Until then, `build_fake_policies` merges the real policy fixtures with a hand-built
   `pol_finance_updates` (scope: connector `gmail`, district `D2`, action `send_email`, level
   `L2`, unexpired) matching that plan fixture's gate exactly, plus PG-10 negative variants
   (expired / wrong level / wrong scope) used only by this ticket's own tests.
3. PG-06 ("raised to T3 by any context modifier that applies; never lower") is only partly
   computable from a `PlanGraph` alone: `unit.schema.json` carries no per-action modifier facts
   (no recipients/attachments/deletion/... at plan time), so no modifier can be shown to apply
   from the plan and config alone. The computable half -- "never lower" -- is tested directly:
   a gate's `risk_tier` must be at or above `contracts/config/autonomy.yaml`'s base tier for its
   `action_type` (via `tilo_policy.tiers.RiskTable.tier_of(action_type, [])`), using the tier
   order T1 < T2 < T3. This is also why the committed valid fixtures use `T3` gates for a `T2`
   base action (`send_email`): raised, never lower, is valid; lower is not.
"""

from __future__ import annotations

import copy
import pathlib
from typing import Any

from _planning_contracts_lib import contracts_dir, load_json

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]

# --- contract fixtures (contracts/fixtures/plan/{valid,invalid}/*.json) -----------------------


def plan_fixture_dir(kind: str, repo_root: pathlib.Path = REPO_ROOT) -> pathlib.Path:
    return contracts_dir(repo_root) / "fixtures" / "plan" / kind


def list_plan_fixtures(kind: str, repo_root: pathlib.Path = REPO_ROOT) -> list[str]:
    return sorted(p.stem for p in plan_fixture_dir(kind, repo_root).glob("*.json"))


def load_plan_fixture(kind: str, name: str, repo_root: pathlib.Path = REPO_ROOT) -> dict[str, Any]:
    return load_json(plan_fixture_dir(kind, repo_root) / f"{name}.json")


def clone(plan: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(plan)


# --- risk table (config/autonomy.yaml, PG-06) --------------------------------------------------


def build_risk_table(repo_root: pathlib.Path = REPO_ROOT):
    from tilo_policy.tiers import load_risk_table  # noqa: PLC0415

    return load_risk_table(repo_root / "config" / "autonomy.yaml")


# --- fake connectors registry (PG-11; config/connectors.yaml does not exist -- see docstring) --


def build_fake_connectors(repo_root: pathlib.Path = REPO_ROOT) -> dict[str, dict[str, Any]]:
    d = contracts_dir(repo_root) / "fixtures" / "connector" / "valid"
    return {c["id"]: c for c in (load_json(p) for p in sorted(d.glob("*.json")))}


# --- fake skill registry (PG-11; skills/ is empty -- see docstring) ----------------------------

FAKE_SKILL_IDS = frozenset({"table-extraction", "quote-comparison", "executive-summary", "email-reply-drafting"})


def build_fake_skills() -> set[str]:
    return set(FAKE_SKILL_IDS)


# --- fake policy registry (PG-10; see docstring ambiguity 2) -----------------------------------

_TS = "2026-09-01T00:00:00.000Z"


def _policy(
    id_: str,
    action_type: str,
    level: str,
    connectors: list[str],
    districts: list[str],
    *,
    expiry: str | None = None,
) -> dict[str, Any]:
    return {
        "id": id_,
        "owner": "u_owner",
        "action_type": action_type,
        "scope": {"connectors": connectors, "recipients": [], "domains": [], "districts": districts},
        "limits": {"per_day": 20, "credits": 50},
        "conditions": {"no_attachments": True, "no_new_recipients": True, "no_safety_flags": True},
        "level": level,
        "undo_window_s": 60,
        "expiry": expiry,
        "notify_channel": "web",
        "team_lead_domains": [],
        "created_by": {"by": "u_owner", "at": _TS},
        "changed_by": None,
        "history": [{"by": "u_owner", "at": _TS, "change": "created for FR-INT-09 tests", "level": level}],
    }


POL_FINANCE_UPDATES = _policy("pol_finance_updates", "send_email", "L2", ["gmail"], ["D2"])
POL_FINANCE_UPDATES_EXPIRED = _policy(
    "pol_finance_updates_expired", "send_email", "L2", ["gmail"], ["D2"], expiry="2020-01-01T00:00:00.000Z"
)
POL_FINANCE_UPDATES_L1 = _policy("pol_finance_updates_l1", "send_email", "L1", ["gmail"], ["D2"])
POL_FINANCE_UPDATES_WRONG_SCOPE = _policy(
    "pol_finance_updates_wrong_scope", "send_email", "L2", ["google_drive"], ["D2"]
)


def build_fake_policies(repo_root: pathlib.Path = REPO_ROOT) -> dict[str, dict[str, Any]]:
    d = contracts_dir(repo_root) / "fixtures" / "policy" / "valid"
    policies = {p["id"]: p for p in (load_json(f) for f in sorted(d.glob("*.json")))}
    for pol in (
        POL_FINANCE_UPDATES,
        POL_FINANCE_UPDATES_EXPIRED,
        POL_FINANCE_UPDATES_L1,
        POL_FINANCE_UPDATES_WRONG_SCOPE,
    ):
        policies[pol["id"]] = pol
    return policies


# --- minimal PlanGraph builders (for the cross-reference-rule tests; the schema-fixture tests --
# --- use the committed contracts/fixtures/plan/*.json instead) ---------------------------------


def approaches_2(repo_root: pathlib.Path = REPO_ROOT) -> list[dict[str, Any]]:
    """The 2 valid, PG-08/PG-09-compliant approaches from the committed `two_approaches_email_
    send_gated` fixture, cloned so callers can mutate freely."""
    return clone(load_plan_fixture("valid", "two_approaches_email_send_gated", repo_root)["approaches"])


def make_unit(
    unit_id: str,
    *,
    unit_type: str = "quote_extracted",
    title: str | None = None,
    role: str = "specialist",
    district: str = "D1",
    skills: tuple[str, ...] = ("table-extraction",),
    connectors: tuple[str, ...] = (),
    actions: tuple[str, ...] = (),
    depends_on: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "id": unit_id,
        "unit_type": unit_type,
        "title": title or f"Unit {unit_id}",
        "role": role,
        "district": district,
        "skills": list(skills),
        "connectors": list(connectors),
        "actions": list(actions),
        "depends_on": list(depends_on),
    }


def make_gate(
    gate_id: str, action_type: str, guards: list[str], risk_tier: str, policy_ref: str | None
) -> dict[str, Any]:
    return {
        "id": gate_id,
        "action_type": action_type,
        "risk_tier": risk_tier,
        "guards": guards,
        "policy_ref": policy_ref,
    }


def make_plan(
    units: list[dict[str, Any]],
    gates: list[dict[str, Any]],
    *,
    approaches: list[dict[str, Any]] | None = None,
    chosen: str = "quick",
    budget_cap: float = 50.0,
    repo_root: pathlib.Path = REPO_ROOT,
) -> dict[str, Any]:
    return {
        "approaches": approaches if approaches is not None else approaches_2(repo_root),
        "chosen_approach": chosen,
        "units": units,
        "gates": gates,
        "budget_cap": budget_cap,
    }


def rule_ids(violations: list[Any]) -> set[str]:
    return {v.rule_id for v in violations}
