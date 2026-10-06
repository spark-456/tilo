"""EV-01..EV-15 row shape, ordering and the honesty rules (PRD 3.5, 9.4-style honesty, 19.3 "honest reporting").

compute_metrics returns rows ordered EV-01..EV-15; one row per basis that has relevant runs ("recorded" first, then
"scripted_fakes"); with no data on any basis, one no_data row (computable metrics) or needs_live_or_pilot row (the
rest). A row on scripted_fakes tests pipeline mechanics and never claims a target is met."""

import copy
import dataclasses
import json
import re

import pytest
from _metrics_lib import (
    CLAIM_SENTENCE,
    COMPUTABLE,
    EV_IDS,
    MODEL_ID,
    NEEDS_LIVE_OR_PILOT,
    alert_raised,
    approval_requested,
    blocked,
    budget_requested,
    completed,
    compute,
    escalated,
    handoff,
    memory_hit,
    metrics,
    metrics_report,
    planned,
    rec,
    recovered,
    rows_for,
)
from hypothesis import given, settings
from hypothesis import strategies as st

TARGETS = {  # the PRD 3.5 numbers, asserted on every row (even with no data)
    "EV-01": ["85%", "60%"],
    "EV-02": ["12 s", "25 s"],
    "EV-03": ["25%"],
    "EV-04": ["2"],
    "EV-05": ["90%"],
    "EV-06": ["70%"],
    "EV-07": ["Reported"],
    "EV-08": ["50%"],
    "EV-09": ["100%"],
    "EV-10": ["95%"],
    "EV-11": ["Reported"],
    "EV-12": ["Reported"],
    "EV-13": ["70%"],
    "EV-14": ["2 min", "5%"],
    "EV-15": ["15 s"],
}
CLAIM_MET = re.compile(r"\b(meets?|target met|targets met|met the target|goal met)\b", re.IGNORECASE)
CLAIM_PASS = re.compile(r"\bPASS(ED)?\b")  # case-sensitive: "passed" in a count is fine, a PASS verdict is not


def _every_computed_on_fakes():
    """Scripted-fake runs that give every computable metric a number, plus a recorded set for contrast."""
    fakes = rec(
        planned(8, 12, "town"),
        blocked("U1"),
        recovered("U2"),
        escalated(),
        handoff(True),
        memory_hit(10, 2),
        completed(10),
        basis="scripted_fakes",
        measures=("EV-01", "EV-09", "EV-10"),
        passed=True,
    )
    recorded = rec(
        planned(8, 12, "town"), blocked("U1"), recovered("U2"), handoff(True), memory_hit(10, 2), completed(9)
    )
    recorded = dataclasses.replace(recorded, measures=("EV-01", "EV-09", "EV-10"))
    return [fakes, recorded]


def _text(row):
    return " ".join(str(v) for v in dataclasses.asdict(row).values() if v is not None)


# ---- shape and order -------------------------------------------------------------------------------------------


def test_EV_01_to_15_records_and_rows_are_frozen_dataclasses_with_the_pinned_fields():
    m = metrics()
    assert [f.name for f in dataclasses.fields(m.RunRecord)] == [
        "run_id", "source", "basis", "case_id", "group", "measures",
        "events", "outputs", "passed", "expected_completed",
    ]  # fmt: skip
    assert [f.name for f in dataclasses.fields(m.MetricRow)] == [
        "id", "name", "target", "basis", "status", "value", "n", "of", "method", "note",
    ]  # fmt: skip
    with pytest.raises(dataclasses.FrozenInstanceError):
        compute([])[0].value = 1.0
    with pytest.raises(dataclasses.FrozenInstanceError):
        rec().passed = False


def test_EV_01_to_15_with_no_runs_there_are_exactly_fifteen_rows_in_order_each_with_target_and_method():
    rows = compute([])

    assert [r.id for r in rows] == list(EV_IDS)
    for row in rows:
        assert row.name.strip() and row.method.strip(), f"{row.id} needs a name and a method"
        for text in TARGETS[row.id]:
            assert text in row.target, f"{row.id} target must show the PRD figure {text!r}: {row.target!r}"
        assert row.basis is None and row.value is None and row.n == 0
        assert row.status == ("no_data" if row.id in COMPUTABLE else "needs_live_or_pilot")


def test_EV_01_to_15_one_row_per_basis_with_relevant_runs_recorded_first_in_ev_order():
    rows = compute(_every_computed_on_fakes())

    assert [r.id for r in rows] == sorted(r.id for r in rows), "ordered EV-01..EV-15"
    for ev_id in COMPUTABLE:
        found = rows_for(rows, ev_id)
        assert [r.basis for r in found] == ["recorded", "scripted_fakes"], f"{ev_id}: recorded then scripted_fakes"
        assert all(r.status == "computed" for r in found)
    for ev_id in NEEDS_LIVE_OR_PILOT:
        assert len(rows_for(rows, ev_id)) == 1, "a live-only metric never gets a row per basis"


def test_EV_01_to_15_a_basis_without_relevant_runs_gets_no_row_of_its_own():
    only_bank = rec(completed(4), basis="scripted_fakes", measures=("EV-01",))

    rows = compute([only_bank])

    assert [r.basis for r in rows_for(rows, "EV-01")] == ["scripted_fakes"]
    assert [r.basis for r in rows_for(rows, "EV-07")] == ["scripted_fakes"]
    assert [(r.status, r.basis) for r in rows_for(rows, "EV-08")] == [("no_data", None)]


def test_EV_01_to_15_compute_metrics_is_deterministic_and_leaves_its_input_untouched():
    runs = _every_computed_on_fakes()
    before = copy.deepcopy([dataclasses.asdict(r) for r in runs])

    first, second = compute(runs), compute(runs)

    assert first == second
    assert [dataclasses.asdict(r) for r in runs] == before


# ---- honesty rules ---------------------------------------------------------------------------------------------


def test_EV_01_to_15_a_scripted_fakes_row_is_labelled_mechanics_only_in_its_note():
    rows = compute(_every_computed_on_fakes())
    fake_rows = [r for r in rows if r.basis == "scripted_fakes"]

    assert {r.id for r in fake_rows} == set(COMPUTABLE), "the fixture must exercise every computable metric"
    for row in fake_rows:
        assert row.note.startswith("mechanics only"), f"{row.id}: {row.note!r}"
    assert not any(r.note.startswith("mechanics only") for r in rows if r.basis == "recorded")


def test_EV_01_to_15_a_scripted_fakes_row_never_claims_a_target_is_met():
    rows = compute(_every_computed_on_fakes())

    for row in rows:
        if row.basis != "scripted_fakes":
            continue
        text = _text(row)
        assert not CLAIM_MET.search(text), f"{row.id} claims a target: {text!r}"
        assert not CLAIM_PASS.search(text), f"{row.id} gives a verdict: {text!r}"
    names = {f.name.lower() for f in dataclasses.fields(metrics().MetricRow)}
    assert not names & {"met", "meets", "target_met", "pass", "passed", "ok", "verdict"}, "no verdict field exists"


def test_EV_01_to_15_no_number_without_a_count_and_no_value_on_no_data_or_live_only_rows():
    rows = compute(_every_computed_on_fakes() + [rec(measures=("EV-09",), passed=None)])

    for row in rows:
        if row.status != "computed":
            assert row.value is None, f"{row.id} has a value although it is {row.status}"
        else:
            assert row.value is not None
            assert row.n >= 0 and row.of >= 0 and max(row.n, row.of) >= 1, f"{row.id}: a number needs its counts"
            assert row.basis in ("recorded", "scripted_fakes")
        if row.id in ("EV-01", "EV-06", "EV-09", "EV-10") and row.status == "computed":
            assert row.n <= row.of, f"{row.id}: a share is n of m"
        assert row.status in ("computed", "no_data", "needs_live_or_pilot")


def test_EV_01_to_15_every_row_note_shows_coverage_cases_that_measure_it_and_how_many_are_recorded():
    coverage = {ev_id: (n + 3, n) for n, ev_id in enumerate(EV_IDS)}

    rows = compute(_every_computed_on_fakes(), coverage=coverage)

    for row in rows:
        k, j = coverage[row.id]
        assert f"{k} cases measure this, {j} recorded" in row.note, f"{row.id}: {row.note!r}"


def test_EV_01_to_15_a_metric_missing_from_coverage_reads_as_no_cases_and_none_recorded():
    rows = compute([], coverage={})

    assert [r.id for r in rows] == list(EV_IDS)
    assert all("0 cases measure this, 0 recorded" in r.note for r in rows)


def test_EV_01_to_15_no_model_id_appears_in_any_row_or_rendering():
    leaky = [
        dataclasses.replace(
            r,
            outputs={"note": "answered by gemini-3.8-flash"},
            events=tuple({**e, "summary": "gpt-5 and claude-opus said so"} for e in r.events),
        )
        for r in _every_computed_on_fakes()
    ]
    rows = compute(leaky)
    report = metrics_report()
    texts = [_text(r) for r in rows]
    texts.append(report.render_markdown(rows, build_hash="abc1234", now_utc="2026-10-06T00:00:00Z"))
    texts.append(json.dumps(report.render_json(rows)))

    for text in texts:
        assert not MODEL_ID.search(text), "PL-01: no model id in the metrics output"


def test_EV_01_to_15_the_claim_sentence_is_in_the_report_header_not_only_in_notes():
    text = metrics_report().render_markdown(compute([]), build_hash="abc1234", now_utc="2026-10-06T00:00:00Z")

    assert CLAIM_SENTENCE in text, "the claim scope is stated in the report header"
    first_table_line = next(ln for ln in text.splitlines() if ln.startswith("|"))
    assert text.index(CLAIM_SENTENCE) < text.index(first_table_line), "and it comes before the table"


@settings(max_examples=40, deadline=None)
@given(
    st.lists(
        st.tuples(
            st.sampled_from(["recorded", "scripted_fakes"]),
            st.sampled_from([True, False, None]),
            st.booleans(),
            st.sets(st.sampled_from(list(EV_IDS)), max_size=4),
            st.lists(
                st.sampled_from(
                    ["plan", "done", "blocked", "recovered", "escalated", "budget", "approval", "alert", "hand"]
                ),
                max_size=8,
            ),
            st.integers(0, 300),
        ),
        max_size=12,
    )
)
def test_EV_01_to_15_property_rows_are_ordered_labelled_and_never_carry_a_number_without_status_computed(specs):
    makers = {
        "plan": lambda used: planned(used, used + 5, "town"),
        "done": lambda used: completed(used),
        "blocked": lambda used: blocked(f"U{used % 3}"),
        "recovered": lambda used: recovered(f"U{used % 3}"),
        "escalated": lambda used: escalated(),
        "budget": lambda used: budget_requested(),
        "approval": lambda used: approval_requested(),
        "alert": lambda used: alert_raised(),
        "hand": lambda used: handoff(used % 2 == 0),
    }
    runs = [
        rec(*[makers[k](used) for k in kinds], basis=basis, passed=passed, expected_completed=exp, measures=measures)
        for basis, passed, exp, measures, kinds, used in specs
    ]

    rows = compute(runs, coverage={ev_id: (5, 1) for ev_id in EV_IDS})

    assert [r.id for r in rows] == sorted(r.id for r in rows)
    assert {r.id for r in rows} == set(EV_IDS)
    for row in rows:
        assert row.method.strip() and "5 cases measure this, 1 recorded" in row.note
        assert (row.value is not None) == (row.status == "computed")
        if row.basis == "scripted_fakes":
            assert row.note.startswith("mechanics only")
        if row.status == "computed":
            assert max(row.n, row.of) >= 1
