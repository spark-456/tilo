"""FR-AGT-14b (design decision 7; PRD 6.3, SEC-05; infra/ACCESS.md): `POST /internal/schedules/tick` on tilo-api.

After PR 2 one Cloud Scheduler job (OIDC as `tilo-schedule-scheduler`) calls this route. It is not under the principal
dependency: it checks the caller itself, because other service accounts hold `run.invoker` on tilo-api (the web, the
Gmail scheduler, the tasks invoker) and a person's session must never start a schedule. The matrix:

- no bearer token: 401; a token the verifier refuses: 401; the verifier is asked for the CONFIGURED audience;
- a verified token that is not exactly (`iss` Google, `aud` == `TILO_SCHEDULE_TICK_AUDIENCE`, `email_verified` is True,
  `email` == `TILO_SCHEDULE_TICK_CALLER`): 401 or 403, and nothing starts. The Gmail scheduler and tasks invoker are the
  two that matter;
- either variable unset (the production default until PR 2 and the user's rollout) or no schedule store: 503, before
  the token is even looked at;
- 200 `{"fired": n}`; no body or query ever selects a schedule or moves the clock; replay-only starts nothing;
- deployed (`K_SERVICE`), the route reaches its own check although the access gate would refuse every anonymous call.

Responses never echo a token, an address or an exception. API_FR_AGT_14b.md. Fakes: `_fr_agt_14_lib.py`.
"""

from __future__ import annotations

import socket
from types import SimpleNamespace
from typing import Any

import pytest
from _fr_agt_14_lib import (
    API_SA,
    AUDIENCE,
    ENV_AUDIENCE,
    ENV_CALLER,
    GMAIL_SA,
    GOOGLE_ISSUER,
    MON_0330Z,
    SCHEDULE_SA,
    TICK,
    WEEK,
    SchedApi,
    bearer,
    l3_budget_policy,
)
from fastapi.testclient import TestClient


@pytest.fixture
def sched(clear_flow, monkeypatch) -> SchedApi:
    rig = SchedApi(clear_flow, monkeypatch)
    rig.clock.set(MON_0330Z)
    return rig


@pytest.fixture
def run_sched(run_flow, monkeypatch) -> SchedApi:
    rig = SchedApi(run_flow.flow, monkeypatch, rf=run_flow)
    rig.clock.set(MON_0330Z)
    return rig


def _with_due_schedule(rig: SchedApi) -> tuple[str, set[str]]:
    """A due schedule `sched_a` (a start would change it: fire, skip or back off) and the worlds that exist now."""
    task = rig.approved_task()
    rig.insert(task, "sched_a")
    rig.insert(task, "sched_later", next_due=MON_0330Z + 10 * WEEK)
    return "sched_a", set(rig.store.worlds)


def _assert_untouched(rig: SchedApi, worlds: set[str]) -> None:
    for schedule_id, due in (("sched_a", MON_0330Z), ("sched_later", MON_0330Z + 10 * WEEK)):
        record = rig.schedules.get(schedule_id)
        assert (record.next_due, record.failures, record.last_error, record.last_world_id) == (due, 0, None, None)
    assert set(rig.store.worlds) == worlds, "a world was created"


# --- who may call ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": ""},
        {"Authorization": "Bearer"},
        {"Authorization": "Bearer "},
        {"Authorization": "Basic abc"},
    ],
)
def test_FR_AGT_14_no_bearer_token_is_401_and_nothing_starts(sched: SchedApi, headers: dict[str, str]) -> None:
    _, worlds = _with_due_schedule(sched)
    assert sched.tick(headers=headers).status_code == 401
    assert sched.verifier.calls == []  # nothing to verify
    _assert_untouched(sched, worlds)


def test_FR_AGT_14_a_token_the_verifier_refuses_is_401(sched: SchedApi) -> None:
    _, worlds = _with_due_schedule(sched)
    response = sched.tick("tok-forged")
    assert response.status_code == 401
    assert "tok-forged" not in response.text
    assert sched.verifier.calls == [("tok-forged", AUDIENCE)]
    _assert_untouched(sched, worlds)


def test_FR_AGT_14_a_signed_in_person_without_the_token_cannot_tick(sched: SchedApi) -> None:
    _, worlds = _with_due_schedule(sched)
    assert sched.flow.client.post(TICK).status_code == 401  # the session (the Flow's principal) authorises nothing here
    _assert_untouched(sched, worlds)


def test_FR_AGT_14_the_tick_does_not_need_or_use_a_principal(sched: SchedApi) -> None:
    sched.sign_out()  # the principal dependency now answers 401; the route must not depend on it
    assert sched.tick().status_code == 200


WRONG_CALLERS = [
    ("gmail scheduler", {"email": GMAIL_SA}),
    # the Tasks identity is a second, body-carrying caller of this route since FR-AGT-14e; that it can never fan out
    # is pinned in test_FR_AGT_14e_task_run.py (test_FR_AGT_14e_the_tasks_identity_can_never_fan_out)
    ("tilo-api itself", {"email": API_SA}),
    ("same account name, another project", {"email": "tilo-schedule-scheduler@other-project.iam.gserviceaccount.com"}),
    ("a person", {"email": "someone@example.com"}),
    ("upper-cased address", {"email": SCHEDULE_SA.upper()}),
    ("padded address", {"email": f" {SCHEDULE_SA}"}),
    ("trailing dot", {"email": SCHEDULE_SA + "."}),
    ("prefix of the address", {"email": SCHEDULE_SA[:-5]}),
    ("no email claim", {"email": None, "drop": ("email",)}),
    ("email is a list", {"email": [SCHEDULE_SA]}),
    ("email is a number", {"email": 5}),
    ("email not verified", {"email_verified": False}),
    ("email_verified is the string true", {"email_verified": "true"}),
    ("email_verified is 1", {"email_verified": 1}),
    ("email_verified is null", {"email_verified": None}),
    ("no email_verified claim", {"drop": ("email_verified",)}),
    ("another audience", {"aud": "https://tilo-harness-abc123-as.a.run.app"}),
    ("audience is a list", {"aud": [AUDIENCE]}),
    ("audience with a slash", {"aud": AUDIENCE + "/"}),
    ("no aud claim", {"drop": ("aud",)}),
]


@pytest.mark.parametrize(("label", "claims"), WRONG_CALLERS, ids=[w[0] for w in WRONG_CALLERS])
def test_FR_AGT_14_any_caller_but_the_schedule_scheduler_is_403_and_nothing_starts(
    sched: SchedApi, label: str, claims: dict[str, Any]
) -> None:
    _, worlds = _with_due_schedule(sched)
    kwargs = {"email": SCHEDULE_SA, **claims}
    token = sched.verifier.register(**kwargs)
    response = sched.tick(token)
    assert response.status_code == 403, label
    for secret in (token, SCHEDULE_SA, "iam.gserviceaccount.com", "someone@example.com", "Traceback"):
        assert secret not in response.text, label
    assert sched.verifier.calls == [(token, AUDIENCE)]  # the audience the route verified against is the configured one
    _assert_untouched(sched, worlds)


@pytest.mark.parametrize("issuer", [GOOGLE_ISSUER, "accounts.google.com"])
def test_FR_AGT_14_both_google_issuer_spellings_are_accepted(sched: SchedApi, issuer: str) -> None:
    response = sched.tick(sched.verifier.register(SCHEDULE_SA, iss=issuer))
    assert (response.status_code, response.json()) == (200, {"fired": 0})


@pytest.mark.parametrize(
    "issuer",
    [
        "https://evil.example.com",
        "http://accounts.google.com",
        "https://accounts.google.com.evil.test",
        "https://accounts.google.com/",
        "ACCOUNTS.GOOGLE.COM",
        "",
        None,
        ["https://accounts.google.com"],
    ],
)
def test_FR_AGT_14_any_other_issuer_is_refused_even_with_the_right_account(sched: SchedApi, issuer: Any) -> None:
    _, worlds = _with_due_schedule(sched)
    response = sched.tick(sched.verifier.register(SCHEDULE_SA, iss=issuer))
    assert response.status_code in (401, 403)
    _assert_untouched(sched, worlds)


def test_FR_AGT_14_a_token_with_no_issuer_claim_is_refused(sched: SchedApi) -> None:
    _, worlds = _with_due_schedule(sched)
    response = sched.tick(sched.verifier.register(SCHEDULE_SA, drop=("iss",)))
    assert response.status_code in (401, 403)
    _assert_untouched(sched, worlds)


# --- not configured: 503, before the token is looked at -------------------------------------------------------------


@pytest.mark.parametrize(
    "unset",
    [(ENV_AUDIENCE,), (ENV_CALLER,), (ENV_AUDIENCE, ENV_CALLER)],
    ids=["no audience", "no caller", "neither"],
)
@pytest.mark.parametrize("blank", [False, True], ids=["unset", "empty"])
def test_FR_AGT_14_unconfigured_is_503_for_any_request_and_the_token_is_not_looked_at(
    sched: SchedApi, monkeypatch: pytest.MonkeyPatch, unset: tuple[str, ...], blank: bool
) -> None:
    _, worlds = _with_due_schedule(sched)
    for name in unset:
        if blank:
            monkeypatch.setenv(name, "")
        else:
            monkeypatch.delenv(name)
    for headers in ({}, bearer(sched.good_token), bearer("tok-anything")):
        response = sched.tick(headers=headers)
        assert response.status_code == 503, headers
        assert "Traceback" not in response.text
    assert sched.verifier.calls == []  # fail closed before any verification
    _assert_untouched(sched, worlds)


def test_FR_AGT_14_the_production_default_is_503_with_no_overrides_and_no_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tilo_api import app

    app.dependency_overrides.clear()
    for name in (ENV_AUDIENCE, ENV_CALLER, "TILO_SCHEDULES_STORE", "TILO_API_DEV", "K_SERVICE"):
        monkeypatch.delenv(name, raising=False)
    client = TestClient(app, raise_server_exceptions=False)
    for headers in ({}, bearer("tok-anything")):
        response = client.post(TICK, headers=headers)
        assert response.status_code == 503
        assert "Traceback" not in response.text


def test_FR_AGT_14_with_no_schedule_store_the_tick_is_503_even_for_the_right_caller(sched: SchedApi) -> None:
    from tilo_api import schedules

    del sched.app.dependency_overrides[schedules.get_schedule_store]
    getattr(schedules.get_schedule_store, "cache_clear", lambda: None)()
    response = sched.tick()
    assert response.status_code == 503 and "Traceback" not in response.text


def test_FR_AGT_14_the_default_verifier_rejects_a_malformed_token_without_any_network_call(
    sched: SchedApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tilo_api import schedules

    del sched.app.dependency_overrides[schedules.get_oidc_verifier]  # the production google-auth wrapper
    connects: list[Any] = []
    real_connect = socket.socket.connect

    def refuse(self: socket.socket, address: Any, *args: Any, **kwargs: Any) -> Any:
        host = address[0] if isinstance(address, tuple) else str(address)
        if host not in (
            "127.0.0.1",
            "::1",
            "localhost",
        ):  # the loop's own socketpair is loopback; nothing else may go out
            connects.append(address)
            raise OSError("network blocked in this test")
        return real_connect(self, address, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", refuse)
    for token in ("garbage", "a.b.c", "x" * 5000):
        response = sched.tick(token)
        assert response.status_code == 401, token[:10]
        assert token not in response.text
    assert connects == []  # a token that is not even a JWT never reaches a certificate fetch


# --- what a good call does ------------------------------------------------------------------------------------------


def test_FR_AGT_14_the_right_caller_gets_200_with_the_number_fired(sched: SchedApi) -> None:
    response = sched.tick()
    assert (response.status_code, response.json()) == (200, {"fired": 0})  # nothing due yet: no schedule at all
    assert sched.verifier.calls == [(sched.good_token, AUDIENCE)]


def test_FR_AGT_14_a_due_schedule_fires_once_and_a_scheduler_retry_fires_nothing(run_sched: SchedApi) -> None:
    source = run_sched.source_run_task()
    run_sched.insert(source, "sched_a")
    run_sched.store.policies["pol_auto_budget"] = l3_budget_policy()
    first = run_sched.tick()
    assert (first.status_code, first.json()) == (200, {"fired": 1})  # FR-AGT-14e: handed to Cloud Tasks, not run here
    assert run_sched.deliver_new_tasks() == 1  # the task's own delivery runs it
    assert run_sched.tick().json() == {"fired": 0}
    world_id = run_sched.schedules.get("sched_a").last_world_id
    assert world_id and world_id != source.world_id
    assert [e["data"]["channel"] for e in run_sched.events(world_id, "world.requested")] == ["schedule"]


def test_FR_AGT_14_only_post_reaches_the_tick(sched: SchedApi) -> None:
    _, worlds = _with_due_schedule(sched)
    for method in ("GET", "PUT", "DELETE", "PATCH"):
        assert sched.flow.client.request(method, TICK, headers=bearer(sched.good_token)).status_code == 405
    _assert_untouched(sched, worlds)


def test_FR_AGT_14_a_body_or_query_cannot_select_a_schedule_or_move_the_clock(sched: SchedApi) -> None:
    """Refused (4xx) or ignored (200, the effect of a bare tick): either is allowed; steering is not."""
    _with_due_schedule(sched)
    token = sched.good_token
    steering = {
        "schedule_id": "sched_later",
        "now": "2099-01-01T00:00:00Z",
        "force": True,
        "slot": "2026-10-05T03:30:00Z",
        "owner_user_id": "u_someone_else",
    }
    queries = "?schedule_id=sched_later&now=2099-01-01T00:00:00Z&force=true"
    responses = [
        sched.flow.client.post(TICK, headers=bearer(token), json=steering),
        sched.flow.client.post(TICK + queries, headers=bearer(token)),
        sched.flow.client.post(TICK, headers=bearer(token), content=b"\x00" * 100_000),
        sched.flow.client.post(TICK, headers={**bearer(token), "content-type": "application/json"}, content=b"{"),
    ]
    for response in responses:
        assert response.status_code == 200 or 400 <= response.status_code < 500, response.status_code
        assert "Traceback" not in response.text
    later = sched.schedules.get("sched_later")
    assert (later.next_due, later.failures, later.last_world_id) == (MON_0330Z + 10 * WEEK, 0, None)
    assert sched.clock() == MON_0330Z  # no request moved the clock


def test_FR_AGT_14_replay_only_starts_nothing_and_moves_nothing(sched: SchedApi) -> None:
    _, worlds = _with_due_schedule(sched)
    sched.flags.set("replay_only", True, reason="NFR-24 test")
    for _ in range(3):
        response = sched.tick()
        assert (response.status_code, response.json()) == (200, {"fired": 0})
    _assert_untouched(sched, worlds)  # not even a failure counted: the slot fires once the flag clears


def test_FR_AGT_14_a_store_that_raises_fails_closed_with_a_fixed_body(sched: SchedApi) -> None:
    _, worlds = _with_due_schedule(sched)

    def broken(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("firestore says: password hunter2 for alice@example.com")

    sched.schedules.due = broken  # type: ignore[method-assign]
    response = sched.tick()
    assert 500 <= response.status_code < 600
    for leaked in ("hunter2", "alice", "firestore", "Traceback"):
        assert leaked not in response.text
    _assert_untouched(sched, worlds)


# --- deployed: the access gate ---------------------------------------------------------------------------------------


def test_FR_AGT_14_deployed_the_tick_reaches_its_own_check_while_every_other_new_route_stays_gated(
    sched: SchedApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SEC-15: deployed, `AccessGate` refuses every route not in PUBLIC_ROUTES from the stored visitor/judge
    declaration, and this test rig has no access store (503). The Scheduler has no declaration and no session, so the
    tick must be a public route of the gate and rely on its OIDC check alone (needs an owner decision, see the doc);
    the schedule routes must stay gated."""
    monkeypatch.setenv("K_SERVICE", "tilo-api")
    assert sched.tick(headers={}).status_code == 401  # its own refusal, not the gate's 503
    wrong = sched.tick(sched.verifier.register(GMAIL_SA))
    assert wrong.status_code == 403
    ok = sched.tick()
    assert (ok.status_code, ok.json()) == (200, {"fired": 0})
    no_task = SimpleNamespace(task_id="t_none", approach_id="quick")
    # SEC-15 open access: the access store and its 503 are gone, so a signed-in caller reaches the schedule routes.
    assert sched.listing().status_code == 200
    for call in (lambda: sched.create(no_task), lambda: sched.get("sched_a")):
        response = call()
        assert response.status_code not in (401, 403, 503), response.status_code  # the route's own answer, no gate
