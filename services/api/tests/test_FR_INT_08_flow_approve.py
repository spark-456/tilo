"""CL-INT-1 / FR-INT-08 (PRD 7.1, 10.1, 10.4) through `POST /tasks/{task_id}/approve` (TiloClient.approve):
the owner picks an approach and confirms a budget cap; the grant is `tilo_planning.budget` with the risk table
from config/autonomy.yaml; the cap is the person's number, never the model's `approach.credits` (issue #106);
a schema-valid, registered `budget.granted` is written to the world's events. Shapes: API_CL_INT_1.md.

Defaults applied (PRD silent): "the person's confirmed cap" is the request's `budget_cap`, granted exactly;
with no policy the grant waits for the person, so an owner's approve is granted with person authz; a
second approve never writes a second grant.
"""

from __future__ import annotations

import json
import math

import pytest
import tilo_planning.budget as budget
import tilo_policy
from _api_contracts_lib import assert_valid_event
from _clint1_lib import FLOW_USER, registered_event_types, spy_on
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from tilo_api import deps

CAP = 50  # not equal to any number in the scripted approaches (credits 30-45 and 90-130)


def _granted(flow, world_id):
    return flow.events(world_id, "budget.granted")


def test_FR_INT_08_flow_owner_approves_and_gets_the_world(clear_flow, repo_root, registry):
    intake = clear_flow.task_with_approaches()

    response = clear_flow.approve(intake["task_id"], "quick", CAP)

    assert response.status_code == 200, response.text
    world_id = response.json()["world_id"]
    assert world_id == intake["world_id"] and world_id.startswith("w_")
    (event,) = _granted(clear_flow, world_id)
    assert_valid_event(repo_root, registry, event)
    assert "budget.granted" in registered_event_types(repo_root)
    assert event["world_id"] == world_id and event["actor"] == FLOW_USER
    assert event["authz"]["by"] == "person" and event["authz"]["ref"] == FLOW_USER
    assert event["data"] == {"granted": CAP, "cap": CAP}


def test_FR_INT_08_flow_cap_is_the_persons_number_not_the_approach_credits(clear_flow):
    intake = clear_flow.task_with_approaches()
    approaches = clear_flow.approaches(intake["task_id"]).json()["approaches"]
    chosen = next(a for a in approaches if a["id"] == "thorough")  # credits 90-130
    assert chosen["credits"]["max"] != 40

    assert clear_flow.approve(intake["task_id"], "thorough", 40).status_code == 200

    (event,) = _granted(clear_flow, intake["world_id"])
    assert event["data"]["cap"] == 40 and event["data"]["granted"] == 40


def test_FR_INT_08_flow_grant_goes_through_planning_budget_with_the_config_risk_table(clear_flow, monkeypatch):
    requests = spy_on(monkeypatch, budget, "request_budget_grant")
    by_person = spy_on(monkeypatch, budget, "grant_budget_by_person")
    intake = clear_flow.task_with_approaches()

    assert clear_flow.approve(intake["task_id"], "quick", CAP).status_code == 200

    (request,) = requests
    assert request["table"] == tilo_policy.load_risk_table()  # config/autonomy.yaml (CC-SP-64 may add grant_budget)
    assert request["world_owner"] == FLOW_USER  # from the task record
    assert request["cap"] == CAP and request["base"]["world_id"] == intake["world_id"]
    # No policy covers the grant (or the table lacks grant_budget): it waits for the person, who is the owner.
    (person,) = by_person
    assert person["world_owner"] == FLOW_USER and person["user"] == FLOW_USER and person["cap"] == CAP


def test_FR_INT_08_flow_approve_before_approaches_is_409(clear_flow):
    intake = clear_flow.new_task()  # approaches not fetched yet

    response = clear_flow.approve(intake["task_id"], "quick", CAP)

    assert response.status_code == 409, response.text
    assert _granted(clear_flow, intake["world_id"]) == []


def test_FR_INT_08_flow_approve_while_questions_are_open_is_409(flow):
    intake = flow.new_task()
    assert intake["questions"]

    assert flow.approve(intake["task_id"], "quick", CAP).status_code == 409
    assert _granted(flow, intake["world_id"]) == []


def test_FR_INT_08_flow_unknown_task_is_404(clear_flow):
    real = clear_flow.task_with_approaches()
    assert clear_flow.approve(real["task_id"], "quick", CAP).status_code == 200  # the route exists

    assert clear_flow.approve("t_does_not_exist", "quick", CAP).status_code == 404


def test_FR_INT_08_flow_unknown_approach_is_refused(clear_flow):
    intake = clear_flow.task_with_approaches()

    response = clear_flow.approve(intake["task_id"], "not-an-approach", CAP)

    assert response.status_code in (404, 422), response.text
    assert _granted(clear_flow, intake["world_id"]) == []


@pytest.mark.parametrize(
    "cap_json", ["0", "-1", "-0.5", "NaN", "Infinity", "-Infinity", "1e999", "true", '"50"', "null", "[50]", "{}"]
)
def test_FR_INT_08_flow_cap_must_be_a_finite_positive_number(clear_flow, cap_json):
    intake = clear_flow.task_with_approaches()

    response = clear_flow.approve_raw(intake["task_id"], f'{{"approach_id": "quick", "budget_cap": {cap_json}}}')

    assert response.status_code in (400, 422), response.text
    assert _granted(clear_flow, intake["world_id"]) == []


def test_FR_INT_08_flow_missing_cap_or_approach_is_refused(clear_flow):
    intake = clear_flow.task_with_approaches()

    assert clear_flow.approve_raw(intake["task_id"], '{"approach_id": "quick"}').status_code in (400, 422)
    assert clear_flow.approve_raw(intake["task_id"], '{"budget_cap": 50}').status_code in (400, 422)
    assert _granted(clear_flow, intake["world_id"]) == []


def test_FR_INT_08_flow_a_second_approve_never_writes_a_second_grant(clear_flow):
    intake = clear_flow.task_with_approaches()
    first = clear_flow.approve(intake["task_id"], "quick", CAP)
    assert first.status_code == 200

    second = clear_flow.approve(intake["task_id"], "quick", CAP * 2)

    assert second.status_code == 409 or second.json()["world_id"] == first.json()["world_id"]
    (event,) = _granted(clear_flow, intake["world_id"])
    assert event["data"]["cap"] == CAP


def test_FR_INT_08_flow_approve_makes_no_model_call(clear_flow):
    intake = clear_flow.task_with_approaches()
    calls = len(clear_flow.provider.calls)

    clear_flow.approve(intake["task_id"], "quick", CAP)

    assert len(clear_flow.provider.calls) == calls == 2  # no model decides authorisation (PRD 10.4)


@settings(max_examples=30, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    cap=st.one_of(
        st.floats(allow_nan=True, allow_infinity=True),
        st.integers(min_value=-10, max_value=10_000),
        st.floats(min_value=0.001, max_value=1e6),
    )
)
def test_FR_INT_08_flow_property_a_grant_is_exactly_a_finite_positive_cap_or_nothing(clear_flow, cap):
    """Budgets never exceeded: either the response is a 200 and exactly one `budget.granted` carries the
    person's cap (finite, positive, equal on `granted` and `cap`), or it is a refusal and nothing is written."""
    intake = clear_flow.task_with_approaches()

    response = clear_flow.approve_raw(
        intake["task_id"],
        json.dumps({"approach_id": "quick", "budget_cap": cap}),  # NaN/Infinity as JSON text
    )

    events = _granted(clear_flow, intake["world_id"])
    if math.isfinite(cap) and 0 < cap <= deps.budget_cap_ceiling():  # above the run cap is 422 (#139, BQ-99)
        assert response.status_code == 200, response.text
        (event,) = events
        # a cap under the run floor is granted at the floor (BQ-BUDGET-FLOOR-1); a higher one is exactly the person's
        assert event["data"]["cap"] == event["data"]["granted"] == max(cap, deps.min_run_grant())
    else:
        assert response.status_code in (400, 422), response.text
        assert events == []
