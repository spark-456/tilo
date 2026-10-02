"""FR-INT-08 (PRD 7.1, 10.4, 14.1, 9.5; GitHub issue #64): "an autonomy policy may pre-approve
budgets under a threshold" -- Given a policy of "auto-approve under 100 credits", when an
approach costs 80, then it starts and the audit log names the policy.

PRD 10.4's risk-tier table lists "spend credits under the run budget" as its own T1 example.
`config/autonomy.yaml` (the table `tilo_policy.RiskTable` loads, PI-07) has no `grant_budget`
entry yet, so `RiskTable.tier_of` falls back to its unknown-action-type default and every grant
fails closed to T3 -- auto-approval can never happen (issue #64). This ticket is additive only:
it adds `grant_budget: T1` to the table and picks what `policy.applied.data.connector` holds for
a grant, which goes through no `tilo-connectors` connector.

Ambiguities this file resolves (CLAUDE.md: "apply the PRD's stated default, log it, keep going";
also listed in the test-writer's report per the ticket instructions, since docs/open-questions.md
does not yet carry a BQ id for either):

- **The over-cap bound is not expressible in the risk-tier table.** `policy.schema.json`
  `$defs.risk_tier_table.modifiers` is `minItems: 6, maxItems: 6` over a closed enum (BQ-16):
  no seventh "over the run cap" modifier can be added without a breaking contract change, which
  this ticket forbids ("Additive only; no change to T3 rules"). PRD 10.4's own T3 modifier
  "money, contract or legal terms" (`money_or_legal`) already covers a bigger money decision than
  spending within an approved budget, so the boundary a grant crosses when it would raise the run
  above its cap (FR-MTR-04, `config/metering.yaml` `run_credits: 300`) is exactly that modifier,
  not a new one -- `RiskTable.tier_of` already makes any active modifier T3 regardless of base
  tier (PI-07). But nothing today documents that an over-cap grant carries `money_or_legal`
  (or otherwise stays below T1), so this file also asserts the rules text says so, per the
  ticket's own fallback ("if the table or rules express the bound; otherwise assert the rules
  text says the policy engine enforces the under-budget condition"): whichever mechanism the
  architect picks (a modifier, or the Treasury structurally refusing the grant, ADR-0002
  decision 13's "the Treasury's grant does not check this yet"), it must be written down next to
  the table it changes, `config/autonomy.yaml`, and in ADR-0002 (CLAUDE.md ticket-loop rule and
  the ticket's own instruction: "document it in the relevant rules file and ADR-0002").
- **`policy.applied.data.connector` for a connector-less action.** SP's stub default is the slug
  `internal` (issue #64): schema-valid (`common.schema.json#/$defs/connector_id`,
  `^[a-z][a-z0-9_]{1,31}$`) but not a real entry once `config/connectors.yaml` exists (P5). It is
  also the least surprising choice already in circulation for this exact gap, so this file locks
  it in as the value under test; the architect may pick differently, but must then update this
  fixture and this file's `GRANT_BUDGET_CONNECTOR` constant, and record the decision in
  `docs/open-questions.md` as overridable (the ticket's own instruction).
"""

from __future__ import annotations

import pathlib

import pytest
import yaml
from _events_lib import data_schema_path, event_fixtures_dir
from _lib import errors_for, load_json, load_schema
from hypothesis import given
from hypothesis import strategies as st

# The value this ticket picks for policy.applied.data.connector (and outbox.connector) on a
# side effect that goes through no tilo-connectors connector, such as grant_budget. See the
# module docstring's second bullet.
GRANT_BUDGET_CONNECTOR = "internal"

GRANT_BUDGET_FIXTURE = "policy.applied--grant_budget.json"

TABLE_REF = {"$ref": "https://contracts.tilo.example/policy.schema.json#/$defs/risk_tier_table"}


def _autonomy_table(repo_root: pathlib.Path) -> dict:
    path = repo_root / "config" / "autonomy.yaml"
    assert path.is_file(), "config/autonomy.yaml must exist (FR-HIL-04; see test_FR_HIL_04_autonomy_config.py)"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _autonomy_text(repo_root: pathlib.Path) -> str:
    return (repo_root / "config" / "autonomy.yaml").read_text(encoding="utf-8").lower()


def _adr_0002_text(repo_root: pathlib.Path) -> str:
    return (repo_root / "docs" / "adr" / "0002-contract-conventions.md").read_text(encoding="utf-8").lower()


def _open_questions_text(repo_root: pathlib.Path) -> str:
    return (repo_root / "docs" / "open-questions.md").read_text(encoding="utf-8").lower()


# ---------------------------------------------------------------------------
# 1) grant_budget: T1 in the risk table (PRD 10.4 T1 example, FR-INT-08)
# ---------------------------------------------------------------------------


def test_FR_INT_08_grant_budget_is_T1_in_autonomy_config(repo_root, registry):
    table = _autonomy_table(repo_root)
    assert not [e.message for e in errors_for(TABLE_REF, table, registry)], (
        "FR-INT-08: config/autonomy.yaml must still validate against policy.schema.json's "
        "risk_tier_table after adding grant_budget"
    )
    actions = table.get("actions", {})
    assert "grant_budget" in actions, (
        "FR-INT-08 / issue #64: config/autonomy.yaml actions must map 'grant_budget' -- PRD 10.4 "
        "gives 'spend credits under the run budget' as its own T1 example, and without it every "
        "budget grant fails closed to T3 (BQ-44) and auto-approval can never happen"
    )
    assert actions["grant_budget"] == "T1", (
        f"FR-INT-08: grant_budget must be T1 (PRD 10.4), got {actions.get('grant_budget')!r}"
    )


# ---------------------------------------------------------------------------
# 2) An action type not in the table still fails closed to T3 (BQ-44), even after the table
#    grows a grant_budget entry -- tilo_policy.RiskTable is the reference implementation of
#    that fail-closed default, loaded from the real config.
# ---------------------------------------------------------------------------


def test_FR_INT_08_unlisted_action_type_still_fails_closed_to_T3(repo_root):
    tilo_policy = pytest.importorskip("tilo_policy.tiers", reason="packages/policy not installed")
    table = tilo_policy.load_risk_table(repo_root / "config" / "autonomy.yaml")
    assert table.tier_of("not_a_real_action_xyz", []) == "T3", (
        "FR-INT-08 / BQ-44: an action type the table does not list must still fail closed to T3, "
        "so adding grant_budget must not weaken the default for every other unlisted action"
    )


@given(
    action_type=st.from_regex(r"^[a-z][a-z0-9_]{1,31}$", fullmatch=True),
)
def test_FR_INT_08_PI_07_property_unknown_action_types_fail_closed_to_T3(repo_root, action_type):
    """Property test (BQ-44, PI-07): for any schema-valid action_type this ticket's table does
    not list, tier_of returns T3. grant_budget itself is excluded since this ticket maps it."""
    tilo_policy = pytest.importorskip("tilo_policy.tiers", reason="packages/policy not installed")
    table = tilo_policy.load_risk_table(repo_root / "config" / "autonomy.yaml")
    if action_type in table.actions:
        return
    assert table.tier_of(action_type, []) == "T3"


# ---------------------------------------------------------------------------
# 3) A grant that would raise the run's budget above its cap is never T1 (PRD 10.4: "a grant
#    that raises the budget above the run cap stays T3/needs a person"; FR-MTR-04 run cap).
#    The risk-tier table's six modifiers are frozen (BQ-16), so this can only be expressed as
#    "any active modifier forces T3 regardless of base tier" (already true, PI-07) PLUS the
#    rules text saying which modifier, or which other mechanism, enforces the under-budget
#    condition -- the ticket's own fallback.
# ---------------------------------------------------------------------------


def test_FR_INT_08_grant_budget_under_run_cap_is_T1_but_any_modifier_is_T3(repo_root):
    tilo_policy = pytest.importorskip("tilo_policy.tiers", reason="packages/policy not installed")
    table = tilo_policy.load_risk_table(repo_root / "config" / "autonomy.yaml")
    assert table.tier_of("grant_budget", []) == "T1", (
        "FR-INT-08: a grant with no active T3 modifier (spending under the run budget) is T1"
    )
    for modifier in table.modifiers:
        assert table.tier_of("grant_budget", [modifier]) == "T3", (
            f"FR-INT-08 / PI-07: any active modifier ({modifier!r} included) must force a "
            "grant_budget action to T3 whatever its base tier -- a modifier is how a grant "
            "above the run cap could stay T3 without a new, frozen risk-tier modifier (BQ-16)"
        )


def test_FR_INT_08_over_run_cap_bound_is_documented(repo_root):
    """The table cannot name credit amounts, so wherever the architect enforces "never above the
    run's budget cap" (a modifier, or the Treasury refusing the grant outright, ADR-0002 decision
    13), it must be written down next to config/autonomy.yaml's table and in ADR-0002 -- the
    ticket's own instruction ("document it in the relevant rules file and ADR-0002")."""
    autonomy_text = _autonomy_text(repo_root)
    assert "grant_budget" in autonomy_text, (
        "FR-INT-08: config/autonomy.yaml's comments must name grant_budget so a reader sees the "
        "PRD 10.4 condition next to the table entry, not only in a commit message"
    )
    assert "run budget" in autonomy_text or "run cap" in autonomy_text or "run's budget" in autonomy_text, (
        "FR-INT-08: config/autonomy.yaml must document that grant_budget's T1 tier covers only "
        "spending under the run's budget (PRD 10.4), and that a grant raising it above the run "
        "cap (FR-MTR-04) does not stay T1"
    )

    adr_text = _adr_0002_text(repo_root)
    assert "grant_budget" in adr_text, (
        "FR-INT-08: docs/adr/0002-contract-conventions.md must record this ticket's decision "
        "(issue #64) the way it records every other config/rules default (see decisions 9, 12, 13)"
    )


# ---------------------------------------------------------------------------
# 4) policy.applied for a grant carries the connector value the architect picks, and it
#    validates against the event schema (PRD 9.5 policy.applied; BQ-23 "policy.applied (policy)"
#    is one of the events that may carry authz by policy).
# ---------------------------------------------------------------------------


@pytest.fixture()
def grant_budget_policy_applied(repo_root):
    path = event_fixtures_dir(repo_root, "valid") / GRANT_BUDGET_FIXTURE
    assert path.is_file(), (
        f"FR-INT-08: {path.relative_to(repo_root)} must exist -- a policy.applied fixture for a "
        "connector-less grant_budget action, alongside the registry's own policy.applied.json "
        "(convention: fixtures/events/valid/<type>--<case>.json, see "
        "question.answered--from_decision.json)"
    )
    return load_json(path)


def test_FR_INT_08_policy_applied_grant_budget_validates_against_event_schema(
    repo_root, registry, grant_budget_policy_applied
):
    event_schema = load_schema(repo_root, "event")
    event_errors = errors_for(event_schema, grant_budget_policy_applied, registry)
    assert not event_errors, (
        f"FR-INT-08: {GRANT_BUDGET_FIXTURE} must validate against event.schema.json, got: "
        f"{[e.message for e in event_errors]}"
    )

    data_path = data_schema_path(repo_root, "policy.applied")
    assert data_path.is_file()
    data_errors = errors_for(load_json(data_path), grant_budget_policy_applied["data"], registry)
    assert not data_errors, (
        f"FR-INT-08: {GRANT_BUDGET_FIXTURE}'s data must validate against "
        f"events/data/policy.applied.schema.json, got: {[e.message for e in data_errors]}"
    )


def test_FR_INT_08_policy_applied_grant_budget_carries_the_chosen_connector(
    grant_budget_policy_applied,
):
    data = grant_budget_policy_applied["data"]
    assert data["action_type"] == "grant_budget"
    assert data["connector"] == GRANT_BUDGET_CONNECTOR, (
        f"FR-INT-08 / issue #64: policy.applied.data.connector for a connector-less grant must be "
        f"the architect's chosen sentinel ({GRANT_BUDGET_CONNECTOR!r}), matching a schema-valid "
        "connector_id (common.schema.json) although it names no config/connectors.yaml entry"
    )


def test_FR_INT_08_connector_less_connector_value_is_documented(repo_root):
    """The chosen connector value for a connector-less action must be written down next to the
    field it fills, not only encoded in a fixture (ticket instruction: "document it in the
    relevant rules file and ADR-0002")."""
    policy_applied_schema_text = data_schema_path(repo_root, "policy.applied").read_text(encoding="utf-8").lower()
    adr_text = _adr_0002_text(repo_root)
    assert GRANT_BUDGET_CONNECTOR in policy_applied_schema_text or GRANT_BUDGET_CONNECTOR in adr_text, (
        f"FR-INT-08 / issue #64: the {GRANT_BUDGET_CONNECTOR!r} sentinel for a connector-less "
        "policy.applied/outbox connector must be documented in "
        "contracts/events/data/policy.applied.schema.json's description or in ADR-0002 (decision "
        "list), so a reader of the schema or the ADR learns what it means without archaeology"
    )


def test_FR_INT_08_connector_less_decision_logged_in_open_questions_as_overridable(repo_root):
    text = _open_questions_text(repo_root)
    assert "grant_budget" in text and "connector" in text, (
        "FR-INT-08 / issue #64: docs/open-questions.md must log the connector-less "
        "policy.applied.connector decision (grant_budget) as a BQ entry, the ticket's own "
        "instruction ('log the decision in docs/open-questions.md as overridable')"
    )
    assert "overridable" in text or "override" in text, (
        "FR-INT-08: the logged decision must say the user may override it (ticket instruction), "
        "not just record the default silently"
    )
