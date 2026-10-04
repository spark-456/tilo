"""CL-INT-5c / FR-INT-09 (EFF-01): on the dev models file the Director is a deterministic fake that also answers the
plan-draft request, so `compile_plan` yields a valid PlanGraph with no recordings, no repair and no paid call. Its
last unit performs the first catalogue action that needs an approval gate; code adds the gate, the cap and the tier."""

from __future__ import annotations

import pathlib

import pytest
import yaml
from _plan_validator_lib import approaches_2, build_risk_table
from _planning_contracts_lib import load_brief_fixture
from tilo_planning.brief import complete_brief
from tilo_planning.compiler import PlanInputs, compile_plan
from tilo_planning.plangraph import validate_plan
from tilo_providers.config import load_providers_config
from tilo_providers.router import Router

ROOT = pathlib.Path(__file__).resolve().parents[3]
OWNER = "u_owner"


@pytest.fixture()
def router(tmp_path, monkeypatch):
    for name in ("LIVE", "K_SERVICE", "CLOUD_RUN_JOB"):
        monkeypatch.delenv(name, raising=False)
    config = load_providers_config(ROOT / "config" / "models.dev.yaml", ROOT / "config" / "prices.yaml")
    return Router(config, fixtures_dir=tmp_path / "no-recordings")


def _inputs(connectors: dict) -> PlanInputs:
    return PlanInputs(
        approaches=approaches_2(), owner=OWNER, skills={}, connectors=connectors, risk_table=build_risk_table(),
        policies={},
    )  # fmt: skip


def _shipped_connectors() -> dict:
    declared = yaml.safe_load((ROOT / "config" / "connectors.yaml").read_text(encoding="utf-8"))
    return {c["id"]: c for c in declared}


def _compile(router, inputs: PlanInputs):
    brief = complete_brief(load_brief_fixture("valid_market_scan"))
    return compile_plan(brief, inputs.approaches[0], 50.0, inputs, router=router)


def test_CL_INT_5c_FR_INT_09_the_fake_director_drafts_a_valid_plan_that_ends_at_a_gated_action(router):
    inputs = _inputs(_shipped_connectors())

    result = _compile(router, inputs)

    plan = result.plan
    assert [a.outcome for a in result.runs[0].attempts] == ["ok"] and len(result.runs) == 1  # no repair
    assert validate_plan(
        plan, risk_table=inputs.risk_table, connectors=inputs.connectors, skills=frozenset(), policies={}, owner=OWNER
    ) == []  # fmt: skip
    assert [u["role"] for u in plan["units"]] == ["specialist", "writer", "verifier", "writer"]
    first = plan["units"][-1]  # the first catalogue connector action whose gate_type is approval
    assert (first["connectors"], first["actions"]) == (["gmail"], ["create_draft"])
    (gate,) = plan["gates"]  # added by code: the fake named none, no policy, the cap is the person's
    assert (gate["action_type"], gate["guards"], gate["policy_ref"]) == ("create_draft", [first["id"]], None)
    assert plan["budget_cap"] == 50.0


def test_CL_INT_5c_FR_INT_09_a_catalogue_with_no_gated_action_gives_a_plan_with_no_gate(router):
    ungated = {
        cid: {**c, "actions": [a for a in c["actions"] if a["gate_type"] != "approval"]}
        for cid, c in _shipped_connectors().items()
    }

    plan = _compile(router, _inputs(ungated)).plan

    assert plan["gates"] == [] and all(u["actions"] == [] for u in plan["units"])


def test_CL_INT_5c_FR_INT_09_the_same_inputs_give_the_same_plan(router):
    inputs = _inputs(_shipped_connectors())
    assert _compile(router, inputs).plan == _compile(router, inputs).plan
