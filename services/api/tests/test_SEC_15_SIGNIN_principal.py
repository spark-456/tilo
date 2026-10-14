"""SEC-15 / SIGNIN (PRD 6 platform row "Firebase Authentication: Google sign-in and anonymous demo sessions"; PRD
supplement SEC-15; PRD R-06; BQ-XWORLD-10): tilo-api turns `Authorization: Bearer <Firebase ID token>` into the
`deps.Principal` of the request, fails closed with 401 on anything else, and keeps dev mode and the SEC-15 gate as
they are. Written before any implementation.

FOUND, NOT AS BRIEFED: there is no `resolve_principal` in this base (the cloud lane's PROD-WIRE seam, issue #522, is
not merged), so these tests pin the production behaviour of `deps.get_current_principal` itself, which is that seam
until it exists: a plain FastAPI dependency that takes the request. If PROD-WIRE lands first and `get_current_principal`
delegates to `resolve_principal(request)`, nothing here changes. Two consequences the builder must meet:

- `get_current_principal` needs the request (it reads `Authorization` and `X-Tilo-Channel`). `access.AccessGate._decide`
  currently calls `overrides.get(deps.get_current_principal, deps.get_current_principal)()` with no
  argument, so the gate
  has to hand the request (or its scope) to the resolver; the end-to-end tests below go through the real gate.
- `deps.get_firebase_verifier()` (new, like `deps.get_app_check_verifier`): returns an object with
  `verify(token) -> Mapping`, raising `tilo_api.firebase_auth.TokenRefused` for a token it refuses. Production default:
  Google's keys for the API's own project (`TILO_FIRESTORE_PROJECT`, else `GOOGLE_CLOUD_PROJECT`); no
  project, or dev mode,
  gets a verifier that refuses everything with no network call. Tests override it with a real
  `FirebaseIdTokenVerifier` over an injected key fetch.

Channel (AMBIGUITY, BQ-SIGNIN-3: the PRD says only "channel web or mobile_web from the request"): the header
`X-Tilo-Channel: mobile_web` selects `mobile_web`; absent or any other value (including "email") is `web`. Both are web
sign-in channels with identical authority (`cards._WEB_CHANNELS`), so a client hint cannot widen anything; an `email`
principal can only come from a signed link, never from this header.

No network (a socket guard fails any attempt), no model, no paid call; fake tokens are assembled at runtime.
"""

from __future__ import annotations

import dataclasses
import socket
import time

import pytest
from _signin_lib import NOW, PROJECT, FailingFetch, Fetch, _b64, _claims, _key, _token
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from tilo_api import access, deps, dev, firebase_auth
from tilo_api import app as tilo_app

ANON_SUB = "anon" + "Q7" * 12
GOOGLE_SUB = "uid" + "A1" * 10
ENV_CLEAR = (
    "K_SERVICE", "CLOUD_RUN_JOB", "LIVE", "TILO_API_DEV", "TILO_JUDGE_LIVE", "TILO_APPCHECK_ENFORCE",
    "TILO_FIRESTORE_PROJECT", "GOOGLE_CLOUD_PROJECT",
)  # fmt: skip


@pytest.fixture(scope="module")
def signer() -> rsa.RSAPrivateKey:
    return _key()


@pytest.fixture(autouse=True)
def _clean_env_and_no_network(monkeypatch):
    for name in ENV_CLEAR:
        monkeypatch.delenv(name, raising=False)

    real_connect = socket.socket.connect

    def guarded(self, address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) else ""
        if host not in ("127.0.0.1", "::1", "localhost", "0.0.0.0"):  # noqa: S104  (the event loop's own socketpair)
            raise AssertionError(f"SIGNIN: nothing may open a network connection (to {host!r})")
        return real_connect(self, address, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", guarded)
    yield
    tilo_app.dependency_overrides.clear()


def verifier_for(signer, *, fetch=None, wall: float | None = None) -> firebase_auth.FirebaseIdTokenVerifier:
    return firebase_auth.FirebaseIdTokenVerifier(
        PROJECT,
        fetch=fetch or Fetch({"k1": signer.public_key()}),
        clock=time.monotonic,
        wall=(lambda: wall) if wall is not None else (lambda: NOW),
    )


def whoami_app(verifier) -> FastAPI:
    """The production `get_current_principal`, behind a one-route app that echoes what it resolved."""
    app = FastAPI()

    @app.get("/whoami")
    def whoami(principal: deps.Principal = Depends(deps.get_current_principal)) -> dict:  # noqa: B008
        return dataclasses.asdict(principal)

    if verifier is not None:
        app.dependency_overrides[deps.get_firebase_verifier] = lambda: verifier
    return app


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def deployed(monkeypatch):
    monkeypatch.setenv("K_SERVICE", "tilo-api")


# --- the Principal a verified token becomes --------------------------------------------------------------------


def test_SEC_15_SIGNIN_a_google_sign_in_becomes_a_full_session_owner(signer, deployed):
    client = TestClient(whoami_app(verifier_for(signer)))
    reply = client.get("/whoami", headers=bearer(_token(signer)))
    assert reply.status_code == 200, reply.text
    who = reply.json()
    assert who["user_id"] == firebase_auth.user_id_for(GOOGLE_SUB)
    assert who["role"] == "owner"
    assert who["channel"] == "web"
    assert who["full_session"] is True


def test_SEC_15_SIGNIN_an_anonymous_demo_session_is_a_principal_but_never_a_full_session(signer, deployed):
    client = TestClient(whoami_app(verifier_for(signer)))
    reply = client.get("/whoami", headers=bearer(_token(signer, provider="anonymous", sub=ANON_SUB)))
    assert reply.status_code == 200, reply.text
    who = reply.json()
    assert who["user_id"] == firebase_auth.user_id_for(ANON_SUB)
    assert who["full_session"] is False
    assert who["role"] == "owner"


def test_SEC_15_SIGNIN_the_same_person_is_always_the_same_user_and_two_people_never_are(signer, deployed):
    client = TestClient(whoami_app(verifier_for(signer)))
    one = client.get("/whoami", headers=bearer(_token(signer))).json()["user_id"]
    again = client.get("/whoami", headers=bearer(_token(signer, iat=NOW - 30))).json()["user_id"]
    other = client.get("/whoami", headers=bearer(_token(signer, sub=GOOGLE_SUB + "x"))).json()["user_id"]
    assert one == again != other


@pytest.mark.parametrize(
    ("header", "channel"),
    [
        ("mobile_web", "mobile_web"),
        ("web", "web"),
        ("email", "web"),
        ("Mobile_Web", "web"),
        ("", "web"),
        ("x" * 500, "web"),
    ],
)
def test_SEC_15_SIGNIN_channel_is_web_or_mobile_web_from_the_request_and_never_email(signer, deployed, header, channel):
    client = TestClient(whoami_app(verifier_for(signer)))
    reply = client.get("/whoami", headers={**bearer(_token(signer)), "X-Tilo-Channel": header})
    assert reply.status_code == 200
    assert reply.json()["channel"] == channel


def test_SEC_15_SIGNIN_nothing_in_a_request_sets_full_session_or_the_user(signer, deployed):
    """A body, query, cookie or header claiming to be someone else or a full session changes nothing."""
    client = TestClient(whoami_app(verifier_for(signer)))
    headers = {
        **bearer(_token(signer, provider="anonymous", sub=ANON_SUB)),
        "X-Tilo-Full-Session": "1", "X-Full-Session": "true", "X-User-Id": "u_dev_owner", "X-Tilo-User": "u_victim",
        "X-Forwarded-User": "u_victim", "X-Goog-Authenticated-User-Id": "accounts.google.com:1",
        "X-Goog-Authenticated-User-Email": "accounts.google.com:owner@example.test",
    }  # fmt: skip
    reply = client.get("/whoami?full_session=true&user_id=u_victim", headers=headers, cookies={"full_session": "1"})
    who = reply.json()
    assert who["full_session"] is False
    assert who["user_id"] == firebase_auth.user_id_for(ANON_SUB)


# --- 401 matrix: everything else fails closed ------------------------------------------------------------------


def _hs256(signer) -> str:
    return _token(signer, alg="HS256")  # an RS256 signature under an HS256 label


def _alg_none() -> str:
    import json  # noqa: PLC0415

    return _b64(json.dumps({"alg": "none", "kid": "k1"}).encode()) + "." + _b64(json.dumps(_claims()).encode()) + "."


def refused_tokens(signer) -> dict[str, str]:
    other = _key()
    return {
        "expired": _token(signer, exp=NOW - 3600),
        "wrong_aud": _token(signer, aud="someone-else"),
        "wrong_iss": _token(signer, iss="https://securetoken.google.com/someone-else"),
        "signed_by_another_key": _token(other),
        "unknown_kid": _token(signer, kid="nope"),
        "alg_none": _alg_none(),
        "alg_hs256": _hs256(signer),
        "email_not_verified": _token(signer, email_verified=False),
        "password_provider": _token(signer, firebase={"sign_in_provider": "password"}),
        "custom_provider": _token(signer, firebase={"sign_in_provider": "custom"}),
        "no_sub": _token(signer, sub=...),
        "auth_time_in_future": _token(signer, auth_time=NOW + 9999),
        "too_long": "a." + "b" * 20000 + ".c",
        "garbage": "not-a-token",
        "an_app_check_style_token": _token(
            signer, iss="https://firebaseappcheck.googleapis.com/123", aud=["projects/1"]
        ),
    }  # fmt: skip


def test_SEC_15_SIGNIN_every_refused_token_is_a_401_with_a_fixed_body(signer, deployed):
    for name, token in refused_tokens(signer).items():
        client = TestClient(whoami_app(verifier_for(signer)))
        reply = client.get("/whoami", headers=bearer(token))
        assert reply.status_code == 401, name
        assert token not in reply.text and "someone-else" not in reply.text, name
        assert set(reply.json()) == {"detail"}, name
        assert isinstance(reply.json()["detail"], str), name


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": ""},
        {"Authorization": "Bearer"},
        {"Authorization": "Bearer "},
        {"Authorization": "Bearer    "},
        {"Authorization": "Basic dXNlcjpwYXNz"},
        {"Authorization": "Token abc.def.ghi"},
        {"Authorization": "abc.def.ghi"},
        {"Authorization": "Bearer a b c"},
        {"Authorization": "Bearer a.b.c, Bearer d.e.f"},
        {"X-Firebase-AppCheck": "a.b.c"},
        {"Cookie": "session=a.b.c; token=a.b.c"},
        {"X-Dev-User": "u_dev_owner"},
        {"X-Dev-Owner": "1"},
        {"X-Tilo-Dev": "1"},
        {"X-User-Id": "u_dev_owner"},
        {"X-Tilo-User": "u_dev_owner"},
        {"X-Forwarded-User": "u_dev_owner"},
        {"X-Goog-Authenticated-User-Email": "accounts.google.com:owner@example.test"},
        {"X-Goog-Authenticated-User-Id": "accounts.google.com:1"},
    ],
)
def test_SEC_15_SIGNIN_production_never_trusts_a_missing_malformed_or_dev_style_credential(signer, deployed, headers):
    client = TestClient(whoami_app(verifier_for(signer)))
    reply = client.get("/whoami", headers=headers)
    assert reply.status_code == 401, reply.text


def test_SEC_15_SIGNIN_a_valid_token_is_read_from_the_authorization_header_only(signer, deployed):
    client = TestClient(whoami_app(verifier_for(signer)))
    token = _token(signer)
    for kwargs in (
        {"params": {"access_token": token, "token": token, "id_token": token}},
        {"headers": {"X-Firebase-AppCheck": token, "X-Id-Token": token, "X-Tilo-Token": token}},
        {"cookies": {"token": token, "id_token": token, "__session": token}},
    ):
        assert client.get("/whoami", **kwargs).status_code == 401, kwargs


def test_SEC_15_SIGNIN_a_dev_flag_in_a_deployed_process_trusts_nothing(signer, monkeypatch):
    monkeypatch.setenv("K_SERVICE", "tilo-api")
    monkeypatch.setenv("TILO_API_DEV", "1")
    client = TestClient(whoami_app(verifier_for(signer)))
    assert client.get("/whoami").status_code == 401
    assert client.get("/whoami", headers={"X-User-Id": "u_dev_owner"}).status_code == 401
    # and a real token still works: the flag neither opens nor closes the verified path
    assert client.get("/whoami", headers=bearer(_token(signer))).status_code == 200


def test_SEC_15_SIGNIN_unavailable_keys_fail_closed_with_401_not_500(signer, deployed):
    fetch = FailingFetch()
    client = TestClient(whoami_app(verifier_for(signer, fetch=fetch)), raise_server_exceptions=False)
    reply = client.get("/whoami", headers=bearer(_token(signer)))
    assert reply.status_code == 401
    assert fetch.calls == 1


@pytest.mark.parametrize(
    "error", [RuntimeError("boom"), KeyError("kid"), ValueError("x"), OSError("net"), TimeoutError()]
)
def test_SEC_15_SIGNIN_a_verifier_that_blows_up_is_still_a_401(deployed, error):
    class Exploding:
        def verify(self, token):
            raise error

    client = TestClient(whoami_app(Exploding()), raise_server_exceptions=False)
    assert client.get("/whoami", headers=bearer("a.b.c")).status_code == 401


def test_SEC_15_SIGNIN_a_verifier_that_answers_with_something_odd_is_a_401_not_a_principal(deployed):
    class Odd:
        def __init__(self, value):
            self.value = value

        def verify(self, token):
            return self.value

    for value in (None, {}, [], "claims", {"sub": ""}, {"sub": 5}, {"sub": "x", "firebase": "google.com"}):
        client = TestClient(whoami_app(Odd(value)), raise_server_exceptions=False)
        assert client.get("/whoami", headers=bearer("a.b.c")).status_code == 401, value


def test_SEC_15_SIGNIN_with_no_project_configured_the_default_verifier_refuses_without_any_call(deployed):
    verifier = deps.get_firebase_verifier()
    with pytest.raises(firebase_auth.TokenRefused):
        verifier.verify("a.b.c")  # the autouse socket guard fails the test if this reached for the network
    client = TestClient(whoami_app(None), raise_server_exceptions=False)
    assert client.get("/whoami", headers=bearer("a.b.c")).status_code == 401


def test_SEC_15_SIGNIN_dev_mode_default_verifier_makes_no_call(monkeypatch):
    monkeypatch.setenv("TILO_API_DEV", "1")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", PROJECT)
    with pytest.raises(firebase_auth.TokenRefused):
        deps.get_firebase_verifier().verify("a.b.c")


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    value=st.text(alphabet=st.characters(min_codepoint=32, max_codepoint=126), max_size=300),
    scheme=st.sampled_from(["Bearer ", "bearer ", "BEARER ", "", "Bearer\t", "Bearer  "]),
)
def test_SEC_15_SIGNIN_property_no_authorization_header_value_gets_in_or_crashes_the_api(
    signer, monkeypatch, value, scheme
):
    monkeypatch.setenv("K_SERVICE", "tilo-api")
    client = TestClient(whoami_app(verifier_for(signer)), raise_server_exceptions=False)
    reply = client.get("/whoami", headers={"Authorization": scheme + value})
    assert reply.status_code == 401, (scheme, value)


# --- dev mode stays as it was ----------------------------------------------------------------------------------


def test_SEC_15_SIGNIN_dev_mode_still_signs_in_the_dev_owner_with_no_token_and_no_google_call(signer):
    fetch = Fetch({"k1": signer.public_key()})
    app = whoami_app(verifier_for(signer, fetch=fetch))
    dev.install(app, {})  # the dev principal overrides the production dependency
    client = TestClient(app, base_url=f"http://localhost:{dev.PORT}")
    who = client.get("/whoami").json()
    assert who["user_id"] == dev.DEV_OWNER and who["full_session"] is True
    # a token, valid or garbage, is not looked at in dev mode: no key fetch, same principal
    for header in (bearer("garbage"), bearer(_token(signer, provider="anonymous", sub=ANON_SUB))):
        assert client.get("/whoami", headers=header).json()["user_id"] == dev.DEV_OWNER
    assert fetch.calls == 0


def test_SEC_15_SIGNIN_a_dev_owner_token_is_not_obtainable_by_naming_it_in_a_firebase_uid(signer, deployed):
    client = TestClient(whoami_app(verifier_for(signer)))
    for sub in ("dev_owner", "u_dev_owner", "DEV_OWNER"):
        who = client.get("/whoami", headers=bearer(_token(signer, sub=sub))).json()
        assert who["user_id"] != dev.DEV_OWNER


# --- end to end through the real app: the SEC-15 gate still decides -------------------------------------------


@pytest.fixture
def real_app(signer, monkeypatch):
    """`tilo_api.app` as deployed: K_SERVICE set, sign-in via the verifier seam, an in-memory access store and Store."""
    monkeypatch.setenv("K_SERVICE", "tilo-api")
    store = access.InMemoryAccessStore()
    tilo_app.dependency_overrides[deps.get_firebase_verifier] = lambda: verifier_for(signer)
    tilo_app.dependency_overrides[deps.get_access_store] = lambda: store
    tilo_app.dependency_overrides[deps.get_store] = lambda: deps.Store()
    with TestClient(tilo_app, raise_server_exceptions=False) as client:
        client.store = store  # type: ignore[attr-defined]
        yield client


def test_SEC_15_SIGNIN_signed_out_requests_to_the_real_app_are_401_and_the_probes_stay_open(real_app):
    assert real_app.get("/health").status_code == 200
    assert real_app.get("/healthz").status_code == 200
    for path in ("/access", "/worlds", "/cards"):
        assert real_app.get(path).status_code == 401, path
    assert real_app.get("/worlds", headers=bearer("a.b.c")).status_code == 401


def test_SEC_15_SIGNIN_a_google_sign_in_with_no_declaration_is_asked_to_declare(real_app, signer):
    headers = bearer(_token(signer))
    assert real_app.get("/access", headers=headers).json()["declaration"] is None
    reply = real_app.get("/worlds", headers=headers)
    assert reply.status_code == 403
    assert reply.json()["code"] == "declaration_required"


def test_SEC_15_SIGNIN_an_anonymous_demo_session_can_declare_and_is_gated_by_the_same_rules(real_app, signer):
    headers = bearer(_token(signer, provider="anonymous", sub=ANON_SUB))
    assert real_app.get("/worlds", headers=headers).json()["code"] == "declaration_required"
    reply = real_app.post("/access/declaration", json={"declaration": "visitor"}, headers=headers)
    assert reply.status_code == 200, reply.text
    assert real_app.store.get(firebase_auth.user_id_for(ANON_SUB)) == "visitor"
    refused = real_app.get("/worlds", headers=headers)
    assert refused.status_code == 403 and refused.json()["code"] == "under_construction"
    assert real_app.post("/access/declaration", json={"declaration": "judge"}, headers=headers).status_code == 409


def test_SEC_15_SIGNIN_a_judge_signed_in_with_google_gets_through_the_gate(real_app, signer):
    headers = bearer(_token(signer))
    assert real_app.post("/access/declaration", json={"declaration": "judge"}, headers=headers).status_code == 200
    assert real_app.store.get(firebase_auth.user_id_for(GOOGLE_SUB)) == "judge"
    reply = real_app.get("/worlds", headers=headers)
    assert reply.status_code == 200, reply.text
    access_view = real_app.get("/access", headers=headers).json()
    assert access_view["declaration"] == "judge" and access_view["allowed"] is True


def test_SEC_15_SIGNIN_a_declaration_belongs_to_the_verified_uid_not_to_anything_the_request_names(real_app, signer):
    mine = bearer(_token(signer))
    real_app.post(
        "/access/declaration",
        json={"declaration": "judge"},
        headers={**mine, "X-User-Id": "u_victim", "X-Tilo-User": "u_victim"},
    )
    assert real_app.store.get("u_victim") is None
    assert real_app.store.get(firebase_auth.user_id_for(GOOGLE_SUB)) == "judge"
    someone_else = bearer(_token(signer, sub="someone" + "Z" * 10))
    assert real_app.get("/worlds", headers=someone_else).json()["code"] == "declaration_required"


def test_SEC_15_SIGNIN_an_expired_token_is_a_401_at_the_real_app_even_for_a_declared_judge(real_app, signer):
    real_app.store.declare(firebase_auth.user_id_for(GOOGLE_SUB), "judge")
    reply = real_app.get("/worlds", headers=bearer(_token(signer, exp=NOW - 3600)))
    assert reply.status_code == 401


def test_SEC_15_SIGNIN_signing_in_does_not_make_a_gated_route_open_to_a_no_op_token_swap(real_app, signer):
    """A token for uid A with a body or header naming uid B: the judge A declared does not make B a judge."""
    real_app.store.declare(firebase_auth.user_id_for(GOOGLE_SUB), "judge")
    other = _token(signer, sub="mallory" + "M" * 10)
    reply = real_app.get("/worlds", headers={**bearer(other), "X-User-Id": firebase_auth.user_id_for(GOOGLE_SUB)})
    assert reply.status_code == 403


def test_SEC_15_SIGNIN_the_gate_has_the_same_public_routes_as_before():
    assert access.PUBLIC_ROUTES == {
        ("GET", "/health"),
        ("GET", "/healthz"),
        ("GET", "/health/deps"),  # Supervisor SEC15-HEALTH: public configuration booleans/fixed kinds only.
        ("GET", "/healthz/deps"),  # Supervisor SEC15-HEALTH: leak-free alias of the public configuration inventory.
        ("GET", "/access"),
        ("POST", "/access/declaration"),
        ("POST", "/internal/schedules/tick"),
        # ADR-0042: default-off meter routes check their own OIDC token, audience, caller and nonce.
        ("POST", "/internal/meeting-voice/reserve"),
        ("POST", "/internal/meeting-voice/close"),
    }, "signing in adds no unreviewed public route: a new one is an owner decision"


def test_SEC_15_SIGNIN_the_real_app_makes_no_key_fetch_when_nobody_sends_a_token(signer, monkeypatch):
    monkeypatch.setenv("K_SERVICE", "tilo-api")
    fetch = Fetch({"k1": signer.public_key()})
    tilo_app.dependency_overrides[deps.get_firebase_verifier] = lambda: verifier_for(signer, fetch=fetch)
    tilo_app.dependency_overrides[deps.get_access_store] = lambda: access.InMemoryAccessStore()
    with TestClient(tilo_app, raise_server_exceptions=False) as client:
        for path in ("/health", "/healthz", "/worlds", "/access"):
            client.get(path)
    assert fetch.calls == 0
