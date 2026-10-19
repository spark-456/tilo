"""BQ-BUDGET-FLOOR-1 (owner decision, 15 Oct 2026; floor raised 30 to 60 by BQ-BUDGET-FLOOR-2): every run's budget
grant is at least 60 credits (US$0.30), whatever the Director's estimate says, and never more than the run cap. The
approaches the confirm card reads are floored, so it shows what a Start grants; `approve` raises a smaller cap to the
floor; a cap the person set higher is kept.
"""

from __future__ import annotations

import copy
import pathlib

import pytest
from _clint1_lib import Flow, brief_reply, make_spy_safety
from tilo_api import deps

FLOOR = 60.0


@pytest.fixture()
def flow(repo_root, store):
    made = Flow(repo_root, store, make_spy_safety(), copy.deepcopy(brief_reply([])))
    yield made
    made.close()


def _priced(flow):
    for approach, credits in zip(
        flow.provider.approaches["approaches"], ({"min": 3, "max": 8}, {"min": 12, "max": 20})
    ):
        approach["credits"] = credits  # the Director's estimates are below the floor
    intake = flow.new_task()
    body = flow.approaches(intake["task_id"]).json()
    return intake, body


def test_BQ_BUDGET_FLOOR_1_the_estimate_the_card_reads_is_floored_and_the_stored_one_is_not(flow) -> None:
    intake, body = _priced(flow)

    stored = flow.store.tasks[intake["task_id"]].approaches
    assert body["min_grant"] == FLOOR
    assert all(a["credits"]["max"] >= FLOOR and a["credits"]["min"] <= a["credits"]["max"] for a in body["approaches"])
    assert any(s["credits"]["max"] < FLOOR for s in stored), "the scripted estimate is below the floor"
    assert body["recommended"] == min(stored, key=lambda a: a["credits"]["max"])["id"]  # the cheapest, as before


def test_BQ_BUDGET_FLOOR_1_a_small_cap_is_granted_at_the_floor(flow) -> None:
    intake, body = _priced(flow)

    approved = flow.approve(intake["task_id"], body["recommended"], 5)

    assert approved.status_code == 200, approved.text
    grants = flow.events(intake["world_id"], "budget.granted")
    assert [g["data"]["cap"] for g in grants] == [FLOOR]


def test_BQ_BUDGET_FLOOR_1_a_higher_cap_the_person_chose_is_kept(flow) -> None:
    intake, body = _priced(flow)

    assert flow.approve(intake["task_id"], body["recommended"], 80).status_code == 200

    assert [g["data"]["cap"] for g in flow.events(intake["world_id"], "budget.granted")] == [80.0]


def test_BQ_BUDGET_FLOOR_1_the_run_cap_still_holds(flow) -> None:
    intake, body = _priced(flow)
    ceiling = deps.budget_cap_ceiling()

    assert flow.approve(intake["task_id"], body["recommended"], ceiling + 1).status_code == 422
    assert flow.approve(intake["task_id"], body["recommended"], ceiling).status_code == 200
    assert [g["data"]["cap"] for g in flow.events(intake["world_id"], "budget.granted")] == [ceiling]


@pytest.mark.parametrize(
    "yaml_text, expected",
    [
        ("min_run_grant_credits: 30\n", 30.0),
        ("min_run_grant_credits: 45.5\n", 45.5),
        ("min_run_grant_credits: 0\n", 0.0),  # the floor can be switched off
        ("min_run_grant_credits: 5000\n", 300.0),  # never above the run cap
        ("min_run_grant_credits: lots\n", 60.0),  # unusable: the owner's default
        ("{ not yaml", 60.0),
        (None, 60.0),  # no file
    ],
)
def test_BQ_BUDGET_FLOOR_1_the_floor_is_configuration(tmp_path, monkeypatch, yaml_text, expected) -> None:
    config = tmp_path / "config"
    config.mkdir()
    (config / "metering.yaml").write_text("caps:\n  run_credits: 300\n", encoding="utf-8")
    if yaml_text is not None:
        (config / "run_grant.yaml").write_text(yaml_text, encoding="utf-8")
    monkeypatch.setattr(deps, "_REPO_ROOT", pathlib.Path(tmp_path))

    assert deps.min_run_grant() == expected


def test_BQ_BUDGET_FLOOR_1_the_shipped_floor_is_sixty_credits() -> None:
    assert deps.min_run_grant() == FLOOR
