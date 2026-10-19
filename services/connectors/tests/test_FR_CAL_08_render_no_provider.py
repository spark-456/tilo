"""FR-CAL-08 acceptance (c): "rendering makes 0 provider calls". PRD addendum 3.4 FR-CAL-08 ("no model call to
render the calendar"), 4 (cost), 6.6 (the safety screen of untrusted calendar text), PRD 6.6 EFF-01;
API_FR_CAL_08.md "tilo_connectors.calendar_cache" (`agenda`, the render seam) and "Acceptance tests (c)".

Render is `agenda(store, user_id, start=..., end=...)`: a pure read of the cached entries. The one safety
screen of a new or changed title happens during a sync inside the window, through the injected `Screen`; it
is a SafetyProvider call, never a model call, never on render. With every tilo_providers method patched to
raise, neither path may touch a provider. Every test fails today with ModuleNotFoundError:
tilo_connectors.calendar_cache (or .calendar_sync).
"""

from __future__ import annotations

import inspect
import subprocess
import sys
import time as real_time
from datetime import UTC, datetime, timedelta

import pytest
from _calendar_lib import (
    CONNECTORS_SRC,
    PRIYA,
    W_PRIYA,
    CountingScreen,
    agenda_item_errors,
    entry_errors,
    expected_agenda,
    make_cal_env,
    make_conn,
    make_entry,
    make_state,
    module_imports,
    outcome_for,
    patch_all_providers,
    run_ticks,
    seed_calendar,
    static_problems,
)
from _connectors_lib import format_ts
from hypothesis import given, settings
from hypothesis import strategies as st

BASE = datetime(2026, 10, 8, 4, 0, tzinfo=UTC)
CACHE = CONNECTORS_SRC / "calendar_cache.py"
SYNC = CONNECTORS_SRC / "calendar_sync.py"
ADAPTER = CONNECTORS_SRC / "adapters" / "calendar.py"


class SpyStore:
    """Delegates to a store and records which methods were called."""

    def __init__(self, inner):
        self._inner = inner
        self.called: list[str] = []

    def __getattr__(self, name):
        attr = getattr(self._inner, name)
        if not callable(attr):
            return attr

        def wrapper(*args, **kwargs):
            self.called.append(name)
            return attr(*args, **kwargs)

        return wrapper


def _store_with(entries_by_conn):
    """An InMemoryCalendarStore holding the given entries, committed the way a sync would."""
    from tilo_connectors.calendar_cache import InMemoryCalendarStore

    store = InMemoryCalendarStore()
    for conn, entries in entries_by_conn:
        state = store.add(make_state(conn))
        assert store.commit(state, make_state(conn, generation=1), upserts=entries, removals=[]) is True
    return store


# ---------------------------------------------------------------------------
# (c) agenda() with every provider patched to raise


def test_FR_CAL_08_c_rendering_the_agenda_makes_zero_provider_calls_and_zero_screen_calls(monkeypatch):
    conn = make_conn()
    entries = [
        make_entry(conn, "e1", title="Standup", start="2026-10-08T04:00:00.000Z", end="2026-10-08T04:30:00.000Z"),
        make_entry(conn, "e2", title="Review", start="2026-10-08T06:00:00.000Z", end="2026-10-08T07:00:00.000Z"),
        make_entry(
            conn, "e3", title="Offsite", start="2026-10-09T00:00:00.000Z", end="2026-10-10T00:00:00.000Z", all_day=True
        ),
        make_entry(
            conn,
            "e4",
            title="Declined",
            start="2026-10-08T05:00:00.000Z",
            end="2026-10-08T06:00:00.000Z",
            state="declined",
        ),
        make_entry(conn, "e5", title="Next month", start="2026-11-20T05:00:00.000Z", end="2026-11-20T06:00:00.000Z"),
    ]
    store = _store_with([(conn, entries)])
    screen = CountingScreen()
    calls = patch_all_providers(monkeypatch)
    from tilo_connectors.calendar_cache import agenda

    rows = agenda(store, PRIYA, start="2026-10-08T00:00:00.000Z", end="2026-10-12T00:00:00.000Z")

    assert calls == [], "no ModelProvider or SafetyProvider method was called"
    assert screen.calls == []
    assert [r["title"] for r in rows] == ["Standup", "Review", "Offsite"]
    assert rows == tuple(expected_agenda(entries, PRIYA, "2026-10-08T00:00:00.000Z", "2026-10-12T00:00:00.000Z"))
    for row in rows:
        assert agenda_item_errors(row) == []
        assert row["kind"] == "event" and row["state"] == "confirmed" and row["shared"] is False
        assert row["source"]["kind"] == "calendar_entry"


def test_FR_CAL_08_c_rendering_a_synced_calendar_makes_no_provider_call_and_no_google_request(monkeypatch):
    ce = make_cal_env(start="2026-10-07T03:30:00.000Z")
    seed_calendar(ce)
    first = outcome_for(ce.run())
    assert first.status == "synced" and first.screened == 5
    screened, requests = len(ce.screen.calls), len(ce.cal.requests)
    calls = patch_all_providers(monkeypatch)
    from tilo_connectors.calendar_cache import agenda

    rows = agenda(ce.store, PRIYA, start="2026-10-08T00:00:00.000Z", end="2026-10-15T00:00:00.000Z")

    assert calls == []
    assert len(ce.screen.calls) == screened, "the safety screen is a sync step, not a render step"
    assert len(ce.cal.requests) == requests, "rendering never talks to Google"
    assert len(rows) == 9, "evt_a, evt_b and seven series instances (Oct 8 to Oct 14) inside the week"
    assert all(agenda_item_errors(r) == [] for r in rows)
    assert [r["start"] for r in rows] == sorted(r["start"] for r in rows)


def test_FR_CAL_08_c_agenda_has_no_provider_like_parameter_and_calls_nothing_but_entries():
    from tilo_connectors.calendar_cache import agenda

    parameters = inspect.signature(agenda).parameters
    assert list(parameters) == ["store", "user_id", "start", "end"]
    assert (
        parameters["start"].kind is inspect.Parameter.KEYWORD_ONLY
        and parameters["end"].kind is inspect.Parameter.KEYWORD_ONLY
    )
    for name in parameters:
        assert not any(word in name.lower() for word in ("provider", "model", "llm", "screen", "safety", "client"))
    conn = make_conn()
    spy = SpyStore(_store_with([(conn, [make_entry(conn, "e1")])]))

    rows = agenda(spy, PRIYA, start="2026-10-07T00:00:00.000Z", end="2026-10-09T00:00:00.000Z")

    assert len(rows) == 1
    assert set(spy.called) == {"entries"}, "the render seam reads the cache and nothing else"


@pytest.mark.parametrize(
    "start, end",
    [
        ("soon", "2026-10-09T00:00:00.000Z"),
        ("2026-10-08T00:00:00.000Z", "later"),
        ("2026-10-08", "2026-10-09"),
        ("2026-10-08T00:00:00Z", "2026-10-09T00:00:00Z"),
        ("2026-10-09T00:00:00.000Z", "2026-10-09T00:00:00.000Z"),  # start >= end
        ("2026-10-10T00:00:00.000Z", "2026-10-09T00:00:00.000Z"),
        ("2026-10-01T00:00:00.000Z", "2026-11-01T00:00:00.001Z"),  # just over 31 days
        ("2026-01-01T00:00:00.000Z", "2026-12-31T00:00:00.000Z"),
    ],
)
def test_FR_CAL_08_c_agenda_refuses_a_bad_or_over_long_range(start, end):
    from tilo_connectors.calendar_cache import InMemoryCalendarStore, agenda

    with pytest.raises(ValueError):
        agenda(InMemoryCalendarStore(), PRIYA, start=start, end=end)


def test_FR_CAL_08_c_agenda_accepts_a_range_of_exactly_31_days():
    from tilo_connectors.calendar_cache import InMemoryCalendarStore, agenda

    assert (
        agenda(InMemoryCalendarStore(), PRIYA, start="2026-10-01T00:00:00.000Z", end="2026-11-01T00:00:00.000Z") == ()
    )


def test_FR_CAL_08_c_agenda_shows_only_the_owners_accepted_entries_and_hands_out_copies():
    from tilo_connectors.calendar_cache import agenda

    mine, theirs = make_conn(), make_conn("u_dana", "org_globex", "w_desk_dana")
    store = _store_with(
        [
            (mine, [make_entry(mine, "e1", title="Mine"), make_entry(mine, "e2", title="Proposed", state="proposed")]),
            (theirs, [make_entry(theirs, "e1", title="Theirs")]),
        ]
    )

    rows = agenda(store, PRIYA, start="2026-10-07T00:00:00.000Z", end="2026-10-09T00:00:00.000Z")
    other = agenda(store, "u_dana", start="2026-10-07T00:00:00.000Z", end="2026-10-09T00:00:00.000Z")

    assert [r["title"] for r in rows] == ["Mine"] and [r["title"] for r in other] == ["Theirs"]
    rows[0]["title"] = "tampered"
    again = agenda(store, PRIYA, start="2026-10-07T00:00:00.000Z", end="2026-10-09T00:00:00.000Z")
    assert again[0]["title"] == "Mine", "a render row is a copy"


def test_FR_CAL_08_c_agenda_overlap_rules_for_entries_at_the_edges_of_the_range():
    from tilo_connectors.calendar_cache import agenda

    conn = make_conn()
    entries = [
        make_entry(conn, "before", start="2026-10-07T22:00:00.000Z", end="2026-10-08T00:00:00.000Z"),  # ends at start
        make_entry(conn, "overlap_start", start="2026-10-07T23:00:00.000Z", end="2026-10-08T01:00:00.000Z"),
        make_entry(conn, "at_end", start="2026-10-09T00:00:00.000Z", end="2026-10-09T01:00:00.000Z"),  # starts at end
        make_entry(conn, "overlap_end", start="2026-10-08T23:00:00.000Z", end="2026-10-09T01:00:00.000Z"),
        make_entry(conn, "zero_at_start", start="2026-10-08T00:00:00.000Z", end="2026-10-08T00:00:00.000Z"),
        make_entry(conn, "zero_before", start="2026-10-07T23:59:59.999Z", end="2026-10-07T23:59:59.999Z"),
        make_entry(conn, "inside", start="2026-10-08T10:00:00.000Z", end="2026-10-08T11:00:00.000Z"),
    ]
    store = _store_with([(conn, entries)])

    rows = agenda(store, PRIYA, start="2026-10-08T00:00:00.000Z", end="2026-10-09T00:00:00.000Z")

    refs = [next(e["source"]["ref"] for e in entries if e["id"] == r["source"]["id"]) for r in rows]
    assert refs == ["overlap_start", "zero_at_start", "inside", "overlap_end"]


_minutes = st.integers(min_value=-3 * 1440, max_value=20 * 1440)


@settings(max_examples=60, deadline=None)
@given(
    st.lists(
        st.tuples(
            st.sampled_from([0, 1]),  # owner
            _minutes,
            st.sampled_from([0, 1, 30, 60, 1440, 3 * 1440]),  # duration in minutes (0: zero-length)
            st.sampled_from(["accepted", "accepted", "accepted", "proposed", "declined", "cancelled"]),
            st.booleans(),
        ),
        max_size=25,
    ),
    st.integers(min_value=-2 * 1440, max_value=15 * 1440),
    st.integers(min_value=1, max_value=31 * 1440),
    st.sampled_from([0, 1]),
)
def test_FR_CAL_08_property_agenda_equals_the_documented_read_model(spec, query_start, span, who):
    from tilo_connectors.calendar_cache import agenda

    conns = [make_conn(PRIYA, "org_acme", W_PRIYA), make_conn("u_dana", "org_globex", "w_desk_dana")]
    base = datetime(2026, 10, 7, tzinfo=UTC)
    per_conn: dict[int, list[dict]] = {0: [], 1: []}
    for n, (owner, offset, duration, state, all_day) in enumerate(spec):
        start = format_ts(base + timedelta(minutes=offset))
        end = format_ts(base + timedelta(minutes=offset + duration))
        per_conn[owner].append(
            make_entry(conns[owner], f"e{n}", title=f"T{n}", start=start, end=end, state=state, all_day=all_day)
        )
    store = _store_with([(conns[i], per_conn[i]) for i in (0, 1)])
    start = format_ts(base + timedelta(minutes=query_start))
    end = format_ts(base + timedelta(minutes=query_start + span))
    user = conns[who].user_id

    rows = agenda(store, user, start=start, end=end)

    assert list(rows) == expected_agenda(per_conn[who], user, start, end)
    assert all(agenda_item_errors(r) == [] for r in rows)
    assert not {r["source"]["id"] for r in rows} & {e["id"] for e in per_conn[1 - who]}, "nobody else's entries"


# ---------------------------------------------------------------------------
# Static and import-time checks


def test_FR_CAL_08_c_a_fresh_interpreter_importing_calendar_cache_loads_no_provider_module():
    code = (
        "import sys, tilo_connectors.calendar_cache\n"
        "roots = ('tilo_providers', 'openai', 'anthropic', 'vertexai')\n"
        "bad = sorted(m for m in sys.modules if m.split('.')[0] in roots or m.startswith('google.genai'))\n"
        "print('LOADED:' + ','.join(bad))\n"
    )

    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120, check=False)

    assert done.returncode == 0, done.stderr[-600:]
    assert done.stdout.strip() == "LOADED:", done.stdout


def test_FR_CAL_08_c_calendar_cache_imports_only_the_standard_library_time_and_schema():
    assert CACHE.is_file(), "services/connectors/src/tilo_connectors/calendar_cache.py does not exist yet"
    stdlib = set(sys.stdlib_module_names)

    foreign = []
    for name, line in module_imports(CACHE):
        if name.startswith("."):
            if name not in (".", "._time", "._schema"):
                foreign.append(f"{CACHE.name}:{line} {name}")
        elif name.split(".")[0] not in stdlib:
            foreign.append(f"{CACHE.name}:{line} {name}")

    assert foreign == [], "calendar_cache.py imports only the standard library, ._time and ._schema"
    assert static_problems(CACHE) == [], "and it logs nothing"


def test_FR_CAL_08_c_calendar_sync_and_the_adapter_import_no_provider_no_network_and_no_logging():
    assert static_problems(SYNC) == []
    assert static_problems(ADAPTER) == []


def test_FR_CAL_08_c_calendar_sync_takes_no_model_provider_and_no_way_to_name_a_world_or_owner():
    from tilo_connectors.calendar_sync import CalendarSync

    init = inspect.signature(CalendarSync.__init__).parameters
    assert set(init) - {"self"} == {"config", "events", "store", "kms", "screen", "zone_of", "clock", "emit"}
    assert all(p.kind is inspect.Parameter.KEYWORD_ONLY for n, p in init.items() if n != "self")
    assert not any(word in name.lower() for name in init for word in ("provider", "model", "llm"))
    assert set(inspect.signature(CalendarSync.run_due).parameters) == {"self"}, "run_due reads everything from state"
    assert set(inspect.signature(CalendarSync.register).parameters) == {"self", "user_id", "org_id", "world_id"}
    assert set(inspect.signature(CalendarSync.forget).parameters) == {"self", "user_id"}
    public = {n for n in dir(CalendarSync) if not n.startswith("_")}
    assert not public & {"sync", "sync_now", "run", "refresh", "render", "agenda"}, "there is no 'sync now' method"


# ---------------------------------------------------------------------------
# (c) the 48-hour run with every provider patched to raise


def test_FR_CAL_08_c_the_48_hour_run_completes_with_providers_patched_and_the_screen_costs_one_call_per_new_title(
    monkeypatch,
):
    def no_sleep(*a, **k):
        raise AssertionError("the sync slept")

    monkeypatch.setattr(real_time, "sleep", no_sleep)
    calls = patch_all_providers(monkeypatch)
    ce = make_cal_env()
    titles = seed_calendar(ce)  # five distinct titles; the series' ten instances share one

    def changes(i, now, ce):
        if now == "2026-10-07T06:00:00.000Z":
            ce.cal.update_event(PRIYA, "evt_a", summary="Design review v2")  # a changed title: one call
            ce.cal.add_event(
                PRIYA, "evt_e", "Retro", BASE + timedelta(days=4), BASE + timedelta(days=4, hours=1)
            )  # new
            ce.cal.add_event(
                PRIYA, "evt_e2", "Retro", BASE + timedelta(days=5), BASE + timedelta(days=5, hours=1)
            )  # same run, same title
            ce.cal.update_event(PRIYA, "evt_c", start=BASE + timedelta(days=31), end=BASE + timedelta(days=31, hours=2))
        if now == "2026-10-07T10:00:00.000Z":
            ce.cal.expire_sync_tokens()  # a full re-list: every title is unchanged, so no title is screened again

    log = run_ticks(ce, before=changes)

    assert calls == [], "no ModelProvider or SafetyProvider method was called"
    assert all(outcome_for(o).status in ("synced", "skipped") for _, o in log)
    expected = sorted(list(titles.values()) + ["Design review v2", "Retro"])
    assert sorted(ce.screen.calls) == expected, "one call per distinct new or changed title, none for an unchanged one"
    assert len(ce.screen.calls) == 7 and len(set(ce.screen.calls)) == 7
    full_runs = [o for _, os in log for o in os if o.kind == "full"]
    assert len(full_runs) == 2 and sum(o.screened for _, os in log for o in os) == 7
    assert [o.screened for o in full_runs] == [5, 0]
    assert len(ce.store.entries(PRIYA)) == 16, "14 seeded, the Retro pair"


def test_FR_CAL_08_c_an_unchanged_title_is_not_screened_again_and_keeps_its_stored_flag():
    screen = CountingScreen(lambda text: {"flagged": text == "Suspicious", "reason": None})
    ce = make_cal_env(start="2026-10-07T03:30:00.000Z", screen=screen)
    ce.cal.add_event(PRIYA, "e1", "Suspicious", BASE, BASE + timedelta(hours=1))
    ce.cal.add_event(PRIYA, "e2", "Fine", BASE + timedelta(days=1), BASE + timedelta(days=1, hours=1))
    ce.run()
    assert {e["title"]: e["flagged"] for e in ce.store.entries(PRIYA)} == {"Suspicious": True, "Fine": False}
    ce.cal.update_event(PRIYA, "e1", start=BASE + timedelta(hours=2), end=BASE + timedelta(hours=3))  # time only
    ce.clock.advance(900)

    out = outcome_for(ce.run())

    assert out.changed == 1 and out.screened == 0 and len(screen.calls) == 2
    assert {e["title"]: e["flagged"] for e in ce.store.entries(PRIYA)} == {"Suspicious": True, "Fine": False}
    assert all(entry_errors(e) == [] for e in ce.store.entries(PRIYA))
