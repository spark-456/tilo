"""FR-MTR-02 (PRD 14.1, 14.5): reserve = estimate x 1.15; a step that cannot reserve waits and
changes nothing; commit/release free the reservation; grant raises the run's cap; a 100-run soak
never exceeds any budget and loses nothing."""

from datetime import UTC, datetime

import pytest
from _metering_testlib import build_treasury
from hypothesis import given, settings
from hypothesis import strategies as st
from tilo_metering import Reservation, Wait

AT = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)


def test_FR_MTR_02_reservation_reserves_estimate_plus_15_percent(tmp_path):
    treasury, _flags = build_treasury(tmp_path, run_credits=1000)
    treasury.open_run("r1", user_id="u_01", org_id="org_01", approved=1000)
    reservation = treasury.reserve("r1", "s1", estimate=100.0, at=AT)
    assert isinstance(reservation, Reservation)
    run = treasury.run("r1")
    assert run.reserved == pytest.approx(115.0)
    assert run.spent == pytest.approx(0.0)


def test_FR_MTR_02_reservation_that_does_not_fit_returns_wait_and_changes_nothing(tmp_path):
    treasury, _flags = build_treasury(tmp_path, run_credits=1000)
    treasury.open_run("r1", user_id="u_01", org_id="org_01", approved=50.0)
    result = treasury.reserve("r1", "s1", estimate=100.0, at=AT)  # 115 > 50
    assert isinstance(result, Wait)
    assert result.reason
    run = treasury.run("r1")
    assert run.reserved == pytest.approx(0.0)
    assert run.spent == pytest.approx(0.0)


def test_FR_MTR_02_commit_frees_the_reservation_and_records_actual(tmp_path):
    treasury, _flags = build_treasury(tmp_path, run_credits=1000)
    treasury.open_run("r1", user_id="u_01", org_id="org_01", approved=1000)
    reservation = treasury.reserve("r1", "s1", estimate=100.0, at=AT)
    result = treasury.commit(reservation, actual=80.0, at=AT)
    run = treasury.run("r1")
    assert run.reserved == pytest.approx(0.0), "commit must free the reservation"
    assert run.spent == pytest.approx(80.0)
    assert run.remaining == pytest.approx(run.cap - run.spent - run.reserved)
    assert result.overrun is False


def test_FR_MTR_02_release_frees_the_reservation_with_nothing_spent(tmp_path):
    treasury, _flags = build_treasury(tmp_path, run_credits=1000)
    treasury.open_run("r1", user_id="u_01", org_id="org_01", approved=1000)
    reservation = treasury.reserve("r1", "s1", estimate=100.0, at=AT)
    treasury.release(reservation)
    run = treasury.run("r1")
    assert run.reserved == pytest.approx(0.0)
    assert run.spent == pytest.approx(0.0)


def test_FR_MTR_02_grant_raises_the_runs_cap(tmp_path):
    treasury, _flags = build_treasury(tmp_path, run_credits=1000)
    treasury.open_run("r1", user_id="u_01", org_id="org_01", approved=100.0)
    cap_before = treasury.run("r1").cap
    treasury.grant("r1", 20.0)
    assert treasury.run("r1").cap == pytest.approx(cap_before + 20.0)


# --- 100-run soak: reserve/commit/release/grant interleaved across runs, users, orgs.

RUN_COUNT = 100
USERS = tuple(f"u_soak{i:02d}" for i in range(5))
ORGS = tuple(f"org_soak{i:02d}" for i in range(3))
USER_DAY_CAP, ORG_DAY_CAP = 1500.0, 4000.0


def _floats(lo: float, hi: float):
    return st.floats(min_value=lo, max_value=hi, allow_nan=False, allow_infinity=False)


@st.composite
def _soak_plan(draw):
    """One (run, user, org, approved, steps) per run; a step is (estimate, resolution,
    commit_fraction) with actual = reserved_amount * commit_fraction, always <= the reservation."""
    step = st.tuples(_floats(1.0, 30.0), st.sampled_from(("commit", "release")), _floats(0.0, 1.0))
    ids = (f"r_soak{i:03d}" for i in range(RUN_COUNT))
    return [
        (
            r,
            draw(st.sampled_from(USERS)),
            draw(st.sampled_from(ORGS)),
            draw(_floats(20.0, 200.0)),
            draw(st.lists(step, min_size=1, max_size=3)),
        )
        for r in ids
    ]


def _round_robin(step_queues: list[list]):
    queues = [list(q) for q in step_queues]
    while any(queues):
        for run_index, queue in enumerate(queues):
            if queue:
                yield run_index, queue.pop(0)


def _day_total(treasury, *, day, **owner) -> float:
    field, value = next(iter(owner.items()))
    return sum(
        e.credits
        for e in treasury.ledger
        if e.kind == "commit" and e.credits is not None and e.at.date() == day and getattr(e, field) == value
    )


@settings(derandomize=True, deadline=None, max_examples=10)
@given(plan=_soak_plan())
def test_FR_MTR_02_soak_100_runs_never_exceed_budgets(tmp_path_factory, plan):
    """No run exceeds its approved budget; user-day and org-day totals stay under cap; nothing lost."""
    tmp_path = tmp_path_factory.mktemp("mtr02_soak")
    treasury, _flags = build_treasury(
        tmp_path,
        run_credits=300.0,
        user_day_credits=USER_DAY_CAP,
        org_day_credits=ORG_DAY_CAP,
        daily_usd_soft=1e6,
        daily_usd_hard=1e6,
    )
    for index, (run_id, user_id, org_id, approved, _steps) in enumerate(plan):
        treasury.open_run(run_id, user_id=user_id, org_id=org_id, approved=approved)
        if index % 7 == 0:
            treasury.grant(run_id, 20.0)

    committed_by_run = {run_id: 0.0 for run_id, *_rest in plan}
    for run_index, (estimate, resolution, commit_fraction) in _round_robin([s for *_r, s in plan]):
        run_id = plan[run_index][0]
        result = treasury.reserve(run_id, f"s{run_index}", estimate=estimate, at=AT)
        if isinstance(result, Wait):
            continue
        reserved_amount = treasury.run(run_id).reserved
        if resolution == "commit":
            actual = reserved_amount * commit_fraction  # harness-enforced: actual <= reservation
            treasury.commit(result, actual=actual, at=AT)
            committed_by_run[run_id] += actual
        else:
            treasury.release(result)
        run_state = treasury.run(run_id)
        assert run_state.spent + run_state.reserved <= run_state.cap + 1e-6
        assert run_state.spent == pytest.approx(committed_by_run[run_id], abs=1e-6)

    day = AT.date()
    for user_id in USERS:
        assert _day_total(treasury, day=day, user=user_id) <= USER_DAY_CAP + 1e-6
    for org_id in ORGS:
        assert _day_total(treasury, day=day, org=org_id) <= ORG_DAY_CAP + 1e-6
    total_committed = sum(committed_by_run.values())
    ledger_commits = sum(e.credits for e in treasury.ledger if e.kind == "commit" and e.credits is not None)
    assert ledger_commits == pytest.approx(total_committed, abs=1e-6), "the ledger must lose nothing"
