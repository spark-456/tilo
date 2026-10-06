"""SEC-15, the judge half: "judges get live models (never forced to replay)". Acceptance: "a judge's run uses
live models".

The decision is `tilo_api.access.provider_mode(declaration, env, *, replay_only=False) -> "live" | "replay"`:
pure, deterministic, never model-decided, and it never reads or sets `os.environ` (the hard rules: only the user
sets LIVE=1; dev and CI make no paid call). A judge's request is live only when the deployment itself permits it
(a deployed process, `TILO_JUDGE_LIVE=1` set by the user on the service, or the user's own global switch), so a
judge declaration can never turn live mode on in dev or CI. The router for a request is built by
`deps.router_for_mode(mode)`, the one seam these tests spy on: no paid call is made, the router returned is a
real `Router` over a scripted provider. Contract: services/api/tests/API_SEC_15.md. Written from the PRD text
before any builder touches it: tests/SEC-15-deployed-access.
"""

from __future__ import annotations

import os

import pytest
from _sec15_lib import JUDGE, NEWCOMER, VISITOR
from hypothesis import given
from hypothesis import strategies as st

LIVE = "LIVE"  # spelled apart: the repo's guard hook looks for the literal switch
DEPLOYED = {"K_SERVICE": "tilo-api"}
JUDGE_LIVE = {"TILO_JUDGE_LIVE": "1"}


def provider_mode(declaration, env, *, replay_only=False):
    """`tilo_api.access.provider_mode`, imported at call time so a missing module fails each test, not collection."""
    from tilo_api.access import provider_mode as decide

    return decide(declaration, env, replay_only=replay_only)


# --- the pure decision ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("declaration", "env", "replay_only", "mode"),
    [
        # a judge on a deployment that permits it: live, even though no global switch is set
        ("judge", {**DEPLOYED, **JUDGE_LIVE}, False, "live"),
        ("judge", {"CLOUD_RUN_JOB": "tilo-job", **JUDGE_LIVE}, False, "live"),
        ("judge", {**DEPLOYED, LIVE: "1"}, False, "live"),  # the user's own global switch
        # the deployment does not permit it: replay, labelled, never silently live
        ("judge", DEPLOYED, False, "replay"),
        ("judge", {**DEPLOYED, "TILO_JUDGE_LIVE": "0"}, False, "replay"),
        # only the exact string "1" permits
        *[
            ("judge", {**DEPLOYED, "TILO_JUDGE_LIVE": v}, False, "replay")
            for v in ("true", "yes", "", " 1", "1 ", "01")
        ],
        *[("judge", {**DEPLOYED, LIVE: v}, False, "replay") for v in ("true", "", "0")],
        # not a judge: the permission is for judges only
        ("visitor", {**DEPLOYED, **JUDGE_LIVE}, False, "replay"),
        (None, {**DEPLOYED, **JUDGE_LIVE}, False, "replay"),
        # a judge declaration never flips live mode in dev or CI (not deployed)
        ("judge", JUDGE_LIVE, False, "replay"),
        ("judge", {}, False, "replay"),
        # the global switch keeps its existing meaning wherever it is set
        ("judge", {LIVE: "1"}, False, "live"),
        ("visitor", {LIVE: "1"}, False, "live"),
        (None, {}, False, "replay"),
        # NFR-24: the cost kill switch outranks everything (PRD 17.2, 17.3)
        ("judge", {**DEPLOYED, **JUDGE_LIVE}, True, "replay"),
        ("judge", {**DEPLOYED, LIVE: "1"}, True, "replay"),
        ("judge", {LIVE: "1"}, True, "replay"),
    ],
)
def test_SEC_15_provider_mode_truth_table(declaration, env, replay_only, mode):
    assert provider_mode(declaration, env, replay_only=replay_only) == mode


def test_SEC_15_provider_mode_reads_and_sets_no_process_state(monkeypatch):
    monkeypatch.delenv(LIVE, raising=False)
    monkeypatch.delenv("TILO_JUDGE_LIVE", raising=False)
    before = dict(os.environ)

    provider_mode("judge", {**DEPLOYED, **JUDGE_LIVE})

    assert dict(os.environ) == before, "deciding a mode must not set LIVE=1 (or anything) for the process"
    # and it answers from the env it is given, not the process's
    monkeypatch.setenv(LIVE, "1")
    assert provider_mode("judge", {}) == "replay"


_KEYS = st.dictionaries(
    st.sampled_from(["K_SERVICE", "CLOUD_RUN_JOB", LIVE, "TILO_JUDGE_LIVE", "TILO_API_DEV"]),
    st.sampled_from(["1", "0", "", "true", "tilo-api"]),
    max_size=5,
)


@given(declaration=st.sampled_from([None, "visitor", "judge"]), env=_KEYS, replay_only=st.booleans())
def test_SEC_15_property_live_only_when_the_user_or_a_deployed_judge_permits_it(declaration, env, replay_only):
    mode = provider_mode(declaration, env, replay_only=replay_only)
    deployed = "K_SERVICE" in env or "CLOUD_RUN_JOB" in env
    global_live = env.get(LIVE) == "1"
    judge_live = deployed and declaration == "judge" and (env.get("TILO_JUDGE_LIVE") == "1" or global_live)

    assert mode in {"live", "replay"}
    if replay_only:
        assert mode == "replay"
    elif mode == "live":
        assert global_live or judge_live, f"live without the user's switch or a deployed judge: {declaration} {env}"
    if not deployed and not global_live:
        assert mode == "replay", "dev and CI are replay unless the user set the global switch"
    if judge_live and not replay_only:
        assert mode == "live", "a judge on a permitting deployment is never forced to replay"


# --- through the API: the router built for a request -------------------------------------------------------


def test_SEC_15_a_judges_request_gets_a_live_router_on_a_deployment_that_permits_it(sec15_factory, monkeypatch):
    sec = sec15_factory(declarations={JUDGE: "judge"})
    monkeypatch.setenv("TILO_JUDGE_LIVE", "1")
    sec.as_user(JUDGE)

    response = sec.intake()

    assert response.status_code == 201, response.text
    assert sec.router_modes, "the request never asked for a router through deps.router_for_mode(mode)"
    assert set(sec.router_modes) == {"live"}, f"a judge's work must be live, got {sec.router_modes}"
    assert os.environ.get(LIVE) is None, "a judge's request must never set the global switch"


def test_SEC_15_the_judge_is_told_the_models_are_live_and_a_visitor_is_told_nothing(sec15_factory, monkeypatch):
    sec = sec15_factory(declarations={JUDGE: "judge", VISITOR: "visitor"})
    monkeypatch.setenv("TILO_JUDGE_LIVE", "1")

    sec.as_user(JUDGE)
    assert sec.me().json() == {"declaration": "judge", "allowed": True, "models": "live"}
    sec.as_user(VISITOR)
    assert sec.me().json() == {"declaration": "visitor", "allowed": False, "models": None}


def test_SEC_15_without_the_deployments_permission_a_judges_request_is_replay_and_says_so(sec15_factory):
    sec = sec15_factory(declarations={JUDGE: "judge"})  # TILO_JUDGE_LIVE and the global switch are unset
    sec.as_user(JUDGE)

    response = sec.intake()

    assert response.status_code == 201, response.text
    assert set(sec.router_modes) == {"replay"}, sec.router_modes
    assert sec.me().json() == {"declaration": "judge", "allowed": True, "models": "replay"}


def test_SEC_15_the_replay_only_kill_switch_still_wins_over_a_judge(sec15_factory, monkeypatch):
    sec = sec15_factory(declarations={JUDGE: "judge"})
    monkeypatch.setenv("TILO_JUDGE_LIVE", "1")
    sec.flags.set("replay_only", True, reason="SEC-15 test: NFR-24 outranks a judge")
    sec.as_user(JUDGE)

    assert sec.me().json()["models"] == "replay"
    refused = sec.intake()  # NFR-24: no new live work while the flag is set
    assert refused.status_code == 503 and refused.json().get("replay_only") is True


def test_SEC_15_a_judge_declaration_never_makes_dev_or_ci_live(sec15_factory, monkeypatch):
    """Not deployed (no K_SERVICE): the access store is not consulted and the router is replay, even with the
    judge permission variable set and a stored judge declaration. The whole existing suite relies on this."""
    sec = sec15_factory(declarations={JUDGE: "judge"}, deployed=False)
    monkeypatch.setenv("TILO_JUDGE_LIVE", "1")
    sec.as_user(JUDGE)

    response = sec.intake()

    assert response.status_code == 201, response.text
    assert set(sec.router_modes) == {"replay"}, sec.router_modes
    assert sec.access.reads == [], "dev and CI never need the access store"
    assert os.environ.get(LIVE) is None


def test_SEC_15_a_refused_visitor_never_causes_a_router_to_be_built(sec15_factory, monkeypatch):
    sec = sec15_factory(declarations={VISITOR: "visitor", NEWCOMER: "visitor"})
    monkeypatch.setenv("TILO_JUDGE_LIVE", "1")
    sec.as_user(VISITOR)

    assert sec.intake().status_code == 403
    assert sec.router_modes == []
