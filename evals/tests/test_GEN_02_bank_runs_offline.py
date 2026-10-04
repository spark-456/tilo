"""GEN-02, GEN-03, GEN-04, GEN-11 (issue #272): the whole bank runs end to end offline, holds its invariants, and is
reported honestly. One module-scoped run of every case feeds all of it."""

import socket

import pytest
from conftest import REPO_ROOT
from tilo_evals.bank import bank_digest, load_bank
from tilo_evals.bank_checks import hard_findings
from tilo_evals.bank_report import CLAIM, CaseResult, render, run_bank
from tilo_evals.bank_run import BankRefused, run_case

BANK = REPO_ROOT / "evals" / "bank"


@pytest.fixture(scope="module")
def results() -> list[CaseResult]:
    guard = pytest.MonkeyPatch()
    real_connect = socket.socket.connect

    def loopback_only(self, address):  # the event loop talks to itself over loopback; nothing else may connect
        host = address[0] if isinstance(address, tuple) else address
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise AssertionError(f"the bank made a network connection to {host!r}")
        return real_connect(self, address)

    guard.setattr(socket.socket, "connect", loopback_only)
    try:
        yield run_bank(load_bank(BANK))
    finally:
        guard.undo()


def test_GEN_02_every_case_reaches_a_terminal_state_with_no_network_and_no_paid_call(results) -> None:
    stuck = [r.case.id for r in results if r.runs[0].outcome is None]
    assert not stuck, f"no terminal state: {stuck}"
    assert all(r.runs[0].seconds < 30 for r in results)


def test_GEN_02_the_bank_refuses_a_live_or_deployed_environment(monkeypatch) -> None:
    case = load_bank(BANK)[0]
    for name in ("LIVE", "K_SERVICE", "CLOUD_RUN_JOB"):
        monkeypatch.setenv(name, "1")
        with pytest.raises(BankRefused):
            run_case(case)
        monkeypatch.delenv(name)


def test_GEN_03_hard_invariants_hold_on_every_case(results) -> None:
    bad = {
        r.case.id: [f"{f.check}: {f.detail}" for f in hard_findings(r.findings)]
        for r in results
        if hard_findings(r.findings)
    }
    assert not bad, bad


def test_GEN_03_each_case_reaches_the_outcome_it_expects(results) -> None:
    assert [(r.case.id, r.runs[0].outcome) for r in results if r.runs[0].outcome != r.case.outcome] == []


def test_GEN_03_a_case_that_expects_the_wrong_outcome_fails_the_bank() -> None:
    import dataclasses

    refused = next(c for c in load_bank(BANK) if c.outcome == "refused")
    wrong = dataclasses.replace(refused, expect={"outcome": "completed"})
    (result,) = run_bank([wrong])
    assert not result.passed and any(f.check == "terminal_honest" for f in hard_findings(result.findings))


def test_GEN_04_the_report_gives_counts_first_then_domain_shape_causes_and_every_failure(results) -> None:
    text = render(results, repeat=1, bank_digest=bank_digest(BANK))
    lines = [ln for ln in text.splitlines() if ln.strip()]
    assert lines[0] == "# Generality bank results"
    first = next(ln for ln in lines if "cases pass every hard check" in ln)
    assert first.startswith(f"**{len(results)} of {len(results)}") or " of " in first
    order = [
        text.index(h)
        for h in ("## By domain", "## By shape", "## Failures by cause", "## Reported, not gated", "## Every failure")
    ]
    assert order == sorted(order)
    assert "finance" in text and "gated_send" in text


def test_GEN_04_repeats_agree_for_a_chain_a_parallel_plan_and_a_gated_plan() -> None:
    cases = load_bank(BANK)
    picks = [
        next(c for c in cases if "deep_chain" in c.shapes and c.outcome == "completed"),
        next(c for c in cases if "parallel_units" in c.shapes and c.outcome == "completed"),
        next(c for c in cases if "gated_send" in c.shapes and c.outcome == "completed"),
    ]
    assert all(r.deterministic for r in run_bank(picks, repeat=3))


def test_GEN_04_a_run_that_drifts_is_reported_with_what_drifted() -> None:
    case = load_bank(BANK)[0]
    (result,) = run_bank([case])
    assert result.deterministic and result.drift == ""


def test_GEN_11_the_report_states_its_claim_scope_and_never_claims_any_scenario(results) -> None:
    text = render(results, repeat=1, bank_digest=bank_digest(BANK))
    assert CLAIM in text
    assert text.count("handles any scenario") == 1  # only inside the sentence that says it is not claimed
    assert "not a statement that Tilo handles any scenario" in text
    assert "Director scripted" in text
