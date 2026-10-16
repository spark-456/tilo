"""SEC-10 (PRD 16 "Rate limits, App Check and spend caps"; PRD 6.2 "Firebase Authentication, App Check"):
tilo-api and the web client's `X-Firebase-AppCheck` token. Written before any implementation.

FOUND, NOT AS BRIEFED: `services/api` has NO App Check verification today (infra/ACCESS.md section 2 lists
"Firebase ID-token and App Check verification" for tilo-api, but there is no code: a case-insensitive search of
services/api/src for "appcheck" or "firebase" finds nothing, and `deps.get_current_principal` is a fail-closed 401
stub). Today the header is ignored: every route answers exactly as it would without it. These tests therefore pin
the smallest seam that keeps that true while the client starts sending tokens, and no more:

- `tilo_api.appcheck` (new module) holds a pure-ASGI middleware, registered on `tilo_api.app` beside `AccessGate`.
  It reads the `X-Firebase-AppCheck` header of every request except the exempt routes below.
- `deps.get_app_check_verifier()` returns an object with
  `verify(token: str) -> Mapping`, which raises for a token it refuses. Tests override it; the default must never
  break a call (no verifier, a verifier that raises, a network that is down: all the same as "not verified").
- Enforcement is a config flag `TILO_APPCHECK_ENFORCE`, read on every request: exactly `"1"` turns it on (the
  convention of `TILO_API_DEV` and `TILO_JUDGE_LIVE`); unset, empty or anything else is off. DEFAULT IS OFF
  (infra/ACCESS.md section 7: "enforcement stays off"), and the owner alone turns it on.
- Enforcement OFF: no behaviour change at all. A missing, empty, invalid or unverifiable token is only logged,
  one WARNING on the logger `tilo_api.appcheck` per request, never carrying the token. A valid token logs nothing.
- Enforcement ON (pinned lightly; AMBIGUITY, PRD gives no status): a missing or refused token gets 401 and the
  route never runs; a valid one passes.
- Exempt routes, never checked or logged in either mode: `/health`, `/healthz` (Cloud Run probes carry no token)
  and `POST /internal/schedules/tick` (its own Google OIDC check, FR-AGT-14b).
- Dev mode (`TILO_API_DEV=1`) and CI make no external call: nothing here opens a socket.

No network, no model, no paid call: the verifier is a fake and tokens are assembled at runtime.
"""

from __future__ import annotations

import logging
import socket
import string

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from tilo_api import app, deps

LOGGER = "tilo_api.appcheck"
HEADER = "X-Firebase-AppCheck"
ENFORCE = "TILO_APPCHECK_ENFORCE"
PROTECTED = "/worlds"  # signed in as the `client` fixture's owner it answers 200 {"worlds": [], ...}
EXEMPT = ("/health", "/healthz")


def good_token(n: int = 1) -> str:
    return ".".join(["fake", "appcheck", "valid", str(n)])


def bad_token() -> str:
    return ".".join(["fake", "appcheck", "refused", "x1"])


class FakeVerifier:
    """`verify(token)` returns claims for a token in `valid`, raises ValueError otherwise (or `error` if set)."""

    def __init__(self, valid: set[str] | None = None, error: Exception | None = None) -> None:
        self.valid = valid if valid is not None else {good_token()}
        self.error = error
        self.calls: list[str] = []

    def verify(self, token: str) -> dict[str, str]:
        self.calls.append(token)
        if self.error is not None:
            raise self.error
        if token not in self.valid:
            raise ValueError("refused")
        return {"sub": "1:000000000000:web:fake", "iss": "https://firebaseappcheck.googleapis.com/000000000000"}


@pytest.fixture
def verifier(client, monkeypatch) -> FakeVerifier:
    """The `client` fixture's app with the verifier seam overridden and enforcement unset (the default)."""
    import tilo_api.appcheck  # noqa: F401, PLC0415  (a missing module fails here, not later)

    monkeypatch.delenv(ENFORCE, raising=False)
    fake = FakeVerifier()
    app.dependency_overrides[deps.get_app_check_verifier] = lambda: fake
    return fake


def warnings_of(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == LOGGER and r.levelno >= logging.WARNING]


def snapshot(response) -> tuple[int, dict | str]:
    """Status and body (JSON when it is JSON): what "behaves the same" means."""
    try:
        return response.status_code, response.json()
    except ValueError:
        return response.status_code, response.text


# --- 1. enforcement off (the default): no behaviour change -----------------------------------------


def test_SEC_10_enforcement_is_off_by_default_a_request_with_no_token_is_served(verifier, client):
    response = client.get(PROTECTED)
    assert response.status_code == 200, response.text
    # STARTER-1 (#739): an owner with no worlds also gets the read-only sample world; it is a fixture, not user data.
    assert [w for w in response.json()["worlds"] if not w.get("sample")] == []


@pytest.mark.parametrize("value", ["", "0", "true", "TRUE", "yes", "on", " 1", "1 ", "01", "2"])
def test_SEC_10_only_exactly_1_turns_enforcement_on(verifier, client, monkeypatch, value):
    monkeypatch.setenv(ENFORCE, value)
    assert client.get(PROTECTED).status_code == 200  # no token, still served: the flag is off


@pytest.mark.parametrize("path", [PROTECTED, "/worlds/w_none", "/worlds/w_none/cards", "/worlds/w_none/layout"])
def test_SEC_10_off_every_route_answers_the_same_with_no_token_a_valid_one_or_a_refused_one(verifier, client, path):
    baseline = snapshot(client.get(path))
    for headers in (
        {HEADER: good_token()},
        {HEADER: bad_token()},
        {HEADER: ""},
    ):
        assert snapshot(client.get(path, headers=headers)) == baseline, (path, headers)
    assert baseline[0] not in (401, 403) or path != PROTECTED  # the protected route is plainly served


def test_SEC_10_off_a_post_answers_the_same_with_and_without_a_token(verifier, client):
    path = "/worlds/w_none/pause"
    baseline = snapshot(client.post(path, json={}))
    assert snapshot(client.post(path, json={}, headers={HEADER: good_token()})) == baseline
    assert snapshot(client.post(path, json={}, headers={HEADER: bad_token()})) == baseline


@pytest.mark.parametrize(
    "error",
    [RuntimeError("jwks unavailable"), OSError("network is down"), TimeoutError("slow"), KeyError("kid")],
    ids=lambda e: type(e).__name__,
)
def test_SEC_10_off_a_verifier_that_fails_never_breaks_the_call(verifier, client, caplog, error):
    verifier.error = error
    baseline = snapshot(client.get(PROTECTED))
    caplog.clear()
    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        response = client.get(PROTECTED, headers={HEADER: good_token()})
    assert snapshot(response) == baseline
    assert response.status_code == 200
    assert len(warnings_of(caplog)) == 1  # it is logged as not verified, once
    assert str(error) not in caplog.text and good_token() not in caplog.text


def test_SEC_10_off_a_missing_token_is_logged_once_as_a_warning_and_nothing_else_changes(verifier, client, caplog):
    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        response = client.get(PROTECTED)
    assert response.status_code == 200
    records = warnings_of(caplog)
    assert len(records) == 1
    assert records[0].levelno == logging.WARNING
    assert "app" in records[0].getMessage().lower() and "check" in records[0].getMessage().lower()
    assert verifier.calls == []  # nothing to verify


def test_SEC_10_off_an_empty_header_counts_as_missing(verifier, client, caplog):
    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        response = client.get(PROTECTED, headers={HEADER: ""})
    assert response.status_code == 200
    assert len(warnings_of(caplog)) == 1
    assert verifier.calls == []


def test_SEC_10_off_a_refused_token_is_logged_once_without_the_token(verifier, client, caplog):
    token = bad_token()
    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        response = client.get(PROTECTED, headers={HEADER: token})
    assert response.status_code == 200
    assert len(warnings_of(caplog)) == 1
    assert verifier.calls == [token]
    assert token not in caplog.text
    assert token not in response.text and token not in str(dict(response.headers))


def test_SEC_10_off_a_valid_token_is_verified_and_logs_no_warning(verifier, client, caplog):
    token = good_token()
    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        response = client.get(PROTECTED, headers={HEADER: token})
    assert response.status_code == 200
    assert verifier.calls == [token]
    assert warnings_of(caplog) == []
    assert token not in caplog.text


@pytest.mark.parametrize("path", EXEMPT)
def test_SEC_10_exempt_routes_are_never_checked_or_logged(verifier, client, caplog, path):
    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        none = client.get(path)
        valid = client.get(path, headers={HEADER: good_token()})
        refused = client.get(path, headers={HEADER: bad_token()})
    assert (none.status_code, valid.status_code, refused.status_code) == (200, 200, 200)
    assert verifier.calls == []
    assert warnings_of(caplog) == []


def test_SEC_10_a_scheduler_tick_is_not_an_app_check_route(verifier, client, caplog, monkeypatch):
    """The tick has its own OIDC check (FR-AGT-14b); unset, it answers 503 before looking at anything."""
    monkeypatch.delenv("TILO_SCHEDULE_TICK_AUDIENCE", raising=False)
    monkeypatch.delenv("TILO_SCHEDULE_TICK_CALLER", raising=False)
    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        response = client.post("/internal/schedules/tick")
    assert response.status_code == 503
    assert verifier.calls == [] and warnings_of(caplog) == []


def test_SEC_10_off_the_default_verifier_never_breaks_a_call_and_opens_no_socket(client, monkeypatch, caplog):
    """No override: the real `deps.get_app_check_verifier`. In CI and dev there is no network, so whatever it does
    with a token (it may try to fetch Google's keys) must end as "not verified", never as an error."""
    import tilo_api.appcheck  # noqa: F401, PLC0415

    monkeypatch.delenv(ENFORCE, raising=False)
    monkeypatch.setenv("TILO_API_DEV", "1")  # dev mode: no cloud, no paid call (services/api/CLAUDE.md)
    attempts: list[object] = []

    def refuse(self, *args, **kwargs):
        attempts.append(args)
        raise OSError("SEC-10 test: no network")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", lambda self, *a, **k: attempts.append(a) or 1)
    baseline = snapshot(client.get(PROTECTED))
    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        response = client.get(PROTECTED, headers={HEADER: good_token()})
    assert snapshot(response) == baseline
    assert response.status_code == 200
    assert attempts == [], "dev mode must not reach Google to verify a token"
    assert good_token() not in caplog.text


# --- 2. enforcement on: the switch the owner turns, pinned lightly --------------------------------


def test_SEC_10_on_a_missing_or_refused_token_is_401_and_the_route_does_not_run(verifier, client, monkeypatch):
    monkeypatch.setenv(ENFORCE, "1")
    for headers in ({}, {HEADER: ""}, {HEADER: bad_token()}):
        response = client.get(PROTECTED, headers=headers)
        assert response.status_code == 401, headers
        assert "worlds" not in response.text
        assert bad_token() not in response.text


def test_SEC_10_on_a_valid_token_is_served_and_verified_exactly_as_sent(verifier, client, monkeypatch):
    monkeypatch.setenv(ENFORCE, "1")
    response = client.get(PROTECTED, headers={HEADER: good_token()})
    assert response.status_code == 200
    assert verifier.calls == [good_token()]


def test_SEC_10_on_a_verifier_that_fails_closes_the_call_with_401_not_a_500(verifier, client, monkeypatch):
    monkeypatch.setenv(ENFORCE, "1")
    verifier.error = OSError("network is down")
    response = client.get(PROTECTED, headers={HEADER: good_token()})
    assert response.status_code == 401
    assert "network" not in response.text


@pytest.mark.parametrize("path", EXEMPT)
def test_SEC_10_on_the_exempt_routes_still_answer_without_a_token(verifier, client, monkeypatch, path):
    monkeypatch.setenv(ENFORCE, "1")
    assert client.get(path).status_code == 200
    assert verifier.calls == []


def test_SEC_10_on_a_scheduler_tick_still_reaches_its_own_check(verifier, client, monkeypatch):
    monkeypatch.setenv(ENFORCE, "1")
    monkeypatch.delenv("TILO_SCHEDULE_TICK_AUDIENCE", raising=False)
    monkeypatch.delenv("TILO_SCHEDULE_TICK_CALLER", raising=False)
    assert client.post("/internal/schedules/tick").status_code == 503  # its own answer, not App Check's 401


def test_SEC_10_the_flag_is_read_on_every_request_and_flipping_it_off_restores_service(verifier, client, monkeypatch):
    assert client.get(PROTECTED).status_code == 200
    monkeypatch.setenv(ENFORCE, "1")
    assert client.get(PROTECTED).status_code == 401
    monkeypatch.delenv(ENFORCE)
    assert client.get(PROTECTED).status_code == 200


# --- 3. properties ----------------------------------------------------------------------------------

TOKENS = st.text(alphabet=string.ascii_letters + string.digits + "-._~+/=", min_size=0, max_size=256)


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(token=TOKENS)
def test_SEC_10_property_off_no_token_value_changes_the_answer_or_leaks(verifier, client, caplog, token):
    verifier.valid = set()  # refuses everything
    baseline = snapshot(client.get(PROTECTED))
    caplog.clear()
    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        response = client.get(PROTECTED, headers={HEADER: token} if token else {})
    assert snapshot(response) == baseline
    assert response.status_code == 200
    if len(token) >= 8:  # shorter strings can occur in a log line by chance
        assert token not in caplog.text and token not in response.text


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(token=TOKENS)
def test_SEC_10_property_on_a_token_the_verifier_refuses_never_gets_through(verifier, client, monkeypatch, token):
    monkeypatch.setenv(ENFORCE, "1")
    verifier.valid = set()
    response = client.get(PROTECTED, headers={HEADER: token} if token else {})
    assert response.status_code == 401
