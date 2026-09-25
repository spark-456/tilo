"""FR-MTR-02 (PRD 14.1, 14.5): reserve = estimate x 1.15, waiting if it does not fit; commit records
the actual in full and halts on overrun; a 100-run soak never exceeds any budget and loses nothing."""

from datetime import UTC, datetime

import pytest
from _metering_testlib import build_treasury
from hypothesis import given, settings
from hypothesis import strategies as st
from tilo_metering import Reservation, Wait

AT = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(("approved", "fits"), [(1000.0, True), (50.0, False)])
def test_FR_MTR_02_reserve_adds_15_percent_or_waits_if_it_does_not_fit(tmp_path, approved, fits):
    treasury, _flags = build_treasury(tmp_path, run_credits=1000)
    treasury.open_run("r1", user_id="u_01", org_id="org_01", approved=approved)
    result = treasury.reserve("r1", "s1", estimate=100.0, at=AT)  # 115 reserved, or > 50 and waits
    assert isinstance(result, Reservation if fits else Wait)
    run = treasury.run("r1")
    assert run.reserved == pytest.approx(115.0 if fits else 0.0)
    assert run.spent == pytest.approx(0.0)


@pytest.mark.parametrize("action", ["commit", "release"])
def test_FR_MTR_02_commit_or_release_frees_the_reservation(tmp_path, action):
    treasury, _flags = build_treasury(tmp_path, run_credits=1000)
    treasury.open_run("r1", user_id="u_01", org_id="org_01", approved=1000)
    reservation = treasury.reserve("r1", "s1", estimate=100.0, at=AT)
    if action == "commit":
        assert treasury.commit(reservation, actual=80.0, at=AT).overrun is False
    else:
        treasury.release(reservation)
    run = treasury.run("r1")
    assert run.reserved == pytest.approx(0.0), "commit and release must both free the reservation"
    assert run.spent == pytest.approx(80.0 if action == "commit" else 0.0)
    assert run.remaining == pytest.approx(run.cap - run.spent - run.reserved)


def test_FR_MTR_02_commit_over_the_reservation_sets_overrun_and_halts_the_run(tmp_path):
    # actual is recorded in full even over the reservation, and the overrun halts the run
    treasury, _flags = build_treasury(tmp_path, run_credits=1000)
    treasury.open_run("r1", user_id="u_01", org_id="org_01", approved=1000)
    reservation = treasury.reserve("r1", "s1", estimate=10.0, at=AT)  # 11.5 reserved
    result = treasury.commit(reservation, actual=50.0, at=AT)
    assert result.overrun is True
    run = treasury.run("r1")
    assert run.halted is True
    assert run.spent == pytest.approx(50.0)
    assert treasury.reserve("r1", "s2", estimate=1.0, at=AT) == Wait("halted")


def test_FR_MTR_02_replay_only_flag_refuses_to_reserve(tmp_path):
    treasury, flags = build_treasury(tmp_path, run_credits=1000)
    treasury.open_run("r1", user_id="u_01", org_id="org_01", approved=1000)
    flags.set("replay_only", True, reason="test")
    assert treasury.reserve("r1", "s1", estimate=10.0, at=AT) == Wait("replay_only")
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
    """(run, user, org, approved, steps); a step is (estimate, resolution, commit_fraction)."""
    step = st.tuples(_floats(1.0, 30.0), st.sampled_from(("commit", "release")), _floats(0.0, 1.0))
    row = st.tuples(
        st.sampled_from(USERS), st.sampled_from(ORGS), _floats(20.0, 200.0), st.lists(step, min_size=1, max_size=3)
    )
    return [(f"r_soak{i:03d}", *draw(row)) for i in range(RUN_COUNT)]


@settings(derandomize=True, deadline=None, max_examples=10)
@given(plan=_soak_plan())
def test_FR_MTR_02_soak_100_runs_never_exceed_budgets(tmp_path_factory, plan):
    """No run exceeds its approved budget; user-day and org-day totals stay under cap; nothing lost."""
    tmp_path = tmp_path_factory.mktemp("mtr02_soak")
    treasury, _flags = build_treasury(
        tmp_path, run_credits=300.0, user_day_credits=USER_DAY_CAP, org_day_credits=ORG_DAY_CAP
    )
    for index, (run_id, user_id, org_id, approved, _steps) in enumerate(plan):
        treasury.open_run(run_id, user_id=user_id, org_id=org_id, approved=approved)
        if index % 7 == 0:
            treasury.grant(run_id, 20.0)

    committed_by_run = {run_id: 0.0 for run_id, *_rest in plan}
    queues = [list(steps) for *_r, steps in plan]
    while any(queues):
        for run_index, queue in enumerate(queues):
            if not queue:
                continue
            estimate, resolution, commit_fraction = queue.pop(0)
            run_id = plan[run_index][0]
            result = treasury.reserve(run_id, f"s{run_index}", estimate=estimate, at=AT)
            if isinstance(result, Wait):
                continue
            if resolution == "commit":
                actual = treasury.run(run_id).reserved * commit_fraction  # harness-enforced: actual <= reservation
                treasury.commit(result, actual=actual, at=AT)
                committed_by_run[run_id] += actual
            else:
                treasury.release(result)
            run_state = treasury.run(run_id)
            assert run_state.spent + run_state.reserved <= run_state.cap + 1e-6
            assert run_state.spent == pytest.approx(committed_by_run[run_id], abs=1e-6)

    for field, ids, cap in (("user", USERS, USER_DAY_CAP), ("org", ORGS, ORG_DAY_CAP)):
        for ident in ids:
            total = sum(e.credits for e in treasury.ledger if e.kind == "commit" and getattr(e, field) == ident)
            assert total <= cap + 1e-6, f"{field} day cap exceeded"
    total_committed = sum(committed_by_run.values())
    ledger_commits = sum(e.credits for e in treasury.ledger if e.kind == "commit" and e.credits is not None)
    assert ledger_commits == pytest.approx(total_committed, abs=1e-6), "the ledger must lose nothing"
