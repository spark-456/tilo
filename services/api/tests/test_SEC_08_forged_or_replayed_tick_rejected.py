"""SEC-08 (PRD 16.4: "Signed webhooks and signed email links" -> "Forged or replayed requests rejected"; PRD 6.3 Cloud
Scheduler; infra/ACCESS.md) for the signed inbound surface of tilo-api, against Google's REAL RS256 verifier.

Signed inbound surfaces of tilo-api, enumerated from the code (`access.PUBLIC_ROUTES`, the OpenAPI route table and a
grep of `hmac`, `compare_digest` and OIDC users under services/api/src, 2026-10-07):

1. `POST /internal/schedules/tick`: Cloud Scheduler's Google-signed OIDC token, checked by
   `tilo_api.schedules.GoogleOidcVerifier` (google-auth, RS256, certificates fetched through an injected transport).
   This is the ONLY route the access gate lets through without a session.
2. Not webhooks, listed so the enumeration is complete: `GET /access` and `POST /access/declaration` are public to the
   access gate but need a signed-in principal (asserted below); every other route needs the principal; `GET|POST
   /share/{token}` is a bearer link looked up by hash that still needs the named person signed in (SEC-06,
   test_FR_HIL_* share tests), and the worlds-list pagination cursor is an HMAC-signed query value
   (`worlds_list.py`, covered by its own tests). Neither is a signed webhook or a signed email link.
3. The signed email links (FR-CHN-07) are verified in tilo-channels, not here; see
   services/channels/tests/test_SEC_08_forged_or_replayed_requests_rejected.py.

Acceptance claim: a forged signature, a tampered payload, a missing signature, an expired token and a replayed
request are rejected and start nothing (no world, no schedule change, no clock move); a correctly signed, fresh
request from the one allowed account is accepted (positive control).

Default where the PRD is silent: replaying a captured, still-valid tick is not an error (Cloud Scheduler retries by
design); it starts nothing new (one run per slot, FR-AGT-14). A capture past its `exp` is rejected (401).
Throwaway RSA keys are made at run time and never written anywhere; the certificate "fetch" is an in-process fake.
"""

from __future__ import annotations

import base64
import datetime as dt
import json
import time
from typing import Any

import pytest
from _fr_agt_14_lib import (
    API_SA,
    AUDIENCE,
    GMAIL_SA,
    GOOGLE_ISSUER,
    MON_0330Z,
    SCHEDULE_SA,
    TASKS_SA,
    TICK,
    WEEK,
    SchedApi,
    l3_budget_policy,
)
from _sec15_lib import route_table
from google.auth import crypt, jwt

KID = "kid-sec08-one"
PUBLIC_NEEDING_A_SESSION = {("GET", "/access"), ("POST", "/access/declaration")}


# --- real signing keys and the real verifier ------------------------------------------------------------------------


def _rsa() -> tuple[bytes, Any]:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    return private, key


def _certificate_pem(key: Any) -> str:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.x509.oid import NameOID

    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "tilo-sec08")])
    now = dt.datetime.now(dt.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=30))
        .sign(key, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.PEM).decode()


class _Response:
    def __init__(self, data: bytes) -> None:
        self.status, self.data, self.headers = 200, data, {}


class _CertTransport:
    """google-auth's `Request` shape: answers Google's certificate endpoint from memory, never the network."""

    def __init__(self, certs: dict[str, str]) -> None:
        self.certs, self.calls = certs, 0

    def __call__(self, url: str, method: str = "GET", **kwargs: Any) -> _Response:
        self.calls += 1
        return _Response(json.dumps(self.certs).encode())


class Keys:
    """Google's key (the one the verifier trusts) and an attacker's."""

    def __init__(self) -> None:
        self.google_private, google_key = _rsa()
        self.attacker_private, _ = _rsa()
        self.cert = _certificate_pem(google_key)

    def token(self, *, private: bytes | None = None, kid: str = KID, **claims: Any) -> str:
        now = int(time.time())
        payload = {
            "iss": GOOGLE_ISSUER,
            "aud": AUDIENCE,
            "email": SCHEDULE_SA,
            "email_verified": True,
            "iat": now,
            "exp": now + 3600,
            "sub": "1234567890",
            **claims,
        }
        signer = crypt.RSASigner.from_string(private or self.google_private, key_id=kid)
        return jwt.encode(signer, payload, header={"kid": kid}).decode()


@pytest.fixture(scope="module")
def keys() -> Keys:
    return Keys()


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


@pytest.fixture
def sched(clear_flow: Any, monkeypatch: pytest.MonkeyPatch, keys: Keys) -> SchedApi:
    """The real tick route wired to the REAL `GoogleOidcVerifier` (certificates from the in-process fake)."""
    from tilo_api import schedules

    rig = SchedApi(clear_flow, monkeypatch)
    rig.clock.set(MON_0330Z)
    rig.transport = _CertTransport({KID: keys.cert})  # type: ignore[attr-defined]
    real = schedules.GoogleOidcVerifier(transport=rig.transport)  # type: ignore[attr-defined]
    rig.app.dependency_overrides[schedules.get_oidc_verifier] = lambda: real
    return rig


@pytest.fixture
def run_sched(run_flow: Any, monkeypatch: pytest.MonkeyPatch, keys: Keys) -> SchedApi:
    from tilo_api import schedules

    rig = SchedApi(run_flow.flow, monkeypatch, rf=run_flow)
    rig.clock.set(MON_0330Z)
    rig.transport = _CertTransport({KID: keys.cert})  # type: ignore[attr-defined]
    real = schedules.GoogleOidcVerifier(transport=rig.transport)  # type: ignore[attr-defined]
    rig.app.dependency_overrides[schedules.get_oidc_verifier] = lambda: real
    return rig


def _with_due_schedule(rig: SchedApi) -> set[str]:
    task = rig.approved_task()
    rig.insert(task, "sched_a")
    rig.insert(task, "sched_later", next_due=MON_0330Z + 10 * WEEK)
    return set(rig.store.worlds)


def _assert_nothing_started(rig: SchedApi, worlds: set[str]) -> None:
    for schedule_id, due in (("sched_a", MON_0330Z), ("sched_later", MON_0330Z + 10 * WEEK)):
        record = rig.schedules.get(schedule_id)
        assert (record.next_due, record.failures, record.last_error, record.last_world_id) == (due, 0, None, None)
    assert set(rig.store.worlds) == worlds, "a world was created"
    assert rig.clock() == MON_0330Z


# --- positive control -----------------------------------------------------------------------------------------------


def test_SEC_08_tick_positive_control_a_really_signed_fresh_token_is_accepted(sched: SchedApi, keys: Keys) -> None:
    response = sched.tick(keys.token())

    assert (response.status_code, response.json()) == (200, {"fired": 0})
    assert sched.transport.calls == 1, "the signature was checked against the fetched certificate"  # type: ignore[attr-defined]


# --- forged, tampered, unsigned -------------------------------------------------------------------------------------


def test_SEC_08_tick_signature_made_with_another_rsa_key_is_rejected_and_starts_nothing(
    sched: SchedApi, keys: Keys
) -> None:
    worlds = _with_due_schedule(sched)
    forged = keys.token(private=keys.attacker_private)  # right kid, issuer, audience and caller; wrong key

    response = sched.tick(forged)

    assert response.status_code == 401
    assert forged not in response.text
    _assert_nothing_started(sched, worlds)


def test_SEC_08_tick_tampered_payload_with_the_original_signature_is_rejected_and_starts_nothing(
    sched: SchedApi, keys: Keys
) -> None:
    worlds = _with_due_schedule(sched)
    head, _, sig = keys.token(email=GMAIL_SA).split(".")  # a genuine token of an account the route refuses
    payload = _b64e(json.dumps({"iss": GOOGLE_ISSUER, "aud": AUDIENCE, "email": SCHEDULE_SA, "email_verified": True,
                                "iat": int(time.time()), "exp": int(time.time()) + 3600}).encode())  # fmt: skip

    response = sched.tick(f"{head}.{payload}.{sig}")

    assert response.status_code == 401
    _assert_nothing_started(sched, worlds)


@pytest.mark.parametrize(
    "unsigned",
    [
        lambda token: token.rsplit(".", 1)[0],
        lambda token: token.rsplit(".", 1)[0] + ".",
        lambda token: _b64e(b'{"alg":"none","typ":"JWT","kid":"%s"}' % KID.encode()) + "." + token.split(".")[1] + ".",
        lambda token: (
            _b64e(b'{"alg":"HS256","typ":"JWT","kid":"%s"}' % KID.encode()) + "." + token.split(".")[1] + ".x"
        ),
    ],
    ids=["no-signature-part", "empty-signature", "alg-none", "alg-confusion-hs256"],
)
def test_SEC_08_tick_token_with_a_missing_or_downgraded_signature_is_rejected_and_starts_nothing(
    sched: SchedApi, keys: Keys, unsigned: Any
) -> None:
    worlds = _with_due_schedule(sched)

    response = sched.tick(unsigned(keys.token()))

    assert response.status_code == 401
    _assert_nothing_started(sched, worlds)


def test_SEC_08_tick_request_with_no_token_is_rejected_and_starts_nothing(sched: SchedApi) -> None:
    worlds = _with_due_schedule(sched)
    for headers in ({}, {"Authorization": ""}, {"Authorization": "Bearer "}, {"Authorization": "Basic abc"}):
        assert sched.tick(headers=headers).status_code == 401
    assert sched.flow.client.post(TICK).status_code == 401  # even a signed-in person's session starts nothing
    _assert_nothing_started(sched, worlds)


def test_SEC_08_tick_expired_token_is_rejected_and_starts_nothing(sched: SchedApi, keys: Keys) -> None:
    worlds = _with_due_schedule(sched)
    now = int(time.time())
    expired = keys.token(iat=now - 7200, exp=now - 3600)  # really signed, but outside its window

    response = sched.tick(expired)

    assert response.status_code == 401
    _assert_nothing_started(sched, worlds)


@pytest.mark.parametrize(
    "claims",
    [{"email": GMAIL_SA}, {"email": TASKS_SA}, {"email": API_SA}, {"email_verified": False}],
    ids=["gmail-scheduler", "tasks-invoker", "tilo-api-itself", "unverified-email"],
)
def test_SEC_08_tick_really_signed_token_of_another_caller_is_rejected_and_starts_nothing(
    sched: SchedApi, keys: Keys, claims: dict[str, Any]
) -> None:
    worlds = _with_due_schedule(sched)

    response = sched.tick(keys.token(**claims))

    assert response.status_code == 403
    _assert_nothing_started(sched, worlds)


@pytest.mark.parametrize(
    "claims",
    [{"aud": "https://tilo-harness-abc123-as.a.run.app"}, {"iss": "https://evil.example.com"}],
    ids=["another-audience", "another-issuer"],
)
def test_SEC_08_tick_really_signed_token_for_another_audience_or_issuer_is_rejected_and_starts_nothing(
    sched: SchedApi, keys: Keys, claims: dict[str, Any]
) -> None:
    worlds = _with_due_schedule(sched)

    response = sched.tick(keys.token(**claims))

    assert response.status_code in (401, 403)
    assert sched.transport.calls == 0, "refused from its own claims before any certificate fetch"  # type: ignore[attr-defined]
    _assert_nothing_started(sched, worlds)


# --- replay ---------------------------------------------------------------------------------------------------------


def test_SEC_08_tick_replayed_request_starts_each_slot_once_and_a_late_replay_is_rejected(
    run_sched: SchedApi, keys: Keys
) -> None:
    source = run_sched.source_run_task()
    run_sched.insert(source, "sched_a")
    run_sched.store.policies["pol_auto_budget"] = l3_budget_policy()
    captured = keys.token()

    first = run_sched.tick(captured)
    replays = [run_sched.tick(captured) for _ in range(3)]  # Scheduler's retry and an attacker's replay look alike

    assert (first.status_code, first.json()) == (200, {"fired": 1})
    assert [(r.status_code, r.json()) for r in replays] == [(200, {"fired": 0})] * 3
    worlds_after = set(run_sched.store.worlds)

    now = int(time.time())
    late = run_sched.tick(keys.token(iat=now - 7200, exp=now - 3600))  # the same capture once its window has closed
    assert late.status_code == 401
    assert set(run_sched.store.worlds) == worlds_after


# --- route guard ----------------------------------------------------------------------------------------------------


def test_SEC_08_api_has_exactly_one_public_signed_route_and_every_other_route_needs_a_session(
    sched: SchedApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tilo_api import access
    from tilo_api.access import PUBLIC_ROUTES

    health = {("GET", "/health"), ("GET", "/healthz")}
    signed = {("POST", TICK)}

    assert PUBLIC_ROUTES - health - signed == PUBLIC_NEEDING_A_SESSION, (
        "a new public route needs forged / tampered / missing / expired / replayed cases in this file, or a session"
    )
    assert signed <= set(route_table(sched.app)) and access.enforced({"K_SERVICE": "x"})

    monkeypatch.setenv("K_SERVICE", "tilo-api")  # deployed: the access gate runs before any body is read
    sched.sign_out()  # nobody is signed in and no token is presented
    exposed = []
    for method, path in route_table(sched.app):
        if (method, path) in health | signed:
            continue
        status = sched.flow.client.request(method, _concrete(path), json={}).status_code
        if status not in (401, 403):
            exposed.append((method, path, status))
    assert exposed == [], f"routes that answered an anonymous request with something other than 401/403: {exposed}"


def _concrete(path: str) -> str:
    from _sec15_lib import concrete

    return concrete(path)
