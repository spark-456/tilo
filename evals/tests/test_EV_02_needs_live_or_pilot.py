"""EV-02, EV-05, EV-11, EV-12, EV-13, EV-14, EV-15 (PRD 3.5): metrics that cannot be computed from a replay or a
scripted-fake run. Each gets one row with status needs_live_or_pilot, never a number, and a method that names the
data it needs. Feeding runs (with or without autorater-pending checks) changes nothing."""

import pytest
from _metrics_lib import NEEDS_LIVE_OR_PILOT, completed, compute, handoff, only, planned, rec, rows_for


def _busy_runs():
    """Runs on both bases, one with a pending autorater and one that measures the metric, with events."""
    return [
        rec(planned(5, 9), completed(7), measures=NEEDS_LIVE_OR_PILOT, passed=None),
        rec(handoff(True), completed(2), basis="scripted_fakes", measures=("EV-01",)),
    ]


def _single_row(ev_id, runs=None):
    rows = rows_for(compute(_busy_runs() if runs is None else runs), ev_id)
    assert len(rows) == 1, f"{ev_id} must have exactly one row, got {[(r.basis, r.status) for r in rows]}"
    row = rows[0]
    assert (row.status, row.value, row.basis) == ("needs_live_or_pilot", None, None)
    assert row.n == 0, "no number, so no n"
    assert row.method.strip(), "the method is never empty"
    return row


def test_EV_02_time_to_first_plan_needs_live_wall_clock_latency():
    row = _single_row("EV-02")

    method = row.method.lower()
    assert "live" in method and ("wall-clock" in method or "latency" in method)
    assert "12 s" in row.target and "25 s" in row.target, "p50 <= 12 s; p95 <= 25 s"


def test_EV_05_groundedness_needs_autorater_on_live_outputs_and_pending_is_never_counted():
    row = _single_row("EV-05")

    method = row.method.lower()
    assert "autorater" in method and "live" in method
    assert "90%" in row.target


def test_EV_11_time_saved_needs_attention_spans_from_pilot_testers_method_section_14():
    row = _single_row("EV-11")

    method = row.method.lower()
    assert "pilot" in method and "attention" in method
    assert "section 14" in method
    assert "Reported" in row.target


def test_EV_12_time_reinvested_is_a_self_reported_survey():
    row = _single_row("EV-12")

    assert "survey" in row.method.lower() and "self-reported" in (row.method + row.target).lower()


def test_EV_13_autopilot_draft_acceptance_needs_pilot_drafts_sent_unedited():
    row = _single_row("EV-13")

    method = row.method.lower()
    assert "pilot" in method and "unedited" in method
    assert "70%" in row.target


def test_EV_14_expert_load_needs_team_lead_answer_time_from_the_pilot():
    row = _single_row("EV-14")

    method = row.method.lower()
    assert "team lead" in method and "pilot" in method
    assert "2 min" in row.target and "5%" in row.target


def test_EV_15_channel_latency_needs_live_channel_and_notes_whatsapp_is_out_of_scope():
    row = _single_row("EV-15")

    assert "live" in row.method.lower() and "channel" in row.method.lower()
    assert "WhatsApp" in row.note and "out of scope" in row.note, "out of scope since 5 Oct 2026"
    assert "5 Oct 2026" in row.note
    assert "15 s" in row.target


@pytest.mark.parametrize("ev_id", NEEDS_LIVE_OR_PILOT)
def test_EV_02_to_15_live_only_rows_exist_with_no_runs_at_all(ev_id):
    rows = rows_for(compute([]), ev_id)

    assert [(r.status, r.value, r.n) for r in rows] == [("needs_live_or_pilot", None, 0)]
    assert only(rows, ev_id, None).method.strip()
