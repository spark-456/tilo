"""FR-CAL-07b-1: a pure free-slot search over the cached calendar_entry records (addendum FR-CAL-07 test:
"every proposed time is free in the fake calendar"). Spec: API.md "Free slots".

Busy means an `accepted` entry of the owner (or a free_busy interval of the owner); proposed, declined,
cancelled and other people's entries never block. All-day entries block the local day. No clock, no I/O.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from tilo_people import errors
from tilo_people.free_slots import FreeSlotError, find_free_slots, parse_working_window

IST = "Asia/Kolkata"
NOW = "2026-10-07T03:00:00.000Z"  # Wednesday 08:30 IST
U = "u_priya"


def ts(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def local(day: str, hm: str, tz: str = IST) -> str:
    return ts(datetime.fromisoformat(f"{day}T{hm}:00").replace(tzinfo=ZoneInfo(tz)))


def entry(start: str, end: str | None, *, state="accepted", owner=U, all_day=False, i=0):
    return {"id": f"ce_{i}", "owner": owner, "start": start, "end": end, "all_day": all_day, "state": state}


def slots(entries, **kw):
    kw.setdefault("owner", U)
    kw.setdefault("now", NOW)
    kw.setdefault("tz", IST)
    kw.setdefault("duration_min", 30)
    return find_free_slots(entries, **kw)


def test_FR_CAL_07b_empty_calendar_proposes_earliest_aligned_working_times():
    assert slots([]) == (local("2026-10-07", "09:00"), local("2026-10-07", "09:30"), local("2026-10-07", "10:00"))


def test_FR_CAL_07b_only_accepted_entries_of_the_owner_block():
    nine = local("2026-10-07", "09:00")
    ten = local("2026-10-07", "10:00")
    for state in ("proposed", "declined", "cancelled"):
        assert slots([entry(nine, ten, state=state)])[0] == nine
    assert slots([entry(nine, ten, owner="u_other")])[0] == nine
    assert slots([entry(nine, ten)])[0] == ten


def test_FR_CAL_07b_adjacent_is_free_and_buffer_pushes_it_out():
    block = entry(local("2026-10-07", "09:00"), local("2026-10-07", "10:00"))
    assert slots([block], count=1) == (local("2026-10-07", "10:00"),)
    assert slots([block], count=1, buffer_min=15) == (local("2026-10-07", "10:15"),)


def test_FR_CAL_07b_overlapping_and_gap_too_small():
    es = [
        entry(local("2026-10-07", "09:00"), local("2026-10-07", "10:00"), i=1),
        entry(local("2026-10-07", "09:30"), local("2026-10-07", "10:30"), i=2),
        entry(local("2026-10-07", "10:45"), local("2026-10-07", "12:00"), i=3),
    ]
    assert slots(es, count=1, duration_min=15) == (local("2026-10-07", "10:30"),)
    assert slots(es, count=1) == (local("2026-10-07", "12:00"),)
    assert slots(es, count=1, duration_min=45) == (local("2026-10-07", "12:00"),)


def test_FR_CAL_07b_entry_without_end_uses_the_default_duration():
    es = [entry(local("2026-10-07", "09:00"), None)]
    assert slots(es, count=1) == (local("2026-10-07", "10:00"),)
    assert slots(es, count=1, default_entry_min=30) == (local("2026-10-07", "09:30"),)


def test_FR_CAL_07b_all_day_entry_blocks_the_whole_local_day():
    es = [entry(local("2026-10-07", "00:00"), None, all_day=True)]
    assert slots(es, count=1) == (local("2026-10-08", "09:00"),)
    es = [entry(local("2026-10-07", "00:00"), local("2026-10-09", "00:00"), all_day=True)]
    assert slots(es, count=1) == (local("2026-10-09", "09:00"),)


def test_FR_CAL_07b_free_busy_intervals_block():
    fb = {
        "user": U,
        "from": NOW,
        "to": NOW,
        "busy": [{"start": local("2026-10-07", "09:00"), "end": local("2026-10-07", "11:00")}],
    }
    assert slots([fb], count=1) == (local("2026-10-07", "11:00"),)
    assert slots([dict(fb, user="u_other")], count=1) == (local("2026-10-07", "09:00"),)


def test_FR_CAL_07b_working_days_and_window_and_range_limits():
    fri = "2026-10-09T10:00:00.000Z"  # 15:30 IST Friday
    got = slots([], now=fri, count=2, duration_min=60)
    assert got == (local("2026-10-09", "15:30"), local("2026-10-09", "16:30"))
    got = slots([], now=fri, count=3, duration_min=60)
    assert got[2] == local("2026-10-12", "09:00")  # weekend skipped
    assert slots([], now=fri, working_days=(5, 6), count=1) == (local("2026-10-10", "09:00"),)
    assert slots([], not_before=local("2026-10-07", "13:07"), count=1) == (local("2026-10-07", "13:15"),)


def test_FR_CAL_07b_not_after_is_an_exclusive_end_of_the_slot():
    got = slots([], not_after=local("2026-10-07", "10:00"), count=5, step_min=30)
    assert got == (local("2026-10-07", "09:00"), local("2026-10-07", "09:30"))


def test_FR_CAL_07b_dst_transitions_keep_wall_clock_window():
    ny = "America/New_York"
    kw = {"tz": ny, "working_days": range(7), "count": 1}
    assert slots([], now="2026-03-08T00:00:00.000Z", **kw) == ("2026-03-08T13:00:00.000Z",)  # EDT, after spring forward
    assert slots([], now="2026-11-01T00:00:00.000Z", **kw) == ("2026-11-01T14:00:00.000Z",)  # EST, after fall back
    es = [entry("2026-03-08T13:00:00.000Z", "2026-03-08T14:00:00.000Z")]
    assert slots(es, now="2026-03-08T00:00:00.000Z", **kw) == ("2026-03-08T14:00:00.000Z",)


def test_FR_CAL_07b_entry_spanning_midnight():
    es = [entry(local("2026-10-07", "22:00"), local("2026-10-08", "09:40"))]
    assert slots(es, now=local("2026-10-07", "20:00"), count=1) == (local("2026-10-08", "09:45"),)


def test_FR_CAL_07b_parse_working_window():
    assert parse_working_window({"start": "09:00", "end": "18:00"}) == ("09:00", "18:00")
    for bad in ({"start": "18:00", "end": "09:00"}, {"start": "9", "end": "10:00"}, {}, None, {"start": 9, "end": 10}):
        with pytest.raises(FreeSlotError):
            parse_working_window(bad)


def test_FR_CAL_07b_window_argument_is_used():
    assert slots([], working_window=("13:00", "14:00"), count=3, duration_min=30)[:2] == (
        local("2026-10-07", "13:00"),
        local("2026-10-07", "13:30"),
    )


@pytest.mark.parametrize(
    "kw",
    [
        {"duration_min": 0},
        {"duration_min": -5},
        {"duration_min": True},
        {"duration_min": 30.5},
        {"duration_min": 541},
        {"duration_min": 10**9},
        {"step_min": 0},
        {"count": 0},
        {"count": 51},
        {"buffer_min": -1},
        {"tz": "Not/AZone"},
        {"tz": "../etc/passwd"},
        {"now": "2026-10-07 03:00:00"},
        {"now": 5},
        {"not_before": "garbage"},
        {"working_window": ("18:00", "09:00")},
        {"working_window": ("09:00", "09:00")},
        {"working_days": ()},
        {"working_days": (7,)},
        {"owner": "not a user"},
    ],
)
def test_FR_CAL_07b_bad_arguments_refuse_with_a_typed_error(kw):
    with pytest.raises(FreeSlotError) as exc:
        slots([], **kw)
    assert isinstance(exc.value, errors.PeopleInputError)
    assert exc.value.reason


def test_FR_CAL_07b_hostile_inputs_are_bounded():
    far = slots([], not_after="2999-01-01T00:00:00.000Z", count=50, step_min=1, duration_min=1)
    assert len(far) == 50
    assert far[-1] < "2026-10-22T00:00:00.000Z"
    huge = [entry(local("2026-10-07", "09:00"), local("2026-10-07", "10:00"), i=i) for i in range(2001)]
    with pytest.raises(FreeSlotError) as exc:
        slots(huge)
    assert exc.value.reason == "too_many_entries"
    assert slots(huge[:2000], count=1) == (local("2026-10-07", "10:00"),)
    for bad in ([{"owner": U, "state": "accepted"}], ["x"], [None], [entry("nope", None)]):
        with pytest.raises(FreeSlotError):
            slots(bad)
    assert slots([], not_after="2026-10-01T00:00:00.000Z") == ()  # range before now: nothing, not an error


def test_FR_CAL_07b_error_text_carries_no_record_text():
    secret = "ZZ-private-title"
    bad = entry("nope", None)
    bad["title"] = secret
    with pytest.raises(FreeSlotError) as exc:
        slots([bad])
    assert secret not in str(exc.value) and secret not in repr(exc.value)


# ---- properties: an independent brute-force check against a random fake calendar ----

_BASE = datetime(2026, 10, 7, 0, 0, tzinfo=UTC)


@st.composite
def calendars(draw):
    n = draw(st.integers(0, 25))
    out = []
    for i in range(n):
        start = _BASE + timedelta(minutes=draw(st.integers(-600, 60 * 24 * 12)))
        length = draw(st.one_of(st.none(), st.integers(1, 60 * 30)))
        out.append(
            entry(
                ts(start),
                None if length is None else ts(start + timedelta(minutes=length)),
                state=draw(st.sampled_from(["accepted", "accepted", "proposed", "declined", "cancelled"])),
                owner=draw(st.sampled_from([U, U, "u_other"])),
                all_day=draw(st.booleans()) and length is None,
                i=i,
            )
        )
    return out


def _busy(es, tz, default_min, buffer_min):
    zone = ZoneInfo(tz)
    out = []
    for e in es:
        if e["owner"] != U or e["state"] != "accepted":
            continue
        s = datetime.strptime(e["start"], "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
        if e["all_day"]:
            d0 = s.astimezone(zone).date()
            a = datetime.combine(d0, datetime.min.time(), tzinfo=zone)
            b = datetime.combine(d0 + timedelta(days=1), datetime.min.time(), tzinfo=zone)
        else:
            a = s
            b = datetime.strptime(e["end"], "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC) if e["end"] else s
            if b <= a:
                b = a + timedelta(minutes=default_min)
        out.append(
            (a.astimezone(UTC) - timedelta(minutes=buffer_min), b.astimezone(UTC) + timedelta(minutes=buffer_min))
        )
    return out


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    es=calendars(),
    tz=st.sampled_from([IST, "America/New_York", "Europe/London", "UTC", "Australia/Lord_Howe"]),
    duration=st.sampled_from([15, 30, 45, 60, 90, 240]),
    step=st.sampled_from([5, 15, 30]),
    buffer=st.sampled_from([0, 0, 10, 30]),
    count=st.integers(1, 8),
    now_min=st.integers(0, 60 * 24 * 5),
)
def test_FR_CAL_07b_property_every_slot_is_free_inside_the_window_and_increasing(
    es, tz, duration, step, buffer, count, now_min
):
    now = ts(_BASE + timedelta(minutes=now_min))
    kw = {"tz": tz, "duration_min": duration, "step_min": step, "buffer_min": buffer, "count": count, "now": now}
    got = slots(es, **kw)
    assert got == slots(list(es), **kw)  # deterministic
    assert len(got) <= count
    assert list(got) == sorted(set(got))
    busy = _busy(es, tz, 60, buffer)
    zone = ZoneInfo(tz)
    for g in got:
        s = datetime.strptime(g, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
        e = s + timedelta(minutes=duration)
        assert g >= now
        assert s <= datetime.strptime(now, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC) + timedelta(days=14)
        assert all(not (s < b and a < e) for a, b in busy)
        ls, le = s.astimezone(zone), e.astimezone(zone)
        assert ls.date() == le.date() and ls.weekday() < 5
        assert (9, 0) <= (ls.hour, ls.minute) and (le.hour, le.minute) <= (18, 0)
        assert (ls.hour * 60 + ls.minute) % step == 0


def test_FR_CAL_07b_many_free_busy_intervals_are_refused_before_they_are_expanded():
    import time

    class Counting(list):  # a busy list that must never be walked
        def __iter__(self):
            raise AssertionError("intervals were expanded")

    row = {"start": local("2026-10-07", "09:00"), "end": local("2026-10-07", "09:30")}
    rows = [row] * 2000
    records = [{"user": U, "from": NOW, "to": NOW, "busy": rows} for _ in range(2000)]
    began = time.perf_counter()
    with pytest.raises(FreeSlotError) as exc:
        slots(records)
    assert exc.value.reason == "too_many_entries"
    assert time.perf_counter() - began < 1.0
    walked = Counting([row] * 2001)
    with pytest.raises(FreeSlotError) as exc:
        slots([{"user": U, "from": NOW, "to": NOW, "busy": walked}])
    assert exc.value.reason == "too_many_entries"


def test_FR_CAL_07b_exclude_ignores_only_the_named_entries():
    moved = entry(local("2026-10-07", "10:00"), local("2026-10-07", "11:00"), i=1)
    other = entry(local("2026-10-07", "09:00"), local("2026-10-07", "10:00"), i=2)
    fb = {
        "user": U,
        "from": NOW,
        "to": NOW,
        "busy": [{"start": local("2026-10-07", "10:00"), "end": local("2026-10-07", "10:30")}],
    }
    # without the exclusion the moved meeting blocks its own hour; with it the hour is free
    assert slots([moved, other], count=1) == (local("2026-10-07", "11:00"),)
    assert slots([moved, other], count=1, exclude=["ce_1"]) == (local("2026-10-07", "10:00"),)
    assert slots([moved, other], count=1, exclude={"ce_2"}) == (local("2026-10-07", "09:00"),)
    assert slots([moved, other], count=1, exclude=["ce_9"]) == slots([moved, other], count=1)
    # a free_busy interval is never dropped by exclude, even when its text names an id
    assert slots([moved, other, fb], count=1, exclude=["ce_1"]) == (local("2026-10-07", "10:30"),)
    for bad in ("ce_1", [1], 5):
        with pytest.raises(FreeSlotError):
            slots([], exclude=bad)


def test_FR_CAL_07b_offset_timestamps_are_refused_as_bad_entry():
    with pytest.raises(FreeSlotError) as exc:
        slots([entry("2026-10-07T09:00:00.000+05:00", "2026-10-07T10:00:00.000+05:00")])
    assert exc.value.reason == "bad_entry"
