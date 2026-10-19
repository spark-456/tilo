"""FR-CAL-08 acceptance (b): "a full sync happens only after a token expires". PRD addendum 3.4 FR-CAL-08
("sync is incremental with a sync token"), API_FR_CAL_08.md "run_due" (Fetching, 410) and "Acceptance tests:
the exact assertions (b)", hostile case "410 mid-fetch".

A full sync (a list with timeMin and timeMax) happens in exactly two cases: the person has no stored sync
token (the first run after `register`, or after a 410 whose full fetch failed), or Google answered 410 to a
request that carried the stored token, in the same run. No timer, restart, error, abort, config change or
clock jump starts one, and exactly one full sync follows a 410, never a loop. Every test fails today with
ModuleNotFoundError: tilo_connectors.calendar_sync (or .calendar_cache, .adapters.calendar).
"""

from __future__ import annotations

import dataclasses
import time as real_time
from datetime import UTC, datetime, timedelta

import pytest
from _calendar_lib import (
    ORG,
    PRIYA,
    W_PRIYA,
    entry_errors,
    make_cal_env,
    outcome_for,
    plus,
    run_ticks,
    seed_calendar,
)
from hypothesis import given, settings
from hypothesis import strategies as st

OPEN = "2026-10-07T03:30:00.000Z"  # 09:00 in Asia/Kolkata
BASE = datetime(2026, 10, 8, 4, 0, tzinfo=UTC)


def _only(outcomes):
    return outcome_for(outcomes, PRIYA)


def _three_events(ce, prefix="evt"):
    for k in range(3):
        ce.cal.add_event(
            PRIYA, f"{prefix}{k}", f"Event {k}", BASE + timedelta(days=k), BASE + timedelta(days=k, hours=1)
        )


def _kinds(requests):
    return ["full" if r.is_full else "inc" for r in requests]


def _ids(ce):
    return {e["source"]["ref"] for e in ce.store.entries(PRIYA)}


# ---------------------------------------------------------------------------
# (b) 48 hours


def test_FR_CAL_08_b_over_48_hours_exactly_one_run_is_full_and_only_its_requests_carry_time_bounds(monkeypatch):
    def no_sleep(*a, **k):
        raise AssertionError("the sync slept")

    monkeypatch.setattr(real_time, "sleep", no_sleep)
    ce = make_cal_env()
    seed_calendar(ce)  # 14 events: four single events and a ten-instance series

    def change_midday(i, now, ce):
        if now == "2026-10-07T08:00:00.000Z":  # 13:30 local, a poll time
            ce.cal.add_event(PRIYA, "evt_new", "Offsite", BASE + timedelta(days=3), BASE + timedelta(days=3, hours=2))

    log = run_ticks(ce, before=change_midday)

    synced = [(t, _only(o)) for t, o in log if _only(o).status == "synced"]
    assert len(synced) == 72
    assert [o.kind for _, o in synced].count("full") == 1 and synced[0][1].kind == "full"
    assert all(o.kind == "incremental" for _, o in synced[1:])
    requests = ce.cal.requests_of(PRIYA)
    fulls = [r for r in requests if r.is_full]
    assert len(fulls) == 1 and fulls[0] is requests[0], "only the first run's request carries timeMin/timeMax"
    assert fulls[0].params["timeMin"] == "2026-09-30T03:30:00.000Z", "now - 7 days"
    assert fulls[0].params["timeMax"] == "2027-10-08T03:30:00.000Z", "now + 366 days"
    assert "syncToken" not in fulls[0].params
    for request in requests[1:]:
        assert request.sync_token and "timeMin" not in request.params and "timeMax" not in request.params
    full_parts = [p for p in ce.calendar_parts() if p["data"]["kind"] == "full"]
    assert len(full_parts) == 1 and full_parts[0]["data"] == {"kind": "full", "changed": 14}
    assert [p["data"] for p in ce.calendar_parts()] == [
        {"kind": "full", "changed": 14},
        {"kind": "incremental", "changed": 1},
    ], "the 70 polls that changed nothing wrote nothing (BQ-CAL8-6)"
    assert len(_ids(ce)) == 15


def test_FR_CAL_08_b_the_full_requests_time_bounds_are_fixed_for_the_run_even_as_the_clock_moves():
    ce = make_cal_env(start=OPEN, page_size=1, advance_per_request_s=1.0)
    _three_events(ce)

    out = _only(ce.run())

    assert out.status == "synced" and out.kind == "full" and out.requests == 3
    bounds = {(r.params["timeMin"], r.params["timeMax"]) for r in ce.cal.requests_of(PRIYA)}
    assert bounds == {("2026-09-30T03:30:00.000Z", "2027-10-08T03:30:00.000Z")}


# ---------------------------------------------------------------------------
# Nothing but a missing or dead token starts a full sync


def _restart(ce):
    ce.sync = ce.new_sync()


def _server_error(ce):
    ce.cal.fail_next(503)
    ce.clock.advance(900)
    out = _only(ce.run())
    assert (out.status, out.reason) == ("failed", "unavailable")
    ce.set_clock(ce.state().next_due_at)


def _forbidden(ce):
    ce.cal.fail_next(403)
    ce.clock.advance(900)
    out = _only(ce.run())
    assert (out.status, out.reason) == ("failed", "rejected")
    ce.set_clock(ce.state().next_due_at)


def _malformed(ce):
    ce.cal.override_next({"items": "not a list", "nextSyncToken": "tok"})
    ce.clock.advance(900)
    out = _only(ce.run())
    assert (out.status, out.reason) == ("failed", "malformed")
    ce.set_clock(ce.state().next_due_at)


def _window_abort(ce):
    for k in range(3):
        ce.cal.update_event(PRIYA, f"evt{k}", summary=f"Changed {k}")
    ce.cal.advance_per_request_s = 2
    ce.set_clock("2026-10-07T12:29:59.000Z")
    out = _only(ce.run())
    assert (out.status, out.reason) == ("aborted", "window_closed")
    ce.cal.advance_per_request_s = 0
    ce.set_clock("2026-10-08T03:30:00.000Z")


def _clock_back(ce):
    ce.set_clock(plus(ce.now(), -3600))  # 09:30 local: inside the window, more than 300 s before last_run_at


def _poll_interval_change(ce):
    ce.sync = ce.new_sync(config=dataclasses.replace(ce.config, poll_interval_s=300))
    ce.clock.advance(900)  # the stored next_due_at was set under the old interval


def _restart_and_wait(ce):
    _restart(ce)
    ce.clock.advance(900)


TRIGGERS = {
    "a second CalendarSync over the same store and Kms": _restart_and_wait,
    "a 503 run": _server_error,
    "a 403 run": _forbidden,
    "a malformed answer": _malformed,
    "a window_closed abort": _window_abort,
    "a backwards clock jump": _clock_back,
    "a changed poll_interval_s": _poll_interval_change,
}


@pytest.mark.parametrize("name", sorted(TRIGGERS))
def test_FR_CAL_08_b_each_of_these_is_followed_by_an_incremental_run_never_a_full_one(name):
    ce = make_cal_env(start="2026-10-07T05:00:00.000Z", page_size=1)  # 10:30 local
    _three_events(ce)
    first = _only(ce.run())
    assert first.kind == "full" and first.requests == 3

    TRIGGERS[name](ce)
    out = _only(ce.run())

    assert out.status == "synced" and out.kind == "incremental", name
    assert len(ce.cal.full_requests(PRIYA)) == 3, "only the first run's three pages (page_size 1) were ever full"
    assert all(r.sync_token for r in ce.cal.requests_of(PRIYA)[3:]), "every later request carries the sync token"


# ---------------------------------------------------------------------------
# First run, register, forget


def test_FR_CAL_08_b_a_first_run_with_no_stored_token_does_a_full_sync():
    ce = make_cal_env(start=OPEN)
    _three_events(ce)
    assert ce.state().sealed_token is None

    out = _only(ce.run())

    assert (out.status, out.kind, out.requests) == ("synced", "full", 1)
    assert ce.cal.requests_of(PRIYA)[0].is_full and ce.state().sealed_token is not None
    assert [p["data"] for p in ce.calendar_parts()] == [{"kind": "full", "changed": 3}]


def test_FR_CAL_08_b_after_forget_and_register_again_the_next_run_is_full():
    ce = make_cal_env(start=OPEN)
    _three_events(ce)
    ce.run()
    ce.sync.forget(PRIYA)
    ce.connections[PRIYA] = ce.sync.register(user_id=PRIYA, org_id=ORG, world_id=W_PRIYA)

    out = _only(ce.run())

    assert out.kind == "full" and ce.cal.requests_of(PRIYA)[-1].is_full
    assert len(ce.cal.full_requests(PRIYA)) == 2


# ---------------------------------------------------------------------------
# 410: an expired token


def test_FR_CAL_08_b_after_expire_sync_tokens_the_next_run_sends_the_old_token_then_exactly_one_full_sync():
    ce = make_cal_env(start=OPEN)
    seed_calendar(ce)
    _only(ce.run())
    old_token = ce.cal.last_sync_token(PRIYA)
    ce.cal.expire_sync_tokens()
    ce.cal.cancel_event(PRIYA, "evt_b")  # deleted while the token was dead: only a full sync can notice
    sent_before = len(ce.cal.requests_of(PRIYA))
    ce.clock.advance(900)

    out = _only(ce.run())

    sent = ce.cal.requests_of(PRIYA)[sent_before:]
    assert _kinds(sent) == ["inc", "full"], "one request with the old token (answered 410), then the full list"
    assert sent[0].sync_token == old_token and "timeMin" not in sent[0].params
    assert "syncToken" not in sent[1].params and "timeMin" in sent[1].params and "timeMax" in sent[1].params
    assert (out.status, out.kind, out.requests) == ("synced", "full", 2)
    assert "evt_b" not in _ids(ce), "a full sync removes a cached entry whose event was deleted"
    assert len(_ids(ce)) == 13
    assert [p["data"] for p in ce.calendar_parts()][-1] == {"kind": "full", "changed": 1}
    assert len([p for p in ce.calendar_parts() if p["data"]["kind"] == "full"]) == 2, "one part for this full sync"

    new_token = ce.cal.last_sync_token(PRIYA)
    assert new_token != old_token
    ce.clock.advance(900)
    after = _only(ce.run())

    assert (after.status, after.kind, after.requests) == ("synced", "incremental", 1)
    assert ce.cal.requests_of(PRIYA)[-1].sync_token == new_token, (
        "the run after it is incremental again, on the new token"
    )
    assert len(ce.cal.full_requests(PRIYA)) == 2


def test_FR_CAL_08_b_a_full_sync_updates_changed_events_and_keeps_unchanged_ones_after_a_410():
    ce = make_cal_env(start=OPEN)
    _three_events(ce)
    ce.run()
    created_at = {e["source"]["ref"]: e["created_by"]["at"] for e in ce.store.entries(PRIYA)}
    ce.cal.expire_sync_tokens()
    ce.cal.update_event(PRIYA, "evt1", summary="Renamed")
    ce.cal.add_event(PRIYA, "evt9", "Brand new", BASE + timedelta(days=9), BASE + timedelta(days=9, hours=1))
    ce.clock.advance(900)

    out = _only(ce.run())

    titles = {e["source"]["ref"]: e["title"] for e in ce.store.entries(PRIYA)}
    assert titles == {"evt0": "Event 0", "evt1": "Renamed", "evt2": "Event 2", "evt9": "Brand new"}
    assert out.changed == 2, "one modified and one created: the unchanged two are not counted"
    after = {e["source"]["ref"]: e["created_by"]["at"] for e in ce.store.entries(PRIYA)}
    assert all(after[k] == created_at[k] for k in created_at), "created_by.at survives a full sync"
    assert all(entry_errors(e) == [] for e in ce.store.entries(PRIYA))


def test_FR_CAL_08_b_a_410_on_page_two_of_an_incremental_fetch_commits_the_full_fetch_only():
    ce = make_cal_env(start=OPEN, page_size=1)
    _three_events(ce)
    ce.run()
    for k in range(3):
        ce.cal.update_event(PRIYA, f"evt{k}", summary=f"Changed {k}")
    generation = ce.state().generation
    ce.cal.fail_next(410, when=lambda r: r.sync_token is not None and "pageToken" in r.params)
    sent_before = len(ce.cal.requests_of(PRIYA))
    ce.clock.advance(900)

    out = _only(ce.run())

    sent = ce.cal.requests_of(PRIYA)[sent_before:]
    assert _kinds(sent) == ["inc", "inc", "full", "full", "full"], "page 1, page 2 (410), then the full fetch"
    assert (out.status, out.kind, out.requests, out.changed) == ("synced", "full", 5, 3)
    assert ce.state().generation == generation + 1, "page 1's events were not committed on their own"
    assert [e["title"] for e in ce.store.entries(PRIYA)] == ["Changed 0", "Changed 1", "Changed 2"]
    assert len(ce.calendar_parts()) == 2 and ce.calendar_parts()[-1]["data"] == {"kind": "full", "changed": 3}


def test_FR_CAL_08_b_a_410_to_a_full_request_is_failed_rejected_and_never_retried_in_a_loop():
    ce = make_cal_env(start=OPEN)
    _three_events(ce)
    ce.cal.fail_next(410, times=50)

    out = _only(ce.run())

    assert (out.status, out.reason, out.requests) == ("failed", "rejected", 1)
    assert len(ce.cal.requests_of(PRIYA)) == 1


def test_FR_CAL_08_b_a_410_then_a_410_on_the_full_fetch_makes_exactly_two_requests():
    ce = make_cal_env(start=OPEN)
    _three_events(ce)
    ce.run()
    ce.cal.expire_sync_tokens()
    ce.cal.fail_next(410, times=50, when=lambda r: r.is_full)
    sent_before = len(ce.cal.requests_of(PRIYA))
    ce.clock.advance(900)

    out = _only(ce.run())

    assert (out.status, out.reason, out.requests) == ("failed", "rejected", 2)
    assert _kinds(ce.cal.requests_of(PRIYA)[sent_before:]) == ["inc", "full"], "exactly one full sync follows a 410"


def test_FR_CAL_08_b_a_410_then_a_503_on_the_full_fetch_commits_no_token_and_the_next_run_is_full():
    ce = make_cal_env(start=OPEN)
    _three_events(ce)
    ce.run()
    ce.cal.expire_sync_tokens()
    ce.cal.fail_next(503, when=lambda r: r.is_full)
    ce.clock.advance(900)
    now = ce.now()

    failed = _only(ce.run())

    assert (failed.status, failed.reason, failed.requests) == ("failed", "unavailable", 2)
    state = ce.state()
    assert state.sealed_token is None, "the dead token is gone: the next run is full"
    assert state.failures == 1 and state.next_due_at == plus(now, 60)
    assert len(_ids(ce)) == 3, "the cache is untouched by the failure"

    ce.set_clock(state.next_due_at)
    sent_before = len(ce.cal.requests_of(PRIYA))
    again = _only(ce.run())

    assert (again.status, again.kind, again.requests) == ("synced", "full", 1)
    assert _kinds(ce.cal.requests_of(PRIYA)[sent_before:]) == ["full"], "no stale token is sent again"


def test_FR_CAL_08_b_when_the_window_closes_during_the_full_fetch_after_a_410_nothing_is_recorded():
    ce = make_cal_env(start=OPEN, page_size=1)
    _three_events(ce)
    ce.run()
    old_token = ce.cal.last_sync_token(PRIYA)
    ce.cal.expire_sync_tokens()
    before = ce.state()
    entries_before = ce.store.entries(PRIYA)
    ce.cal.advance_per_request_s = 2
    ce.set_clock("2026-10-07T12:29:59.000Z")  # 17:59:59 local: the 410 answer comes at 18:00:01
    sent_before = len(ce.cal.requests_of(PRIYA))

    out = _only(ce.run())

    assert (out.status, out.reason, out.requests) == ("aborted", "window_closed", 1)
    assert ce.state() == before and ce.store.entries(PRIYA) == entries_before
    ce.cal.advance_per_request_s = 0
    ce.set_clock("2026-10-08T03:30:00.000Z")
    again = _only(ce.run())

    sent = ce.cal.requests_of(PRIYA)[sent_before + 1 :]
    assert sent[0].sync_token == old_token, "the next run meets the 410 again"
    assert _kinds(sent) == ["inc", "full", "full", "full"]
    assert (again.status, again.kind) == ("synced", "full")


# ---------------------------------------------------------------------------
# The rule as a property: a full request is made iff there is no token, or a 410 came first in the same run


OPS = ["run", "expire", "fail503", "expire503", "restart", "change"]


@settings(max_examples=30, deadline=None)
@given(st.lists(st.sampled_from(OPS), min_size=1, max_size=8))
def test_FR_CAL_08_property_a_full_sync_follows_only_a_missing_token_or_a_410(ops):
    ce = make_cal_env(start=OPEN)
    _three_events(ce)
    known = False  # does the stored state hold a sync token?
    for day, op in enumerate(ops, start=1):
        ce.set_clock(f"2026-10-{7 + day:02d}T05:00:00.000Z")  # 10:30 local, a new day each time: always due
        if op == "restart":
            ce.sync = ce.new_sync()
        if op == "change":
            ce.cal.add_event(
                PRIYA, f"extra{day}", f"Extra {day}", BASE + timedelta(days=day), BASE + timedelta(days=day, hours=1)
            )
        if op in ("expire", "expire503"):
            ce.cal.expire_sync_tokens()
        if op == "fail503":
            ce.cal.fail_next(503)
        if op == "expire503":
            ce.cal.fail_next(503, when=lambda r: r.is_full)
        sent_before = len(ce.cal.requests_of(PRIYA))

        out = _only(ce.run())

        sent = _kinds(ce.cal.requests_of(PRIYA)[sent_before:])
        stale = known and op in ("expire", "expire503")
        if not known:
            expected_seq = ["full"]
        elif stale:
            expected_seq = ["inc", "full"]
        else:
            expected_seq = ["inc"]
        assert sent == expected_seq, (ops, day, op, sent)
        failing = op in ("fail503", "expire503")
        assert (out.status == "failed") is failing, (ops, day, op, out)
        if failing:
            known = known and op == "fail503"  # a failed full after a 410 drops the dead token
        else:
            assert out.kind == ("full" if "full" in expected_seq else "incremental")
            known = True
    assert len(ce.cal.full_requests(PRIYA)) == sum(1 for r in ce.cal.requests_of(PRIYA) if r.is_full)
    assert all(r.sync_token or r.is_full for r in ce.cal.requests_of(PRIYA)), "every request is one or the other"
