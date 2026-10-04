"""GEN-03 (issue #272): every structural check of the generality bank fails on the defect it exists to catch.

One real gated run is the base; each test plants one defect in a copy and expects exactly that check to find it. A
harness whose checks cannot fail proves nothing, so this is the part that makes "37 of 37" mean something.
"""

import copy
import dataclasses

import pytest
from conftest import REPO_ROOT
from tilo_evals import bank_checks as bc
from tilo_evals.bank import load_bank
from tilo_evals.bank_run import Observation, run_case


@pytest.fixture(scope="module")
def base() -> Observation:
    cases = load_bank(REPO_ROOT / "evals" / "bank")
    case = next(c for c in cases if "gated_send" in c.shapes and c.outcome == "completed")
    obs = run_case(case)
    assert not bc.hard_findings(bc.check_case(obs)), "the base run must be clean"
    return obs


def _named(found: list[bc.Finding], check: str) -> list[bc.Finding]:
    return [f for f in found if f.check == check]


def test_GEN_03_no_crash_sees_a_crash_a_timeout_and_a_500(base: Observation) -> None:
    assert _named(bc.no_crash(dataclasses.replace(base, crash="boom")), "no_crash")
    assert _named(bc.no_crash(dataclasses.replace(base, timed_out=True)), "no_crash")
    assert _named(bc.no_crash(dataclasses.replace(base, http=[("GET", "/x", 500)])), "no_crash")
    assert not bc.no_crash(dataclasses.replace(base, http=[("GET", "/tasks/t/approaches", 502)]))  # said on purpose


def test_GEN_03_events_valid_sees_an_unregistered_type_a_seq_slip_and_a_repeated_id(base: Observation) -> None:
    unregistered = copy.deepcopy(base.events)
    unregistered[2]["type"] = "invented.event"
    assert bc.events_valid(dataclasses.replace(base, events=unregistered))
    slipped = copy.deepcopy(base.events)
    slipped[3]["seq"] = slipped[2]["seq"]
    assert any("seq" in f.detail for f in bc.events_valid(dataclasses.replace(base, events=slipped)))
    repeated = copy.deepcopy(base.events)
    repeated[4]["id"] = repeated[3]["id"]
    assert any("duplicate" in f.detail for f in bc.events_valid(dataclasses.replace(base, events=repeated)))


def test_GEN_03_plan_valid_sees_a_cycle(base: Observation) -> None:
    plan = copy.deepcopy(base.plan)
    plan["units"][0]["depends_on"] = [plan["units"][-1]["id"]]
    assert any("PG-03" in f.detail for f in bc.plan_valid(dataclasses.replace(base, plan=plan)))


def test_GEN_03_gates_as_policy_sees_a_low_tier_a_policy_resolved_t3_and_an_early_send(base: Observation) -> None:
    low = copy.deepcopy(base.events)
    for e in low:
        if e["type"] == "approval.requested":
            e["data"]["risk_tier"] = "T1"  # send_email is T2 in the table
    assert bc.gates_as_policy(dataclasses.replace(base, events=low))
    by_policy = copy.deepcopy(base.events)
    for e in by_policy:
        if e["type"] == "approval.resolved":
            e["authz"]["by"] = "policy"
    assert any("person" in f.detail for f in bc.gates_as_policy(dataclasses.replace(base, events=by_policy)))
    assert bc.gates_as_policy(dataclasses.replace(base, sent_at_first_gate=1))
    assert bc.gates_as_policy(dataclasses.replace(base, sent_total=base.approved_gates + 1))
    unasked = [e for e in base.events if e["type"] != "approval.requested"]
    assert any(
        "no approval was asked" in f.detail for f in bc.gates_as_policy(dataclasses.replace(base, events=unasked))
    )


def test_GEN_03_terminal_honest_sees_a_wrong_outcome_and_a_false_count(base: Observation) -> None:
    assert bc.terminal_honest(dataclasses.replace(base, outcome="refused", reason="x"))
    miscounted = copy.deepcopy(base.events)
    for e in miscounted:
        if e["type"] == "world.completed":
            e["data"]["deliverable_count"] = 9
    assert any(
        "deliverable_count" in f.detail for f in bc.terminal_honest(dataclasses.replace(base, events=miscounted))
    )
    case = dataclasses.replace(base.case, expect={"outcome": "refused"})
    assert bc.terminal_honest(dataclasses.replace(base, case=case, outcome="refused", reason=""))  # no reason shown


def test_GEN_03_budget_respected_sees_spending_over_the_cap(base: Observation) -> None:
    assert not bc.budget_respected(base)
    assert bc.budget_respected(dataclasses.replace(base, cap=0.5))


def test_GEN_03_delivers_something_is_reported_not_gated(base: Observation) -> None:
    empty = copy.deepcopy(base.events)
    for e in empty:
        if e["type"] == "world.completed":
            e["data"]["deliverable_count"] = 0
    found = bc.delivers_something(dataclasses.replace(base, events=empty))
    assert found and not any(f.hard for f in found)


def test_GEN_03_a_check_that_breaks_is_a_finding_not_an_exception(base: Observation) -> None:
    broken = dataclasses.replace(base, events=[{"type": "world.completed"}])  # no `data`, no `seq`
    assert bc.check_case(broken)  # reports; never raises
