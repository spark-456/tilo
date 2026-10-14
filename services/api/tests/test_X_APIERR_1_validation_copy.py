"""Validation keeps its status, field diagnostics and refusal of writes."""

import asyncio

import pytest
from _team_routes_lib import MEMBER, ROLES, team_api
from starlette.requests import Request
from tilo_api.tasks import ApproveIn, _json_body
from tilo_api.validation_copy import ValidationRefusal, validation_response


@pytest.mark.parametrize("body", [b"{", b'{"approach_id":"quick","budget_cap":-1}', b"[]"])
def test_task_validation_has_readable_copy_and_never_echoes_input(body):
    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    request = Request({"type": "http", "headers": [(b"content-type", b"application/json")]}, receive)
    with pytest.raises(ValidationRefusal) as caught:
        asyncio.run(_json_body(ApproveIn)(request))
    refusal = caught.value
    assert refusal.status_code == 422
    assert refusal.detail == "Check the task information and try again."
    assert refusal.extra["errors"]
    assert all(set(error) == {"loc", "msg"} for error in refusal.extra["errors"])
    assert validation_response(request, refusal).status_code == 422


@pytest.mark.parametrize("body", [{}, {"role": 42}, {"role": "Viewer", "secret": "CANARY-VALIDATION"}])
def test_team_validation_has_readable_copy_and_keeps_members(body):
    with team_api() as api:
        response = api.put(f"/v1/team/members/{MEMBER}/role", body)
        assert response.status_code == 422
        assert response.json()["detail"] == "Check the team settings and try again."
        assert response.json()["errors"]
        assert all(set(error) == {"loc", "msg"} for error in response.json()["errors"])
        assert "CANARY-VALIDATION" not in response.text
        assert api.store.read().roles == ROLES
