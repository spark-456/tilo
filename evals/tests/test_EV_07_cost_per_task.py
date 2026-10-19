"""EV-07 cost per task (PRD 3.5 EV-07: credits per successful run, by tier, with USD; reported, no target).

A successful run reaches the terminal world.completed; its cost is data.credits_used. The value is the mean
credits over successful runs; the note carries USD = credits * credit_usd and the per-tier breakdown. credit_usd
is an argument (it comes from config/prices.yaml through tilo_metering), never a literal in the module."""

import pathlib

import pytest
from _evals_lib import REPO_ROOT
from _metrics_lib import blocked, completed, compute, only, planned, rec, rows_for


def test_EV_07_value_is_mean_credits_per_successful_run_and_the_note_has_usd_from_credit_usd():
    runs = [rec(planned(8, 12, "town"), completed(10)), rec(planned(8, 12, "town"), completed(14))]

    row = only(compute(runs, credit_usd=0.01), "EV-07", "recorded")

    assert row.status == "computed"
    assert row.value == pytest.approx(12.0), "the value is credits, not dollars"
    assert row.n == 2
    assert "0.12" in row.note, "USD = 12 credits * 0.01"
    assert "Reported" in row.target, "no target: reported"
    assert row.method.strip()


def test_EV_07_usd_follows_the_credit_usd_argument_it_is_not_hard_coded():
    runs = [rec(planned(8, 12, "town"), completed(10)), rec(planned(8, 12, "town"), completed(14))]

    low = only(compute(runs, credit_usd=0.01), "EV-07", "recorded").note
    high = only(compute(runs, credit_usd=0.02), "EV-07", "recorded").note

    assert "0.24" in high and "0.24" not in low
    assert "0.12" in low and "0.12" not in high


def test_EV_07_the_module_source_has_no_literal_credit_price():
    """credit_usd comes from config/prices.yaml through tilo_metering's PriceBook, never typed into the module."""
    sources = sorted((REPO_ROOT / "evals" / "src" / "tilo_evals").glob("metrics*.py"))

    assert sources, "evals/src/tilo_evals/metrics.py does not exist yet"
    for path in sources:
        assert "0.005" not in path.read_text(encoding="utf-8"), f"{path.name} hard-codes the credit price"


def test_EV_07_only_runs_that_reached_world_completed_count_as_successful():
    runs = [rec(planned(5, 5, "town"), completed(10)), rec(planned(5, 5, "town"), blocked()), rec(blocked())]

    row = only(compute(runs), "EV-07", "recorded")

    assert row.n == 1 and row.value == pytest.approx(10.0)


def test_EV_07_the_per_tier_breakdown_is_in_the_note_and_a_run_without_a_plan_is_unknown_tier():
    runs = [
        rec(planned(5, 5, "town"), completed(12)),
        rec(planned(1, 1, "village"), completed(4)),
        rec(completed(2)),
    ]

    row = only(compute(runs), "EV-07", "recorded")

    assert row.value == pytest.approx(6.0)
    note = row.note.lower()
    for tier in ("town", "village", "unknown"):
        assert tier in note, f"per-tier breakdown names {tier}"


def test_EV_07_cost_is_credits_used_of_the_completion_not_a_sum_of_event_credits():
    run = rec(planned(5, 5, "town"), completed(3.5))
    run.events[0]["credits"] = 99.0  # event-level credits are not the run's cost

    assert only(compute([run]), "EV-07", "recorded").value == pytest.approx(3.5)


def test_EV_07_no_successful_run_is_no_data_without_a_number():
    rows = rows_for(compute([rec(blocked())]), "EV-07")

    assert [(r.status, r.value, r.basis) for r in rows] == [("no_data", None, None)]


def test_EV_07_scripted_fakes_cost_is_labelled_mechanics_only_and_not_pooled_with_recorded():
    runs = [rec(completed(10)), rec(completed(2), basis="scripted_fakes")]

    rows = rows_for(compute(runs), "EV-07")

    assert [(r.basis, r.value) for r in rows] == [
        ("recorded", pytest.approx(10.0)),
        ("scripted_fakes", pytest.approx(2.0)),
    ]
    assert rows[1].note.startswith("mechanics only")


def test_EV_07_compute_metrics_is_pure_no_io_and_no_clock(monkeypatch):
    """Pure: no I/O, no clock, no model. Any open() or clock read while computing is a failure."""
    import builtins
    import time

    runs = [rec(planned(8, 12, "town"), completed(10))]

    def refuse(*_a, **_k):
        raise AssertionError("compute_metrics must not do I/O or read the clock")

    monkeypatch.setattr(builtins, "open", refuse)
    monkeypatch.setattr(time, "time", refuse)
    monkeypatch.setattr(pathlib.Path, "read_text", refuse)

    assert only(compute(runs), "EV-07", "recorded").status == "computed"
