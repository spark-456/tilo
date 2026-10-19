"""FR-AGT-14 (PRD 6.3 Cloud Scheduler, infra/ACCESS.md "Route requirements", SEC-05): `POST /internal/schedules/tick`.

One Cloud Scheduler job (`tilo-schedule-tick`, every minute, OIDC as `tilo-schedule-scheduler`) calls it. The route
checks the
caller itself, because `run.invoker` on harness is also held by tilo-api, tilo-tasks-invoker and tilo-gmail-scheduler:
- no bearer token: 401; a token the verifier refuses: 401;
- a verified token for any other service account, the right name in another project, an unverified email, or another
  audience: 403, and nothing starts. `tilo-gmail-scheduler` and `tilo-tasks-invoker` are the two that matter;
- the right account: 200 `{"fired": n}`;
- nothing wired (no verifier): 503, whatever token arrives (fail closed);
- the tick takes no parameters and no body: whatever a caller adds neither selects a schedule nor moves the clock.
Responses never echo a token, an address or an exception. No network: starlette's TestClient, fakes from
schedule_support.py.
Interface: API_FR_AGT_14.md.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from schedule_support import (
    API_SA,
    AUDIENCE,
    GMAIL_SA,
    MON_0330Z,
    SCHEDULE_SA,
    TASKS_SA,
    WEEK,
    FakeOidcVerifier,
    bearer,
    make_rig,
    make_schedule,
)
from tilo_harness.app import app as production_app
from tilo_harness.app import create_app
from tilo_harness.schedule import TickWiring

PATH = "/internal/schedules/tick"


def _client(rig, verifier: FakeOidcVerifier | None = None):
    verifier = verifier or FakeOidcVerifier()
    wiring = TickWiring(verifier=verifier, audience=AUDIENCE, service_account=SCHEDULE_SA, ticker=rig.ticker)
    return TestClient(create_app(schedule_tick=wiring)), verifier


def _assert_nothing_started(rig):
    assert rig.starter.attempts == []
    assert rig.store.get("sched_a").next_due == MON_0330Z
    assert rig.store.held() == {}


def test_FR_AGT_14_no_token_is_401_and_nothing_starts():
    rig = make_rig()
    client, verifier = _client(rig)
    for headers in ({}, {"Authorization": ""}, {"Authorization": "Bearer"}, {"Authorization": "Bearer "}):
        assert client.post(PATH, headers=headers).status_code == 401
    assert verifier.calls == []  # nothing to verify
    _assert_nothing_started(rig)


def test_FR_AGT_14_a_token_the_verifier_refuses_is_401_and_a_non_bearer_scheme_is_401():
    rig = make_rig()
    client, verifier = _client(rig)
    assert client.post(PATH, headers=bearer("tok-forged")).status_code == 401
    good = verifier.register(SCHEDULE_SA)
    assert client.post(PATH, headers={"Authorization": f"Basic {good}"}).status_code == 401
    _assert_nothing_started(rig)


@pytest.mark.parametrize(
    ("label", "email", "kwargs"),
    [
        ("gmail scheduler", GMAIL_SA, {}),
        ("tasks invoker", TASKS_SA, {}),
        ("tilo-api", API_SA, {}),
        ("same account name in another project", "tilo-schedule-scheduler@other-project.iam.gserviceaccount.com", {}),
        ("a person", "someone@example.com", {}),
        ("no email claim", None, {}),
        ("right account but email not verified", SCHEDULE_SA, {"email_verified": False}),
        ("right account but another audience", SCHEDULE_SA, {"aud": "https://tilo-api-abc123-as.a.run.app"}),
    ],
)
def test_FR_AGT_14_any_caller_but_the_schedule_scheduler_is_403_and_nothing_starts(label, email, kwargs):
    rig = make_rig()
    client, verifier = _client(rig)
    token = verifier.register(email, **kwargs)
    response = client.post(PATH, headers=bearer(token))
    assert response.status_code == 403, label
    assert token not in response.text and "iam.gserviceaccount.com" not in response.text
    assert verifier.calls == [(token, AUDIENCE)]  # the audience the route verified against is its own
    _assert_nothing_started(rig)


def test_FR_AGT_14_the_schedule_scheduler_gets_200_with_the_number_fired_and_the_run_starts():
    rig = make_rig([make_schedule("sched_a"), make_schedule("sched_b")])
    client, verifier = _client(rig)
    token = verifier.register(SCHEDULE_SA)
    response = client.post(PATH, headers=bearer(token))
    assert response.status_code == 200
    assert response.json() == {"fired": 2}
    assert len(rig.starter.started) == 2
    assert verifier.calls == [(token, AUDIENCE)]
    assert client.post(PATH, headers=bearer(token)).json() == {"fired": 0}  # Scheduler retry: nothing twice
    assert len(rig.starter.started) == 2


def test_FR_AGT_14_a_tick_with_nothing_due_is_200_fired_0():
    rig = make_rig([make_schedule(next_due=MON_0330Z + WEEK)])
    client, verifier = _client(rig)
    response = client.post(PATH, headers=bearer(verifier.register(SCHEDULE_SA)))
    assert (response.status_code, response.json()) == (200, {"fired": 0})


def test_FR_AGT_14_nothing_wired_is_503_for_any_token_and_the_production_app_is_wired_to_nothing():
    for client in (TestClient(production_app), TestClient(create_app())):
        for headers in ({}, bearer("tok-anything")):
            response = client.post(PATH, headers=headers)
            assert response.status_code == 503
            assert "Traceback" not in response.text


def test_FR_AGT_14_only_post_reaches_the_tick():
    rig = make_rig()
    client, verifier = _client(rig)
    token = verifier.register(SCHEDULE_SA)
    for method in ("GET", "PUT", "DELETE", "PATCH"):
        assert client.request(method, PATH, headers=bearer(token)).status_code == 405
    _assert_nothing_started(rig)


def test_FR_AGT_14_a_body_or_query_cannot_select_a_schedule_or_move_the_clock():
    """Refused (4xx) or ignored (200, same effect as a bare tick): either is allowed; steering is not."""
    not_due = make_schedule("sched_later", next_due=MON_0330Z + 10 * WEEK)
    rig = make_rig([make_schedule("sched_a"), not_due])
    client, verifier = _client(rig)
    token = verifier.register(SCHEDULE_SA)
    steering = {
        "schedule_id": "sched_later",
        "now": "2099-01-01T00:00:00Z",
        "force": True,
        "slot": "2026-10-05T03:30:00Z",
        "owner_user_id": "u_someone_else",
    }
    queries = "?schedule_id=sched_later&now=2099-01-01T00:00:00Z&force=true"
    responses = [
        client.post(PATH, headers=bearer(token), json=steering),
        client.post(PATH + queries, headers=bearer(token)),
        client.post(PATH, headers=bearer(token), content=b"\x00" * 100_000),
    ]
    for response in responses:
        assert response.status_code == 200 or 400 <= response.status_code < 500
        assert "Traceback" not in response.text
    started_ids = {r.schedule_id for r in rig.starter.started}
    assert "sched_later" not in started_ids  # not due at the injected clock, whatever the caller said
    assert rig.store.get("sched_later").next_due == MON_0330Z + 10 * WEEK
    assert {r.owner_user_id for r in rig.starter.started} <= {"u_owner"}
    assert len(rig.starter.started) <= 1  # sched_a at most once across all three calls
    assert all(r.slot == MON_0330Z for r in rig.starter.started)


def test_FR_AGT_14_the_other_harness_routes_are_untouched_by_the_tick_wiring():
    rig = make_rig()
    client, _ = _client(rig)
    assert client.get("/health").status_code == 200
    assert client.get("/healthz").json() == {"status": "ok"}
