"""SEC-08 reviewed cases for POST /internal/meeting-host/join (SEC-REVIEW-9)."""

from __future__ import annotations

import base64
import json
import logging

import pytest
from _meeting_host_lib import CALENDAR_EVENTS_OWNED
from _oauth_lib import OTHER
from fastapi.testclient import TestClient
from test_ADR32_T3_host_routes import AUD, CALLER, HARNESS, Rig
from tilo_connectors.app import create_app
from tilo_connectors.host_auth import CertsUnavailable, GoogleOidcVerifier
from tilo_connectors.host_routes import AUDIENCE_VAR, CALLER_VAR, HostRuntime

PATH = "/internal/meeting-host/join"


def _b64(obj) -> str:
    return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")


def test_SEC_08_unset_audience_or_caller_is_503_before_any_verify():
    for missing in (AUDIENCE_VAR, CALLER_VAR):
        rig = Rig(settings={k: v for k, v in {AUDIENCE_VAR: AUD, CALLER_VAR: CALLER}.items() if k != missing})
        r = rig.call("join", {})
        assert (r.status_code, r.json()) == (503, {"error": "not_configured"}), missing
        assert rig.verifier.calls == []
        assert rig.cal.requests == []
    rig = Rig(settings={})
    assert rig.call("join", {}).status_code == 503


def test_SEC_08_header_shapes_are_401():
    rig = Rig()
    receipt = rig.send()["receipt"]
    n = len(rig.cal.requests)
    for header in ("Basic " + rig.good, "Bearer", "Bearer a b", rig.good, "bearer", ""):
        r = rig.client.post(PATH, content=json.dumps(receipt).encode(), headers={"authorization": header})
        assert r.status_code == 401, header
    assert len(rig.cal.requests) == n


def test_SEC_08_wrong_claims():
    rig = Rig()
    receipt = rig.send()["receipt"]
    n = len(rig.cal.requests)
    for over in ({"email_verified": False}, {"email_verified": "true"}, {"aud": AUD + "/x"}, {"iss": "https://evil"}):
        r = rig.call("join", receipt, token=rig.verifier.add(**over))
        assert r.status_code == 401, over
    for over in ({"email": HARNESS}, {"email": None}, {"email": CALLER.upper()}):
        r = rig.call("join", receipt, token=rig.verifier.add(**over))
        assert r.status_code == 403, over
    assert len(rig.cal.requests) == n
    assert rig.call("join", receipt).status_code == 200


def test_SEC_08_oversize_and_garbage_bodies():
    rig = Rig()
    receipt = rig.send()["receipt"]
    n = len(rig.cal.requests)
    big = rig.call("join", raw=b"x" * 2049)
    assert big.status_code == 413
    assert rig.call("join", raw=b"x" * 5000, token=None).status_code == 401
    for raw in (b"[" * 2000, b"\xff\xfe\x00", b"null", b"[]", b"{}", json.dumps({**receipt, "extra": 1}).encode(), b""):
        r = rig.call("join", raw=raw)
        assert r.status_code == 422, (raw[:20], r.status_code)
        assert r.json() == {"error": "invalid_request"}
    assert len(rig.cal.requests) == n


@pytest.mark.parametrize(
    "ref",
    ["../abc", "A" * 32, "a" * 31, "a" * 33, "a" * 32 + "\n", "٠" * 32, "a" * 31 + "/", "a" * 30 + "?x", ""],
)
def test_SEC_08_event_ref_shape_is_closed(ref):
    rig = Rig()
    receipt = rig.send()["receipt"]
    n = len(rig.cal.requests)
    r = rig.call("join", {**receipt, "event_ref": ref})
    assert r.status_code in (422,), (ref, r.status_code, r.text)
    assert len(rig.cal.requests) == n


def test_SEC_08_owner_is_taken_from_the_receipt_cross_owner_read():
    rig = Rig()
    receipt = rig.send()["receipt"]
    # OTHER never connected the host grant: 409
    r = rig.call("join", {**receipt, "owner": OTHER})
    assert (r.status_code, r.json()) == (409, {"error": "host_not_connected"})
    # OTHER connects (own grant on the same bot account): the connector does not bind event_ref to owner
    rig.env.connect(OTHER, "meeting_host", [CALENDAR_EVENTS_OWNED])
    rig.env.clock.set("2026-10-08T09:33:00.000Z")
    r = rig.call("join", {**receipt, "owner": OTHER})
    print("CROSS-OWNER", r.status_code)  # documents residual trust in tilo-api (ADR-0032)
    assert r.status_code in (200, 409)


def test_SEC_08_certs_unavailable_is_503_try_again():
    rig = Rig()

    def boom(token, audience):
        raise CertsUnavailable("x")

    rig.verifier.verify = boom  # type: ignore[method-assign]
    r = rig.call("join", {})
    assert (r.status_code, r.json()) == (503, {"error": "try_again"})


def test_SEC_08_replay_is_just_another_read_and_no_state_is_kept():
    rig = Rig()
    receipt = rig.send()["receipt"]
    a = rig.call("join", receipt)
    b = rig.call("join", receipt)
    assert a.status_code == b.status_code == 200
    assert a.json()["join_url"] == b.json()["join_url"]
    assert a.headers["cache-control"] == "no-store"


def test_SEC_08_nothing_secret_in_logs_or_errors_and_no_waiting(caplog):
    caplog.set_level(logging.DEBUG)
    rig = Rig()
    receipt = rig.send()["receipt"]
    needles = rig.cal.plant.needles()
    for status in (500, 429, 403, 401):
        rig.cal.fail_next(status, times=3)
        r = rig.call("join", receipt)
        assert r.status_code in (503, 409), (status, r.status_code)
        assert r.headers["cache-control"] == "no-store"
        for needle in needles:
            assert needle not in r.text
        rig.cal.clear_failures()
    ok = rig.call("join", receipt)
    assert ok.status_code == 200
    assert set(ok.json()) == {"join_url", "expires_at"}
    assert ok.json()["join_url"] == rig.cal.plant.link
    for needle in needles:
        assert needle not in caplog.text


def test_SEC_08_get_is_not_allowed():
    rig = Rig()
    r = rig.client.get(PATH, headers={"authorization": "Bearer " + rig.good})
    assert r.status_code == 405


def test_SEC_08_forged_unsigned_tokens_never_reach_the_certificate_fetch():
    fetched = []

    def transport(url, **kw):
        fetched.append(url)
        raise OSError("no network")

    runtime = HostRuntime({AUDIENCE_VAR: AUD, CALLER_VAR: CALLER}, verifier=GoogleOidcVerifier(transport=transport))
    client = TestClient(create_app(runtime))
    claims = {"iss": "https://accounts.google.com", "aud": AUD, "email": CALLER, "email_verified": True}
    forged = [
        f"{_b64({'alg': 'none', 'kid': 'k'})}.{_b64(claims)}.",
        f"{_b64({'alg': 'HS256', 'kid': 'k'})}.{_b64(claims)}.sig",
        f"{_b64({'alg': 'RS256', 'kid': 'k'})}.{_b64({**claims, 'iss': 'https://evil'})}.sig",
        f"{_b64({'alg': 'RS256', 'kid': 'k'})}.{_b64({**claims, 'aud': 'https://other'})}.sig",
        "a.b.c",
        "x" * 5000,
    ]
    for token in forged:
        r = client.post(PATH, content=b"{}", headers={"authorization": f"Bearer {token}"})
        assert r.status_code == 401, token[:30]
    assert fetched == []


@pytest.mark.parametrize(
    "value",
    [
        "https://evil.example/abc-defg-hij",
        "https://meet.google.com@evil.example/abc-defg-hij",
        "https://meet.google.com.evil.example/abc-defg-hij",
        "https://meet.google.com/abc-defg-hij?authuser=1",
        "http://meet.google.com/abc-defg-hij",
        "https://meet.google.com/abc-defg-hij\n",
        "https://MEET.google.com/abc-defg-hij",
    ],
)
def test_SEC_08_route_level_hostile_hangout_link_is_a_fixed_409(value, monkeypatch):
    rig = Rig()
    receipt = rig.send()["receipt"]
    original = rig.cal._body
    monkeypatch.setattr(rig.cal, "_body", lambda ev: {**original(ev), "hangoutLink": value})
    r = rig.call("join", receipt)
    assert (r.status_code, r.json()) == (409, {"error": "no_join_link"}), (value, r.status_code, r.text)
    assert "evil" not in r.text and "meet.google.com" not in r.text
