"""GEN-03 / FR-CON-10 / BQ-218 (issue #283): every bank case that completes delivers at least one artifact. Before the
fix 9 of the 38 bank plans (research-and-report shapes) finished with deliverable_count 0 and the reported check
`delivers_something` counted them; now none may."""

import pytest
from _evals_lib import REPO_ROOT
from tilo_evals.bank import load_bank
from tilo_evals.bank_report import CaseResult, run_bank


@pytest.fixture(scope="module")
def results() -> list[CaseResult]:
    return run_bank(load_bank(REPO_ROOT / "evals" / "bank"))


def test_GEN_03_no_completed_case_finishes_with_zero_deliverables(results) -> None:
    empty = [r.case.id for r in results if any(f.check == "delivers_something" for f in r.findings)]
    assert empty == []


def test_GEN_03_the_bank_still_has_completing_cases_to_prove_it_on(results) -> None:
    completed = [r for r in results if r.runs[0].outcome == "completed"]
    assert len(completed) >= 20


def _done(count: int, *types: str):
    from types import SimpleNamespace

    events = [{"type": t} for t in types] + [{"type": "world.completed", "data": {"deliverable_count": count}}]
    return SimpleNamespace(events=events)


def test_GEN_03_made_items_with_nothing_delivered_is_a_finding_but_nothing_made_is_not() -> None:
    from tilo_evals.bank_checks import delivers_something

    assert delivers_something(_done(0, "artifact.created")), "items were made and none delivered"
    assert not delivers_something(_done(0)), "nothing was made: nothing is invented to fill the count (HR-1)"
    assert not delivers_something(_done(1, "artifact.created", "artifact.delivered"))
