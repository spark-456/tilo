"""E-BUILD integration and fail-closed checks; flows themselves run once through just eval."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from tilo_evals import load_cases
from tilo_evals.checks import Outcome, get
from tilo_evals.ebuild_fake import SCENARIOS, execute
from tilo_evals.executors import ExecutorError
from tilo_evals.runner import _is_runnable

ROOT = Path(__file__).resolve().parents[2]


def test_PREP_EBUILD_eight_ready_fake_cases_and_checks_have_teeth():
    cases = load_cases(str(ROOT / "evals/build-cases"))
    assert [c.id for c in cases] == [f"E-BUILD-{i:02}" for i in range(1, 9)]
    assert tuple(c.inputs["scenario"] for c in cases) == SCENARIOS
    for case in cases:
        assert _is_runnable(case) and case.recording is None and not case.deploy_gate
        for entry in case.checks:
            check = get(entry["check"])
            assert check(case, Outcome((), dict(case.ground_truth)), entry["args"]).passed
            assert not check(case, Outcome((), {}), entry["args"]).passed
        bad = dict(case.ground_truth, mechanics_passed=False)
        assert not get("equals_ground_truth")(case, Outcome((), bad), {"field": "mechanics_passed"}).passed


def test_PREP_EBUILD_unknown_scenario_refuses_before_a_process(monkeypatch):
    def forbid(*args, **kwargs):
        raise AssertionError("must not start an unknown flow")

    monkeypatch.setattr("tilo_evals.ebuild_fake.subprocess.run", forbid)
    with pytest.raises(ExecutorError, match="unknown"):
        execute(SimpleNamespace(id="E-BUILD-99", inputs={"scenario": "unknown"}))


def test_PREP_EBUILD_assertion_failure_is_not_runnable(monkeypatch):
    monkeypatch.setattr(
        "tilo_evals.ebuild_fake.subprocess.run",
        lambda *a, **k: SimpleNamespace(returncode=1, stderr="AssertionError: prompt differs", stdout=""),
    )
    with pytest.raises(ExecutorError, match="prompt differs"):
        execute(SimpleNamespace(id="E-BUILD-01", inputs={"scenario": "standard"}))
