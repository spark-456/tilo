"""SEC-16 / OPEN-ACCESS (owner's order, 16 Oct 2026): opening sign-in to everyone must not open spending. A person
who signs in with their own mail and never declared anything starts with the normal per-uid allowance: live
models only where the deployment permits them, the lifetime spend cap per uid, the per-uid rate limit, and the
shared kill switch.
"""

from __future__ import annotations

from _sec15_lib import NEWCOMER, VISITOR, concrete
from _sec16_lib import spend

BIG_LIMIT = {"rate_limit_requests": 1_000}


def test_SEC_16_OPEN_ACCESS_a_new_person_gets_the_live_path_under_the_per_uid_cap(sec16_factory):
    h = sec16_factory(declarations={}, **BIG_LIMIT)
    h.as_user(NEWCOMER)

    response = h.intake()

    assert response.status_code == 201, response.text
    assert set(h.router_modes) == {"live"}, "the deployment permits live models and the person is under the cap"


def test_SEC_16_OPEN_ACCESS_a_new_person_at_the_lifetime_cap_is_refused_new_work(sec16_factory):
    h = sec16_factory(declarations={}, **BIG_LIMIT)
    h.as_user(NEWCOMER)
    spend(h.ledger, NEWCOMER, h.caps.uid_lifetime_minor)
    h.ledger.calls.clear()
    before = h.snapshot()

    response = h.intake()

    assert response.status_code == 403 and response.json()["code"] == "spend_cap_reached", response.text
    assert h.snapshot() == before and h.router_modes == []
    assert h.me().json()["models"] == "replay", "a capped person is told the truth: replay"


def test_SEC_16_OPEN_ACCESS_one_person_filling_their_cap_never_spends_another_new_persons_allowance(sec16_factory):
    h = sec16_factory(declarations={}, **BIG_LIMIT)
    spend(h.ledger, VISITOR, h.caps.uid_lifetime_minor)
    h.ledger.calls.clear()

    h.as_user(NEWCOMER)
    assert h.intake().status_code == 201
    h.as_user(VISITOR)
    assert h.intake().status_code == 403


def test_SEC_16_OPEN_ACCESS_a_new_person_is_rate_limited_per_uid(sec16_factory):
    h = sec16_factory(declarations={}, rate_limit_requests=3)
    h.as_user(NEWCOMER)

    statuses = [h.client.get(concrete("/worlds/{world_id}/events")).status_code for _ in range(4)]

    assert 429 not in statuses[:3] and statuses[3] == 429, statuses
    h.as_user(VISITOR)
    assert h.client.get(concrete("/worlds/{world_id}/events")).status_code != 429, "another uid has its own window"


def test_SEC_16_OPEN_ACCESS_deployed_demo_is_replay_and_google_session_is_live(sec16_factory, monkeypatch):
    h = sec16_factory(declarations={}, **BIG_LIMIT)
    monkeypatch.setenv("K_SERVICE", "tilo-api")
    monkeypatch.setenv("TILO_JUDGE_LIVE", "1")
    from tilo_api import app, deps

    h.demo_session = True
    app.dependency_overrides[deps.get_current_principal] = lambda: deps.Principal(
        user_id=NEWCOMER, role="owner", demo_session=h.demo_session, full_session=not h.demo_session
    )
    demo = h.intake()
    assert demo.status_code == 201, demo.text
    assert h.router_modes[-1] == "replay", "SEC-15 access.py:158 carries verified demo_session into request state"

    h.demo_session = False
    google = h.intake()
    assert google.status_code == 201, google.text
    assert h.router_modes[-1] == "live"


def test_SEC_16_OPEN_ACCESS_the_kill_switch_still_forces_replay_for_a_new_person(sec16_factory):
    h = sec16_factory(declarations={}, **BIG_LIMIT)
    h.as_user(NEWCOMER)
    h.flags.set("replay_only", True, reason="OPEN-ACCESS test: NFR-24 outranks every person")

    assert h.me().json()["models"] == "replay"
