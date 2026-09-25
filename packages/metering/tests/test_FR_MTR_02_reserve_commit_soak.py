"""FR-MTR-02 (PRD 14.5): "Reserve-then-commit budgets with 15% reserve" --
acceptance test: "No run exceeds its approved budget in a 100-run soak
test." PRD 14.1: "Reserve, then commit. Each step reserves its estimated
cost plus 15% before running and commits the actual cost after. A step
that cannot reserve waits."

se-spec.md "## P8-01" fixes the acceptance tests verbatim:
- a reservation is the estimate x 1.15;
- a reservation that does not fit returns Wait and changes nothing;
- a commit frees the reservation;
- a 100-run soak property test (Hypothesis): 100 runs with random approved
  budgets, users and orgs, and interleaved reserve, commit, release and
  grant steps where every actual cost is <= its reservation. At every
  point, and at the end: for each run, spent + reserved <= cap; each
  user-day and org-day total is <= its cap; nothing is lost (spent equals
  the sum of the commits).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from _metering_testlib import build_treasury
from hypothesis import given, settings
from hypothesis import strategies as st
from tilo_metering import Reservation, Wait

AT = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)


def test_FR_MTR_02_reservation_reserves_estimate_plus_15_percent(tmp_path):
    """ "reserves estimate * (1 + reserve_margin), which is estimate plus
    15%." reserve_margin: 0.15 is se-spec.md's "Config files (new)" default
    (contract-change issue #7)."""
    treasury, _flags = build_treasury(tmp_path, run_credits=1000)
    treasury.open_run("r1", user_id="u_01", org_id="org_01", approved=1000)

    reservation = treasury.reserve("r1", "s1", estimate=100.0, at=AT)

    assert isinstance(reservation, Reservation)
    run = treasury.run("r1")
    assert run.reserved == pytest.approx(115.0)
    assert run.spent == pytest.approx(0.0)


def test_FR_MTR_02_reservation_that_does_not_fit_returns_wait_and_changes_nothing(tmp_path):
    """ "A step that cannot reserve waits." 100 * 1.15 = 115 exceeds the
    run's 50-credit approved budget, so reserve() hands back Wait and the
    run's spent/reserved stay untouched."""
    treasury, _flags = build_treasury(tmp_path, run_credits=1000)
    treasury.open_run("r1", user_id="u_01", org_id="org_01", approved=50.0)

    result = treasury.reserve("r1", "s1", estimate=100.0, at=AT)

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
    """ "release(reservation) means the step was cancelled, so it frees the
    reservation with nothing spent." """
    treasury, _flags = build_treasury(tmp_path, run_credits=1000)
    treasury.open_run("r1", user_id="u_01", org_id="org_01", approved=1000)
    reservation = treasury.reserve("r1", "s1", estimate=100.0, at=AT)

    treasury.release(reservation)

    run = treasury.run("r1")
    assert run.reserved == pytest.approx(0.0)
    assert run.spent == pytest.approx(0.0)


def test_FR_MTR_02_grant_raises_the_runs_cap(tmp_path):
    """ "grant(run_id, credits) is a top-up that raises the run's cap (it is
    used by budget.granted)." """
    treasury, _flags = build_treasury(tmp_path, run_credits=1000)
    treasury.open_run("r1", user_id="u_01", org_id="org_01", approved=100.0)
    cap_before = treasury.run("r1").cap

    treasury.grant("r1", 20.0)

    assert treasury.run("r1").cap == pytest.approx(cap_before + 20.0)


# ---------------------------------------------------------------------------
# The 100-run soak property test.
# ---------------------------------------------------------------------------

RUN_COUNT = 100
USERS = tuple(f"u_soak{i:02d}" for i in range(5))
ORGS = tuple(f"org_soak{i:02d}" for i in range(3))
USER_DAY_CAP = 1500.0
ORG_DAY_CAP = 4000.0


@st.composite
def _soak_plan(draw):
    """One entry per simulated run: its owner, its approved budget and a
    short queue of (estimate, resolution, commit_fraction) reserve steps.
    commit_fraction in [0, 1] is how the test harness keeps "every actual
    cost ... <= its reservation" (se-spec.md): actual = reserved_amount *
    commit_fraction, which is always <= the just-made reservation."""
    plan = []
    for i in range(RUN_COUNT):
        user_id = draw(st.sampled_from(USERS))
        org_id = draw(st.sampled_from(ORGS))
        approved = draw(st.floats(min_value=20.0, max_value=200.0, allow_nan=False, allow_infinity=False))
        steps = draw(
            st.lists(
                st.tuples(
                    st.floats(min_value=1.0, max_value=30.0, allow_nan=False, allow_infinity=False),
                    st.sampled_from(("commit", "release")),
                    st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
                ),
                min_size=1,
                max_size=3,
            )
        )
        plan.append((f"r_soak{i:03d}", user_id, org_id, approved, steps))
    return plan


def _round_robin(step_queues: list[list]):
    """Yields (run_index, step) across every run's step queue in
    round-robin order, so reserve/commit/release/grant calls for different
    runs interleave instead of running one run fully before the next."""
    queues = [list(q) for q in step_queues]
    while any(queues):
        for run_index, queue in enumerate(queues):
            if queue:
                yield run_index, queue.pop(0)


def _day_committed(treasury, *, day, user_id=None, org_id=None) -> float:
    total = 0.0
    for entry in treasury.ledger:
        if entry.kind != "commit" or entry.credits is None:
            continue
        if entry.at.date() != day:
            continue
        if user_id is not None and entry.user != user_id:
            continue
        if org_id is not None and entry.org != org_id:
            continue
        total += entry.credits
    return total


@settings(derandomize=True, deadline=None, max_examples=10)
@given(plan=_soak_plan())
def test_FR_MTR_02_soak_100_runs_never_exceed_budgets(tmp_path_factory, plan):
    """FR-MTR-02 acceptance test, verbatim: "No run exceeds its approved
    budget in a 100-run soak test." Daily USD spend caps are set high here
    on purpose: FR-MTR-04's kill switch is this ticket's other acceptance
    test and has its own file, so this soak isolates FR-MTR-02's
    reserve/commit/release/grant bookkeeping."""
    tmp_path = tmp_path_factory.mktemp("mtr02_soak")
    treasury, _flags = build_treasury(
        tmp_path,
        run_credits=300.0,
        user_day_credits=USER_DAY_CAP,
        org_day_credits=ORG_DAY_CAP,
        daily_usd_soft=1_000_000.0,
        daily_usd_hard=1_000_000.0,
    )

    for index, (run_id, user_id, org_id, approved, _steps) in enumerate(plan):
        treasury.open_run(run_id, user_id=user_id, org_id=org_id, approved=approved)
        if index % 7 == 0:
            treasury.grant(run_id, 20.0)  # exercises the "grant" step kind

    committed_by_run: dict[str, float] = {run_id: 0.0 for run_id, *_rest in plan}
    step_queues = [steps for *_rest, steps in plan]

    for run_index, (estimate, resolution, commit_fraction) in _round_robin(step_queues):
        run_id, user_id, org_id, approved, _steps = plan[run_index]

        result = treasury.reserve(run_id, f"s{run_index}", estimate=estimate, at=AT)
        if isinstance(result, Wait):
            continue
        reservation = result
        reserved_amount = treasury.run(run_id).reserved

        if resolution == "commit":
            actual = reserved_amount * commit_fraction  # harness-enforced: actual <= reservation
            treasury.commit(reservation, actual=actual, at=AT)
            committed_by_run[run_id] += actual
        else:
            treasury.release(reservation)

        # Invariant, checked after every step -- not only at the end.
        run_state = treasury.run(run_id)
        assert run_state.spent + run_state.reserved <= run_state.cap + 1e-6, (
            f"{run_id}: spent {run_state.spent} + reserved {run_state.reserved} exceeds cap {run_state.cap}"
        )
        assert run_state.spent == pytest.approx(committed_by_run[run_id], abs=1e-6), (
            f"{run_id}: spent must equal the sum of that run's commits (nothing lost)"
        )

    day = AT.date()
    for run_id, user_id, org_id, approved, _steps in plan:
        run_state = treasury.run(run_id)
        assert run_state.spent + run_state.reserved <= run_state.cap + 1e-6
        assert run_state.spent == pytest.approx(committed_by_run[run_id], abs=1e-6)

    for user_id in USERS:
        assert _day_committed(treasury, day=day, user_id=user_id) <= USER_DAY_CAP + 1e-6
    for org_id in ORGS:
        assert _day_committed(treasury, day=day, org_id=org_id) <= ORG_DAY_CAP + 1e-6

    total_committed = sum(committed_by_run.values())
    ledger_commits = sum(e.credits for e in treasury.ledger if e.kind == "commit" and e.credits is not None)
    assert ledger_commits == pytest.approx(total_committed, abs=1e-6), "the ledger must lose nothing"
