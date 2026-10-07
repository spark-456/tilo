"""SEC-08 (PRD 16.4: "Signed webhooks and signed email links" -> "Forged or replayed requests rejected"; PRD 6.3 Cloud
Scheduler; infra/ACCESS.md "Route requirements") for the one signed inbound surface of tilo-harness.

Signed inbound surfaces of tilo-harness, enumerated from the code (route decorators and `tick_caller_ok` users under
services/harness/src, 2026-10-07):

1. `POST /internal/schedules/tick`: Cloud Scheduler's Google-signed OIDC bearer token. The route trusts only the
   VERIFIED claims (issuer, audience, verified e-mail and the single allowed service account).
2. `GET /health`, `GET /healthz`: unauthenticated liveness, no state, no side effect.
The route guard at the end fails when a new route is mounted, so a new webhook cannot ship without its own SEC-08
cases here.

Acceptance claim: a forged signature, a tampered payload, a missing signature, an expired token and a replayed
request are rejected and start nothing (no run attempted, no schedule claimed, no clock moved); a correctly signed,
fresh request from the one allowed account is accepted (positive control).

Seam note: tilo-harness has no production verifier yet (`create_app()` with no wiring answers 503 to everything, which
is fail closed, and is asserted below). The route's verifier seam is the `OidcVerifier` Protocol, so these tests plug
in `SignedTokenVerifier`, a real signature and expiry check (HMAC-SHA256 over the JWT signing input, a key made at run
time) that raises on anything it did not sign, as google-auth does. The same attack matrix against Google's real RS256
verifier is in services/api/tests/test_SEC_08_forged_or_replayed_tick_rejected.py (tilo-api's tick is the same
contract and ships the real verifier).

Default where the PRD is silent: replaying a captured, still-valid tick request is not an error (Cloud Scheduler
retries by design); it is idempotent, one run per schedule slot (FR-AGT-14 "exactly one run per slot"). Once the token
has expired the replay is rejected (401). No real secrets: keys and tokens are made at run time.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import threading
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from schedule_support import (
    API_SA,
    AUDIENCE,
    GMAIL_SA,
    GOOGLE_ISSUER,
    MON_0330Z,
    SCHEDULE_SA,
    TASKS_SA,
    bearer,
    make_rig,
    make_schedule,
)
from tilo_harness.app import app as production_app
from tilo_harness.app import create_app
from tilo_harness.schedule import TickWiring

PATH = "/internal/schedules/tick"
SIGNED_ROUTES = frozenset({("POST", PATH)})
HEALTH_ROUTES = frozenset({("GET", "/health"), ("GET", "/healthz")})
TOKEN_LIFE_S = 3600


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class SignedTokenVerifier:
    """`verify(token, audience) -> claims`: accepts only a JWT whose HMAC-SHA256 signature it can recompute with its
    own key and whose `exp` is in the future by the injected clock. Like google-auth's `id_token.verify_oauth2_token`
    it does NOT decide who may call: that is the route's job, from the claims it returns."""

    def __init__(self, now: Any) -> None:
        self._key = secrets.token_bytes(32)
        self._now = now
        self.calls: list[str] = []

    def mint(self, *, key: bytes | None = None, **claims: Any) -> str:
        now = int(self._now())
        payload = {
            "iss": GOOGLE_ISSUER,
            "aud": AUDIENCE,
            "email": SCHEDULE_SA,
            "email_verified": True,
            "iat": now,
            "exp": now + TOKEN_LIFE_S,
            **claims,
        }
        head = _b64e(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
        body = _b64e(json.dumps(payload).encode())
        sig = hmac.new(key or self._key, f"{head}.{body}".encode(), hashlib.sha256).digest()
        return f"{head}.{body}.{_b64e(sig)}"

    def verify(self, token: str, audience: str) -> Mapping[str, Any]:
        self.calls.append(token)
        head, body, sig = token.split(".")  # a token with no signature part raises here
        if json.loads(_b64d(head)).get("alg") != "HS256":
            raise ValueError("unsupported algorithm")
        expected = hmac.new(self._key, f"{head}.{body}".encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _b64d(sig)):
            raise ValueError("signature check failed")
        claims = json.loads(_b64d(body))
        if claims["exp"] <= self._now():
            raise ValueError("token expired")
        return claims


def _client(rig: Any) -> tuple[TestClient, SignedTokenVerifier]:
    verifier = SignedTokenVerifier(lambda: rig.clock().timestamp())
    wiring = TickWiring(verifier=verifier, audience=AUDIENCE, service_account=SCHEDULE_SA, ticker=rig.ticker)
    return TestClient(create_app(schedule_tick=wiring)), verifier


def _nothing_started(rig: Any) -> None:
    assert rig.starter.attempts == [], "a run start was attempted"
    assert rig.store.claims_won == [] and rig.store.claims_lost == [], "a schedule was claimed"
    assert rig.store.held() == {}
    assert rig.store.get("sched_a").next_due == MON_0330Z
    assert rig.clock() == MON_0330Z


def test_SEC_08_tick_positive_control_a_correctly_signed_fresh_request_starts_the_due_run():
    rig = make_rig([make_schedule("sched_a")])
    client, verifier = _client(rig)

    response = client.post(PATH, headers=bearer(verifier.mint()))

    assert (response.status_code, response.json()) == (200, {"fired": 1})
    assert [r.schedule_id for r in rig.starter.started] == ["sched_a"]


def test_SEC_08_tick_token_signed_with_another_key_is_rejected_and_starts_nothing():
    rig = make_rig()
    client, verifier = _client(rig)
    forged = verifier.mint(key=secrets.token_bytes(32))  # every claim right, the signature not ours

    response = client.post(PATH, headers=bearer(forged))

    assert response.status_code == 401
    assert forged not in response.text
    _nothing_started(rig)


def test_SEC_08_tick_tampered_payload_with_the_original_signature_is_rejected_and_starts_nothing():
    rig = make_rig()
    client, verifier = _client(rig)
    harmless = verifier.mint(email=GMAIL_SA)  # a genuine token of an account the route refuses
    head, _, sig = harmless.split(".")
    body = _b64e(json.dumps({"iss": GOOGLE_ISSUER, "aud": AUDIENCE, "email": SCHEDULE_SA, "email_verified": True,
                             "iat": 1, "exp": 4_000_000_000}).encode())  # fmt: skip

    response = client.post(PATH, headers=bearer(f"{head}.{body}.{sig}"))

    assert response.status_code == 401
    _nothing_started(rig)


@pytest.mark.parametrize(
    "unsigned",
    [
        lambda token: token.rsplit(".", 1)[0],  # no signature part
        lambda token: token.rsplit(".", 1)[0] + ".",  # an empty signature
        lambda token: _b64e(b'{"alg":"none","typ":"JWT"}') + "." + token.split(".")[1] + ".",  # alg none
    ],
    ids=["no-signature-part", "empty-signature", "alg-none"],
)
def test_SEC_08_tick_token_with_a_missing_signature_is_rejected_and_starts_nothing(unsigned):
    rig = make_rig()
    client, verifier = _client(rig)

    response = client.post(PATH, headers=bearer(unsigned(verifier.mint())))

    assert response.status_code == 401
    _nothing_started(rig)


def test_SEC_08_tick_request_with_no_token_is_rejected_and_starts_nothing():
    rig = make_rig()
    client, verifier = _client(rig)

    for headers in ({}, {"Authorization": ""}, {"Authorization": "Bearer "}, {"Authorization": "Basic abc"}):
        assert client.post(PATH, headers=headers).status_code == 401
    assert verifier.calls == []
    _nothing_started(rig)


def test_SEC_08_tick_expired_token_is_rejected_and_starts_nothing():
    rig = make_rig()
    client, verifier = _client(rig)
    token = verifier.mint()
    rig.clock.advance(TOKEN_LIFE_S + 1)

    response = client.post(PATH, headers=bearer(token))

    assert response.status_code == 401
    assert rig.starter.attempts == [] and rig.store.claims_won == []


@pytest.mark.parametrize(
    "claims",
    [
        {"email": GMAIL_SA},
        {"email": TASKS_SA},
        {"email": API_SA},
        {"aud": "https://tilo-api-abc123-as.a.run.app"},
        {"iss": "https://evil.example.com"},
        {"email_verified": False},
    ],
    ids=["gmail-scheduler", "tasks-invoker", "tilo-api", "other-audience", "other-issuer", "unverified-email"],
)
def test_SEC_08_tick_validly_signed_token_of_another_caller_is_rejected_and_starts_nothing(claims):
    rig = make_rig()
    client, verifier = _client(rig)

    response = client.post(PATH, headers=bearer(verifier.mint(**claims)))

    assert response.status_code == 403
    _nothing_started(rig)


def test_SEC_08_tick_replayed_request_starts_each_slot_once_and_a_late_replay_is_rejected():
    rig = make_rig([make_schedule("sched_a")])
    client, verifier = _client(rig)
    captured = verifier.mint()

    first = client.post(PATH, headers=bearer(captured))
    replays = [client.post(PATH, headers=bearer(captured)) for _ in range(5)]

    assert first.json() == {"fired": 1}
    assert [r.json() for r in replays] == [{"fired": 0}] * 5
    assert len(rig.starter.attempts) == 1, "a replay never starts the same slot twice"

    rig.clock.advance(TOKEN_LIFE_S + 1)  # the capture is outside its window
    late = client.post(PATH, headers=bearer(captured))
    assert late.status_code == 401
    assert len(rig.starter.attempts) == 1


def test_SEC_08_tick_replayed_concurrently_starts_each_slot_once():
    rig = make_rig([make_schedule("sched_a")])
    client, verifier = _client(rig)
    captured = verifier.mint()
    barrier = threading.Barrier(8)

    def go(_: int) -> int:
        barrier.wait()
        return client.post(PATH, headers=bearer(captured)).json()["fired"]

    with ThreadPoolExecutor(8) as pool:
        fired = list(pool.map(go, range(8)))

    assert sum(fired) == 1
    assert len(rig.starter.attempts) == 1


def test_SEC_08_tick_with_no_verifier_wired_fails_closed_for_every_token():
    for client in (TestClient(production_app), TestClient(create_app())):
        for headers in ({}, bearer("tok-" + secrets.token_urlsafe(16))):
            assert client.post(PATH, headers=headers).status_code == 503


def test_SEC_08_harness_app_mounts_no_inbound_route_outside_the_signed_surface_list():
    rig = make_rig()
    client, _ = _client(rig)
    app = client.app

    mounted = {(method, route.path) for route in app.routes if isinstance(route, APIRoute) for method in route.methods}
    # FastAPI 0.14x wraps included routers lazily, and a route can be left out of the schema: read both views.
    mounted |= {(m.upper(), p) for p, ops in app.openapi()["paths"].items() for m in ops}
    assert all(isinstance(r, APIRoute) for r in app.routes), "a mounted router or sub-app: list its routes here"
    unknown = mounted - HEALTH_ROUTES - SIGNED_ROUTES

    assert unknown == set(), (
        f"{sorted(unknown)} is an inbound route with no SEC-08 test: add forged, tampered, missing, expired and "
        "replayed cases for it to this file, then list it in SIGNED_ROUTES"
    )
    assert SIGNED_ROUTES <= mounted
    assert app.openapi_url is None
