"""Default-off owner minutes routes, real adopted callers and offline T3 plumbing."""

import pytest
from _ppl11a_lib import OWNER, PRIYA, SAM
from test_FR_MTG_03_analysis_publication import integration  # noqa: F401
from test_FR_MTG_03_owner_analysis_mode import owner_call  # noqa: F401
from test_FR_MTG_03_owner_minutes_caller import caller_app  # noqa: F401
from test_FR_MTG_08_owner_followup import followup  # noqa: F401
from test_FR_MTG_08_owner_followup_caller import caller_app as followup_app  # noqa: F401
from tilo_api import app, deps
from tilo_api.people_limits import NoStore, write_limit
from tilo_api.people_writes import Refusal
from tilo_metering.flags import InMemoryFlagStore

FLAG = "meeting.minutes.enabled"
ANALYZE = "/v1/meetings/mt_q4_plan/analyze-minutes"
FOLLOWUP = "/v1/meetings/mt_q4_plan/draft-followup"


def install(c, enabled=True):
    from tilo_api.owner_minutes_routes import install_owner_minutes_routes

    flags = InMemoryFlagStore()
    if enabled:
        flags.set(FLAG, True, reason="explicit offline test")
    c.app.dependency_overrides[deps.get_flag_store] = lambda: flags
    c.app.add_middleware(NoStore)
    assert install_owner_minutes_routes(c.app, flags) is enabled
    return flags


def test_FR_MTG_03_08_default_off_production_routes_and_openapi_absent():
    assert all("analyze-minutes" not in p and "draft-followup" not in p for p in app.openapi()["paths"])
    assert all("analyze-minutes" not in getattr(r, "path", "") for r in app.routes)


def test_FR_MTG_03_08_unreadable_flag_never_registers(caller_app):  # noqa: F811
    from tilo_api.owner_minutes_routes import install_owner_minutes_routes

    class Unreadable:
        def get(self, name):
            raise OSError("offline failure")

    assert install_owner_minutes_routes(caller_app.app, Unreadable()) is False
    assert all("analyze-minutes" not in p for p in caller_app.app.openapi()["paths"])


def test_FR_MTG_03_08_off_install_never_registers(caller_app):  # noqa: F811
    c = caller_app
    install(c, False)
    assert call_route(c, ANALYZE).status_code == 404
    assert all("analyze-minutes" not in p and "draft-followup" not in p for p in c.app.openapi()["paths"])
    assert not c.router.calls


def call_route(c, path, body=None, headers=None):
    return c.client.post(path, json={} if body is None else body, headers=c.headers if headers is None else headers)


def test_FR_MTG_03_enabled_owner_analyzes_through_adopted_caller(caller_app):  # noqa: F811
    c = caller_app
    install(c)
    c.app.dependency_overrides[c.budget_seam] = lambda: 2
    response = call_route(c, ANALYZE)
    assert response.status_code == 200 and response.json()["status"] == "minuted"
    assert response.json()["minutes_confirmed_by"] is None
    assert response.headers["cache-control"] == "no-store"
    assert len(c.rig.event_store.events[c.scope.world_id]) == 1


def test_FR_MTG_03_enabled_flag_does_not_open_server_budget(caller_app):  # noqa: F811
    c = caller_app
    install(c)
    response = call_route(c, ANALYZE)
    assert response.status_code == 503 and response.headers["cache-control"] == "no-store"
    assert not c.router.calls


@pytest.mark.parametrize("body", [{"budget": 3}, {"minutes": {}}, {"recipients": [PRIYA]}])
def test_FR_MTG_03_analysis_body_cannot_supply_authority(caller_app, body):  # noqa: F811
    c = caller_app
    install(c)
    c.app.dependency_overrides[c.budget_seam] = lambda: 2
    response = call_route(c, ANALYZE, body)
    assert response.status_code == 422 and response.headers["cache-control"] == "no-store"
    assert not c.router.calls and not c.rig.events.calls


@pytest.mark.parametrize("path", [ANALYZE, FOLLOWUP])
@pytest.mark.parametrize(
    "headers", [{}, {"Authorization": "Bearer test-owner"}, {"X-Firebase-AppCheck": "test-appcheck"}]
)
def test_FR_MTG_03_08_routes_require_auth_and_appcheck(caller_app, path, headers):  # noqa: F811
    c = caller_app
    install(c)
    c.app.dependency_overrides[c.budget_seam] = lambda: pytest.fail("unauthorized budget access")
    response = call_route(c, path, headers=headers)
    assert response.status_code == 401 and response.headers["cache-control"] == "no-store"
    assert not c.router.calls


def test_FR_MTG_03_foreign_meeting_owner_uniform404(caller_app):  # noqa: F811
    c = caller_app
    install(c)
    c.app.dependency_overrides[c.budget_seam] = lambda: 2
    c.writer.actor = SAM
    response = call_route(c, ANALYZE)
    assert response.status_code == 404 and response.json()["detail"] == "not_found"
    assert not c.router.calls


@pytest.mark.parametrize("path", [ANALYZE, FOLLOWUP])
def test_FR_MTG_03_08_demo_refused_before_caller(caller_app, path):  # noqa: F811
    c = caller_app
    install(c)
    c.demo = True
    c.app.dependency_overrides[c.budget_seam] = lambda: pytest.fail("demo budget access")
    assert call_route(c, path).status_code == 403
    assert not c.router.calls


def test_FR_MTG_03_runtime_flag_off_refuses_before_caller(caller_app):  # noqa: F811
    c = caller_app
    flags = install(c)
    flags.set(FLAG, False, reason="offline revoke")
    c.app.dependency_overrides[c.budget_seam] = lambda: pytest.fail("disabled budget access")
    assert call_route(c, ANALYZE).status_code == 404
    assert not c.router.calls


@pytest.mark.parametrize("path", [ANALYZE, FOLLOWUP])
def test_FR_MTG_03_08_owner_write_limit_applies(caller_app, path):  # noqa: F811
    c = caller_app
    install(c)

    def capped():
        raise Refusal(429, "rate_limited", headers={"Retry-After": "60"})

    c.app.dependency_overrides[write_limit] = capped
    response = call_route(c, path)
    assert response.status_code == 429 and response.headers["retry-after"] == "60"
    assert response.headers["cache-control"] == "no-store" and not c.router.calls


@pytest.mark.parametrize("meeting_id", ["not_meeting", "mt_" + "x" * 49])
def test_FR_MTG_03_malformed_id_has_no_provider(caller_app, meeting_id):  # noqa: F811
    c = caller_app
    install(c)
    c.app.dependency_overrides[c.budget_seam] = lambda: 2
    assert call_route(c, f"/v1/meetings/{meeting_id}/analyze-minutes").status_code == 404
    assert not c.router.calls


def test_FR_MTG_08_explicit_followup_is_one_t3_preview_and_zero_sends(followup_app):  # noqa: F811
    c = followup_app
    install(c)
    first = call_route(c, FOLLOWUP, {"recipients": [PRIYA]})
    assert first.status_code == 200 and first.json()["tier"] == "T3"
    assert first.json()["to"] == ["priya@example.com"]
    assert call_route(c, FOLLOWUP, {"recipients": [PRIYA]}).json()["card_id"] == first.json()["card_id"]
    assert c.line.bench.cards.get(OWNER, first.json()["card_id"])["thread_id"] is None
    assert len(c.calls) == 1 and c.line.entries() == [] and c.line.api.sent == []


@pytest.mark.parametrize(
    "body",
    [
        {"budget": 3},
        {"recipients": []},
        {"recipients": ["priya@example.com"]},
        {"recipients": [PRIYA, PRIYA]},
        {"recipients": ["u_meera"]},
    ],
)
def test_FR_MTG_08_closed_recipient_body_refuses_without_side_effects(followup_app, body):  # noqa: F811
    c = followup_app
    install(c)
    assert call_route(c, FOLLOWUP, body).status_code == 422
    assert c.calls == [] and c.line.bench.cards.dump() == "{}" and c.line.entries() == []
