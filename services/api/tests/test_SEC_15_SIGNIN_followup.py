"""SEC-15 / SIGNIN follow-up (security review, BQ-SIGNIN-9, BQ-SIGNIN-10): a tenant token is refused, an integer too
large for a float is a refusal and not a crash, the principal is verified ONCE per gated request, an anonymous demo
session gets replay models only whatever `TILO_JUDGE_LIVE` says, and the bootstrap helper prints the id the API gives a
Firebase uid. Tokens are made at runtime (`_signin_lib`); no network."""

from __future__ import annotations

import importlib.util
import pathlib
import socket

import pytest
from _sec15_lib import VISITOR
from _sec16_lib import JUDGE_A
from _signin_lib import NOW, PROJECT, Fetch, _key, _token
from fastapi.testclient import TestClient
from tilo_api import app as tilo_app
from tilo_api import deps, firebase_auth

GOOGLE_SUB = "uid" + "A1" * 10
ANON_SUB = "anon" + "Q7" * 12
ENV_CLEAR = (
    "K_SERVICE", "CLOUD_RUN_JOB", "LIVE", "TILO_API_DEV", "TILO_JUDGE_LIVE", "TILO_APPCHECK_ENFORCE",
    "TILO_FIRESTORE_PROJECT", "GOOGLE_CLOUD_PROJECT",
)  # fmt: skip


@pytest.fixture(scope="module")
def signer():
    return _key()


@pytest.fixture(autouse=True)
def _clean_env_and_no_network(monkeypatch):
    for name in ENV_CLEAR:
        monkeypatch.delenv(name, raising=False)
    real_connect = socket.socket.connect

    def guarded(self, address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) else ""
        if host not in ("127.0.0.1", "::1", "localhost", "0.0.0.0"):  # noqa: S104
            raise AssertionError(f"SIGNIN: nothing may open a network connection (to {host!r})")
        return real_connect(self, address, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", guarded)
    yield
    tilo_app.dependency_overrides.clear()


def verifier(signer):
    return firebase_auth.FirebaseIdTokenVerifier(
        PROJECT, fetch=Fetch({"k1": signer.public_key()}), clock=lambda: 0.0, wall=lambda: NOW
    )


# --- a tenant token, an integer too large for a float ------------------------------------------------------------


@pytest.mark.parametrize("provider", ["google.com", "anonymous"])
@pytest.mark.parametrize("tenant", ["tenant-1", "", None, 7])
def test_SEC_15_SIGNIN_followup_a_token_carrying_a_tenant_is_refused(signer, provider, tenant):
    token = _token(signer, provider=provider, firebase={"sign_in_provider": provider, "tenant": tenant})
    with pytest.raises(firebase_auth.TokenRefused) as info:
        verifier(signer).verify(token)
    assert info.value.code == "tenant_not_allowed"


@pytest.mark.parametrize("claim", ["exp", "iat", "auth_time", "nbf"])
@pytest.mark.parametrize("value", [10**400, -(10**400)])
def test_SEC_15_SIGNIN_followup_an_integer_too_large_for_a_float_is_a_refusal_not_a_crash(signer, claim, value):
    with pytest.raises(firebase_auth.TokenRefused) as info:
        verifier(signer).verify(_token(signer, **{claim: value}))
    assert info.value.code in {"expired", "bad_time", "not_yet_valid"}


# --- verified once per gated request --------------------------------------------------------------------------------


class Counting:
    def __init__(self, inner):
        self.inner, self.calls = inner, 0

    def verify(self, token):
        self.calls += 1
        return self.inner.verify(token)


def test_SEC_15_SIGNIN_followup_a_gated_request_verifies_its_token_once(signer, monkeypatch):
    monkeypatch.setenv("K_SERVICE", "tilo-api")
    counting = Counting(verifier(signer))
    tilo_app.dependency_overrides[deps.get_firebase_verifier] = lambda: counting
    tilo_app.dependency_overrides[deps.get_store] = lambda: deps.Store()
    headers = {"Authorization": f"Bearer {_token(signer)}"}
    with TestClient(tilo_app, raise_server_exceptions=False) as client:
        reply = client.get("/worlds", headers=headers)
        assert reply.status_code == 200, reply.text
        assert counting.calls == 1, "the gate verified, and the route's own dependency reused the result"
        client.get("/worlds", headers=headers)
        assert counting.calls == 2, "a new request verifies again: nothing is kept between requests"


def test_SEC_15_SIGNIN_followup_a_public_route_still_verifies_for_itself(signer, monkeypatch):
    monkeypatch.setenv("K_SERVICE", "tilo-api")
    counting = Counting(verifier(signer))
    tilo_app.dependency_overrides[deps.get_firebase_verifier] = lambda: counting
    with TestClient(tilo_app, raise_server_exceptions=False) as client:
        assert client.get("/access", headers={"Authorization": f"Bearer {_token(signer)}"}).status_code == 200
    assert counting.calls == 1


def test_SEC_15_SIGNIN_followup_a_request_cannot_supply_the_cached_principal(signer, monkeypatch):
    """The reuse is scope state the gate sets; nothing a client sends (header, query, cookie) can stand in for it."""
    monkeypatch.setenv("K_SERVICE", "tilo-api")
    tilo_app.dependency_overrides[deps.get_firebase_verifier] = lambda: verifier(signer)
    with TestClient(tilo_app, raise_server_exceptions=False) as client:
        headers = {"principal": "u_victim", "X-Principal": "u_victim", "state": "x"}
        assert client.get("/worlds?principal=u_victim", headers=headers).status_code == 401


# --- a demo session is replay only ----------------------------------------------------------------------------------


def test_SEC_15_SIGNIN_followup_principal_flags_google_is_full_and_anonymous_is_a_demo_session():
    google = firebase_auth.principal_from_claims(
        {"sub": GOOGLE_SUB, "firebase": {"sign_in_provider": "google.com"}}, channel="web"
    )
    anonymous = firebase_auth.principal_from_claims(
        {"sub": ANON_SUB, "firebase": {"sign_in_provider": "anonymous"}}, channel="web"
    )
    assert (google.full_session, google.demo_session) == (True, False)
    assert (anonymous.full_session, anonymous.demo_session) == (False, True)


def test_SEC_15_SIGNIN_followup_an_anonymous_judge_gets_replay_models_even_with_judge_live(sec16_factory):
    h = sec16_factory(declarations={JUDGE_A: "judge", VISITOR: "visitor"}, rate_limit_requests=1_000)
    assert h.me().json()["models"] == "live", "a Google judge on a TILO_JUDGE_LIVE deployment is live, as before"
    tilo_app.dependency_overrides[deps.get_current_principal] = lambda: deps.Principal(
        user_id=JUDGE_A, role="owner", demo_session=True
    )
    view = h.me().json()
    assert view["declaration"] == "judge" and view["allowed"] is True
    assert view["models"] == "replay", "an anonymous demo session never runs on live models"


def test_SEC_15_SIGNIN_followup_a_google_judge_principal_keeps_live_models(sec16_factory):
    h = sec16_factory(declarations={JUDGE_A: "judge"}, rate_limit_requests=1_000)
    tilo_app.dependency_overrides[deps.get_current_principal] = lambda: deps.Principal(
        user_id=JUDGE_A, role="owner", full_session=True
    )
    assert h.me().json()["models"] == "live"


# --- the bootstrap helper ------------------------------------------------------------------------------------------


def test_SEC_15_SIGNIN_followup_the_bootstrap_helper_prints_the_user_id_the_api_gives_a_firebase_uid(capsys):
    path = pathlib.Path(__file__).resolve().parents[3] / "scripts" / "signin_user_id.py"
    spec = importlib.util.spec_from_file_location("signin_user_id", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.main(["signin_user_id.py", GOOGLE_SUB]) == 0
    assert capsys.readouterr().out.strip() == firebase_auth.user_id_for(GOOGLE_SUB)
    assert module.main(["signin_user_id.py"]) == 2
    assert module.main(["signin_user_id.py", "x" * 129]) == 2
