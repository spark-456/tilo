"""FR-CAL-08 acceptance (a): "Fake clock: no sync outside the window". PRD addendum 3.4 FR-CAL-08 ("push or
poll only inside the working window"), API_FR_CAL_08.md "run_due" and "Acceptance tests: the exact
assertions (a)", BQ-CAL8-1 (config/personal.yaml: 09:00 to 18:00 in each person's own time_zone, start
inclusive, end exclusive, every day of the week: the config has no weekday key, so a Saturday syncs like a
Wednesday), BQ-CAL8-2 (the first sync after connecting waits for the window).

The fake clock is one ManualClock shared by the broker, the adapter, the fake Google and CalendarSync; the
window is checked against that clock before every request. Every test fails today with
ModuleNotFoundError: tilo_connectors.calendar_sync (or .calendar_cache, .adapters.calendar).
"""

from __future__ import annotations

import time as real_time
from collections import Counter
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from _calendar_lib import (
    DANA,
    IST,
    LOS_ANGELES,
    NEW_YORK,
    ORG,
    PRIYA,
    W_DANA,
    W_PRIYA,
    in_window,
    local_of,
    local_to_ts,
    make_cal_env,
    outcome_for,
    plus,
    run_ticks,
    seed_calendar,
)
from _connectors_lib import format_ts
from hypothesis import given, settings
from hypothesis import strategies as st

ZONES = [
    "Asia/Kolkata",
    "America/New_York",
    "America/Los_Angeles",
    "Europe/London",
    "Australia/Lord_Howe",
    "Pacific/Auckland",
    "Asia/Kathmandu",
    "America/St_Johns",
    "UTC",
    "Pacific/Kiritimati",
    "Pacific/Pago_Pago",
]
NINE, SIX = time(9, 0), time(18, 0)


def _no_sleep(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("the sync slept: the adapter never waits and the poller ticks")

    monkeypatch.setattr(real_time, "sleep", boom)


def _only(outcomes):
    return outcome_for(outcomes, PRIYA)


# ---------------------------------------------------------------------------
# WorkingWindow


def test_FR_CAL_08_the_working_window_is_a_half_open_wall_clock_interval_in_the_persons_zone():
    from tilo_connectors.calendar_sync import WorkingWindow

    window = WorkingWindow(start=NINE, end=SIX)

    assert window.contains("2026-10-07T03:29:59.999Z", IST) is False
    assert window.contains("2026-10-07T03:30:00.000Z", IST) is True, "start is inclusive"
    assert window.contains("2026-10-07T12:29:59.999Z", IST) is True
    assert window.contains("2026-10-07T12:30:00.000Z", IST) is False, "end is exclusive"
    assert window.contains("2026-10-07T03:30:00.000Z", "UTC") is False
    assert window.contains("2026-10-07T09:00:00.000Z", "UTC") is True


def test_FR_CAL_08_a_zone_the_database_cannot_load_raises_and_is_never_a_silent_false():
    from tilo_connectors.calendar_sync import WorkingWindow

    window = WorkingWindow(start=NINE, end=SIX)

    for bad in ("Mars/Base", "../../etc/passwd", ""):
        with pytest.raises(Exception):  # noqa: B017 - ZoneInfoNotFoundError, ValueError or KeyError
            window.contains("2026-10-07T10:00:00.000Z", bad)


def test_FR_CAL_08_the_window_follows_the_wall_clock_across_a_dst_change():
    from tilo_connectors.calendar_sync import WorkingWindow

    window = WorkingWindow(start=NINE, end=SIX)

    # New York: EST (UTC-5) from 2026-11-01 02:00, EDT (UTC-4) from 2026-03-08 02:00
    assert window.contains("2026-10-31T13:00:00.000Z", NEW_YORK) is True  # 09:00 EDT
    assert window.contains("2026-11-01T13:59:59.999Z", NEW_YORK) is False  # 08:59 EST
    assert window.contains("2026-11-01T14:00:00.000Z", NEW_YORK) is True  # 09:00 EST
    assert window.contains("2026-11-01T22:59:59.999Z", NEW_YORK) is True  # 17:59 EST
    assert window.contains("2026-11-01T23:00:00.000Z", NEW_YORK) is False  # 18:00 EST
    assert window.contains("2026-03-07T14:00:00.000Z", NEW_YORK) is True  # 09:00 EST
    assert window.contains("2026-03-08T12:59:59.999Z", NEW_YORK) is False  # 08:59 EDT
    assert window.contains("2026-03-08T13:00:00.000Z", NEW_YORK) is True  # 09:00 EDT
    assert window.contains("2026-03-08T21:59:59.999Z", NEW_YORK) is True  # 17:59 EDT
    assert window.contains("2026-03-08T22:00:00.000Z", NEW_YORK) is False  # 18:00 EDT


_instants = st.datetimes(min_value=datetime(2026, 1, 1), max_value=datetime(2028, 12, 31)).map(
    lambda d: format_ts(d.replace(tzinfo=UTC))
)


@settings(max_examples=300, deadline=None)
@given(_instants, st.sampled_from(ZONES))
def test_FR_CAL_08_property_contains_is_start_le_local_time_lt_end(instant, zone):
    from tilo_connectors.calendar_sync import WorkingWindow

    window = WorkingWindow(start=NINE, end=SIX)

    assert window.contains(instant, zone) == (NINE <= local_of(instant, zone).time() < SIX)


@settings(max_examples=100, deadline=None)
@given(st.dates(min_value=date(2026, 1, 1), max_value=date(2028, 12, 31)), st.sampled_from(ZONES))
def test_FR_CAL_08_property_the_edges_of_the_window_are_exact_on_every_day_in_every_zone(day, zone):
    from tilo_connectors.calendar_sync import WorkingWindow

    window = WorkingWindow(start=NINE, end=SIX)
    opens = datetime.strptime(local_to_ts(day, NINE, zone), "%Y-%m-%dT%H:%M:%S.%fZ")
    closes = datetime.strptime(local_to_ts(day, SIX, zone), "%Y-%m-%dT%H:%M:%S.%fZ")
    ms = timedelta(milliseconds=1)

    assert window.contains(format_ts((opens - ms).replace(tzinfo=UTC)), zone) is False
    assert window.contains(format_ts(opens.replace(tzinfo=UTC)), zone) is True
    assert window.contains(format_ts((closes - ms).replace(tzinfo=UTC)), zone) is True
    assert window.contains(format_ts(closes.replace(tzinfo=UTC)), zone) is False
    assert closes - opens == timedelta(hours=9), (
        "the window is nine wall-clock hours on a day with no change at 9 or 18"
    )


@pytest.mark.parametrize(
    "zone, first_day", [(NEW_YORK, date(2026, 3, 7)), (NEW_YORK, date(2026, 10, 31)), (IST, date(2026, 10, 7))]
)
def test_FR_CAL_08_every_whole_local_day_has_exactly_540_minutes_inside_the_window_dst_or_not(zone, first_day):
    from tilo_connectors.calendar_sync import WorkingWindow

    window = WorkingWindow(start=NINE, end=SIX)
    start = datetime.combine(first_day, time(0), tzinfo=UTC)
    end = start + timedelta(days=4)
    per_local_day: Counter = Counter()

    for minute in range(4 * 24 * 60):
        instant = format_ts(start + timedelta(minutes=minute))
        if window.contains(instant, zone):
            per_local_day[local_of(instant, zone).date()] += 1

    tz = ZoneInfo(zone)
    whole = [
        d
        for d in per_local_day
        if datetime.combine(d, time(0), tzinfo=tz) >= start
        and datetime.combine(d + timedelta(days=1), time(0), tzinfo=tz) <= end
    ]
    assert len(whole) >= 2 and all(per_local_day[d] == 540 for d in whole), per_local_day


# ---------------------------------------------------------------------------
# (a) 48 hours of one-minute ticks


def test_FR_CAL_08_a_no_sync_request_outside_the_working_window_over_48_hours(monkeypatch):
    _no_sleep(monkeypatch)
    ce = make_cal_env()  # Priya, Asia/Kolkata, registered at 2026-10-07T00:00:00.000Z (05:30 local)
    seed_calendar(ce)

    log = run_ticks(ce)

    assert len(log) == 48 * 60
    requests = ce.cal.requests_of(PRIYA)
    assert requests, "the person was synced"
    for request in requests:
        assert in_window(request.t, IST), f"a Calendar request at {request.t} is outside 09:00-18:00 Asia/Kolkata"
    assert requests[0].t == "2026-10-07T03:30:00.000Z", "the first request is at exactly 09:00 local"
    synced_at = []
    for instant, outcomes in log:
        out = _only(outcomes)
        assert out.user_id == PRIYA
        if not in_window(instant, IST):
            assert (out.status, out.reason) == ("skipped", "outside_window"), instant
            assert out.requests == 0 and out.kind is None and out.changed == 0 and out.emitted is False
        elif out.status == "synced":
            synced_at.append(instant)
            assert out.requests >= 1
        else:
            assert (out.status, out.reason, out.requests) == ("skipped", "not_due", 0), instant
    per_day = Counter(local_of(t, IST).date() for t in synced_at)
    assert per_day == {date(2026, 10, 7): 36, date(2026, 10, 8): 36}, "09:00, 09:15 ... 17:45 local each day"
    assert {local_of(t, IST).strftime("%H:%M") for t in synced_at} == {
        f"{h:02d}:{m:02d}" for h in range(9, 18) for m in (0, 15, 30, 45)
    }
    assert len(requests) == sum(_only(o).requests for _, o in log) == 72, "one page per run, 72 runs"


@pytest.mark.parametrize(
    "instant, allowed",
    [
        ("2026-10-07T03:29:59.999Z", False),  # 08:59:59.999 local
        ("2026-10-07T03:30:00.000Z", True),  # 09:00:00.000
        ("2026-10-07T12:29:59.999Z", True),  # 17:59:59.999
        ("2026-10-07T12:30:00.000Z", False),  # 18:00:00.000
    ],
)
def test_FR_CAL_08_a_request_is_allowed_at_0900_000_and_refused_at_1800_000_local(instant, allowed):
    ce = make_cal_env(start=instant)  # registered (so due) at exactly that reading

    out = _only(ce.run())

    if allowed:
        assert out.status == "synced" and out.requests >= 1
        assert [r.t for r in ce.cal.requests_of(PRIYA)] == [instant]
    else:
        assert (out.status, out.reason, out.requests) == ("skipped", "outside_window", 0)
        assert ce.cal.requests == []


def test_FR_CAL_08_a_first_sync_after_connecting_outside_the_window_waits_for_the_window():
    """BQ-CAL8-2: no Google Calendar request goes out outside the window, ever, the first one included."""
    ce = make_cal_env(start="2026-10-07T13:00:00.000Z")  # 18:30 local, after close

    first = _only(ce.run())
    ce.set_clock("2026-10-08T03:29:59.999Z")
    second = _only(ce.run())
    ce.set_clock("2026-10-08T03:30:00.000Z")
    third = _only(ce.run())

    assert (first.reason, second.reason) == ("outside_window", "outside_window")
    assert third.status == "synced" and third.kind == "full"
    assert [r.t for r in ce.cal.requests_of(PRIYA)] == ["2026-10-08T03:30:00.000Z"]


def test_FR_CAL_08_a_run_that_starts_at_175959_and_crosses_1800_aborts_with_nothing_committed():
    ce = make_cal_env(start="2026-10-07T03:30:00.000Z", page_size=1)  # 09:00 local, one event per page
    base = datetime(2026, 10, 8, 4, 0, tzinfo=UTC)
    for k in range(3):
        ce.cal.add_event(PRIYA, f"evt{k}", f"Event {k}", base + timedelta(days=k), base + timedelta(days=k, hours=1))
    first = _only(ce.run())
    assert first.status == "synced" and first.kind == "full" and first.requests == 3
    token_before = ce.cal.last_sync_token(PRIYA)
    state_before, entries_before, parts_before = ce.state(), ce.store.entries(PRIYA), list(ce.parts)
    for k in range(3):  # three changes: the next incremental fetch needs three pages
        ce.cal.update_event(PRIYA, f"evt{k}", summary=f"Changed {k}")
    ce.cal.advance_per_request_s = 2
    ce.set_clock("2026-10-07T12:29:59.000Z")  # 17:59:59 local, and the first sync's next_due_at has passed

    out = _only(ce.run())

    assert (out.status, out.reason) == ("aborted", "window_closed")
    assert out.requests == 1 and out.changed == 0 and out.kind is None and out.emitted is False
    sent = ce.cal.requests_of(PRIYA)[3:]
    assert len(sent) == 1, "page 1 was sent; page 2 was not: the window had closed at 17:59:59 + 2 s"
    assert sent[0].t == "2026-10-07T12:29:59.000Z" and sent[0].sync_token == token_before
    assert ce.state() == state_before, "token, generation, next_due_at and failures are exactly as before"
    assert ce.store.entries(PRIYA) == entries_before, "the staged page was dropped"
    assert ce.parts == parts_before, "nothing is emitted"

    ce.cal.advance_per_request_s = 0
    ce.set_clock("2026-10-08T03:30:00.000Z")  # next day, 09:00 local
    again = _only(ce.run())

    assert again.status == "synced" and again.kind == "incremental" and again.changed == 3
    assert ce.cal.requests_of(PRIYA)[4].sync_token == token_before, "the next run continues from the same token"
    assert [e["title"] for e in ce.store.entries(PRIYA)] == ["Changed 0", "Changed 1", "Changed 2"]


@pytest.mark.parametrize(
    "first_day, days, expected_open_utc",
    [
        # The fall-back day: 09:00 EDT = 13:00Z on Oct 31, 09:00 EST = 14:00Z on Nov 1 and Nov 2
        (
            date(2026, 10, 31),
            3,
            {"2026-10-31": "13:00:00.000Z", "2026-11-01": "14:00:00.000Z", "2026-11-02": "14:00:00.000Z"},
        ),
        # The spring-forward day: 09:00 EST = 14:00Z on Mar 7, 09:00 EDT = 13:00Z on Mar 8 and Mar 9
        (
            date(2026, 3, 7),
            3,
            {"2026-03-07": "14:00:00.000Z", "2026-03-08": "13:00:00.000Z", "2026-03-09": "13:00:00.000Z"},
        ),
    ],
)
def test_FR_CAL_08_a_person_in_new_york_is_synced_only_inside_the_window_across_a_dst_change(
    monkeypatch, first_day, days, expected_open_utc
):
    _no_sleep(monkeypatch)
    start = datetime.combine(first_day, time(0), tzinfo=UTC)
    ce = make_cal_env(start=format_ts(start), persons=[(PRIYA, ORG, W_PRIYA, NEW_YORK)])

    log = run_ticks(ce, seconds=days * 24 * 3600)

    requests = ce.cal.requests_of(PRIYA)
    assert requests
    assert all(in_window(r.t, NEW_YORK) for r in requests)
    by_day: dict[str, list[str]] = {}
    for request in requests:
        by_day.setdefault(request.t[:10], []).append(request.t[11:])
    for day, opens in expected_open_utc.items():
        assert by_day[day][0] == opens, f"{day}: the first request is at 09:00 local = {opens}"
    for day, instants in by_day.items():
        if day in expected_open_utc:
            assert len(instants) == 36, f"{day}: 36 runs, 09:00 to 17:45 local"
    for instant, outcomes in log:
        if not in_window(instant, NEW_YORK):
            out = _only(outcomes)
            assert (out.status, out.reason, out.requests) == ("skipped", "outside_window", 0)


def test_FR_CAL_08_two_people_in_different_zones_are_each_synced_only_inside_their_own_window():
    ce = make_cal_env(  # 01:00Z: 06:30 in Kolkata and 18:00 in Los Angeles, both outside their windows
        start="2026-10-07T01:00:00.000Z", persons=[(PRIYA, ORG, W_PRIYA, IST), (DANA, ORG, W_DANA, LOS_ANGELES)]
    )

    log = run_ticks(ce, seconds=36 * 3600)

    priya, dana = ce.cal.requests_of(PRIYA), ce.cal.requests_of(DANA)
    assert priya and dana
    assert all(in_window(r.t, IST) for r in priya)
    assert all(in_window(r.t, LOS_ANGELES) for r in dana)
    assert priya[0].t == "2026-10-07T03:30:00.000Z"  # 09:00 IST
    assert dana[0].t == "2026-10-07T16:00:00.000Z"  # 09:00 PDT
    for instant, outcomes in log:
        assert {o.user_id for o in outcomes} == {PRIYA, DANA}
        for out in outcomes:
            zone = IST if out.user_id == PRIYA else LOS_ANGELES
            if not in_window(instant, zone):
                assert (out.status, out.reason, out.requests) == ("skipped", "outside_window", 0)


def test_FR_CAL_08_a_saturday_is_synced_like_any_other_day():
    """BQ-CAL8-1: one window for everyone, no weekday key in config/personal.yaml."""
    ce = make_cal_env(start="2026-10-10T03:30:00.000Z")  # Saturday 2026-10-10, 09:00 local
    assert datetime(2026, 10, 10).weekday() == 5

    log = run_ticks(ce, seconds=9 * 3600)

    assert sum(_only(o).status == "synced" for _, o in log) == 36


@pytest.mark.parametrize(
    "zone",
    [None, "Mars/Base", "../../etc/passwd", "", "Asia/Kolkata\n", "asia/kolkata", 123, ["Asia/Kolkata"], "UTC+5"],
)
def test_FR_CAL_08_a_person_with_no_usable_time_zone_is_skipped_with_zero_requests(zone):
    ce = make_cal_env(start="2026-10-07T05:00:00.000Z")
    ce.zones[PRIYA] = zone

    out = _only(ce.run())

    assert (out.status, out.reason, out.requests, out.kind, out.changed) == ("skipped", "no_time_zone", 0, None, 0)
    assert ce.cal.requests == []
    assert ce.state().generation == 0, "a skip records nothing"


def test_FR_CAL_08_utc_is_a_usable_time_zone():
    ce = make_cal_env(start="2026-10-07T09:00:00.000Z")
    ce.zones[PRIYA] = "UTC"

    assert _only(ce.run()).status == "synced"


def test_FR_CAL_08_a_change_of_the_persons_zone_applies_at_the_next_tick():
    ce = make_cal_env(start="2026-10-07T05:00:00.000Z")  # 10:30 in Kolkata, 01:00 in New York
    ce.zones[PRIYA] = NEW_YORK
    first = _only(ce.run())
    ce.zones[PRIYA] = IST
    second = _only(ce.run())
    ce.zones[PRIYA] = NEW_YORK
    third = _only(ce.tick(1_000))

    assert first.reason == "outside_window"
    assert second.status == "synced"
    assert third.reason == "outside_window", "moved away again: the window is re-read from the person record every tick"


def test_FR_CAL_08_an_empty_store_has_nothing_to_run():
    ce = make_cal_env(persons=[])

    assert ce.run() == ()


# ---------------------------------------------------------------------------
# The clock


def test_FR_CAL_08_a_clock_moved_back_a_day_after_a_sync_syncs_at_the_next_tick_inside_the_window():
    ce = make_cal_env(start="2026-10-08T05:00:00.000Z")  # 10:30 local
    assert _only(ce.run()).kind == "full"
    assert _only(ce.tick(60)).reason == "not_due"

    ce.set_clock("2026-10-07T05:00:00.000Z")  # a day earlier, still inside the window
    out = _only(ce.run())

    assert out.status == "synced" and out.kind == "incremental", "not a day later: the clock jump re-arms the poll"


@pytest.mark.parametrize("back_s, runs", [(299, False), (300, False), (301, True), (3600, True)])
def test_FR_CAL_08_a_small_clock_step_back_is_tolerated_but_more_than_300_seconds_is_a_jump(back_s, runs):
    """CLOCK_SKEW_S = 300: `now < last_run_at - 300` makes the person due."""
    ce = make_cal_env(start="2026-10-08T05:00:00.000Z")
    ce.run()
    ce.set_clock(plus("2026-10-08T05:00:00.000Z", -back_s))

    out = _only(ce.run())

    assert (out.status == "synced") is runs
    if not runs:
        assert (out.status, out.reason) == ("skipped", "not_due")


def test_FR_CAL_08_a_clock_jump_forward_past_several_intervals_gives_one_run_not_a_burst():
    ce = make_cal_env(start="2026-10-08T04:00:00.000Z")  # 09:30 local
    ce.run()
    before = len(ce.cal.requests)

    ce.set_clock("2026-10-08T07:30:00.000Z")  # 13:00 local: eight poll intervals later
    jumped = _only(ce.run())
    next_tick = _only(ce.tick(60))

    assert jumped.status == "synced" and jumped.requests == 1
    assert (next_tick.status, next_tick.reason) == ("skipped", "not_due")
    assert len(ce.cal.requests) == before + 1


def test_FR_CAL_08_a_jump_forward_out_of_the_window_waits_for_the_next_window_and_runs_once():
    ce = make_cal_env(start="2026-10-08T04:00:00.000Z")
    ce.run()

    ce.set_clock("2026-10-08T14:30:00.000Z")  # 20:00 local
    out_of_window = _only(ce.run())
    ce.set_clock("2026-10-09T03:30:00.000Z")  # next morning 09:00
    morning = _only(ce.run())
    after = _only(ce.tick(60))

    assert out_of_window.reason == "outside_window"
    assert morning.status == "synced" and after.reason == "not_due"


# ---------------------------------------------------------------------------
# The poll interval, as a property of the clock maths


@settings(max_examples=20, deadline=None)
@given(st.integers(min_value=60, max_value=3600))
def test_FR_CAL_08_property_runs_per_window_follow_the_interval_and_never_leave_the_window(poll_interval_s):
    ce = make_cal_env(start="2026-10-07T03:30:00.000Z", poll_interval_s=poll_interval_s)  # opens now
    seed_calendar(ce)

    log = run_ticks(ce, seconds=24 * 3600)

    ticks_per_run = -(-poll_interval_s // 60)  # ticks are 60 s apart: a run waits for the first tick >= due
    expected_runs = -(-540 // ticks_per_run)  # minutes 0, k, 2k ... below 540 (09:00 to 18:00)
    runs = [t for t, o in log if _only(o).status == "synced"]
    assert len(runs) == expected_runs
    assert all(in_window(r.t, IST) for r in ce.cal.requests_of(PRIYA))
    assert runs[0] == "2026-10-07T03:30:00.000Z"
