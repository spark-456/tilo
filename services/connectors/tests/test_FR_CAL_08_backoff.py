"""FR-CAL-08: failures, backoff, the per-person request cap and the page guards. PRD addendum 3.4 FR-CAL-08
("the Calendar API is free" is no licence to hammer it), API_FR_CAL_08.md "Failures, retries and backoff"
(`backoff(n) = min(backoff_base_s * 2 ** (n - 1), backoff_max_s)`, `n` = failures in a row, this one
included; Retry-After capped at MAX_RETRY_AFTER_S = 86400), "Fetching" (page_loop, too_many_pages,
local_rate_limit: more than per_minute requests for one person in the 60 s ending now), hostile cases
"Backoff", "Page loops", "Scope".

Every test fails today with ModuleNotFoundError: tilo_connectors.calendar_sync (or .calendar_cache,
.adapters.calendar).
"""

from __future__ import annotations

import time as real_time
from datetime import UTC, datetime, timedelta

import pytest
from _calendar_lib import (
    DANA,
    ORG_B,
    PRIYA,
    W_DANA,
    backoff,
    make_cal_env,
    outcome_for,
    plus,
    recording_store,
    run_ticks,
)
from _connectors_lib import parse_ts
from _oauth_lib import GMAIL_READONLY, validate_part
from hypothesis import given, settings
from hypothesis import strategies as st

OPEN = "2026-10-07T03:30:00.000Z"  # 09:00 in Asia/Kolkata
BASE = datetime(2026, 10, 8, 4, 0, tzinfo=UTC)
DAY = 86_400


def _only(outcomes, user=PRIYA):
    return outcome_for(outcomes, user)


def _events(ce, n=3, user=PRIYA):
    for k in range(n):
        ce.cal.add_event(user, f"evt{k}", f"Event {k}", BASE + timedelta(days=k), BASE + timedelta(days=k, hours=1))


def test_FR_CAL_08_the_module_constants_are_the_pinned_ones():
    from tilo_connectors import calendar_sync as mod

    assert mod.CONNECTOR_ID == "google_calendar"
    assert mod.SEAL_CONTEXT == b"tilo.calendar_sync.v1"
    assert mod.MAX_RETRY_AFTER_S == 86400
    assert mod.CLOCK_SKEW_S == 300


# ---------------------------------------------------------------------------
# 503: +60, +120, +240, +480, then a sync resets


def test_FR_CAL_08_four_503s_in_a_row_are_retried_at_60_120_240_480_seconds_and_a_sync_resets():
    store = recording_store()
    ce = make_cal_env(start=OPEN, store=store)
    _events(ce)
    ce.cal.fail_next(503, times=4)
    t = ce.now()

    for n, gap in enumerate((60, 120, 240, 480), start=1):
        out = _only(ce.run())
        assert (out.status, out.reason, out.requests, out.kind, out.changed, out.emitted) == (
            "failed",
            "unavailable",
            1,
            None,
            0,
            False,
        )
        state = ce.state()
        assert (state.failures, state.generation, state.last_run_at) == (n, n, t)
        assert state.next_due_at == plus(t, gap), f"failure {n}: +{gap} s"
        assert state.sealed_token is None
        assert store.commits[-1] == (True, n, [], []), "a failure is a compare-and-set commit with no entries"
        ce.set_clock(plus(t, gap - 1))
        waiting = _only(ce.run())
        assert (waiting.status, waiting.reason, waiting.requests) == ("skipped", "backing_off", 0)
        t = plus(t, gap)
        ce.set_clock(t)

    ok = _only(ce.run())

    assert (ok.status, ok.kind, ok.changed) == ("synced", "full", 3)
    state = ce.state()
    assert state.failures == 0 and state.next_due_at == plus(t, 900), "a sync resets the count"
    assert len(ce.cal.requests_of(PRIYA)) == 5


def test_FR_CAL_08_the_backoff_doubles_up_to_the_cap_and_stays_there():
    ce = make_cal_env(start=OPEN)
    _events(ce)
    ce.cal.fail_next(503, times=9)
    waits = []

    for n in range(1, 10):
        ce.set_clock(f"2026-10-{7 + n:02d}T05:00:00.000Z")  # a new day each time: always due, always inside
        now = ce.now()
        out = _only(ce.run())
        assert out.reason == "unavailable"
        waits.append(int((parse_ts(ce.state().next_due_at) - parse_ts(now)).total_seconds()))

    assert waits == [60, 120, 240, 480, 960, 1920, 3600, 3600, 3600]


@settings(max_examples=25, deadline=None)
@given(st.integers(1, 100), st.integers(0, 4000), st.integers(1, 6))
def test_FR_CAL_08_property_the_next_due_time_is_min_base_times_two_to_n_minus_one_and_the_cap(base, extra, n):
    cap = base + extra
    ce = make_cal_env(start=OPEN, backoff_base_s=base, backoff_max_s=cap)
    _events(ce, 1)
    ce.cal.fail_next(503, times=n)

    for k in range(1, n + 1):
        now = ce.now()
        out = _only(ce.run())
        assert out.status == "failed"
        assert ce.state().next_due_at == plus(now, backoff(base, cap, k)), (base, cap, k)
        ce.set_clock(ce.state().next_due_at)


# ---------------------------------------------------------------------------
# 429 and Retry-After


@pytest.mark.parametrize(
    "header, wait",
    [
        ("120", 120),
        ("86400", 86400),
        ("86401", 86400),
        ("999999", 86400),
        ("999999999999", 86400),
        ("5", 60),  # max(backoff(1) = 60, 5)
        ("0", 60),
        (None, 60),
        ("Wed, 21 Oct 2026 07:28:00 GMT", 60),  # an HTTP date is not a number of seconds: the backoff applies
    ],
)
def test_FR_CAL_08_a_429_waits_the_larger_of_retry_after_and_the_backoff_capped_at_86400(header, wait):
    ce = make_cal_env(start=OPEN)
    _events(ce)
    ce.cal.fail_next(429, retry_after=header)
    now = ce.now()

    out = _only(ce.run())

    assert (out.status, out.reason, out.requests) == ("failed", "rate_limited", 1)
    assert ce.state().next_due_at == plus(now, wait)
    (part,) = ce.env.parts_of("connection.rate_limited")
    validate_part(part)
    assert part["data"]["connector"] == "google_calendar" and part["user_id"] == PRIYA
    if header is not None and header.isdigit():
        assert part["data"]["retry_after_s"] == int(header) or int(header) > 999_999


def test_FR_CAL_08_a_retry_after_of_120_emits_one_part_and_waits_exactly_120_seconds():
    ce = make_cal_env(start=OPEN)
    _events(ce)
    ce.cal.fail_next(429, retry_after=120)
    t = ce.now()

    out = _only(ce.run())

    assert out.reason == "rate_limited" and len(ce.env.parts_of("connection.rate_limited")) == 1
    assert ce.env.parts_of("connection.rate_limited")[0]["data"] == {
        "connector": "google_calendar",
        "retry_after_s": 120,
    }
    ce.set_clock(plus(t, 119))
    assert _only(ce.run()).reason == "backing_off"
    ce.set_clock(plus(t, 120))
    assert _only(ce.run()).status == "synced"


def test_FR_CAL_08_the_backoff_wins_when_it_is_longer_than_retry_after():
    ce = make_cal_env(start=OPEN)
    _events(ce)
    ce.cal.fail_next(429, retry_after=30, times=2)
    t = ce.now()
    _only(ce.run())
    assert ce.state().next_due_at == plus(t, 60)
    ce.set_clock(plus(t, 60))

    _only(ce.run())

    assert ce.state().next_due_at == plus(plus(t, 60), 120), "max(backoff(2) = 120, 30)"
    assert len(ce.env.parts_of("connection.rate_limited")) == 2


# ---------------------------------------------------------------------------
# The failure table


def _inject_503(ce):
    ce.cal.fail_next(503)


def _inject_500(ce):
    ce.cal.fail_next(500)


def _inject_lost(ce):
    ce.cal.fail_next(None)


def _inject_403(ce):
    ce.cal.fail_next(403)


def _inject_404(ce):
    ce.cal.fail_next(404)


def _inject_400(ce):
    ce.cal.fail_next(400)


def _inject_410_on_full(ce):
    ce.cal.fail_next(410)


def _inject_malformed_list(ce):
    ce.cal.override_next([1, 2, 3])


def _inject_malformed_items(ce):
    ce.cal.override_next({"items": "nope", "nextSyncToken": "tok"})


def _inject_malformed_both_tokens(ce):
    ce.cal.override_next({"items": [], "nextPageToken": "a", "nextSyncToken": "b"})


def _inject_expired_connection(ce):
    ce.set_clock("2026-10-07T05:00:00.000Z")  # the access token (1 h) has expired: the broker refreshes
    ce.env.google.refresh_mode = "invalid_grant"


def _inject_refresh_unavailable(ce):
    ce.set_clock("2026-10-07T05:00:00.000Z")
    ce.env.google.refresh_mode = "unavailable"


FAILURES = {
    "503": (_inject_503, "unavailable", 60),
    "500": (_inject_500, "unavailable", 60),
    "a lost answer": (_inject_lost, "unavailable", 60),
    "403": (_inject_403, "rejected", 60),
    "404": (_inject_404, "rejected", 60),
    "400": (_inject_400, "rejected", 60),
    "410 to a full request": (_inject_410_on_full, "rejected", 60),
    "an answer that is a list": (_inject_malformed_list, "malformed", 60),
    "items that are not a list": (_inject_malformed_items, "malformed", 60),
    "both a page and a sync token": (_inject_malformed_both_tokens, "malformed", 60),
    "a refresh Google answers 503": (_inject_refresh_unavailable, "unavailable", 60),
    "a connection Google no longer honours": (_inject_expired_connection, "connection_expired", 3600),
}


@pytest.mark.parametrize("name", sorted(FAILURES))
def test_FR_CAL_08_each_failure_gets_its_reason_and_its_backoff(name):
    inject, reason, wait = FAILURES[name]
    ce = make_cal_env(start=OPEN)
    _events(ce)
    inject(ce)
    now = ce.now()

    out = _only(ce.run())

    assert (out.status, out.reason) == ("failed", reason)
    assert (out.kind, out.changed, out.emitted) == (None, 0, False)
    state = ce.state()
    assert state.failures == 1 and state.generation == 1 and state.last_run_at == now
    assert state.next_due_at == plus(now, wait)
    assert ce.store.entries(PRIYA) == () and ce.parts == []


def test_FR_CAL_08_a_person_who_granted_no_calendar_scope_fails_missing_scope_and_waits_the_maximum():
    ce = make_cal_env(start=OPEN, persons=[])
    ce.env.connect(PRIYA, "google_calendar", [GMAIL_READONLY])
    ce.add_person(PRIYA, "org_acme", "w_desk_priya", "Asia/Kolkata", connect=False)
    now = ce.now()

    out = _only(ce.run())

    assert (out.status, out.reason) == ("failed", "missing_scope")
    assert ce.state().next_due_at == plus(now, 3600) and ce.cal.requests == []


def test_FR_CAL_08_an_unreadable_sealed_token_fails_token_unreadable_keeps_the_token_and_sends_nothing():
    from tilo_connectors.tokens import FakeKms

    ce = make_cal_env(start=OPEN)
    _events(ce)
    _only(ce.run())
    sealed, sent = ce.state().sealed_token, len(ce.cal.requests)
    ce.sync = ce.new_sync(kms=FakeKms())  # a Kms with another key cannot open it
    ce.clock.advance(900)
    now = ce.now()

    out = _only(ce.run())

    assert (out.status, out.reason, out.requests) == ("failed", "token_unreadable", 0)
    assert len(ce.cal.requests) == sent
    state = ce.state()
    assert state.sealed_token == sealed, "the token is kept"
    assert state.failures == 1 and state.next_due_at == plus(now, 60)


def test_FR_CAL_08_an_unexpected_exception_is_failed_error_with_the_ordinary_backoff():
    ce = make_cal_env(start=OPEN)

    class Exploding:
        def list_events(self, user_id, **kw):
            raise RuntimeError("anything")

    ce.sync = ce.new_sync(events=Exploding())
    now = ce.now()

    out = _only(ce.run())

    assert (out.status, out.reason) == ("failed", "error")
    assert ce.state().next_due_at == plus(now, 60) and ce.state().failures == 1


def test_FR_CAL_08_one_persons_exception_never_stops_the_others():
    ce = make_cal_env(start="2026-10-07T06:00:00.000Z", persons=[])
    ce.add_person(PRIYA, "org_acme", "w_desk_priya", "Asia/Kolkata")
    ce.add_person(DANA, ORG_B, W_DANA, "Asia/Dubai")  # both windows are open at 06:00Z
    _events(ce, 2, PRIYA)
    _events(ce, 2, DANA)
    real = ce.adapter

    class FailsForDana:
        def list_events(self, user_id, **kw):
            if user_id == DANA:  # sorted first: u_dana < u_priya
                raise RuntimeError("boom")
            return real.list_events(user_id, **kw)

    ce.sync = ce.new_sync(events=FailsForDana())

    outcomes = ce.run()

    assert [(o.user_id, o.status) for o in outcomes] == [(DANA, "failed"), (PRIYA, "synced")]
    assert len(ce.store.entries(PRIYA)) == 2 and ce.store.entries(DANA) == ()


# ---------------------------------------------------------------------------
# No hot loop


def test_FR_CAL_08_a_permanent_503_is_tried_at_most_six_times_in_an_hour_of_ten_second_ticks(monkeypatch):
    def no_sleep(*a, **k):
        raise AssertionError("the sync slept")

    monkeypatch.setattr(real_time, "sleep", no_sleep)
    ce = make_cal_env(start=OPEN)
    _events(ce)
    ce.cal.fail_next(503, times=100_000)

    log = run_ticks(ce, seconds=3600, step=10)

    sent = [r.t for r in ce.cal.requests_of(PRIYA)]
    assert [(plus(OPEN, s)) for s in (0, 60, 180, 420, 900, 1860)] == sent, "+60, +120, +240, +480, +960 apart"
    assert all(_only(o).status in ("failed", "skipped") for _, o in log)
    assert sum(_only(o).status == "failed" for _, o in log) == 6


# ---------------------------------------------------------------------------
# Page guards


def test_FR_CAL_08_a_repeated_page_token_fails_page_loop_after_two_requests_and_changes_nothing():
    ce = make_cal_env(start=OPEN)
    _events(ce)
    _only(ce.run())
    state, entries, parts = ce.state(), ce.store.entries(PRIYA), list(ce.parts)
    ce.cal.loop_pages()
    ce.clock.advance(900)
    now = ce.now()

    out = _only(ce.run())

    assert (out.status, out.reason, out.requests) == ("failed", "page_loop", 2), "requests for page tokens A, A"
    after = ce.state()
    assert after.sealed_token == state.sealed_token, "the token is unchanged"
    assert (after.failures, after.generation, after.next_due_at) == (1, state.generation + 1, plus(now, 60))
    assert ce.store.entries(PRIYA) == entries and ce.parts == parts


def test_FR_CAL_08_a_page_loop_on_the_first_run_keeps_no_token_and_backs_off():
    ce = make_cal_env(start=OPEN)
    _events(ce)
    ce.cal.loop_pages()
    now = ce.now()

    out = _only(ce.run())

    assert (out.status, out.reason, out.requests) == ("failed", "page_loop", 2)
    state = ce.state()
    assert state.sealed_token is None and state.next_due_at == plus(now, 60) and ce.store.entries(PRIYA) == ()


def test_FR_CAL_08_endless_fresh_page_tokens_fail_too_many_pages_after_exactly_max_pages_requests():
    ce = make_cal_env(start=OPEN, max_pages=4)
    _events(ce)
    _only(ce.run())
    state, entries = ce.state(), ce.store.entries(PRIYA)
    ce.cal.endless_pages()
    ce.clock.advance(900)
    now = ce.now()
    sent_before = len(ce.cal.requests)

    out = _only(ce.run())

    assert (out.status, out.reason, out.requests) == ("failed", "too_many_pages", 4)
    assert len(ce.cal.requests) - sent_before == 4
    after = ce.state()
    assert after.sealed_token == state.sealed_token and after.next_due_at == plus(now, 60)
    assert ce.store.entries(PRIYA) == entries


@pytest.mark.parametrize("n_events, ok", [(3, True), (4, True), (5, False), (9, False)])
def test_FR_CAL_08_max_pages_pages_ending_with_a_sync_token_are_fine_one_more_is_too_many(n_events, ok):
    ce = make_cal_env(start=OPEN, max_pages=4, page_size=1)
    _events(ce, n_events)

    out = _only(ce.run())

    if ok:
        assert (out.status, out.requests) == ("synced", n_events)
    else:
        assert (out.status, out.reason, out.requests) == ("failed", "too_many_pages", 4)
        assert ce.store.entries(PRIYA) == () and ce.state().sealed_token is None


# ---------------------------------------------------------------------------
# The per-person request cap (per_minute = google_calendar limits.per_minute)


def test_FR_CAL_08_the_run_that_would_send_a_sixth_request_in_a_minute_sends_nothing_more_and_fails_local_rate_limit():
    ce = make_cal_env(start=OPEN, per_minute=5, max_pages=2, backoff_base_s=1, page_size=1)
    _events(ce, 10)
    t0 = ce.now()

    run1 = _only(ce.run())  # pages 1 and 2, no sync token yet: too_many_pages
    ce.set_clock(plus(t0, 1))
    run2 = _only(ce.run())
    ce.set_clock(plus(t0, 3))
    run3 = _only(ce.run())

    assert [(o.reason, o.requests) for o in (run1, run2)] == [("too_many_pages", 2)] * 2
    assert (run3.status, run3.reason, run3.requests) == ("failed", "local_rate_limit", 1)
    assert len(ce.cal.requests_of(PRIYA)) == 5, "the sixth request was never sent"
    assert ce.state().failures == 3 and ce.state().next_due_at == plus(plus(t0, 3), 4), "backoff(3) = 4 s"

    ce.add_person(DANA, ORG_B, W_DANA, "Asia/Dhaka")  # another person has a count of their own (window 03:00-12:00Z)
    ce.cal.add_event(DANA, "d1", "Dana's", BASE, BASE + timedelta(hours=1))
    ce.set_clock(plus(t0, 7))
    outcomes = ce.run()

    assert (_only(outcomes).reason, _only(outcomes).requests) == ("local_rate_limit", 0), "nothing at all is sent"
    assert _only(outcomes, DANA).status == "synced"
    assert len(ce.cal.requests_of(PRIYA)) == 5

    ce.set_clock(plus(t0, 62))  # the first four requests are more than a minute old
    later = _only(ce.run())

    assert (later.reason, later.requests) == ("too_many_pages", 2)
    assert len(ce.cal.requests_of(PRIYA)) == 7


def test_FR_CAL_08_forget_clears_the_instances_request_log_for_the_person():
    ce = make_cal_env(start=OPEN, per_minute=5, max_pages=2, backoff_base_s=1, page_size=1)
    _events(ce, 10)
    t0 = ce.now()
    _only(ce.run())
    ce.set_clock(plus(t0, 1))
    _only(ce.run())
    ce.set_clock(plus(t0, 3))
    assert _only(ce.run()).reason == "local_rate_limit"

    ce.sync.forget(PRIYA)
    ce.sync.register(user_id=PRIYA, org_id="org_acme", world_id="w_desk_priya")
    out = _only(ce.run())

    assert out.reason == "too_many_pages" and out.requests == 2, "the count started again"
