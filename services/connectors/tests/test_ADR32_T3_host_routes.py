"""ADR32_T3 / FR_MTG_09: the internal meeting-host routes of tilo-connectors (ADR-0032, HB-01 to HB-06).

The base request is the contract's own valid fixture. FakeGoogle, FakeKms, an in-memory token store and the hostile
FakeHostCalendar stand in for Google: no network, no paid call, nothing reads the live switch. Every token, secret and
caller identity here is assembled at runtime.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import logging
import pathlib
import secrets
import threading
from typing import Any

import pytest
from _connectors_lib import ManualClock
from _meeting_host_lib import CALENDAR_EVENTS_OWNED, OWNER, FakeHostCalendar
from _oauth_lib import make_env
from fastapi.testclient import TestClient
from test_ADR32_T2_host_broker import FakeFirestore, FakeHttp, _build, _env, _grant
from tilo_connectors.adapters import side_effect_marker
from tilo_connectors.app import create_app
from tilo_connectors.host_auth import GOOGLE_ISSUERS, GoogleOidcVerifier
from tilo_connectors.host_broker import BrokerNotConfigured, BrokerSeam, open_broker
from tilo_connectors.host_routes import AUDIENCE_VAR, CALLER_VAR, MAX_BODY_BYTES, HostRuntime
from tilo_connectors.tokens import REVOKE_URL, TokenBroker

CONTRACTS = pathlib.Path(__file__).resolve().parents[3] / "contracts"
BASE = json.loads((CONTRACTS / "fixtures/meeting_host_rpc.send_request/valid/owner_and_one_invitee.json").read_text())
AUD = "https://connectors." + secrets.token_hex(3) + ".example.test"
CALLER = "api-" + secrets.token_hex(3) + "@demo-tilo.example.test"
HARNESS = "harness-" + secrets.token_hex(3) + "@demo-tilo.example.test"
APPROVED_AT = BASE["entry"]["authz"]["at"]  # 2026-10-08T09:32:09.500Z
BEFORE, NOW = "2026-10-08T09:00:00.000Z", "2026-10-08T09:33:00.000Z"
ROUTES = ("send", "status", "disconnect")


class FakeVerifier:
    def __init__(self) -> None:
        self.tokens: dict[str, dict[str, Any]] = {}
        self.calls: list[str] = []

    def add(self, **over: Any) -> str:
        token = "id-" + secrets.token_hex(8)
        base = {"iss": "https://accounts.google.com", "aud": AUD, "email": CALLER, "email_verified": True}
        self.tokens[token] = {**base, **over}
        return token

    def verify(self, token: str, audience: str) -> dict[str, Any]:
        self.calls.append(token)
        if token not in self.tokens:
            raise ValueError("bad token")
        return self.tokens[token]


class Rig:
    def __init__(self, *, settings: dict[str, str] | None = None, connect_at: str | None = BEFORE) -> None:
        self.env = make_env()
        self.cal = FakeHostCalendar(self.env.google)
        self.verifier = FakeVerifier()
        self.good = self.verifier.add()
        self.settings = {AUDIENCE_VAR: AUD, CALLER_VAR: CALLER} if settings is None else settings
        self.response: dict[str, Any] | None = None
        env = self.env

        def opener(_env: Any, *, emit: Any, alert: Any) -> TokenBroker:
            return TokenBroker(
                store=env.store, kms=env.kms, http=env.google, settings=env.settings, clock=env.clock,
                emit=emit, alert=alert,
            )  # fmt: skip

        self.runtime = HostRuntime(
            self.settings, verifier=self.verifier, broker_opener=opener, transport_opener=lambda e: self.cal,
            clock=env.clock,
        )  # fmt: skip
        self.client = TestClient(create_app(self.runtime))
        if connect_at is not None:
            env.clock.set(connect_at)
            self.response = env.connect(OWNER, "meeting_host", [CALENDAR_EVENTS_OWNED])
        env.clock.set(NOW)

    def call(self, route: str, body: Any = None, *, token: str | None = "good", raw: bytes | None = None) -> Any:
        headers = {} if token is None else {"authorization": f"Bearer {self.good if token == 'good' else token}"}
        data = raw if raw is not None else json.dumps(body).encode()
        return self.client.post(f"/internal/meeting-host/{route}", content=data, headers=headers)

    def send(self, body: dict[str, Any] | None = None) -> dict[str, Any]:
        response = self.call("send", BASE if body is None else body)
        assert response.status_code == 200, response.text
        return response.json()


def with_draft(body: dict[str, Any], **changes: Any) -> dict[str, Any]:
    """The request with its draft document changed and its hash and base64 recomputed."""
    out = copy.deepcopy(body)
    document = json.loads(base64.b64decode(out["draft"]["content_b64"]))
    document.update(changes)
    raw = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    out["draft"].update(content_b64=base64.b64encode(raw).decode(), content_sha256=hashlib.sha256(raw).hexdigest())
    return out


def user_body(user: str = OWNER) -> dict[str, str]:
    return {"user_id": user}


# ---- HB-01: configuration and caller ----------------------------------------------------------


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("missing", [AUDIENCE_VAR, CALLER_VAR])
def test_ADR32_T3_FR_MTG_09_unset_audience_or_caller_is_503_not_configured(route: str, missing: str) -> None:
    rig = Rig(settings={k: v for k, v in {AUDIENCE_VAR: AUD, CALLER_VAR: CALLER}.items() if k != missing})
    response = rig.call(route, BASE if route == "send" else user_body())
    assert (response.status_code, response.json()) == (503, {"error": "not_configured"})
    assert rig.verifier.calls == []


@pytest.mark.parametrize("route", ROUTES)
def test_ADR32_T3_FR_MTG_09_no_valid_token_is_401_and_nothing_is_read_or_done(route: str) -> None:
    rig = Rig()
    body = BASE if route == "send" else user_body()
    for token in (None, "unknown-" + secrets.token_hex(4)):
        response = rig.call(route, body, token=token)
        assert (response.status_code, response.json()) == (401, {"error": "unauthenticated"})
    for header in ("Basic " + rig.good, "Bearer", "Bearer a b", rig.good):
        r = rig.client.post(f"/internal/meeting-host/{route}", content=b"{}", headers={"authorization": header})
        assert r.status_code == 401
    assert rig.cal.requests == []
    big = rig.call(route, raw=b"x" * (MAX_BODY_BYTES + 1), token=None)  # the caller is checked before the body
    assert big.status_code == 401


def test_ADR32_T3_FR_MTG_09_other_accounts_are_403_and_wrong_claims_are_401() -> None:
    rig = Rig()
    harness = rig.verifier.add(email=HARNESS)
    no_email = rig.verifier.add(email=None)
    for token in (harness, no_email):
        response = rig.call("status", user_body(), token=token)
        assert (response.status_code, response.json()) == (403, {"error": "forbidden"})
    for over in ({"email_verified": False}, {"email_verified": "true"}, {"aud": AUD + "/x"}, {"iss": "https://evil"}):
        response = rig.call("status", user_body(), token=rig.verifier.add(**over))
        assert (response.status_code, response.json()) == (401, {"error": "unauthenticated"})
    assert rig.call("status", user_body()).status_code == 200
    assert {"https://accounts.google.com", "accounts.google.com"} == GOOGLE_ISSUERS


def test_ADR32_T3_FR_MTG_09_the_allowed_account_comes_from_the_environment_not_the_request() -> None:
    rig = Rig()
    forged = rig.verifier.add(email=HARNESS)
    body = {**user_body(), "caller": HARNESS}
    assert rig.call("status", body, token=forged).status_code == 403  # the body cannot name the caller
    assert rig.call("status", user_body(), token=forged).status_code == 403


# ---- request shape ----------------------------------------------------------------------------


@pytest.mark.parametrize("route", ROUTES)
def test_ADR32_T3_FR_MTG_09_a_bad_request_is_422_with_a_fixed_body(route: str) -> None:
    rig = Rig()
    good = BASE if route == "send" else user_body()
    bad = [b"not json", b"[]", b"null", json.dumps({**good, "extra": 1}).encode(), b"{}"]
    bad += [b"x" * (MAX_BODY_BYTES + 1), b"[" * 100_000]
    for raw in bad:
        response = rig.call(route, raw=raw)
        assert (response.status_code, response.json()) == (422, {"error": "invalid_request"})
    assert rig.cal.requests == []


def test_ADR32_T3_FR_MTG_09_the_body_cap_is_checked_while_streaming_and_before_parsing() -> None:
    rig = Rig()

    def chunks() -> Any:
        for _ in range(8):
            yield b" " * (MAX_BODY_BYTES // 4)  # no content-length: over the cap only after five chunks

    headers = {"authorization": f"Bearer {rig.good}"}
    response = rig.client.post("/internal/meeting-host/send", content=chunks(), headers=headers)
    assert (response.status_code, response.json()) == (422, {"error": "invalid_request"})
    assert len(json.dumps(BASE)) < MAX_BODY_BYTES  # a real request is under the cap


def test_ADR32_T3_FR_MTG_09_a_request_that_would_break_a_different_route_contract_is_422() -> None:
    rig = Rig()
    assert rig.call("send", user_body()).status_code == 422
    assert rig.call("status", BASE).status_code == 422
    entry_not_queued = copy.deepcopy(BASE)
    entry_not_queued["entry"]["state"] = "sent"
    assert rig.call("send", entry_not_queued).status_code == 422


# ---- status -----------------------------------------------------------------------------------


def test_ADR32_T3_FR_MTG_09_status_reads_the_store_only() -> None:
    rig = Rig()
    assert rig.call("status", user_body()).json() == {"state": "connected", "scope_ok": True}
    assert rig.call("status", user_body("u_nobody")).json() == {"state": "none", "scope_ok": False}
    assert rig.cal.requests == [] and rig.env.google.revoked == []
    rig.env.clock.advance(7200)
    rig.env.google.refresh_mode = "invalid_grant"
    assert rig.call("status", user_body()).json() == {
        "state": "connected",
        "scope_ok": True,
    }  # no token use: no refresh
    rig.send()  # the refresh runs inside a send, which finds out
    assert rig.call("status", user_body()).json() == {"state": "expired", "scope_ok": False}


def test_ADR32_T3_FR_MTG_09_a_grant_without_the_calendar_scope_is_not_scope_ok() -> None:
    rig = Rig(connect_at=None)
    rig.env.connect(OWNER, "meeting_host", ["https://www.googleapis.com/auth/gmail.readonly"])
    assert rig.call("status", user_body()).json() == {"state": "connected", "scope_ok": False}


# ---- send -------------------------------------------------------------------------------------


def test_ADR32_T3_FR_MTG_09_send_makes_one_event_and_answers_a_receipt_that_matches_the_entry() -> None:
    rig = Rig()
    answer = rig.send()
    marker = side_effect_marker(BASE["entry"])
    assert answer["outcome"] == "sent" and answer["parts"] == [] and answer["may_have_sent"] is None
    assert answer["receipt"] == {
        "world_id": BASE["entry"]["world_id"],
        "outbox_id": BASE["entry"]["id"],
        "meeting_id": "mt_weekly1",
        "owner": OWNER,
        "draft": {"artifact_id": "art_meeting_draft", "version": 1},
        "event_ref": marker,
        "conference": "success",
    }
    assert [event.id for event in rig.cal.created()] == [marker]
    assert len(rig.cal.invitations()) == 2


def test_ADR32_T3_FR_MTG_09_a_retried_send_finds_the_earlier_event_and_invites_nobody_twice() -> None:
    rig = Rig()
    first, second = rig.send(), rig.send()  # connectors keeps no outbox state: Google's 409 is the memory (MH-13)
    assert first["outcome"] == second["outcome"] == "sent" and first["receipt"] == second["receipt"]
    assert len(rig.cal.posts()) == 2 and len(rig.cal.invitations()) == 2


@pytest.mark.parametrize(
    "mutate",
    [
        lambda b: b["draft"].update(content_sha256="0" * 64),
        lambda b: b["draft"].update(version=2),
        lambda b: b["draft"].update(artifact_id="art_other"),
        lambda b: b.update(draft=with_draft(b, kind="note")["draft"]),
        lambda b: b.update(draft=with_draft(b, attendees=["eve@example.org"])["draft"]),  # MH-11
        lambda b: b.update(draft=with_draft(b, owner="u_eve")["draft"]),  # MH-11
        lambda b: b["evidence"].update(world_owner="u_eve"),  # MH-11 reads the world owner from the evidence
        lambda b: b["evidence"]["authorised_by"]["data"].update(option="hold"),  # OB-01 on connectors' own outbox
        lambda b: b["entry"].update(recipients=["eve@example.org", "owner@example.com"]),
    ],
)
def test_ADR32_T3_FR_MTG_09_a_draft_or_case_that_does_not_hold_is_refused_and_nothing_reaches_google(
    mutate: Any,
) -> None:
    rig = Rig()
    body = copy.deepcopy(BASE)
    mutate(body)
    answer = rig.send(body)
    assert answer["outcome"] == "refused" and answer["receipt"] is None and answer["may_have_sent"] is None
    assert rig.cal.requests == []


def test_ADR32_T3_FR_MTG_09_a_meeting_that_has_started_is_refused() -> None:
    rig = Rig()
    rig.env.clock.set("2026-10-12T04:30:01.000Z")
    assert rig.send()["outcome"] == "refused" and rig.cal.requests == []


def test_ADR32_T3_FR_MTG_09_HB_06_a_grant_made_after_the_approval_never_sends_it() -> None:
    rig = Rig(connect_at="2026-10-08T09:32:10.000Z")  # half a second after the approval
    answer = rig.send()
    assert answer["outcome"] == "refused" and rig.cal.requests == []
    assert rig.call("status", user_body()).json()["state"] == "connected"  # the grant itself is fine


def test_ADR32_T3_FR_MTG_09_HB_06_a_grant_made_at_the_moment_of_approval_sends() -> None:
    assert Rig(connect_at=APPROVED_AT).send()["outcome"] == "sent"


def test_ADR32_T3_FR_MTG_09_HB_06_a_revoke_and_reconnect_after_the_approval_refuses_it() -> None:
    rig = Rig()
    rig.call("disconnect", user_body())
    rig.env.clock.set("2026-10-08T09:32:30.000Z")
    rig.env.connect(OWNER, "meeting_host", [CALENDAR_EVENTS_OWNED])
    rig.env.clock.set(NOW)
    assert rig.send()["outcome"] == "refused" and rig.cal.requests == []


def test_ADR32_T3_FR_MTG_09_HB_06_check_and_token_fetch_are_one_locked_step() -> None:
    rig = Rig()
    broker = rig.runtime._broker.get()
    token = broker.access_token_for_adapter(OWNER, "meeting_host", required_scopes=[CALENDAR_EVENTS_OWNED])
    assert token in rig.env.google.issued_access
    with pytest.raises(Exception, match="after the approval"):
        broker.access_token_for_adapter(
            OWNER, "meeting_host", required_scopes=[CALENDAR_EVENTS_OWNED], not_before="2026-10-08T08:00:00.000Z"
        )


def test_ADR32_T3_FR_MTG_09_HB_06_a_record_without_a_readable_connected_at_is_refused() -> None:
    rig = Rig()
    record = rig.env.store.get(OWNER, "meeting_host") or {}
    record.pop("connected_at")  # also breaks the seal, so the record cannot be used at all
    rig.env.store.put(OWNER, "meeting_host", record)
    answer = rig.send()
    assert answer["outcome"] in ("retry", "refused") and answer["may_have_sent"] in (False, None)
    assert rig.cal.requests == []


def test_ADR32_T3_FR_MTG_09_not_connected_is_retry_with_nothing_sent() -> None:
    rig = Rig(connect_at=None)
    answer = rig.send()
    assert (answer["outcome"], answer["may_have_sent"], answer["receipt"]) == ("retry", False, None)
    assert rig.cal.requests == []


def test_ADR32_T3_FR_MTG_09_an_expired_grant_is_retry_false_and_the_expiry_rides_the_answer() -> None:
    rig = Rig()
    rig.env.clock.advance(7200)
    rig.env.google.refresh_mode = "invalid_grant"
    answer = rig.send()
    assert (answer["outcome"], answer["may_have_sent"]) == ("retry", False)
    assert answer["parts"] == [{"type": "connection.expired", "connector": "meeting_host", "user_id": OWNER}]
    assert rig.cal.requests == []


def test_ADR32_T3_FR_MTG_09_a_missing_scope_is_retry_false() -> None:
    rig = Rig(connect_at=None)
    rig.env.clock.set(BEFORE)
    rig.env.connect(OWNER, "meeting_host", ["https://www.googleapis.com/auth/gmail.readonly"])
    rig.env.clock.set(NOW)
    answer = rig.send()
    assert (answer["outcome"], answer["may_have_sent"]) == ("retry", False) and rig.cal.requests == []


def test_ADR32_T3_FR_MTG_09_a_google_5xx_or_a_lost_answer_is_retry_with_may_have_sent() -> None:
    rig = Rig()
    rig.cal.fail_next(503)
    answer = rig.send()
    assert (answer["outcome"], answer["may_have_sent"]) == ("retry", True)
    rig2 = Rig()
    rig2.cal.lose_answer_after_create()
    answer2 = rig2.send()
    assert (answer2["outcome"], answer2["may_have_sent"]) == ("retry", True)
    assert rig2.send()["outcome"] == "sent" and len(rig2.cal.invitations()) == 2  # the retry reads the event


def test_ADR32_T3_FR_MTG_09_a_google_400_is_refused_and_a_foreign_event_is_possibly_sent() -> None:
    rig = Rig()
    rig.cal.fail_next(400)
    assert rig.send()["outcome"] == "refused"
    rig2 = Rig()
    rig2.cal.answer_id = "f" * 32
    assert rig2.send()["outcome"] == "possibly_sent"


def test_ADR32_T3_FR_MTG_09_a_rate_limit_part_rides_the_answer_of_the_call_that_caused_it() -> None:
    rig = Rig()
    rig.cal.fail_next(429, headers={"retry-after": "1"}, times=5)
    answer = rig.send()
    assert answer["outcome"] == "retry"
    assert {"type": "connection.rate_limited", "connector": "meeting_host", "user_id": OWNER} in answer["parts"]


def test_ADR32_T3_FR_MTG_09_the_sink_keeps_only_the_calls_own_connection_parts() -> None:
    rig = Rig()
    runtime = rig.runtime
    runtime._emit(
        {"type": "connection.revoked", "data": {"connector": "meeting_host"}, "user_id": OWNER}
    )  # no call open
    with runtime.capture(OWNER) as parts:
        for user, connector, kind in (
            ("u_other", "meeting_host", "connection.revoked"),
            (OWNER, "gmail", "connection.revoked"),
            (OWNER, "meeting_host", "connection.established"),
            (OWNER, "meeting_host", "data.transfer"),
        ):
            runtime._emit({"type": kind, "data": {"connector": connector}, "user_id": user})
        runtime._alert({"type": "alert.raised", "data": {"alert_id": "A" * 26}, "user_id": "u_other"})
        for _ in range(40):
            runtime._emit({"type": "connection.expired", "data": {"connector": "meeting_host"}, "user_id": OWNER})
    assert len(parts.items) == 16 and {p["type"] for p in parts.items} == {"connection.expired"}


def test_ADR32_T3_FR_MTG_09_two_calls_at_once_each_get_their_own_parts() -> None:
    rig = Rig()
    results: dict[str, list[dict[str, str]]] = {}

    def run(user: str) -> None:
        with rig.runtime.capture(user) as parts:
            barrier.wait(timeout=5)
            rig.runtime._emit({"type": "connection.revoked", "data": {"connector": "meeting_host"}, "user_id": user})
            barrier.wait(timeout=5)
        results[user] = parts.items

    barrier = threading.Barrier(2)
    threads = [threading.Thread(target=run, args=(u,)) for u in ("u_a", "u_b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert [p["user_id"] for p in results["u_a"]] == ["u_a"] and [p["user_id"] for p in results["u_b"]] == ["u_b"]


# ---- disconnect and the revoke retry ----------------------------------------------------------


def test_ADR32_T3_FR_MTG_09_disconnect_revokes_deletes_and_is_idempotent() -> None:
    rig = Rig()
    answer = rig.call("disconnect", user_body()).json()
    assert answer == {
        "revoked_at_provider": True,
        "parts": [{"type": "connection.revoked", "connector": "meeting_host", "user_id": OWNER}],
    }
    assert rig.env.google.revoked and rig.env.store.get(OWNER, "meeting_host") is None
    assert rig.call("disconnect", user_body()).json() == {"revoked_at_provider": False, "parts": []}
    assert rig.call("status", user_body()).json() == {"state": "none", "scope_ok": False}


def test_ADR32_T3_FR_MTG_09_a_failed_revoke_is_kept_and_alerted_and_the_hook_retries_it() -> None:
    rig = Rig()
    rig.env.google.revoke_mode = "unavailable"
    answer = rig.call("disconnect", user_body()).json()
    kinds = [part["type"] for part in answer["parts"]]
    assert answer["revoked_at_provider"] is False and kinds == ["alert.raised", "connection.revoked"]
    assert rig.env.store.get(OWNER, "meeting_host") is None  # fail toward deletion
    rig.env.google.revoke_mode = "ok"
    assert rig.runtime.retry_pending_revokes(OWNER) == 1
    assert rig.runtime.retry_pending_revokes(OWNER) == 0


def test_ADR32_T3_FR_MTG_09_a_send_after_a_disconnect_began_is_refused_not_retried() -> None:
    rig = Rig()
    rig.runtime._closing.add(OWNER)  # what disconnect sets while it runs
    answer = rig.send()
    assert answer["outcome"] == "refused" and rig.cal.requests == []
    rig.runtime._closing.discard(OWNER)
    assert rig.send()["outcome"] == "sent"


# ---- nothing secret crosses -------------------------------------------------------------------


def test_ADR32_T3_FR_MTG_09_no_token_secret_link_or_address_is_in_any_answer_or_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    rig = Rig()
    rig.cal.fail_next(503)
    texts = [rig.call("send", BASE).text, rig.call("send", BASE).text]  # a retry, then a sent
    rig.cal.fail_next(400)
    texts += [rig.call("send", with_draft(BASE, title="other")).text]
    texts += [rig.call("status", user_body()).text, rig.call("disconnect", user_body()).text]
    texts += [rig.call("send", {"x": 1}).text, rig.call("status", user_body(), token="nope").text]
    secrets_ = [*rig.env.google.issued_access, rig.env.secrets["client_secret"], rig.good]
    secrets_ += rig.cal.plant.needles() + ["owner@example.com", "invitee@example.org", "Weekly planning"]
    blob = "\n".join(texts) + caplog.text
    assert [s for s in secrets_ if s in blob] == []
    assert rig.response is not None and rig.response["refresh_token"] not in blob


def test_ADR32_T3_FR_MTG_09_an_unexpected_failure_is_a_fixed_503_that_names_only_a_type(
    caplog: pytest.LogCaptureFixture,
) -> None:
    rig = Rig()
    leak = "sk-" + secrets.token_hex(6)

    def boom(*_: Any, **__: Any) -> Any:
        raise RuntimeError(leak)

    rig.runtime.status = boom  # type: ignore[method-assign]
    response = rig.call("status", user_body())
    assert (response.status_code, response.json()) == (503, {"error": "not_configured"})
    assert leak not in response.text + caplog.text and "RuntimeError" in caplog.text


def test_ADR32_T3_FR_MTG_09_an_unconfigured_broker_is_503_and_health_still_answers() -> None:
    rig = Rig()
    rig.runtime._broker._opener = lambda *a, **k: (_ for _ in ()).throw(BrokerNotConfigured("set TILO_KMS_KEY"))
    response = rig.call("status", user_body())
    assert (response.status_code, response.json()) == (503, {"error": "not_configured"})
    assert rig.client.get("/health").json() == {"status": "ok"}


# ---- the verifier -----------------------------------------------------------------------------


class _Certs:
    """google-auth's `Request` shape: counts fetches and serves one certificate set."""

    def __init__(self, certs: dict[str, str] | None = None, status: int = 200) -> None:
        self.certs, self.status, self.calls = certs or {}, status, 0

    def __call__(self, url: str, method: str = "GET", **_: Any) -> Any:
        self.calls += 1
        return type("R", (), {"status": self.status, "data": json.dumps(self.certs).encode()})()


def _signed(claims: dict[str, Any], kid: str = "k1") -> tuple[str, dict[str, str]]:
    import datetime as dt

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    from google.auth import crypt, jwt

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "t")])
    now = dt.datetime.now(dt.UTC)
    cert = (
        x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(1).not_valid_before(now - dt.timedelta(days=1)).not_valid_after(now + dt.timedelta(days=1))
        .sign(key, hashes.SHA256())
    )  # fmt: skip
    pem = cert.public_bytes(serialization.Encoding.PEM).decode()
    private = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    signer = crypt.RSASigner.from_string(private, key_id=kid)
    stamps = {"iat": int(now.timestamp()), "exp": int(now.timestamp()) + 600}
    return jwt.encode(signer, {**stamps, **claims}).decode(), {kid: pem}


def test_ADR32_T3_FR_MTG_09_the_google_verifier_checks_the_signature_with_cached_certificates() -> None:
    claims = {"iss": "https://accounts.google.com", "aud": AUD, "email": CALLER, "email_verified": True}
    token, certs = _signed(claims)
    transport = _Certs(certs)
    verifier = GoogleOidcVerifier(transport=transport, clock=lambda: 100.0)
    assert verifier.verify(token, AUD)["email"] == CALLER
    assert verifier.verify(token, AUD)["email"] == CALLER and transport.calls == 1
    head, body, sig = token.split(".")
    for forged in (f"{head}.{body}.{sig[:-4]}AAAA", f"{head}.{body[:-2]}xx.{sig}"):
        with pytest.raises(Exception, match=".+"):
            verifier.verify(forged, AUD)


def test_ADR32_T3_FR_MTG_09_a_token_that_is_not_ours_is_refused_before_any_certificate_fetch() -> None:
    other, certs = _signed({"iss": "https://evil.example", "aud": AUD})
    wrong_aud, _ = _signed({"iss": "https://accounts.google.com", "aud": "https://elsewhere"})
    transport = _Certs(certs)
    verifier = GoogleOidcVerifier(transport=transport)
    for token in ("", "a.b", "a.b.c", "x" * 5000, other, wrong_aud, "e30.e30.sig", "!!.!!.!!"):
        with pytest.raises(Exception, match=".+"):
            verifier.verify(token, AUD)
    assert transport.calls == 0


def test_ADR32_T3_FR_MTG_09_certificate_fetches_are_rate_limited_and_a_failed_fetch_keeps_nothing() -> None:
    claims = {"iss": "https://accounts.google.com", "aud": AUD}
    token, certs = _signed(claims, kid="k9")
    now = [0.0]
    down = _Certs({}, status=500)
    verifier = GoogleOidcVerifier(transport=down, clock=lambda: now[0])
    for _ in range(3):
        with pytest.raises(Exception, match=".+"):
            verifier.verify(token, AUD)
    assert down.calls == 1  # the cooldown stops a hammering caller
    now[0] += 31
    verifier._transport = _Certs(certs)
    assert verifier.verify(token, AUD)["aud"] == AUD


# ---- the T2 follow-ups ------------------------------------------------------------------------


def test_ADR32_T3_FR_MTG_09_emit_and_alert_are_required_keywords() -> None:
    with pytest.raises(TypeError):
        open_broker(_env())  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        open_broker(_env(), emit=lambda part: None)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        BrokerSeam(_env(), emit=lambda part: None)  # type: ignore[call-arg]


def test_ADR32_T3_FR_MTG_09_the_seam_builds_without_its_lock_and_lets_go_of_the_environment() -> None:
    seen: list[bool] = []
    seam: BrokerSeam

    def opener(env: Any, **wiring: Any) -> Any:
        seen.append(seam._lock.locked())  # a slow client build must not stall every other request
        return object()

    seam = BrokerSeam(_env(), emit=lambda p: None, alert=lambda p: None, opener=opener)
    assert seam._env is not None
    built = seam.get()
    assert seen == [False] and seam._env is None and seam.get() is built


def test_ADR32_T3_FR_MTG_09_a_junk_document_is_present_but_unreadable_and_disconnect_clears_it() -> None:
    client = FakeFirestore()
    broker = _build(client=client, alert=lambda part: None)
    path = ("token_grants", "u_owner", "connectors", "meeting_host")
    for junk in ({}, {"record": "text"}, {"record": None}, {"other": 1}):
        client.docs[path] = junk
        assert broker.connection_state("u_owner", "meeting_host") == "expired"
        with pytest.raises(Exception, match="expired"):
            broker.access_token_for_adapter("u_owner", "meeting_host", required_scopes=[CALENDAR_EVENTS_OWNED])
        assert broker.disconnect("u_owner", "meeting_host").revoked_at_provider is False
        assert path not in client.docs
    client.docs[path] = {"x": 1}
    broker.store_tokens("u_owner", "meeting_host", _grant())  # a new consent replaces it
    assert broker.connection_state("u_owner", "meeting_host") == "connected"


@pytest.mark.parametrize("key", ["projects/demo-tilo/locations/asia-southeast1/keyRings/tilo/cryptoKeys/жж"])
def test_ADR32_T3_FR_MTG_09_the_kms_key_name_is_ascii_only(key: str) -> None:
    with pytest.raises(BrokerNotConfigured):
        _build({**_env(), "TILO_KMS_KEY": key}, alert=lambda part: None)


def test_ADR32_T3_FR_MTG_09_connected_at_is_the_repair_time_after_every_forged_record() -> None:
    client, clock = FakeFirestore(), ManualClock("2026-10-08T09:00:00.000Z")
    broker = _build(client=client, clock=clock, alert=lambda part: None)
    broker.store_tokens("u_owner", "meeting_host", _grant())
    record = client.docs[("token_grants", "u_owner", "connectors", "meeting_host")]["record"]
    for forged in ("2030-01-01T00:00:00.000Z", "2000-01-01T00:00:00.000Z", None):
        clock.advance(600)
        record = client.docs[("token_grants", "u_owner", "connectors", "meeting_host")]["record"]
        if forged is None:
            record.pop("connected_at")
        else:
            record["connected_at"] = forged
        broker.store_tokens("u_owner", "meeting_host", _grant())  # the unreadable record is replaced, not kept
        assert broker.connected_at("u_owner", "meeting_host") == clock()
        assert (
            client.docs[("token_grants", "u_owner", "connectors", "meeting_host")]["record"]["connected_at"] == clock()
        )


def test_ADR32_T3_FR_MTG_09_a_persons_disconnect_leaves_the_bot_grant_and_revokes_no_bot_token() -> None:
    client, http = FakeFirestore(), FakeHttp()
    broker = _build(client=client, http=http, alert=lambda part: None)
    broker.store_tokens("u_owner", "meeting_host", _grant())
    broker.store_tokens("u_owner", "gmail", _grant(scope="https://www.googleapis.com/auth/gmail.readonly"))
    bot = copy.deepcopy(client.docs[("token_grants", "u_owner", "connectors", "meeting_host")])
    result = broker.disconnect("u_owner", "gmail")
    assert result.revoked_at_provider is True
    assert client.docs[("token_grants", "u_owner", "connectors", "meeting_host")] == bot
    assert http.calls.count(REVOKE_URL) == 1  # the person's own grant only
    assert broker.access_token_for_adapter("u_owner", "meeting_host", required_scopes=[CALENDAR_EVENTS_OWNED])
