"""FR-AGT-14e (design: NO new public route; SEC-15; PPL-11a): the Cloud Tasks hand-off reuses the one tick route.

A second public route is the owner's call (`access.PUBLIC_ROUTES` is pinned as literals here, in the SEC-15 test and in
the PPL-11a test). Both callers, the Scheduler (fan-out) and Cloud Tasks (run), go through
`POST /internal/schedules/tick`: no new path, no new method, no new public route, nothing under `/internal` besides it.
Deployed, the route still reaches its own OIDC check for the Tasks caller while every other route stays gated.
"""

from __future__ import annotations

import pytest
from _fr_agt_14_lib import MON_0330Z, TASKS_SA, TICK, SchedApi, task_body
from _sec15_lib import PINNED_PUBLIC_ROUTES, route_table

PUBLIC = frozenset(
    {
        ("GET", "/health"),
        ("GET", "/healthz"),
        ("GET", "/access"),
        ("POST", "/access/declaration"),
        ("POST", "/internal/schedules/tick"),
    }
)
# ADR-0042 (BQ-M2-5, the user's decision pending; inert until TILO_VOICE_METER=1): the meeting bot's own two routes.
# They are not part of the schedule hand-off: this test still pins that the hand-off added nothing of its own.
METER = frozenset({("POST", "/internal/meeting-voice/reserve"), ("POST", "/internal/meeting-voice/close")})
SCHEDULE_ROUTES = frozenset(
    {
        ("POST", "/internal/schedules/tick"),
        ("POST", "/schedules"),
        ("GET", "/schedules"),
        ("GET", "/schedules/{schedule_id}"),
        ("PATCH", "/schedules/{schedule_id}"),
        ("DELETE", "/schedules/{schedule_id}"),
    }
)


def _routes() -> set[tuple[str, str]]:
    from tilo_api import app

    return set(route_table(app))  # read from the OpenAPI document, as the SEC-15 tests do


def test_FR_AGT_14e_the_public_routes_are_exactly_the_five_already_pinned() -> None:
    from tilo_api import access

    assert access.PUBLIC_ROUTES == PUBLIC | METER
    assert frozenset(PINNED_PUBLIC_ROUTES) == PUBLIC | METER  # the five, and the meter's two by name


def test_FR_AGT_14e_the_tick_is_the_only_internal_route_and_the_schedule_routes_are_unchanged() -> None:
    routes = _routes()
    assert {r for r in routes if r[1].startswith("/internal")} == {("POST", TICK)} | METER
    assert {r for r in routes if "schedule" in r[1]} == SCHEDULE_ROUTES
    assert not [r for r in routes if "tick" in r[1] and r != ("POST", TICK)]
    assert not [r for r in routes if r[1].startswith(("/tasks/run", "/runs", "/internal/tasks", "/internal/runs"))]


@pytest.fixture
def sched(clear_flow, monkeypatch) -> SchedApi:
    rig = SchedApi(clear_flow, monkeypatch)
    rig.clock.set(MON_0330Z)
    return rig


def test_FR_AGT_14e_deployed_the_tasks_caller_reaches_the_routes_own_check_and_others_stay_gated(
    sched: SchedApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SEC-15: deployed, `AccessGate` refuses every route not in PUBLIC_ROUTES. Cloud Tasks has no session or
    declaration, so its delivery must be answered by the tick's own check (the same public route, no new one)."""
    monkeypatch.setenv("K_SERVICE", "tilo-api")
    body = task_body("sched_gone", MON_0330Z)
    assert sched.task_call(body, headers={}).status_code == 401  # its own refusal, not the gate's 503
    assert sched.task_call(body, sched.verifier.register("someone@example.com")).status_code == 403
    ok = sched.task_call(body)  # the Tasks identity: a schedule that is gone is a permanent refusal, not a gate answer
    assert (ok.status_code, ok.json()) == (200, {"ran": 0, "skipped": "schedule_missing"})
    assert TASKS_SA not in ok.text
    for call in (sched.listing, lambda: sched.get("sched_a")):
        assert call().status_code in (401, 403, 503)  # the gate's refusal, never a route answer
