"""FR-AGT-14 (PRD 8.6, 6.3): "A weekly schedule fires on time and reuses memory." This file is the "on time" arithmetic:
`next_slot(cadence, after)` is pure, weekly (weekday + local time + IANA zone) and DST-safe. Interface:
API_FR_AGT_14.md.

DST rules (design brief rule 9): a local time that does not exist that day fires at the next valid instant; an ambiguous
local time fires once, at its first occurrence. The brief does not say whether "the next valid instant" is the end of
the
gap (03:00 after 02:00 -> 03:00) or the shifted wall time (02:30 -> 03:30), so the gap tests accept anything from the
gap's
end to the shifted time and nothing else. Listed in the report.

Every expected instant below was computed with zoneinfo from the IANA database, not by the implementation.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from tilo_harness.schedule import Cadence, next_slot


def utc(*parts: int) -> datetime:
    return datetime(*parts, tzinfo=UTC)


NEW_YORK = "America/New_York"
LONDON = "Europe/London"


def test_FR_AGT_14_slot_is_the_next_local_weekday_and_time_converted_to_utc():
    monday_0900_ist = Cadence(weekday=0, hour=9, minute=0, tz="Asia/Kolkata")  # 03:30Z, Monday 2026-10-05
    assert next_slot(monday_0900_ist, utc(2026, 10, 4, 0, 0)) == utc(2026, 10, 5, 3, 30)
    assert next_slot(monday_0900_ist, utc(2026, 10, 5, 3, 29, 59)) == utc(2026, 10, 5, 3, 30)
    assert next_slot(monday_0900_ist, utc(2026, 10, 6, 0, 0)) == utc(2026, 10, 12, 3, 30)


def test_FR_AGT_14_slot_is_strictly_after_the_instant_it_is_given():
    cadence = Cadence(weekday=0, hour=9, minute=0, tz="Asia/Kolkata")
    due = utc(2026, 10, 5, 3, 30)
    assert next_slot(cadence, due) == due + timedelta(days=7)
    assert next_slot(cadence, due - timedelta(microseconds=1)) == due


def test_FR_AGT_14_weekday_is_the_local_one_not_the_utc_one():
    # Monday 01:00 in Kolkata is Sunday 19:30 UTC: the UTC weekday is not the cadence weekday.
    cadence = Cadence(weekday=0, hour=1, minute=0, tz="Asia/Kolkata")
    assert next_slot(cadence, utc(2026, 10, 4, 0, 0)) == utc(2026, 10, 4, 19, 30)
    # Auckland is UTC+13 in October (NZDT): Sunday 07:00 local is Saturday 18:00 UTC.
    auckland = Cadence(weekday=6, hour=7, minute=0, tz="Pacific/Auckland")
    assert next_slot(auckland, utc(2026, 10, 3, 0, 0)) == utc(2026, 10, 3, 18, 0)


def test_FR_AGT_14_an_aware_non_utc_input_is_the_same_instant_and_the_answer_is_utc():
    cadence = Cadence(weekday=0, hour=9, minute=0, tz="Asia/Kolkata")
    after = datetime(2026, 10, 5, 9, 0, tzinfo=ZoneInfo("Asia/Kolkata"))  # 03:30Z exactly
    slot = next_slot(cadence, after)
    assert slot == utc(2026, 10, 12, 3, 30)
    assert slot.utcoffset() == timedelta(0)


def test_FR_AGT_14_a_naive_datetime_is_refused():
    with pytest.raises(ValueError):
        next_slot(Cadence(weekday=0, hour=9, minute=0, tz="UTC"), datetime(2026, 10, 5, 3, 30))


@pytest.mark.parametrize(
    "bad",
    [
        {"weekday": 7},
        {"weekday": -1},
        {"hour": 24},
        {"hour": -1},
        {"minute": 60},
        {"minute": -1},
        {"tz": "Not/AZone"},
        {"tz": ""},
        {"tz": "+05:30"},
    ],
)
def test_FR_AGT_14_a_cadence_outside_its_ranges_or_with_an_unknown_zone_is_refused(bad):
    fields = {"weekday": 0, "hour": 9, "minute": 0, "tz": "Asia/Kolkata"} | bad
    with pytest.raises(ValueError):
        Cadence(**fields)


def test_FR_AGT_14_the_same_wall_clock_time_is_kept_across_a_dst_change():
    monday_0900 = Cadence(weekday=0, hour=9, minute=0, tz=NEW_YORK)
    # Autumn: 09:00 EDT = 13:00Z, a week later 09:00 EST = 14:00Z. Not exactly 7 * 24 h later.
    assert next_slot(monday_0900, utc(2026, 10, 26, 13, 0)) == utc(2026, 11, 2, 14, 0)
    # Spring: 09:00 EST = 14:00Z, a week later 09:00 EDT = 13:00Z.
    assert next_slot(monday_0900, utc(2026, 3, 2, 14, 0)) == utc(2026, 3, 9, 13, 0)


@pytest.mark.parametrize(
    ("tz", "day", "hour", "minute", "gap_end", "shifted", "next_week"),
    [
        # New York 2026-03-08: 02:00 EST jumps to 03:00 EDT, so Sunday 02:30 local does not exist.
        (NEW_YORK, (2026, 3, 8), 2, 30, utc(2026, 3, 8, 7, 0), utc(2026, 3, 8, 7, 30), utc(2026, 3, 15, 6, 30)),
        # London 2026-03-29: 01:00 GMT jumps to 02:00 BST, so Sunday 01:30 local does not exist.
        (LONDON, (2026, 3, 29), 1, 30, utc(2026, 3, 29, 1, 0), utc(2026, 3, 29, 1, 30), utc(2026, 4, 5, 0, 30)),
    ],
)
def test_FR_AGT_14_a_local_time_that_does_not_exist_fires_that_day_at_the_next_valid_instant(
    tz, day, hour, minute, gap_end, shifted, next_week
):
    cadence = Cadence(weekday=date(*day).weekday(), hour=hour, minute=minute, tz=tz)
    slot = next_slot(cadence, datetime(*day, tzinfo=UTC) - timedelta(days=1))
    assert gap_end <= slot <= shifted, (
        f"{slot.isoformat()} is not between {gap_end.isoformat()} and {shifted.isoformat()}"
    )
    # And the week after is back on the real wall time, once.
    assert next_slot(cadence, slot) == next_week


@pytest.mark.parametrize(
    ("tz", "day", "first", "second", "next_week"),
    [
        # New York 2026-11-01: 02:00 EDT falls back to 01:00 EST, so Sunday 01:30 happens twice.
        (NEW_YORK, (2026, 11, 1), utc(2026, 11, 1, 5, 30), utc(2026, 11, 1, 6, 30), utc(2026, 11, 8, 6, 30)),
        # London 2026-10-25: 02:00 BST falls back to 01:00 GMT, so Sunday 01:30 happens twice.
        (LONDON, (2026, 10, 25), utc(2026, 10, 25, 0, 30), utc(2026, 10, 25, 1, 30), utc(2026, 11, 1, 1, 30)),
    ],
)
def test_FR_AGT_14_an_ambiguous_local_time_fires_once_at_its_first_occurrence(tz, day, first, second, next_week):
    cadence = Cadence(weekday=date(*day).weekday(), hour=1, minute=30, tz=tz)
    assert next_slot(cadence, datetime(*day, tzinfo=UTC) - timedelta(days=1)) == first
    assert next_slot(cadence, first) == next_week  # never the second occurrence an hour later
    assert next_slot(cadence, first + timedelta(minutes=15)) == next_week
    assert next_slot(cadence, second - timedelta(microseconds=1)) == next_week


# ---------------------------------------------------------------------------
# Properties (Hypothesis). Local hours 6..22 stay clear of every DST gap and overlap in these zones.

ZONES = [NEW_YORK, LONDON, "Asia/Kolkata", "Pacific/Auckland", "Australia/Lord_Howe", "America/Sao_Paulo", "UTC"]
cadences = st.builds(
    Cadence,
    weekday=st.integers(0, 6),
    hour=st.integers(6, 22),
    minute=st.sampled_from([0, 15, 30, 45]),
    tz=st.sampled_from(ZONES),
)
instants = st.datetimes(min_value=datetime(2025, 1, 1), max_value=datetime(2031, 12, 31)).map(
    lambda d: d.replace(tzinfo=UTC)
)
FUZZ = settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])


@FUZZ
@given(cadence=cadences, after=instants)
def test_FR_AGT_14_property_slot_is_after_input_within_a_week_and_on_the_cadence_wall_time(cadence, after):
    slot = next_slot(cadence, after)
    assert slot > after
    assert slot - after <= timedelta(days=7, hours=1)
    local = slot.astimezone(ZoneInfo(cadence.tz))
    assert (local.weekday(), local.hour, local.minute, local.second, local.microsecond) == (
        cadence.weekday,
        cadence.hour,
        cadence.minute,
        0,
        0,
    )


@FUZZ
@given(cadence=cadences, after=instants)
def test_FR_AGT_14_property_slots_are_exactly_one_local_week_apart_and_strictly_increasing(cadence, after):
    zone = ZoneInfo(cadence.tz)
    slot = next_slot(cadence, after)
    for _ in range(6):
        following = next_slot(cadence, slot)
        assert following > slot
        assert (following.astimezone(zone).date() - slot.astimezone(zone).date()) == timedelta(days=7)
        assert next_slot(cadence, following - timedelta(microseconds=1)) == following  # nothing between two slots
        slot = following


@FUZZ
@given(cadence=cadences, after=instants)
def test_FR_AGT_14_property_next_slot_is_pure(cadence, after):
    assert next_slot(cadence, after) == next_slot(cadence, after)
