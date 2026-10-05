"""FR-INT-11 security review fix: approving a task that names a scenario builds every `policy.changed` event before it
stores anything, so a failure leaves no grant, no policy and no event, and the owner can approve again."""

from __future__ import annotations

import pathlib
import shutil
import sys
from typing import Any

import pytest
import yaml
from tilo_api import tasks

SCENARIO: dict[str, Any] = {
    "id": "TS-91",
    "title": "Fictional vendor comparison",
    "skills": ["vendor-research"],
    "connectors": ["google_drive"],
    "seed_data": ["seed/vendors.yaml"],
    "theme": "metropolis",
    "autonomy": [
        {"action_type": "save_file", "level": "L2", "connectors": ["google_drive"], "per_day": 5},
        {"action_type": "create_draft", "level": "L1", "connectors": ["google_drive"]},
    ],
}


@pytest.fixture()
def scenario_flow(clear_flow, tmp_path: pathlib.Path, repo_root: pathlib.Path, monkeypatch):
    root = tmp_path / "repo"
    (root / "config" / "scenarios").mkdir(parents=True)
    for name in ("connectors.yaml", "autonomy.yaml"):
        shutil.copy(repo_root / "config" / name, root / "config" / name)
    (root / "seed").mkdir()
    (root / "seed" / "vendors.yaml").write_text("vendors:\n  - name: Fictional Vendor One\n", encoding="utf-8")
    (root / "config" / "scenarios" / "TS-91.yaml").write_text(yaml.safe_dump(SCENARIO), encoding="utf-8")
    import tilo_planning.scenarios as scenarios  # noqa: PLC0415

    original = scenarios.load_scenario

    def load(scenario_id: str, **kwargs: Any) -> Any:
        return original(scenario_id, **{**kwargs, "repo_root": root})

    monkeypatch.setattr(scenarios, "load_scenario", load)
    for module in list(sys.modules.values()):
        if (
            getattr(module, "__name__", "").startswith("tilo_api")
            and getattr(module, "load_scenario", None) is original
        ):
            monkeypatch.setattr(module, "load_scenario", load)
    return clear_flow


def test_FR_INT_11_a_failure_while_building_the_policy_events_leaves_nothing_and_a_retry_succeeds(
    scenario_flow, monkeypatch
):
    flow = scenario_flow
    intake = flow.client.post("/intake", data={"text": "Compare three vendors.", "scenario": "TS-91"}).json()
    flow.approaches(intake["task_id"])
    real, calls = tasks.build_event, []

    def flaky(*args: Any, **kwargs: Any) -> Any:
        calls.append(kwargs.get("type"))
        if kwargs.get("type") == "policy.changed" and calls.count("policy.changed") == 2:
            raise RuntimeError("the second event could not be built")
        return real(*args, **kwargs)

    monkeypatch.setattr(tasks, "build_event", flaky)
    failed = flow.approve(intake["task_id"], "quick", 50)
    assert failed.status_code == 500
    task = flow.store.tasks[intake["task_id"]]
    assert not task.granted and flow.store.policies == {} and flow.store.policy_worlds == {}
    assert not flow.events(intake["world_id"], "policy.changed") and not flow.events(
        intake["world_id"], "budget.granted"
    )

    monkeypatch.setattr(tasks, "build_event", real)
    retry = flow.approve(intake["task_id"], "quick", 50)

    assert retry.status_code == 200, retry.text
    assert len(flow.store.policies) == 2 and len(flow.events(intake["world_id"], "policy.changed")) == 2
    seqs = [e["seq"] for e in flow.store.events[intake["world_id"]]]
    assert seqs == sorted(set(seqs)), "seq stays strictly increasing"
