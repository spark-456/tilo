"""FR-AGT-12 / FR-INT-03, INTAKE-QUALITY-1: the live-e2e unit runner (the second unit-runner path) gives a verifier
unit the deterministic date-window check before any model call, and every prompt of a run states one date. A replay
states the date its recordings were made with (the `TODAY` marker), so a recording key does not change from day to
day. No model, no network."""

from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path

import pytest
from tilo_evals import live_e2e
from tilo_providers.clock import real_today

REPO_ROOT = Path(__file__).resolve().parents[2]
TODAY = date(2026, 10, 9)
BRIEF = {"goal": "g", "audience": "a", "deliverables": [], "constraints": [], "deadline": "2027-02-07"}
PLAN = {
    "units": [
        {"id": "U1", "role": "specialist", "title": "Draft", "unit_type": "draft", "district": "D1", "depends_on": []},
        {
            "id": "U2",
            "role": "verifier",
            "title": "Verify",
            "unit_type": "verify",
            "district": "D2",
            "depends_on": ["U1"],
        },
    ]
}


class _Context:
    skills: tuple = ()


def _runner(replies: dict[str, str], asked: list[str]) -> live_e2e._UnitRunner:
    runner = live_e2e._UnitRunner(None, None, TODAY)  # type: ignore[arg-type]
    runner.capture(BRIEF, PLAN)

    def ask(role: str, prompt: str) -> tuple[str, float]:
        asked.append(prompt)
        return replies[role], 0.0

    runner._ask = ask  # type: ignore[method-assign]
    return runner


def _run(runner: live_e2e._UnitRunner, unit_id: str):
    unit = next(u for u in PLAN["units"] if u["id"] == unit_id)
    return asyncio.run(runner.run(unit, _Context()))


def test_FR_AGT_12_a_verifier_unit_fails_on_a_date_before_today_without_a_model_call() -> None:
    asked: list[str] = []
    runner = _runner({"specialist": "Roadmap: start March 2025, exam 2027-02-07.", "lead": "ok"}, asked)
    _run(runner, "U1")
    before = len(asked)

    outcome = _run(runner, "U2")

    verdict = outcome.outputs[0].content.decode("utf-8")
    assert verdict.splitlines()[0] == "FAIL" and '"March 2025"' in verdict
    assert "Verdict: FAIL" in outcome.summary
    assert [p for p in asked[before:] if "<<<WORK" in p and "Verify" in p and "Lead" not in p] == []


def test_FR_AGT_12_a_verifier_unit_inside_the_window_goes_to_the_model() -> None:
    asked: list[str] = []
    runner = _runner(
        {"specialist": "Start 2026-11-02, exam 2027-02-07.", "verifier": "PASS\nfine", "lead": "ok"}, asked
    )
    _run(runner, "U1")

    outcome = _run(runner, "U2")

    assert outcome.outputs[0].content.decode("utf-8").startswith("PASS")
    verifier_prompt = next(p for p in asked if "You are Tilo's Verifier" in p)
    assert "Today is 2026-10-09" in verifier_prompt and "121 days from today" in verifier_prompt


def test_FR_AGT_12_the_failed_check_asks_no_verifier_model_at_all() -> None:
    asked: list[str] = []
    runner = _runner(
        {"specialist": "Start March 2025.", "lead": "ok"}, asked
    )  # no "verifier" reply: a call would KeyError
    _run(runner, "U1")

    _run(runner, "U2")

    assert not any("You are Tilo's Verifier" in p for p in asked)


def test_FR_INT_03_a_replay_states_the_date_its_recordings_were_made_with(tmp_path) -> None:
    (tmp_path / live_e2e.TODAY_MARKER).write_text("2026-10-09\n", encoding="utf-8")

    assert live_e2e._run_date(tmp_path, None, live=False) == TODAY
    assert live_e2e._run_date(tmp_path, date(2030, 1, 1), live=False) == date(2030, 1, 1)  # the caller's date wins
    assert live_e2e._run_date(tmp_path, None, live=True) == real_today()  # a live run states the real date


@pytest.mark.parametrize("content", [None, "not a date\n", "2026-13-01\n"])
def test_FR_INT_03_without_a_usable_marker_a_replay_uses_the_real_date(tmp_path, content) -> None:
    if content is not None:
        (tmp_path / live_e2e.TODAY_MARKER).write_text(content, encoding="utf-8")

    assert live_e2e._run_date(tmp_path, None, live=False) == real_today()


def test_FR_INT_03_the_committed_fixture_records_the_date_its_prompts_stated() -> None:
    marker = REPO_ROOT / "evals" / "bank" / "live" / "B-007" / live_e2e.TODAY_MARKER

    assert marker.read_text(encoding="utf-8").strip() == "2026-10-09"
