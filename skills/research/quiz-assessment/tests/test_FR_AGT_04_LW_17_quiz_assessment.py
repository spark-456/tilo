"""FR-AGT-04 / LW-17 golden tests for skills/research/quiz-assessment (ADR-0029, PRD 8.2)."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import yaml
from tilo_harness.skills import SkillRegistry
from tilo_harness.validator import repo_validator

SKILL_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SKILL_DIR.parents[2]
SKILLS_ROOT = REPO_ROOT / "skills"
SKILL_ID = "quiz-assessment"


def _load_yaml() -> dict:
    return yaml.safe_load((SKILL_DIR / "skill.yaml").read_text(encoding="utf-8"))


def _load_golden() -> dict:
    return json.loads((SKILL_DIR / "examples" / "golden_cases.json").read_text(encoding="utf-8"))


def test_FR_AGT_04_LW_17_quiz_assessment_loads_and_declares_diagnostic_outputs() -> None:
    registry = SkillRegistry(SKILLS_ROOT)
    assert registry.problems == {}, f"SkillRegistry reported problems: {registry.problems}"
    catalog = dict(registry.catalog())
    assert SKILL_ID in catalog
    loaded = registry.load(SKILL_ID)
    assert loaded.id == SKILL_ID and loaded.version == "1.0.0"

    data = _load_yaml()
    assert repo_validator().contract_problems("skill", data) == []
    assert data["tools_allowed"] == []
    for heading in ("When to use", "Steps", "Quality bar", "Checklist", "Pitfalls"):
        assert heading in loaded.body, f"SKILL.md missing section {heading!r}"
    assert "weak_topics" in loaded.body and "next_practice_set" in loaded.body


def test_FR_AGT_04_LW_17_quiz_assessment_golden_cases_score_weak_topics_and_next_practice_set() -> None:
    data = _load_yaml()
    in_validator = jsonschema.Draft202012Validator(data["inputs"])
    out_validator = jsonschema.Draft202012Validator(data["outputs"])
    cases = _load_golden()["cases"]
    assert len(cases) >= 2

    for case in cases:
        in_validator.validate(case["input"])
        out_validator.validate(case["expected_output"])
        questions = {q["id"]: q for q in case["input"]["questions"]}
        responses = {r["question_id"]: r["selected"] for r in case["input"]["responses"]}
        expected_correct = sum(1 for qid, q in questions.items() if responses.get(qid) == q["answer"])
        output = case["expected_output"]
        assert output["score"]["total"] == len(questions)
        assert output["score"]["correct"] == expected_correct
        weak = {row["topic"] for row in output["topic_breakdown"] if row["status"] == "weak"}
        assert set(output["weak_topics"]) == weak
        practice_topics = {item["topic"] for item in output["next_practice_set"]}
        assert weak <= practice_topics
        assert output["summary"].strip()
