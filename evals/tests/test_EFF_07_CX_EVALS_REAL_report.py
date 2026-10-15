"""CX-EVALS-REAL: an executed fake case and an unavailable replay are distinct."""

from types import SimpleNamespace

from tilo_evals.real_report import render_report


def test_EFF_07_CX_EVALS_REAL_reports_executed_failed_and_not_runnable_separately():
    bank = [
        SimpleNamespace(case=SimpleNamespace(id="B-001"), passed=True),
        SimpleNamespace(case=SimpleNamespace(id="B-002"), passed=False),
    ]
    replay = SimpleNamespace(
        ran=[SimpleNamespace(case=SimpleNamespace(id="E-PLAN-01"), passed=True)],
        failed=[],
        not_runnable={"E-PLAN-02": "no recording", "E-RED-01": "status skeleton"},
        not_run=[],
    )

    report = render_report(bank, replay, build_hash="abc123")

    assert "| Executed | 3 |" in report
    assert "| Failed | 1 |" in report
    assert "| Not runnable | 2 |" in report
    assert "B-002" in report and "E-PLAN-02" in report
    assert "fake" in report.lower() and "recording" in report.lower()
