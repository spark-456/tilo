"""CL-INT-4 hardening (security round 1 on #220): the task routes read only `application/json`. A cross-site form or
`text/plain` POST needs no CORS preflight, so a body in those types must never change anything, in any mode."""

from __future__ import annotations

import json

import pytest

ANSWERS = {"answers": [], "brief_edits": {}}


@pytest.mark.parametrize("content_type", ["text/plain", "application/x-www-form-urlencoded", "multipart/form-data", ""])
def test_CL_INT_4_answers_and_approve_refuse_a_body_that_is_not_json(clear_flow, content_type):
    intake = clear_flow.task_with_approaches()
    task_id, world_id = intake["task_id"], intake["world_id"]
    before = list(clear_flow.store.events[world_id])
    headers = {"content-type": content_type} if content_type else {}
    approve = {"approach_id": "quick", "budget_cap": 50}
    for path, body in ((f"/tasks/{task_id}/answers", ANSWERS), (f"/tasks/{task_id}/approve", approve)):
        response = clear_flow.client.post(path, content=json.dumps(body), headers=headers)
        assert response.status_code == 415, (path, response.text)
    assert clear_flow.store.events[world_id] == before, "a refused body writes nothing, grants nothing"
    assert not clear_flow.store.tasks[task_id].granted


def test_CL_INT_4_json_with_a_charset_or_any_case_is_still_read(clear_flow):
    intake = clear_flow.task_with_approaches()
    body = json.dumps({"approach_id": "quick", "budget_cap": 50})
    response = clear_flow.client.post(
        f"/tasks/{intake['task_id']}/approve", content=body, headers={"content-type": "Application/JSON; charset=utf-8"}
    )
    assert response.status_code == 200, response.text
