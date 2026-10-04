"""CL-INT-5 (FR-INT-03/05/06, EFF-01): brief extraction, questions and approaches run end to end on the dev models
file, whose Director is the deterministic fake, for arbitrary task text, with no recordings and no repair or
escalation (the fake's replies pass the router's schema check and the PG-07/08/09 checks first time)."""

from __future__ import annotations

import pathlib

import pytest
from tilo_planning.approaches import propose_approaches
from tilo_planning.brief import extract_brief
from tilo_planning.memory import InMemoryPreferenceStore
from tilo_planning.questions import MAX_QUESTIONS, generate_questions
from tilo_providers.config import load_providers_config
from tilo_providers.router import Router

ROOT = pathlib.Path(__file__).resolve().parents[3]
BASE = {
    "v": "1.0",
    "ts": "2026-10-03T00:00:00.000Z",
    "world_id": "w_testworld00000000000000",
    "run_id": "r_testrun0000000000000000",
    "actor": "u_test",
}


@pytest.fixture()
def router(tmp_path, monkeypatch):
    for name in ("LIVE", "K_SERVICE", "CLOUD_RUN_JOB"):
        monkeypatch.delenv(name, raising=False)
    config = load_providers_config(ROOT / "config" / "models.dev.yaml", ROOT / "config" / "prices.yaml")
    return Router(config, fixtures_dir=tmp_path / "no-recordings")


@pytest.mark.parametrize("task", ["Prepare the weekly supplier summary.", "Plan a launch, due 2026-11-02.", "a"])
def test_CL_INT_5_any_task_text_reaches_questions_and_approaches(router, task):
    extraction = extract_brief(task, router=router)
    questions = generate_questions(
        extraction.brief, extraction.ambiguous_fields, memory=InMemoryPreferenceStore(), base=BASE, seq=1
    )
    approaches = propose_approaches(questions.brief, router=router, base=BASE, seq=2)

    assert questions.brief["goal"] == task
    assert 1 <= len(questions.questions) <= MAX_QUESTIONS  # FR-INT-05: unknown fields are asked, capped at 3
    assert questions.event is not None and questions.event["type"] == "plan.questions_asked"
    assert len(approaches.approaches) == 3
    assert approaches.event["type"] == "plan.approaches_proposed"
    for run in (extraction.run, *approaches.runs):
        assert [a.outcome for a in run.attempts] == ["ok"], "no repair, escalation or fallback was needed"
        assert [a.profile_id for a in run.attempts] == ["director-dev"]
    assert len(approaches.runs) == 1
