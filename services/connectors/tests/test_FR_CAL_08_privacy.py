"""FR-CAL-08 / FR-CAL-02: what the cache keeps and what never leaks. contracts/people.rules.md PE-13 (a synced
event keeps title, times, all-day flag and a count of other attendees; disconnecting deletes the cache), PE-04
(a person reads only their own calendar), PE-12 (calendar.synced: a count, never a title, in the person's
Desk world), PE-16, PE-19, PE-21 (`flagged`), PE-24 (control and bidi characters); PRD SEC-02 (one scope, the
broker), 16.1 (no secret or title in any event, log, error or repr); API_FR_CAL_08.md "Building the commit",
"Commit", "Emit", "The secret-like values" and the hostile cases "Malicious event", "Privacy", "Secrets",
"Disconnect", "Duplicate delivery". BQ-CAL8-4, BQ-CAL8-5, BQ-CAL8-6.

Every test fails today with ModuleNotFoundError: tilo_connectors.calendar_sync (or .calendar_cache,
.adapters.calendar).
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from _calendar_lib import (
    ALLOWED_PARAM_KEYS,
    CALENDAR_READONLY,
    DANA,
    ENTRY_KEYS,
    IST,
    LOS_ANGELES,
    NEW_YORK,
    NO_TITLE,
    ORG,
    ORG_B,
    PRIYA,
    W_DANA,
    W_PRIYA,
    entry_errors,
    everything_text,
    hostile_item,
    local_to_ts,
    make_cal_env,
    outcome_for,
    raw_item,
    recording_store,
    sealed_aad,
    seed_calendar,
)
from _gapi_lib import log_text
from _oauth_lib import fake_secret, leaks, schema_errors, validate_part
from hypothesis import given, settings
from hypothesis import strategies as st

OPEN = "2026-10-07T03:30:00.000Z"  # 09:00 in Asia/Kolkata
BASE = datetime(2026, 10, 8, 4, 0, tzinfo=UTC)
CONNECTION_ID = re.compile(r"cc_[0-9A-HJKMNP-TV-Z]{26}")


def _only(outcomes, user=PRIYA):
    return outcome_for(outcomes, user)


def _entries(ce, user=PRIYA):
    return ce.store.entries(user)


def _one_event(ce, event_id="evt1", title="Design review", **kw):
    ce.cal.add_event(PRIYA, event_id, title, BASE, BASE + timedelta(hours=1), **kw)


def _lib_entry_id(user, event):
    return "ce_g" + hashlib.sha256(f"{user}\x00primary\x00{event}".encode()).hexdigest()[:40]


# ---------------------------------------------------------------------------
# The malicious event (PE-13, PE-24, addendum 6.6-6.7)


def test_FR_CAL_08_PE_13_a_malicious_event_leaves_exactly_the_fifteen_schema_keys_and_nothing_planted(caplog):
    caplog.set_level(logging.DEBUG)
    ce = make_cal_env(start=OPEN)
    item, canaries = hostile_item()
    ce.cal.raw_items(PRIYA, [item])

    outcomes = ce.run()

    out = _only(outcomes)
    assert (out.status, out.kind, out.changed, out.skipped, out.screened) == ("synced", "full", 1, 0, 1)
    (entry,) = _entries(ce)
    assert set(entry) == ENTRY_KEYS, "exactly the 15 schema keys"
    assert entry_errors(entry) == []
    title = entry["title"]
    assert 1 <= len(title) <= 140
    assert "<img" in title, "HTML stays as literal text"
    assert "@" not in title and "meet.google.com" not in title and "://" not in title, "no address, no host, no link"
    assert not {"‮", "​", "\x00", "\ud800"} & set(title)
    assert entry["attendee_count"] == 500
    assert entry["flagged"] is True, "the screen flags the injection text"
    assert ce.screen.calls == [title], "the screen saw the cleaned title, once"
    blob = everything_text(ce, outcomes) + log_text(caplog)
    for name, canary in canaries.items():
        assert canary not in blob, f"the planted {name} reached the store, an outcome, a part, a request or a log"
    assert "attacker@example.org" not in blob and "zoom.us" not in blob
    assert [r for r in caplog.records if r.name.startswith("tilo_connectors")] == []


def test_FR_CAL_08_PE_13_odd_summaries_become_no_title_and_unusable_items_are_skipped_and_counted():
    ce = make_cal_env(start=OPEN)
    ce.cal.raw_items(
        PRIYA,
        [
            raw_item("t_dict", summary={"a": 1}),
            raw_item("t_list", summary=["x"]),
            raw_item("t_num", summary=5),
            raw_item("t_empty", summary="   "),
            raw_item("e" * 2000),
            raw_item("b_start", start={"dateTime": "soon"}),
            raw_item("b_offset", start={"dateTime": "2026-10-08T10:00:00"}, end={"dateTime": "2026-10-08T11:00:00"}),
            raw_item("b_order", start={"dateTime": "2026-10-08T11:00:00Z"}, end={"dateTime": "2026-10-08T10:00:00Z"}),
        ],
    )

    out = _only(ce.run())

    assert (out.status, out.skipped, out.changed) == ("synced", 4, 4)
    entries = _entries(ce)
    assert sorted(e["source"]["ref"] for e in entries) == ["t_dict", "t_empty", "t_list", "t_num"]
    assert {e["title"] for e in entries} == {NO_TITLE}
    assert all(e["flagged"] is False for e in entries), "NO_TITLE is Tilo's own text: not screened, not flagged"
    assert ce.screen.calls == [] and out.screened == 0
    assert all(entry_errors(e) == [] for e in entries)


def test_FR_CAL_08_PE_13_cancelled_declined_and_working_location_events_are_never_cached():
    ce = make_cal_env(start=OPEN)
    ce.cal.raw_items(
        PRIYA,
        [
            {"id": "gone", "status": "cancelled"},
            raw_item(
                "declined", attendees=[{"responseStatus": "accepted"}, {"self": True, "responseStatus": "declined"}]
            ),
            raw_item("place", eventType="workingLocation", summary="Home"),
            raw_item("keep", summary="Keep me"),
        ],
    )

    out = _only(ce.run())

    assert [e["source"]["ref"] for e in _entries(ce)] == ["keep"]
    assert (out.changed, out.skipped) == (1, 0)


def test_FR_CAL_08_PE_13_an_event_that_is_later_cancelled_declined_or_made_a_place_is_removed():
    ce = make_cal_env(start=OPEN)
    for name in ("cancel", "decline", "place", "stay"):
        _one_event(ce, name, f"Event {name}")
    _only(ce.run())
    assert len(_entries(ce)) == 4
    ce.cal.cancel_event(PRIYA, "cancel")
    ce.cal.update_event(PRIYA, "decline", attendees=[{"self": True, "responseStatus": "declined"}])
    ce.cal.update_event(PRIYA, "place", eventType="workingLocation")
    ce.clock.advance(900)

    out = _only(ce.run())

    assert (out.kind, out.changed) == ("incremental", 3)
    assert [e["source"]["ref"] for e in _entries(ce)] == ["stay"]
    assert ce.calendar_parts()[-1]["data"] == {"kind": "incremental", "changed": 3}


def test_FR_CAL_08_PE_13_the_removal_of_an_event_that_was_never_cached_counts_for_nothing():
    ce = make_cal_env(start=OPEN)
    _one_event(ce, "ghost")
    ce.cal.cancel_event(PRIYA, "ghost")  # cancelled before the first sync ever saw it as live
    _only(ce.run())
    parts_before = len(ce.parts)
    ce.cal.raw_items(PRIYA, [{"id": "never_seen", "status": "cancelled"}])
    ce.clock.advance(900)

    out = _only(ce.run())

    assert (out.status, out.changed, out.emitted) == ("synced", 0, False)
    assert len(ce.parts) == parts_before, "a delta that changes nothing writes no event"


# ---------------------------------------------------------------------------
# What is stored, field by field


def test_FR_CAL_08_PE_13_a_synced_entry_has_exactly_the_documented_fields_and_values():
    from tilo_connectors.calendar_cache import entry_id

    ce = make_cal_env(start=OPEN)
    start = datetime(2026, 10, 8, 10, 0, tzinfo=ZoneInfo(IST))
    ce.cal.add_event(PRIYA, "evt1", "Design review", start, start + timedelta(hours=1), attendees=3)
    now = ce.now()

    out = _only(ce.run())

    assert out.changed == 1
    (entry,) = _entries(ce)
    assert entry == {
        "id": entry_id(PRIYA, "evt1"),
        "org_id": ORG,
        "owner": PRIYA,
        "title": "Design review",
        "start": "2026-10-08T04:30:00.000Z",
        "end": "2026-10-08T05:30:00.000Z",
        "all_day": False,
        "attendee_count": 3,
        "source": {"kind": "google", "ref": "evt1", "synced_at": now},
        "state": "accepted",
        "share": None,
        "created_by": {"by": "tilo", "ref": "system", "at": now},
        "confirmed_by": None,
        "flagged": False,
        "updated_at": now,
    }
    assert entry["id"] == _lib_entry_id(PRIYA, "evt1")
    assert entry_errors(entry) == []


@pytest.mark.parametrize(
    "zone, first, last, start_utc, end_utc",
    [
        (IST, date(2026, 10, 8), date(2026, 10, 9), "2026-10-07T18:30:00.000Z", "2026-10-08T18:30:00.000Z"),
        (NEW_YORK, date(2026, 10, 8), date(2026, 10, 9), "2026-10-08T04:00:00.000Z", "2026-10-09T04:00:00.000Z"),
        (LOS_ANGELES, date(2026, 10, 8), date(2026, 10, 9), "2026-10-08T07:00:00.000Z", "2026-10-09T07:00:00.000Z"),
        ("UTC", date(2026, 10, 8), date(2026, 10, 9), "2026-10-08T00:00:00.000Z", "2026-10-09T00:00:00.000Z"),
        (NEW_YORK, date(2026, 10, 31), date(2026, 11, 2), "2026-10-31T04:00:00.000Z", "2026-11-02T05:00:00.000Z"),
    ],
    ids=["Kolkata", "New York", "Los Angeles", "UTC", "New York across the fall-back"],
)
def test_FR_CAL_08_PE_13_an_all_day_event_becomes_local_midnights_with_googles_exclusive_end(
    zone, first, last, start_utc, end_utc
):
    ce = make_cal_env(start=local_to_ts(date(2026, 10, 7), time(10, 0), zone), persons=[(PRIYA, ORG, W_PRIYA, zone)])
    ce.cal.add_event(PRIYA, "allday", "Offsite", first, last)

    _only(ce.run())

    (entry,) = _entries(ce)
    assert entry["all_day"] is True
    assert (entry["start"], entry["end"]) == (start_utc, end_utc), "midnight in the person's zone, end exclusive"
    assert entry_errors(entry) == []


def test_FR_CAL_08_PE_13_a_changed_entry_keeps_its_id_and_created_by_but_gets_new_updated_at_and_synced_at():
    ce = make_cal_env(start=OPEN)
    _one_event(ce)
    created = ce.now()
    _only(ce.run())
    (before,) = _entries(ce)
    ce.cal.update_event(
        PRIYA, "evt1", summary="Design review (moved)", start=BASE + timedelta(hours=3), end=BASE + timedelta(hours=4)
    )
    ce.clock.advance(900)
    later = ce.now()

    out = _only(ce.run())

    (after,) = _entries(ce)
    assert out.changed == 1 and after["id"] == before["id"]
    assert after["title"] == "Design review (moved)" and after["start"] == "2026-10-08T07:00:00.000Z"
    assert after["created_by"]["at"] == created, "created_by.at is the first time Tilo cached it"
    assert after["updated_at"] == later and after["source"]["synced_at"] == later
    assert entry_errors(after) == []


def test_FR_CAL_08_PE_13_an_unchanged_entry_is_not_rewritten_and_a_repeated_delta_changes_nothing():
    store = recording_store()
    ce = make_cal_env(start=OPEN, store=store)
    for k in range(3):
        _one_event(ce, f"evt{k}", f"Event {k}")
    _only(ce.run())
    assert [(applied, gen, len(ups), rems) for applied, gen, ups, rems in store.commits] == [(True, 1, 3, [])]
    ce.clock.advance(900)
    nothing = _only(ce.run())
    assert store.commits[-1][2:] == ([], []) and nothing.changed == 0

    ce.cal.update_event(PRIYA, "evt1", summary="Renamed")
    ce.clock.advance(900)
    _only(ce.run())
    assert len(store.commits[-1][2]) == 1, "only the changed entry is upserted"

    ce.cal.repeat_next_delta(PRIYA)  # Google delivers the same delta again
    ce.clock.advance(900)
    again = _only(ce.run())
    assert again.changed == 0 and store.commits[-1][2:] == ([], [])
    assert [p["data"]["changed"] for p in ce.calendar_parts()] == [3, 1], "no part the second time"


# ---------------------------------------------------------------------------
# The horizon (BQ-CAL8-4)


def test_FR_CAL_08_PE_13_events_outside_the_horizon_are_not_cached_and_the_edges_are_inclusive_of_the_window():
    ce = make_cal_env(start="2026-10-07T05:00:00.000Z")
    now = datetime(2026, 10, 7, 5, 0, tzinfo=UTC)
    ce.cal.raw_items(
        PRIYA,
        [
            raw_item(
                "old",
                start={"dateTime": (now - timedelta(days=8, hours=1)).isoformat()},
                end={"dateTime": (now - timedelta(days=8)).isoformat()},
            ),
            raw_item(
                "recent",
                start={"dateTime": (now - timedelta(days=6, hours=1)).isoformat()},
                end={"dateTime": (now - timedelta(days=6)).isoformat()},
            ),
            raw_item(
                "far",
                start={"dateTime": (now + timedelta(days=367)).isoformat()},
                end={"dateTime": (now + timedelta(days=367, hours=1)).isoformat()},
            ),
            raw_item(
                "near",
                start={"dateTime": (now + timedelta(days=365)).isoformat()},
                end={"dateTime": (now + timedelta(days=365, hours=1)).isoformat()},
            ),
        ],
    )

    out = _only(ce.run())

    assert sorted(e["source"]["ref"] for e in _entries(ce)) == ["near", "recent"]
    assert out.changed == 2 and out.skipped == 0


def test_FR_CAL_08_PE_13_an_entry_that_ended_before_the_horizon_is_evicted_without_counting_as_a_change():
    ce = make_cal_env(start="2026-10-07T05:00:00.000Z")
    ce.cal.add_event(
        PRIYA, "ended", "Past", datetime(2026, 10, 1, 4, 0, tzinfo=UTC), datetime(2026, 10, 1, 5, 0, tzinfo=UTC)
    )
    ce.cal.add_event(PRIYA, "future", "Future", BASE, BASE + timedelta(hours=1))
    first = _only(ce.run())
    assert first.changed == 2 and len(_entries(ce)) == 2
    ce.set_clock("2026-10-10T05:00:00.000Z")  # horizon start is now 2026-10-03: the Oct 1 entry is behind it

    out = _only(ce.run())

    assert [e["source"]["ref"] for e in _entries(ce)] == ["future"]
    assert (out.kind, out.changed, out.emitted) == ("incremental", 0, False), (
        "an eviction is housekeeping, not a change"
    )
    assert [p["data"] for p in ce.calendar_parts()] == [{"kind": "full", "changed": 2}]


# ---------------------------------------------------------------------------
# Ids, owners, orgs (PE-04)


@settings(max_examples=100, deadline=None)
@given(
    st.lists(
        st.tuples(
            st.from_regex(r"u_[0-9A-Za-z_]{1,48}", fullmatch=True),
            st.from_regex(r"[A-Za-z0-9_-]{1,128}", fullmatch=True),
        ),
        min_size=2,
        max_size=30,
        unique=True,
    )
)
def test_FR_CAL_08_property_entry_ids_follow_the_formula_match_the_contract_and_never_collide(pairs):
    from tilo_connectors.calendar_cache import entry_id

    ids = [entry_id(user, event) for user, event in pairs]

    assert len(set(ids)) == len(ids), "(user, event) pairs never collide"
    for (user, event), made in zip(pairs, ids, strict=True):
        assert made == _lib_entry_id(user, event)
        assert re.fullmatch(r"ce_[0-9A-Za-z_]{1,48}", made)
        assert entry_id(user, event) == made, "deterministic"


def test_FR_CAL_08_PE_04_two_attendees_of_one_event_get_separate_entries_and_never_see_each_other():
    from tilo_connectors.calendar_cache import agenda, entry_id

    ce = make_cal_env(
        start="2026-10-07T06:00:00.000Z",
        persons=[(PRIYA, ORG, W_PRIYA, IST), (DANA, ORG_B, W_DANA, "Asia/Dubai")],  # both windows are open at 06:00Z
    )
    a_title, b_title = "Priya-only title Tango", "Dana-only title Whisky"
    ce.cal.add_event(PRIYA, "shared_event_1", a_title, BASE, BASE + timedelta(hours=1))
    ce.cal.add_event(DANA, "shared_event_1", b_title, BASE, BASE + timedelta(hours=1))

    outcomes = ce.run()

    assert {o.user_id: o.status for o in outcomes} == {PRIYA: "synced", DANA: "synced"}
    (a,), (b,) = _entries(ce, PRIYA), _entries(ce, DANA)
    assert (
        a["id"] != b["id"]
        and a["id"] == entry_id(PRIYA, "shared_event_1")
        and b["id"] == entry_id(DANA, "shared_event_1")
    )
    assert (a["owner"], a["org_id"], a["title"]) == (PRIYA, ORG, a_title)
    assert (b["owner"], b["org_id"], b["title"]) == (DANA, ORG_B, b_title)
    rows_b = agenda(ce.store, DANA, start="2026-10-07T00:00:00.000Z", end="2026-10-14T00:00:00.000Z")
    rows_a = agenda(ce.store, PRIYA, start="2026-10-07T00:00:00.000Z", end="2026-10-14T00:00:00.000Z")
    assert [r["title"] for r in rows_b] == [b_title] and [r["title"] for r in rows_a] == [a_title]
    assert a_title not in str(rows_b) + str(_entries(ce, DANA)) and b_title not in str(rows_a) + str(
        _entries(ce, PRIYA)
    )
    assert all(r.user == PRIYA for r in ce.cal.requests_of(PRIYA)) and all(
        r.user == DANA for r in ce.cal.requests_of(DANA)
    )

    ce.sync.forget(PRIYA)

    assert ce.store.get(PRIYA) is None and _entries(ce, PRIYA) == ()
    assert _entries(ce, DANA) == (b,), "forgetting one person leaves the other's cache"
    assert ce.store.user_ids() == (DANA,)


def test_FR_CAL_08_owner_org_and_world_come_from_the_stored_connection_never_from_the_events():
    ce = make_cal_env(start=OPEN)
    ce.cal.raw_items(
        PRIYA,
        [
            raw_item(
                "spoof",
                organizer={"email": "u_mallory@example.org", "self": False},
                creator={"email": "owner@example.net"},
                owner="u_mallory",
                org_id="org_evil",
                world_id="w_evil",
                calendarId="mallory@example.org",
            )
        ],
    )

    outcomes = ce.run()

    (entry,) = _entries(ce)
    assert (entry["owner"], entry["org_id"]) == (PRIYA, ORG)
    (part,) = ce.calendar_parts()
    assert (part["user_id"], part["world_id"]) == (PRIYA, W_PRIYA)
    assert "mallory" not in everything_text(ce, outcomes) and "org_evil" not in everything_text(ce, outcomes)


# ---------------------------------------------------------------------------
# register


def test_FR_CAL_08_register_stores_a_fresh_state_and_makes_no_google_call_and_no_event():
    from tilo_connectors.calendar_cache import CalendarConnection

    ce = make_cal_env(start=OPEN, persons=[])
    ce.env.connect(PRIYA, "google_calendar", [CALENDAR_READONLY])
    ce.env.connect(DANA, "google_calendar", [CALENDAR_READONLY])
    ce.zones.update({PRIYA: IST, DANA: LOS_ANGELES})

    conn = ce.sync.register(user_id=PRIYA, org_id=ORG, world_id=W_PRIYA)
    other = ce.sync.register(user_id=DANA, org_id=ORG_B, world_id=W_DANA)

    assert isinstance(conn, CalendarConnection)
    assert (conn.user_id, conn.org_id, conn.world_id, conn.registered_at) == (PRIYA, ORG, W_PRIYA, OPEN)
    assert CONNECTION_ID.fullmatch(conn.connection_id) and conn.connection_id != other.connection_id
    state = ce.store.get(PRIYA)
    assert state.connection == conn
    assert (state.generation, state.sealed_token, state.next_due_at, state.last_run_at, state.failures) == (
        0,
        None,
        OPEN,
        None,
        0,
    )
    assert ce.cal.requests == [] and ce.parts == [], "no Google call and no event"
    assert ce.store.user_ids() == (DANA, PRIYA)


def test_FR_CAL_08_registering_the_same_person_again_changes_nothing_and_starts_no_full_sync():
    ce = make_cal_env(start=OPEN)
    _one_event(ce)
    _only(ce.run())
    state, token = ce.store.get(PRIYA), ce.cal.last_sync_token(PRIYA)

    again = ce.sync.register(user_id=PRIYA, org_id=ORG, world_id=W_PRIYA)

    assert again == state.connection and ce.store.get(PRIYA) == state, "no reset"
    ce.clock.advance(900)
    out = _only(ce.run())
    assert out.kind == "incremental" and ce.cal.requests_of(PRIYA)[-1].sync_token == token


@pytest.mark.parametrize("org, world", [("org_other", W_PRIYA), (ORG, "w_other_desk"), ("org_other", "w_other_desk")])
def test_FR_CAL_08_registering_a_person_under_another_org_or_world_is_refused_and_changes_nothing(org, world):
    from tilo_connectors.errors import CalendarSyncRefused

    ce = make_cal_env(start=OPEN)
    state = ce.store.get(PRIYA)

    with pytest.raises(CalendarSyncRefused):
        ce.sync.register(user_id=PRIYA, org_id=org, world_id=world)

    assert issubclass(CalendarSyncRefused, ValueError)
    assert ce.store.get(PRIYA) == state


BAD = [
    None,
    5,
    "",
    " ",
    "u_priya ",
    " u_priya",
    "u_priya\n",
    "x_priya",
    "u_pri ya",
    "u_" + "a" * 49,
    "U_PRIYA",
    b"u_priya",
]


@pytest.mark.parametrize("bad", BAD, ids=repr)
@pytest.mark.parametrize("field", ["user_id", "org_id", "world_id"])
def test_FR_CAL_08_register_refuses_an_id_that_is_not_a_str_in_its_common_pattern(field, bad):
    from tilo_connectors.errors import CalendarSyncRefused

    ce = make_cal_env(start=OPEN, persons=[])
    ids = {"user_id": "u_sam", "org_id": ORG, "world_id": "w_desk_sam"}
    ids[field] = bad

    with pytest.raises(CalendarSyncRefused):
        ce.sync.register(**ids)

    assert ce.store.user_ids() == ()


# ---------------------------------------------------------------------------
# calendar.synced


def test_FR_CAL_08_PE_12_a_calendar_synced_part_has_the_pinned_shape_and_never_a_title():
    ce = make_cal_env(start=OPEN)
    seed_calendar(ce)

    out = _only(ce.run())

    (part,) = ce.calendar_parts()
    assert set(part) == {"type", "authz", "data", "user_id", "world_id", "key"}
    assert part["type"] == "calendar.synced" and part["authz"] is None
    assert part["data"] == {"kind": "full", "changed": 14}
    assert schema_errors("events/data/calendar.synced.schema.json", part["data"]) == []
    validate_part(part)
    assert (part["user_id"], part["world_id"]) == (PRIYA, W_PRIYA)
    state = ce.state()
    assert part["key"] == f"{state.connection.connection_id}:{state.generation}", "one key per commit"
    assert out.emitted is True
    for title in ("Design review", "Dentist", "Daily standup"):
        assert title not in str(part)


def test_FR_CAL_08_PE_12_the_part_key_is_unique_per_commit_and_follows_the_generation():
    ce = make_cal_env(start=OPEN)
    _one_event(ce)
    _only(ce.run())
    keys = [ce.calendar_parts()[0]["key"]]
    for n in range(3):
        ce.cal.update_event(PRIYA, "evt1", summary=f"Change {n}")
        ce.clock.advance(900)
        _only(ce.run())
        keys.append(ce.calendar_parts()[-1]["key"])

    connection_id = ce.state().connection.connection_id
    assert keys == [f"{connection_id}:{g}" for g in (1, 2, 3, 4)]
    assert len(set(keys)) == 4


def test_FR_CAL_08_PE_12_a_first_sync_of_an_empty_calendar_emits_full_zero_and_a_quiet_poll_emits_nothing():
    ce = make_cal_env(start=OPEN)

    first = _only(ce.run())
    ce.clock.advance(900)
    quiet = _only(ce.run())

    assert (first.status, first.kind, first.changed, first.emitted) == ("synced", "full", 0, True)
    assert [p["data"] for p in ce.calendar_parts()] == [{"kind": "full", "changed": 0}]
    assert (quiet.status, quiet.kind, quiet.changed, quiet.emitted) == ("synced", "incremental", 0, False)


def test_FR_CAL_08_PE_12_an_emit_that_raises_leaves_the_run_synced_and_is_never_retried():
    ce = make_cal_env(start=OPEN)
    _one_event(ce)

    def boom(part):
        raise RuntimeError(f"event writer down {part['type']}")

    ce.sync = ce.new_sync(emit=boom)

    out = _only(ce.run())

    assert (out.status, out.kind, out.changed, out.emitted) == ("synced", "full", 1, False)
    assert len(_entries(ce)) == 1, "the cache is the truth"
    sent_before = len(ce.cal.requests_of(PRIYA))
    token = ce.cal.last_sync_token(PRIYA)
    ce.clock.advance(900)

    nxt = _only(ce.run())

    assert nxt.changed == 0 and nxt.emitted is False
    assert ce.cal.requests_of(PRIYA)[sent_before].sync_token == token, "the delta is not fetched again"
    assert ce.calendar_parts() == []


# ---------------------------------------------------------------------------
# Duplicate delivery


def test_FR_CAL_08_the_same_event_on_two_pages_is_one_entry_counted_once_and_the_last_copy_wins():
    ce = make_cal_env(start=OPEN, page_size=1)
    ce.cal.raw_items(
        PRIYA,
        [
            raw_item("dup", summary="First copy"),
            raw_item("other", summary="Other"),
            raw_item("dup", summary="Second copy"),
        ],
    )

    out = _only(ce.run())

    titles = {e["source"]["ref"]: e["title"] for e in _entries(ce)}
    assert titles == {"dup": "Second copy", "other": "Other"}
    assert out.changed == 2 and out.requests == 3
    assert ce.screen.calls.count("First copy") == 0, "only the surviving copy's title is screened"


# ---------------------------------------------------------------------------
# Secrets (SEC-02, 16.1)


def test_FR_CAL_08_SEC_02_the_sync_token_is_sealed_bound_to_the_user_and_connection_and_never_appears(caplog):
    from tilo_connectors.tokens import KmsError

    caplog.set_level(logging.DEBUG)
    ce = make_cal_env(start=OPEN)
    seed_calendar(ce)
    outcomes = list(ce.run())
    ce.cal.update_event(PRIYA, "evt_a", summary="Changed")
    ce.clock.advance(900)
    outcomes += ce.run()

    tokens = ce.cal.all_sync_tokens()
    assert len(tokens) == 2
    state = ce.state()
    assert state.sealed_token and isinstance(state.sealed_token, bytes)
    token = ce.cal.last_sync_token(PRIYA)
    assert token.encode() not in state.sealed_token, "the token is not in the sealed bytes in the clear"
    blob = everything_text(ce, outcomes, params=False) + log_text(caplog) + repr(state) + repr(ce.store)
    assert leaks(blob, tokens) == [], "no sync token in any part, outcome, repr, event or log"
    aad = sealed_aad(PRIYA, state.connection.connection_id)
    assert token.encode() in ce.kms.decrypt(state.sealed_token, aad=aad)
    for wrong in (sealed_aad(DANA, state.connection.connection_id), sealed_aad(PRIYA, "cc_" + "0" * 26), b""):
        with pytest.raises(KmsError):
            ce.kms.decrypt(state.sealed_token, aad=wrong)
    assert "syncToken" not in str(ce.parts), "it travels only in the request params"


def test_FR_CAL_08_SEC_02_every_request_asks_the_read_scope_only_and_sends_only_the_pinned_params():
    ce = make_cal_env(start=OPEN, page_size=2)
    seed_calendar(ce)
    ce.run()
    ce.cal.expire_sync_tokens()
    ce.clock.advance(900)
    ce.run()
    ce.clock.advance(900)
    ce.run()

    assert ce.spy.asked and all(
        asked == (PRIYA, "google_calendar", (CALENDAR_READONLY,), False) for asked in ce.spy.asked
    ), "the broker is asked for calendar.readonly and nothing else; no forced refresh was needed"
    for request in ce.cal.requests:
        assert request.method == "GET" and request.url.endswith("/calendars/primary/events")
        assert set(request.params) <= ALLOWED_PARAM_KEYS
        assert request.params["singleEvents"] == "true" and request.params["maxResults"] == 2
        assert not {"q", "showDeleted", "orderBy", "iCalUID", "updatedMin", "maxAttendees"} & set(request.params)
        assert request.token and request.token not in str(request.params)


def test_FR_CAL_08_SEC_02_a_403_whose_body_holds_a_title_and_a_token_is_failed_rejected_and_leaks_nothing(caplog):
    caplog.set_level(logging.DEBUG)
    ce = make_cal_env(start=OPEN)
    seed_calendar(ce)
    outcomes = list(ce.run())
    token = ce.cal.last_sync_token(PRIYA)
    planted_title, planted_token = "Secret Merger Lunch CANARY", fake_secret("planted-access-token")
    ce.cal.fail_next(403, body={"error": {"message": f"{planted_title} {planted_token} {token}"}})
    ce.clock.advance(900)

    out = _only(ce.run())
    outcomes.append(out)

    assert (out.status, out.reason, out.requests) == ("failed", "rejected", 1)
    blob = everything_text(ce, outcomes) + log_text(caplog)
    for secret in (planted_title, planted_token):
        assert secret not in blob


def test_FR_CAL_08_SEC_02_an_unexpected_exception_is_failed_error_with_its_type_only(caplog):
    caplog.set_level(logging.DEBUG)
    ce = make_cal_env(start=OPEN)

    class Exploding:
        def list_events(self, user_id, **kw):
            raise RuntimeError("Dentist at 3 with attacker@example.org CANARY-EXC")

    ce.sync = ce.new_sync(events=Exploding())

    out = _only(ce.run())

    assert (out.status, out.reason) == ("failed", "error")
    assert "CANARY-EXC" not in repr(out) + log_text(caplog) + everything_text(ce, [out])
    assert ce.state().failures == 1


def test_FR_CAL_08_SEC_02_a_whole_lifecycle_writes_no_log_record_from_tilo_connectors(caplog):
    from tilo_connectors.calendar_cache import agenda

    caplog.set_level(logging.DEBUG)
    ce = make_cal_env(start=OPEN)
    seed_calendar(ce)
    ce.run()
    ce.cal.fail_next(503)
    ce.clock.advance(900)
    ce.run()
    ce.clock.advance(60)
    ce.run()
    agenda(ce.store, PRIYA, start="2026-10-07T00:00:00.000Z", end="2026-10-20T00:00:00.000Z")
    ce.sync.forget(PRIYA)

    assert [r for r in caplog.records if r.name.startswith("tilo_connectors")] == []


# ---------------------------------------------------------------------------
# Disconnect and delete (PE-13, PE-16)


def test_FR_CAL_08_PE_13_forget_deletes_the_cache_and_the_token_together_and_is_idempotent():
    from tilo_connectors.calendar_cache import agenda

    ce = make_cal_env(start=OPEN)
    seed_calendar(ce)
    _only(ce.run())
    assert ce.state().sealed_token and len(_entries(ce)) == 14

    ce.sync.forget(PRIYA)
    ce.sync.forget(PRIYA)
    ce.sync.forget("u_never_registered")

    assert ce.store.get(PRIYA) is None
    assert _entries(ce) == ()
    assert ce.store.user_ids() == ()
    assert agenda(ce.store, PRIYA, start="2026-10-07T00:00:00.000Z", end="2026-10-20T00:00:00.000Z") == ()
    assert ce.run() == (), "nothing left to sync"


def test_FR_CAL_08_PE_13_after_forget_and_register_the_cache_starts_empty_and_the_token_is_gone():
    ce = make_cal_env(start=OPEN)
    _one_event(ce)
    _only(ce.run())
    ce.sync.forget(PRIYA)

    ce.sync.register(user_id=PRIYA, org_id=ORG, world_id=W_PRIYA)

    assert _entries(ce) == () and ce.store.get(PRIYA).sealed_token is None


def test_FR_CAL_08_PE_13_when_the_broker_says_not_connected_the_next_due_run_forgets_the_person_and_sends_nothing():
    ce = make_cal_env(start=OPEN)
    seed_calendar(ce)
    _only(ce.run())
    sent = len(ce.cal.requests)
    ce.env.broker.disconnect(PRIYA, "google_calendar")
    ce.clock.advance(900)

    out = _only(ce.run())

    assert (out.status, out.reason, out.changed, out.kind) == ("forgotten", "not_connected", 0, None)
    assert ce.store.get(PRIYA) is None and _entries(ce) == ()
    assert len(ce.cal.requests) == sent, "the fake logged no request"
    assert ce.run() == (), "a disconnected person is never synced again"
    ce.clock.advance(86_400)
    assert ce.run() == ()


def test_FR_CAL_08_PE_13_a_revoked_person_stays_out_of_every_later_tick_over_two_days():
    ce = make_cal_env(start=OPEN)
    _one_event(ce)
    _only(ce.run())
    ce.env.broker.disconnect(PRIYA, "google_calendar")
    ce.clock.advance(900)
    ce.run()
    sent = len(ce.cal.requests)

    for _ in range(48):
        ce.clock.advance(3600)
        assert ce.run() == ()

    assert len(ce.cal.requests) == sent
