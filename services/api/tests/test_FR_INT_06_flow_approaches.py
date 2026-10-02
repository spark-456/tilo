"""CL-INT-1 / FR-INT-06 (PRD 7.1) through `GET /tasks/{task_id}/approaches` (TiloClient.getApproaches):
the Director's 2-3 approaches for the person's confirmed brief, a recommendation, and the credit rate.
Shapes: API_CL_INT_1.md.
"""

from __future__ import annotations

import pytest
from _api_contracts_lib import errors_for, load_schema

CREDIT_USD = 0.005  # PRD 14.1: 1 credit = US$0.005 (config/prices.yaml credit_usd)


def test_FR_INT_06_flow_returns_approaches_recommended_and_credit_rate(clear_flow, repo_root, registry):
    intake = clear_flow.new_task()

    response = clear_flow.approaches(intake["task_id"])

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["task_id"] == intake["task_id"]
    assert 2 <= len(body["approaches"]) <= 3
    wrapper = {"$ref": f"{load_schema(repo_root, 'plan')['$id']}#/$defs/approach"}
    for approach in body["approaches"]:
        assert not errors_for(wrapper, approach, registry)
    assert body["recommended"] in {a["id"] for a in body["approaches"]}
    assert body["credit_usd"] == pytest.approx(CREDIT_USD)


def test_FR_INT_06_flow_approaches_use_the_edited_brief_and_the_answers(flow):
    intake = flow.new_task()
    answers = [{"field": "audience", "answer": "The board of directors"}, {"field": "deadline", "answer": None}]
    edits = {"goal": "Compare three suppliers on landed price."}
    assert flow.answers(intake["task_id"], answers, brief_edits=edits).status_code == 200

    response = flow.approaches(intake["task_id"])

    assert response.status_code == 200, response.text
    prompt = flow.provider.calls[-1].prompt  # the approaches request, as sent through the Router
    assert "Compare three suppliers on landed price." in prompt
    assert "The board of directors" in prompt


def test_FR_INT_06_flow_approaches_come_through_the_router_with_one_extra_call(clear_flow):
    intake = clear_flow.new_task()
    assert len(clear_flow.provider.calls) == 1

    clear_flow.approaches(intake["task_id"])

    assert len(clear_flow.provider.calls) == 2  # one brief call, one approaches call; nothing else


def test_FR_INT_06_flow_unknown_task_is_404(clear_flow):
    clear_flow.task_with_approaches()  # the route exists

    assert clear_flow.approaches("t_does_not_exist").status_code == 404
