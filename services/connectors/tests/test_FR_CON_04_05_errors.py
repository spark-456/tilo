"""FR-CON-04 / FR-CON-05: token errors, rate limits and 5xx (PRD 11.5 re-consent, 12.1 token broker,
NFR-26). Never a crash: every failure is a typed error, and in the outbox an entry stays due until it
can run. API_FR_CON_04_05.md "Errors, retries and events".
"""

from __future__ import annotations

import time

import pytest
from _gapi_lib import DRIVE_UPLOAD_API, GMAIL_API, drive_case, enqueue, gmail_case, make_gapi_env
from _oauth_lib import EXPIRES_IN, GMAIL_READONLY, GMAIL_SEND, OWNER, validate_part


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    def refuse(_seconds):
        raise AssertionError("adapters wait through the injected sleep, never time.sleep")

    monkeypatch.setattr(time, "sleep", refuse)


def _thread(g):
    g.apis.seed_message(thread_id="thr_supplier_1", subject="Delivery date")


def _gmail_reads(g):
    return [r for r in g.apis.requests if r.url == f"{GMAIL_API}/labels"]


# ---------------------------------------------------------------------------
# Token errors


def test_FR_CON_04_an_expired_access_token_is_refreshed_through_the_broker():
    g = make_gapi_env()
    before = len(g.env.google.refresh_calls())
    g.env.clock.advance(EXPIRES_IN + 1)

    g.gmail.list_labels(OWNER)

    assert len(g.env.google.refresh_calls()) == before + 1
    assert _gmail_reads(g)[-1].token == g.env.google.issued_access[-1], "the call used the refreshed token"


def test_FR_CON_05_an_expired_access_token_is_refreshed_through_the_broker():
    g = make_gapi_env()
    fid = g.apis.seed_file(name="a.pdf")
    g.picks.add(OWNER, [fid])
    g.env.clock.advance(EXPIRES_IN + 1)

    g.drive.get_metadata(OWNER, fid)

    assert len(g.env.google.refresh_calls()) == 1
    assert g.apis.requests[-1].token == g.env.google.issued_access[-1]


def test_FR_CON_04_a_401_gets_one_fresh_token_and_one_retry():
    """Google can drop a token before Tilo's clock says it expired."""
    g = make_gapi_env()
    g.gmail.list_labels(OWNER)
    stale = _gmail_reads(g)[-1].token
    g.apis.reject_token(stale)

    labels = g.gmail.list_labels(OWNER)

    assert labels
    assert len(g.env.google.refresh_calls()) == 1
    reads = _gmail_reads(g)
    assert len(reads) == 3, "one failed try with the stale token, one retry"
    assert reads[-1].token not in (stale, None)


def test_FR_CON_04_access_revoked_at_google_expires_the_connection_and_says_so_once():
    from tilo_connectors.tokens import ConnectionExpired

    g = make_gapi_env()
    g.gmail.list_labels(OWNER)
    g.apis.reject_token(_gmail_reads(g)[-1].token)
    g.env.google.refresh_mode = "invalid_grant"  # the person removed Tilo in their Google account

    with pytest.raises(ConnectionExpired):
        g.gmail.list_labels(OWNER)
    with pytest.raises(ConnectionExpired):
        g.gmail.list_labels(OWNER)

    expired = g.parts_of("connection.expired")
    assert len(expired) == 1
    validate_part(expired[0])
    assert expired[0]["data"] == {"connector": "gmail"}
    assert g.env.broker.connection_state(OWNER, "gmail") == "expired"


def test_FR_CON_04_an_expired_connection_during_a_send_never_crashes_and_sends_nothing():
    g = make_gapi_env()
    _thread(g)
    enqueue(g.outbox, gmail_case(item=g.artifacts.put_email("art_r1"), destination="thr_supplier_1"))
    g.env.clock.advance(EXPIRES_IN + 1)
    g.env.google.refresh_mode = "invalid_grant"

    assert g.outbox.dispatch_due() == []  # does not raise

    assert g.apis.sent() == []
    assert [p for p in g.emitted if p["type"] == "data.transfer"] == []
    assert len(g.parts_of("connection.expired")) == 1

    g.env.connect(OWNER, "gmail", [GMAIL_READONLY, GMAIL_SEND])  # the person reconnects (re-consent)
    g.env.google.refresh_mode = "ok"
    settled = g.outbox.dispatch_due()

    assert [e["state"] for e in settled] == ["sent"]
    assert len(g.apis.sent()) == 1


def test_FR_CON_04_a_missing_send_scope_asks_for_incremental_consent_then_sends_once():
    """FR-CON-03: only the missing scope is asked for, when needed; nothing is sent before it."""
    g = make_gapi_env(gmail_scopes=[GMAIL_READONLY])
    _thread(g)
    enqueue(g.outbox, gmail_case(item=g.artifacts.put_email("art_r1"), destination="thr_supplier_1"))

    assert g.outbox.dispatch_due() == []
    assert g.apis.writes() == []
    assert g.env.service.scopes_needed(user_id=OWNER, connector="gmail", capabilities=["send"]) == [GMAIL_SEND]

    g.env.connect(OWNER, "gmail", [GMAIL_READONLY, GMAIL_SEND])
    settled = g.outbox.dispatch_due()

    assert [e["state"] for e in settled] == ["sent"]
    assert len(g.apis.sent()) == 1


def test_FR_CON_04_insufficient_scope_names_only_the_missing_scope():
    from tilo_connectors.tokens import InsufficientScope

    g = make_gapi_env(gmail_scopes=[GMAIL_SEND])
    with pytest.raises(InsufficientScope) as raised:
        g.gmail.get_message(OWNER, "m1")
    assert raised.value.missing == [GMAIL_READONLY]
    assert g.apis.requests == []


def test_FR_CON_05_no_drive_connection_is_a_typed_error_and_a_save_stays_due():
    from tilo_connectors.tokens import NotConnected

    g = make_gapi_env(drive_scopes=None)
    fid = g.apis.seed_file(name="a.pdf")
    g.picks.add(OWNER, [fid])
    with pytest.raises(NotConnected):
        g.drive.get_metadata(OWNER, fid)

    enqueue(g.outbox, drive_case(item=g.artifacts.put_file("art_r1")))
    assert g.outbox.dispatch_due() == []
    assert g.apis.writes() == []


# ---------------------------------------------------------------------------
# Rate limits and 5xx: bounded retry through the injected sleep


def test_FR_CON_04_a_429_waits_retry_after_retries_and_says_so():
    g = make_gapi_env()
    g.apis.fail_next(429, headers={"Retry-After": "7"})

    labels = g.gmail.list_labels(OWNER)

    assert labels
    assert g.sleeps == [7]
    (part,) = g.parts_of("connection.rate_limited")
    validate_part(part)
    assert part["data"] == {"connector": "gmail", "retry_after_s": 7}
    assert part["user_id"] == OWNER


def test_FR_CON_04_a_429_that_never_clears_raises_rate_limited_after_three_requests():
    from tilo_connectors.adapters import RateLimited

    g = make_gapi_env()
    g.apis.fail_next(429, times=10, headers={"Retry-After": "2"})

    with pytest.raises(RateLimited) as raised:
        g.gmail.list_labels(OWNER)

    assert raised.value.retry_after_s == 2
    assert len(g.apis.requests) == 3
    assert sum(g.sleeps) <= 60


def test_FR_CON_04_a_retry_after_over_60_seconds_is_not_waited():
    from tilo_connectors.adapters import RateLimited

    g = make_gapi_env()
    g.apis.fail_next(429, times=10, headers={"Retry-After": "3600"})

    with pytest.raises(RateLimited) as raised:
        g.gmail.list_labels(OWNER)

    assert raised.value.retry_after_s == 3600
    assert sum(g.sleeps) <= 60
    assert [p["data"]["retry_after_s"] for p in g.parts_of("connection.rate_limited")][:1] == [3600]


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_FR_CON_04_a_5xx_is_retried_at_most_three_times_then_provider_unavailable(status):
    from tilo_connectors.adapters import ProviderUnavailable

    g = make_gapi_env()
    g.apis.fail_next(status, times=10)

    with pytest.raises(ProviderUnavailable):
        g.gmail.list_labels(OWNER)

    assert len(g.apis.requests) == 3
    assert len(g.sleeps) <= 2 and sum(g.sleeps) <= 60


def test_FR_CON_04_a_5xx_that_clears_on_retry_returns_the_result():
    g = make_gapi_env()
    g.apis.fail_next(503, times=2)

    assert g.gmail.list_labels(OWNER)
    assert len(g.apis.requests) == 3


def test_FR_CON_04_a_lost_read_response_is_retried():
    g = make_gapi_env()
    g.apis.lose_response(lambda r: r.url == f"{GMAIL_API}/labels")

    assert g.gmail.list_labels(OWNER)
    assert len(_gmail_reads(g)) == 2


def test_FR_CON_04_a_404_is_one_request_and_a_typed_error():
    from tilo_connectors.adapters import AdapterError

    g = make_gapi_env()

    with pytest.raises(AdapterError):
        g.gmail.get_message(OWNER, "missing_message")

    assert len(g.apis.requests) == 1
    assert g.sleeps == []


def test_FR_CON_05_a_5xx_on_drive_read_is_bounded_too():
    from tilo_connectors.adapters import ProviderUnavailable

    g = make_gapi_env()
    fid = g.apis.seed_file(name="a.pdf")
    g.picks.add(OWNER, [fid])
    g.apis.fail_next(500, times=10)

    with pytest.raises(ProviderUnavailable):
        g.drive.get_metadata(OWNER, fid)

    assert len(g.apis.requests) == 3


def test_FR_CON_04_a_send_hitting_5xx_stays_due_and_sends_once_after_recovery():
    g = make_gapi_env()
    _thread(g)
    case = gmail_case(item=g.artifacts.put_email("art_r1"), destination="thr_supplier_1")
    enqueue(g.outbox, case)
    g.apis.fail_next(503, times=10, when=lambda r: r.method == "POST")

    assert g.outbox.dispatch_due() == []
    assert g.apis.sent() == []
    assert len([r for r in g.apis.requests if r.method == "POST"]) <= 3

    g.apis.clear_failures()  # Google recovered
    settled = g.outbox.dispatch_due()

    assert [e["id"] for e in settled] == [case["entry"]["id"]]
    assert len(g.apis.sent()) == 1
    assert len([p for p in g.emitted if p["type"] == "data.transfer"]) == 1


def test_FR_CON_05_an_upload_hitting_429_stays_due_and_uploads_once_after_recovery():
    g = make_gapi_env()
    enqueue(g.outbox, drive_case(item=g.artifacts.put_file("art_r1", name="once.pdf")))
    g.apis.fail_next(429, times=10, headers={"Retry-After": "1"}, when=lambda r: r.url == DRIVE_UPLOAD_API)

    assert g.outbox.dispatch_due() == []
    g.apis.clear_failures()
    g.outbox.dispatch_due()

    assert len([f for f in g.apis.files.values() if f.name == "once.pdf"]) == 1
    for part in g.parts_of("connection.rate_limited"):
        validate_part(part)
        assert part["data"]["connector"] == "google_drive"
