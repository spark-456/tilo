"""FR-PA-20 invariants of `GET /v1/effort` over generated ledgers and events (Hypothesis): the numbers are always the
ledger's and the events' for the signed-in person's own worlds, whatever the mix of spend, finished units, redelivery,
completion and foreign runs. Credits are whole numbers and baselines binary-exact, so every sum is checked for equality.
See `API_FR_PA_20.md`. No network, no provider.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

import pytest
from _fr_pa_20_lib import (
    ALLOWED_KEYS,
    HUMAN_TIME_KEY,
    OWNER_OF,
    OWNER_RUNS,
    RUN_OF,
    Effort,
    commits,
    event,
    expected_time_saved,
    make,
    meeting_row,
    minutes_of,
    task,
    triple,
    walk_keys,
)
from _ppl11a_lib import OWNER, PRIYA
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from tilo_metering import LedgerEntry

UNITS = st.lists(
    st.tuples(st.sampled_from(["reply_handled", "mail_triaged", "research"]), st.integers(0, 9)), max_size=4
)
CREDITS = st.lists(st.integers(0, 20), max_size=3)
WORLD = st.tuples(CREDITS, UNITS, st.booleans(), st.booleans())  # spend, finished units, redelivered, completed
SCENARIO = st.fixed_dictionaries({world: WORLD for world in RUN_OF})
WHEN = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)


@pytest.fixture()
def fx(people_rig, tmp_path) -> Effort:
    return make(people_rig, tmp_path)


def _load(fx: Effort, scenario: dict) -> list[LedgerEntry]:
    ledger: list[LedgerEntry] = []
    for world, (spend, units, redelivered, completed) in scenario.items():
        run, owner = RUN_OF[world], OWNER_OF[world]
        events = [
            event(
                "world.planned",
                world,
                1,
                {"tier": "village", "approach": "standard", "unit_count": 3, "credits": {"min": 20, "max": 35}},
                check=False,
            )
        ]
        for number, (unit_type, count) in enumerate(units, start=2):
            events.append(
                event("building.completed", world, number, {"unit_type": unit_type, "unit_count": count}, check=False)
            )
        if redelivered and units:
            events.append(dict(events[-1]))
        if completed:
            events.append(
                event("world.completed", world, 20, {"credits_used": 1.0, "deliverable_count": 1}, check=False)
            )
        fx.store.events[world] = events
        for step, credits in enumerate(spend):
            ledger.append(LedgerEntry("commit", run, owner, "org_test", WHEN, f"U{step}", float(credits)))
        ledger.append(LedgerEntry("reserve", run, owner, "org_test", WHEN, "U9", 999.0))  # never spend
        ledger.append(LedgerEntry("release", run, owner, "org_test", WHEN, "U9"))
    fx.set_ledger(ledger)
    return ledger


@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(scenario=SCENARIO)
def test_FR_PA_20_property_the_numbers_are_the_ledgers_and_the_events_for_the_callers_own_worlds(fx, scenario):
    ledger = _load(fx, scenario)
    for who, runs in ((OWNER, OWNER_RUNS), (PRIYA, {"w_p1": "r_p1"})):
        body = fx.body(who)
        assert [t["run_id"] for t in body["tasks"]] == sorted(runs.values())
        # credits: equal to the ledger, per run and in total; the reserve and the other person's spend never enter
        for world, run in runs.items():
            row = task(body, world)
            assert row["credits"] == math.fsum(e.credits for e in commits(ledger, [run]))
            assert row["completed"] == scenario[world][3]
        assert body["totals"]["credits"] == math.fsum(e.credits for e in commits(ledger, runs.values()))
        assert body["totals"]["credits"] == math.fsum(t["credits"] for t in body["tasks"])
        assert body["totals"]["completed_tasks"] == sum(scenario[w][3] for w in runs)
        # time saved: the method written out again from the events, per run; totals are the rows' sums; a range
        for world in runs:
            row = task(body, world)
            assert triple(row["time_saved"]) == expected_time_saved(fx.store.events[world], fx.baselines)
        assert triple(body["totals"]["time_saved"]) == minutes_of(body["tasks"])
        for ts in [body["totals"]["time_saved"], *(t["time_saved"] for t in body["tasks"])]:
            assert 0 <= ts["low"] <= ts["minutes"] <= ts["high"]
            assert ts["steering_measured"] is False
        # a meeting is a view of its own world's task, never extra
        if who == OWNER:
            for meeting_id, world in (("mt_e1", "w_e1"), ("mt_e2", "w_e2")):
                row, mine = meeting_row(body, meeting_id), task(body, world)
                assert (row["credits"], row["tasks"]) == (mine["credits"], 1)
                assert triple(row["time_saved"]) == triple(mine["time_saved"])
            assert meeting_row(body, "mt_foreign")["credits"] == 0
            assert math.fsum(m["credits"] for m in body["meetings"]) <= body["totals"]["credits"]
        # shape: nothing but the allowlisted keys, none of them a person or tracked human time
        keys = {key for _, key in walk_keys(body)}
        assert keys <= set().union(*ALLOWED_KEYS.values())
        assert not [k for k in keys if HUMAN_TIME_KEY.search(k)]
