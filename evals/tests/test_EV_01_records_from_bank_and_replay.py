"""EV-01..EV-15 inputs: the record builders (PRD 3.5, 19.3). `records_from_bank` turns bank results (scripted
Director on fakes) into RunRecords labelled scripted_fakes; `records_from_pass` turns a replay pass into RunRecords
labelled recorded. `CaseRunResult` must keep the replayed outcome's events and outputs for that.

Ambiguity resolved here, not in the PRD: for a replayed case `expected_completed` is true when the case's
`measures` list EV-01 (the cases that measure task success), see the ticket design note."""

import dataclasses
from pathlib import Path

from _evals_lib import add_case, make_event
from _metrics_lib import metrics
from tilo_evals.bank import BankCase
from tilo_evals.bank_checks import Finding
from tilo_evals.bank_report import CaseResult
from tilo_evals.bank_run import Observation
from tilo_evals.cases import load_cases
from tilo_evals.config import EvalsConfig
from tilo_evals.runner import CaseRunResult, run_pass


def _bank_case(case_id="B-900", outcome="completed"):
    return BankCase(
        id=case_id, title="t", domain="marketing", shapes=("chain",), brief="b", director={},
        expect={"outcome": outcome}, path=Path(f"{case_id}.yaml"),
    )  # fmt: skip


def _bank_result(case_id="B-900", outcome="completed", *, events=None, findings=(), deterministic=True):
    case = _bank_case(case_id, outcome)
    events = events if events is not None else [make_event(1, "world.started"), make_event(2, "world.completed")]
    first = Observation(case=case, outcome=outcome, events=list(events), world_id="w_1")
    later = Observation(case=case, outcome=outcome, events=[make_event(9, "world.failed")])
    return CaseResult(case, [first, later], list(findings), deterministic)


def _config(repo):
    return EvalsConfig.load(str(repo / "config" / "evals.yaml"))


# ---- records_from_bank -----------------------------------------------------------------------------------------


def test_EV_01_records_from_bank_labels_every_record_scripted_fakes_from_the_bank():
    results = [_bank_result("B-900"), _bank_result("B-901", "held_at_gate")]

    records = metrics().records_from_bank(results)

    assert [r.case_id for r in records] == ["B-900", "B-901"]
    assert {(r.basis, r.source) for r in records} == {("scripted_fakes", "bank")}
    assert all(isinstance(r.run_id, str) and r.run_id for r in records)
    assert len({r.run_id for r in records}) == 2, "run ids are unique"
    assert all(r.group is None or isinstance(r.group, str) for r in records)


def test_EV_01_records_from_bank_measures_task_success_only_for_cases_expected_to_complete():
    done, held, refused = (
        _bank_result(c, o) for c, o in (("B-900", "completed"), ("B-901", "held_at_gate"), ("B-902", "refused"))
    )

    a, b, c = metrics().records_from_bank([done, held, refused])

    assert (a.expected_completed, a.measures) == (True, ("EV-01",))
    assert (b.expected_completed, b.measures) == (False, ())
    assert (c.expected_completed, c.measures) == (False, ())


def test_EV_01_records_from_bank_passed_is_the_bank_result_and_events_come_from_the_first_run():
    ok = _bank_result("B-900", events=[make_event(1, "world.started"), make_event(2, "world.completed")])
    bad = _bank_result("B-901", findings=[Finding("honest_terminal_state", "completed without delivery")])
    drifted = _bank_result("B-902", deterministic=False)

    a, b, c = metrics().records_from_bank([ok, bad, drifted])

    assert a.passed is True and b.passed is False and c.passed is False
    assert [e["type"] for e in a.events] == ["world.started", "world.completed"], "events of the first run only"
    assert isinstance(a.events, tuple)


def test_EV_01_records_from_bank_of_nothing_is_empty():
    assert list(metrics().records_from_bank([])) == []


# ---- CaseRunResult keeps the outcome --------------------------------------------------------------------------


def test_EV_01_case_run_result_has_events_and_outputs_fields_with_defaults_after_the_old_ones(fake_repo):
    add_case(fake_repo, "E-PLAN-01")
    case = load_cases("evals/cases")[0]

    result = CaseRunResult(case, True)  # the old positional call still works

    assert result.events == () and result.outputs == {}
    names = [f.name for f in dataclasses.fields(CaseRunResult)]
    old = ["case", "passed", "check_results", "cost", "role_costs", "roles", "cause", "pending_autoraters"]
    assert names[: len(old)] == old, "the new fields come after the existing ones"
    assert {"events", "outputs"} <= set(names[len(old) :])


def test_EV_01_run_pass_keeps_the_recorded_events_and_outputs_on_each_case_result(fake_repo):
    events = [make_event(1, "world.planned", data={"tier": "town"}), make_event(2, "world.completed")]
    add_case(fake_repo, "E-PLAN-01", events, outputs={"answer": 42}, credits=3.0)

    result = run_pass(pass_kind="full", config=_config(fake_repo))

    ran = result.ran[0]
    assert [e["type"] for e in ran.events] == ["world.planned", "world.completed"]
    assert isinstance(ran.events, tuple)
    assert ran.outputs == {"answer": 42}


# ---- records_from_pass -----------------------------------------------------------------------------------------


def test_EV_01_records_from_pass_labels_every_record_recorded_from_replay_and_keeps_events(fake_repo):
    events = [make_event(1, "world.planned", data={"tier": "town"}), make_event(2, "world.completed")]
    add_case(fake_repo, "E-RES-01", events, measures=["EV-01", "EV-05"], outputs={"answer": 42}, credits=2.0)
    add_case(fake_repo, "E-RED-01", [make_event(1, "alert.raised")], measures=["EV-09"], credits=1.0,
             checks=[{"check": "flagged_or_blocked", "args": {}}])  # fmt: skip
    result = run_pass(pass_kind="full", config=_config(fake_repo))

    records = metrics().records_from_pass(result)

    by_case = {r.case_id: r for r in records}
    assert set(by_case) == {"E-RED-01", "E-RES-01"}
    res = by_case["E-RES-01"]
    assert (res.basis, res.source, res.group) == ("recorded", "replay", "E-RES")
    assert res.measures == ("EV-01", "EV-05")
    assert res.passed is True
    assert [e["type"] for e in res.events] == ["world.planned", "world.completed"]
    assert res.outputs == {"answer": 42}
    assert isinstance(res.run_id, str) and res.run_id
    assert res.run_id != by_case["E-RED-01"].run_id


def test_EV_01_records_from_pass_expected_completed_follows_whether_the_case_measures_task_success(fake_repo):
    add_case(fake_repo, "E-RES-01", [make_event(1, "world.completed")], measures=["EV-01"])
    add_case(fake_repo, "E-RED-01", [make_event(1, "alert.raised")], measures=["EV-09"],
             checks=[{"check": "flagged_or_blocked", "args": {}}])  # fmt: skip

    records = {r.case_id: r for r in metrics().records_from_pass(run_pass(pass_kind="full", config=_config(fake_repo)))}

    assert records["E-RES-01"].expected_completed is True
    assert records["E-RED-01"].expected_completed is False


def test_EV_01_records_from_pass_carries_a_failed_check_and_a_pending_autorater_as_they_are(fake_repo):
    add_case(fake_repo, "E-RED-01", [make_event(1, "alert.raised")], measures=["EV-09"],
             checks=[{"check": "flagged_or_blocked", "args": {}}])  # fmt: skip
    add_case(fake_repo, "E-RED-02", [make_event(1, "world.started")], measures=["EV-09"],
             checks=[{"check": "flagged_or_blocked", "args": {}}])  # no alert: fails  # fmt: skip
    add_case(fake_repo, "E-RES-02", [make_event(1, "world.completed")], measures=["EV-05"],
             checks=[{"check": "groundedness", "args": {}, "kind": "autorater"}])  # fmt: skip

    records = {r.case_id: r for r in metrics().records_from_pass(run_pass(pass_kind="full", config=_config(fake_repo)))}

    assert records["E-RED-01"].passed is True
    assert records["E-RED-02"].passed is False
    assert records["E-RES-02"].passed is None, "only autorater checks: pending, never a pass"


def test_EV_01_records_from_pass_skips_cases_that_did_not_run(fake_repo):
    add_case(fake_repo, "E-PLAN-01", [make_event(1, "world.completed")], measures=["EV-01"])
    add_case(fake_repo, "E-PLAN-02", status="skeleton", ground_truth=None, recording=None, measures=["EV-01"])

    records = metrics().records_from_pass(run_pass(pass_kind="full", config=_config(fake_repo)))

    assert [r.case_id for r in records] == ["E-PLAN-01"]


def test_EV_01_a_repeated_deploy_gate_case_gives_one_record_per_run_with_distinct_run_ids(fake_repo):
    add_case(fake_repo, "E-HAND-01", [make_event(1, "world.completed")], measures=["EV-10"], deploy_gate=True)

    records = metrics().records_from_pass(run_pass(pass_kind="full", config=_config(fake_repo)))

    assert len(records) == 3 and len({r.run_id for r in records}) == 3, "deploy_gate_repeats = 3 (PRD 19.2)"
