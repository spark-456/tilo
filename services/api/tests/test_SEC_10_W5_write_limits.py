"""SEC-10 W5: share revocation and schedule edits share the existing write-attempt budget."""

import pytest
from _team_routes_lib import team_api
from fastapi import HTTPException
from tilo_api import deps, schedules
from tilo_api.people_limits import WRITES_PER_MINUTE
from tilo_harness.schedule_store import InMemoryScheduleStore

WRITES = [
    ("DELETE", "/worlds/w_missing/shares/share_missing", 404),
    ("DELETE", "/schedules/sched_missing", 404),
    ("PATCH", "/schedules/sched_missing", 422),
]


@pytest.mark.parametrize(("method", "path", "status"), WRITES)
def test_SEC_10_W5_refused_writes_count_and_share_the_team_budget(method, path, status):
    with team_api() as api:
        api.client.app.dependency_overrides[schedules.get_schedule_store] = lambda: InMemoryScheduleStore()
        api.client.app.dependency_overrides[deps.get_store] = lambda: deps.Store()
        for n in range(WRITES_PER_MINUTE):
            response = api.client.request(method, path, json={"unknown": True})
            assert response.status_code == status, (n, response.status_code, response.text)
        response = api.client.request(method, path, json={"unknown": True})
        assert response.status_code == 429, response.text
        assert 1 <= int(response.headers["retry-after"]) <= 60
        assert api.put("/v1/team/switches/weekend", {"on": True}).status_code == 429
        api.advance_clock(61)
        assert api.client.request(method, path, json={"unknown": True}).status_code == status


@pytest.mark.parametrize(("method", "path", "_status"), WRITES)
def test_SEC_10_W5_unsigned_attempts_are_refused_before_the_write_counter(method, path, _status):
    with team_api() as api:
        overrides = api.client.app.dependency_overrides
        signed_in = overrides[deps.get_current_principal]

        def unsigned():
            raise HTTPException(status_code=401, detail="unauthorized")

        overrides[deps.get_current_principal] = unsigned
        for _ in range(WRITES_PER_MINUTE + 1):
            assert api.client.request(method, path, json={"unknown": True}).status_code == 401
        overrides[deps.get_current_principal] = signed_in
        assert api.put("/v1/team/switches/weekend", {"on": True}).status_code == 200
