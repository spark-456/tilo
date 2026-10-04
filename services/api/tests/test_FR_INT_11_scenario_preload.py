"""FR-INT-11 (PRD 7.1, 4.3) at the API: `POST /intake` takes an optional `scenario` form field (an id of
`config/scenarios/<id>.yaml`); approving the task starts the world with that scenario's autonomy policy
preloaded, as the owner's own policy (PRD 10.1: only the owner creates one) with a `policy.changed` event
(authz person), and nothing before the person approves. The loader is `tilo_planning.scenarios.load_scenario`
(tests: `packages/planning/tests/test_FR_INT_11_scenario_config.py`); the API calls no other code for a
scenario, so a new scenario file needs no API change. Shapes: `packages/planning/tests/API_FR_INT_11_12.md`.

Uses a fictional scenario in a tmp repo root (the shipped SC-01 file is loaded in the planning tests), routed
to the API by patching `load_scenario` the way `_clint1_lib.spy_on` does, so the test fixes only what the
loader receives, not how the API finds the config.
"""

from __future__ import annotations

import pathlib
import shutil
import sys
from typing import Any

import pytest
import yaml
from _api_contracts_lib import assert_valid_event, build_registry, errors_for, load_schema
from _clint1_lib import FLOW_USER

CAP = 50
SCENARIO: dict[str, Any] = {
    "id": "TS-91",
    "title": "Fictional vendor comparison",
    "skills": ["vendor-research"],
    "connectors": ["google_drive"],
    "seed_data": ["seed/vendors.yaml"],
    "theme": "metropolis",
    "autonomy": [
        {"action_type": "save_file", "level": "L2", "connectors": ["google_drive"], "per_day": 5, "undo_window_s": 60}
    ],
}


@pytest.fixture()
def scenario_root(tmp_path: pathlib.Path, repo_root: pathlib.Path) -> pathlib.Path:
    root = tmp_path / "repo"
    (root / "config" / "scenarios").mkdir(parents=True)
    for name in ("connectors.yaml", "autonomy.yaml"):
        shutil.copy(repo_root / "config" / name, root / "config" / name)
    (root / "seed").mkdir()
    (root / "seed" / "vendors.yaml").write_text("vendors:\n  - name: Fictional Vendor One\n", encoding="utf-8")
    (root / "config" / "scenarios" / "TS-91.yaml").write_text(yaml.safe_dump(SCENARIO), encoding="utf-8")
    return root


@pytest.fixture()
def scenario_flow(clear_flow, scenario_root, monkeypatch):
    """The Flow with `load_scenario` reading the tmp repo root, wherever tilo_api imported it."""
    import tilo_planning.scenarios as scenarios  # noqa: PLC0415

    original = scenarios.load_scenario

    def load(scenario_id: str, **kwargs: Any) -> Any:
        return original(scenario_id, **{**kwargs, "repo_root": scenario_root})

    monkeypatch.setattr(scenarios, "load_scenario", load)
    for module in list(sys.modules.values()):
        if (
            getattr(module, "__name__", "").startswith("tilo_api")
            and getattr(module, "load_scenario", None) is original
        ):
            monkeypatch.setattr(module, "load_scenario", load)
    return clear_flow


def intake_with(flow, scenario: str | None, text: str = "Compare three vendors."):
    data = {"text": text, **({"scenario": scenario} if scenario is not None else {})}
    return flow.client.post("/intake", data=data)


def test_FR_INT_11_intake_with_a_scenario_names_it_and_preloads_nothing_before_approval(scenario_flow):
    response = intake_with(scenario_flow, "TS-91")

    assert response.status_code == 201, response.text
    assert response.json()["scenario"] == "TS-91"
    assert scenario_flow.store.policies == {}, "a policy is the owner's act: nothing exists before they approve"


def test_FR_INT_11_intake_without_a_scenario_is_unchanged(scenario_flow):
    body = intake_with(scenario_flow, None).json()

    assert body.get("scenario") is None
    assert scenario_flow.approaches(body["task_id"]).status_code == 200
    assert scenario_flow.approve(body["task_id"], "quick", CAP).status_code == 200
    assert scenario_flow.store.policies == {}, "no scenario, no preloaded policy"


@pytest.mark.parametrize("scenario_id", ["TS-404", "../config/autonomy", "TS-91/../x", "a" * 200])
def test_FR_INT_11_an_unknown_or_hostile_scenario_is_422_and_stores_nothing(scenario_flow, scenario_id):
    response = intake_with(scenario_flow, scenario_id)

    assert response.status_code == 422, response.text
    assert not scenario_flow.store.tasks and not scenario_flow.store.worlds and not scenario_flow.store.policies


def test_FR_INT_11_approving_preloads_the_scenarios_policy_as_the_owners_own(scenario_flow, repo_root):
    intake = intake_with(scenario_flow, "TS-91").json()
    assert scenario_flow.approaches(intake["task_id"]).status_code == 200

    response = scenario_flow.approve(intake["task_id"], "quick", CAP)

    assert response.status_code == 200, response.text
    world_id = response.json()["world_id"]
    (policy,) = scenario_flow.store.policies.values()
    assert not errors_for(load_schema(repo_root, "policy"), policy, build_registry(repo_root))
    assert (policy["owner"], policy["action_type"], policy["level"]) == (FLOW_USER, "save_file", "L2")
    assert policy["limits"]["per_day"] == 5 and policy["created_by"]["by"] == FLOW_USER
    assert scenario_flow.store.policy_worlds[policy["id"]] == world_id
    changed = scenario_flow.events(world_id, "policy.changed")
    assert [e["data"] for e in changed] == [{"policy_id": policy["id"], "change": "created", "level": "L2"}]
    assert changed[0]["authz"]["by"] == "person" and changed[0]["authz"]["ref"] == FLOW_USER
    assert_valid_event(repo_root, build_registry(repo_root), changed[0])


def test_FR_INT_11_a_second_approve_never_duplicates_the_preloaded_policy(scenario_flow):
    intake = intake_with(scenario_flow, "TS-91").json()
    scenario_flow.approaches(intake["task_id"])
    scenario_flow.approve(intake["task_id"], "quick", CAP)

    scenario_flow.approve(intake["task_id"], "quick", CAP)

    assert len(scenario_flow.store.policies) == 1
    assert len(scenario_flow.events(intake["world_id"], "policy.changed")) == 1
