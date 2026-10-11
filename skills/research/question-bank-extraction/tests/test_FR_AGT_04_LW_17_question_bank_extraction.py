"""FR-AGT-04 / LW-17 golden tests for skills/research/question-bank-extraction (ADR-0029, PRD 8.2)."""

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
SKILL_ID = "question-bank-extraction"


def _load_yaml() -> dict:
    return yaml.safe_load((SKILL_DIR / "skill.yaml").read_text(encoding="utf-8"))


def _load_golden() -> dict:
    return json.loads((SKILL_DIR / "examples" / "golden_cases.json").read_text(encoding="utf-8"))


def test_FR_AGT_04_LW_17_question_bank_extraction_loads_and_documents_no_invented_answers() -> None:
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
    assert "unknown" in loaded.body and "never invent" in loaded.body.lower()


def test_FR_AGT_04_LW_17_question_bank_extraction_golden_cases_extract_mcqs_and_mark_unknown_answers() -> None:
    data = _load_yaml()
    in_validator = jsonschema.Draft202012Validator(data["inputs"])
    out_validator = jsonschema.Draft202012Validator(data["outputs"])
    cases = _load_golden()["cases"]
    assert len(cases) >= 2

    for case in cases:
        in_validator.validate(case["input"])
        out_validator.validate(case["expected_output"])
        part_ids = {p["artifact"]["artifact_id"] for p in case["input"]["parts"]}
        for q in case["expected_output"]["questions"]:
            assert set(q["options"]) == {"a", "b", "c", "d"}
            assert q["source"]["artifact"]["artifact_id"] in part_ids
            assert q["source"]["page"] >= 1
            if q["answer"] == "unknown":
                assert q["answer_source"] is None
            else:
                assert q["answer"] in {"a", "b", "c", "d"}
                assert q["answer_source"] is not None
                assert q["answer_source"]["artifact"]["artifact_id"] in part_ids

    with_key = next(c for c in cases if c["id"] == "paper_with_answer_key")
    quiz_spec = {
        "v": "1.0",
        "kind": "quiz",
        "title": "Northbridge Imaginary Systems Practice Set",
        "theme": "metropolis",
        "timer": {"seconds": 900},
        "questions": [
            {k: q[k] for k in ("id", "stem", "options", "answer", "topic", "source")}
            for q in with_key["expected_output"]["questions"]
            if q["answer"] != "unknown"
        ],
    }
    assert repo_validator().contract_problems("appspec", quiz_spec) == []

    without_key = next(c for c in cases if c["id"] == "paper_without_answer_key")
    assert all(q["answer"] == "unknown" for q in without_key["expected_output"]["questions"])
