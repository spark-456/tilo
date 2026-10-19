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


# Thresholds mirror SKILL.md step 2: strong >= 75, needs_practice 50-74, weak < 50.
STRONG_MIN = 75.0
NEEDS_PRACTICE_MIN = 50.0


def _pct(correct: int, total: int) -> float:
    """SKILL.md step 1: correct / total * 100 rounded to 2 decimal places."""
    return round(correct / total * 100, 2)


def _status(correct: int, total: int) -> str:
    # Thresholds apply to the exact ratio, not the rounded display value.
    ratio = correct * 100 / total
    if ratio >= STRONG_MIN:
        return "strong"
    if ratio >= NEEDS_PRACTICE_MIN:
        return "needs_practice"
    return "weak"


def _check_quiz_output(quiz_input: dict, output: dict) -> list[str]:
    """Recompute every derived field from the input and return the mismatches."""
    problems: list[str] = []
    questions = quiz_input["questions"]
    responses = {r["question_id"]: r["selected"] for r in quiz_input["responses"]}

    per_topic: dict[str, list[int]] = {}
    topic_refs: dict[str, set[tuple[str, int, int]]] = {}
    for q in questions:
        row = per_topic.setdefault(q["topic"], [0, 0])
        row[1] += 1
        if responses.get(q["id"]) == q["answer"]:
            row[0] += 1
        art = q["source"]["artifact"]
        topic_refs.setdefault(q["topic"], set()).add((art["artifact_id"], art["version"], q["source"]["page"]))

    total = len(questions)
    correct = sum(c for c, _ in per_topic.values())
    score = output["score"]
    if (score["correct"], score["total"]) != (correct, total):
        problems.append(f"score counts {score['correct']}/{score['total']} != {correct}/{total}")
    if score["accuracy_pct"] != _pct(correct, total):
        problems.append(f"score accuracy_pct {score['accuracy_pct']} != {_pct(correct, total)}")

    breakdown = {row["topic"]: row for row in output["topic_breakdown"]}
    if len(breakdown) != len(output["topic_breakdown"]) or set(breakdown) != set(per_topic):
        problems.append("topic_breakdown topics do not match the question topics")
    for topic, (t_correct, t_total) in per_topic.items():
        row = breakdown.get(topic)
        if row is None:
            continue
        if (row["correct"], row["total"]) != (t_correct, t_total):
            problems.append(f"{topic} counts {row['correct']}/{row['total']} != {t_correct}/{t_total}")
        if row["accuracy_pct"] != _pct(t_correct, t_total):
            problems.append(f"{topic} accuracy_pct {row['accuracy_pct']} != {_pct(t_correct, t_total)}")
        if row["status"] != _status(t_correct, t_total):
            problems.append(f"{topic} status {row['status']!r} != {_status(t_correct, t_total)!r}")

    weak = {t for t, (c, n) in per_topic.items() if _status(c, n) == "weak"}
    if set(output["weak_topics"]) != weak or len(output["weak_topics"]) != len(weak):
        problems.append(f"weak_topics {output['weak_topics']} != {sorted(weak)}")

    needs_work = {t for t, (c, n) in per_topic.items() if _status(c, n) != "strong"}
    # SKILL.md step 3: practice targets weak / needs-practice topics; with none, strong topics.
    allowed = needs_work or set(per_topic)
    practice_topics = [item["topic"] for item in output["next_practice_set"]]
    if len(set(practice_topics)) != len(practice_topics):
        problems.append("next_practice_set repeats a topic")
    if not weak <= set(practice_topics):
        problems.append("next_practice_set misses a weak topic")
    for item in output["next_practice_set"]:
        if item["topic"] not in allowed:
            problems.append(f"next_practice_set targets {item['topic']!r}, which is not weak or needs practice")
            continue
        for ref in item["source_refs"]:
            key = (ref["artifact_id"], ref["version"], ref["page"])
            if key not in topic_refs[item["topic"]]:
                problems.append(f"{item['topic']} source_ref {key} is not a source of that topic's questions")
    return problems


def test_FR_AGT_04_LW_17_quiz_assessment_golden_scores_topics_and_sources_recompute() -> None:
    for case in _load_golden()["cases"]:
        assert _check_quiz_output(case["input"], case["expected_output"]) == [], case["id"]


def test_FR_AGT_04_LW_17_quiz_assessment_golden_covers_exact_threshold_boundaries() -> None:
    seen: dict[float, str] = {}
    for case in _load_golden()["cases"]:
        for row in case["expected_output"]["topic_breakdown"]:
            seen[row["accuracy_pct"]] = row["status"]
    assert seen[75.0] == "strong"
    assert seen[50.0] == "needs_practice"
    assert any(pct < NEEDS_PRACTICE_MIN and status == "weak" for pct, status in seen.items())


def test_FR_AGT_04_LW_17_quiz_assessment_check_rejects_tampered_output() -> None:
    case = next(c for c in _load_golden()["cases"] if c["id"] == "threshold_boundary_attempt")

    def tampered(mutate) -> list[str]:
        output = json.loads(json.dumps(case["expected_output"]))
        mutate(output)
        return _check_quiz_output(case["input"], output)

    assert _check_quiz_output(case["input"], case["expected_output"]) == []
    assert tampered(lambda o: o["topic_breakdown"][2].update(accuracy_pct=40.0))
    assert tampered(lambda o: o["score"].update(accuracy_pct=56.0))
    assert tampered(lambda o: o["topic_breakdown"][1].update(status="weak"))
    assert tampered(lambda o: o["topic_breakdown"][0].update(status="needs_practice"))
    assert tampered(lambda o: o.update(weak_topics=[]))
    assert tampered(lambda o: o["next_practice_set"][0]["source_refs"][0].update(page=99))
    assert tampered(lambda o: o["next_practice_set"][0]["source_refs"][0].update(artifact_id="art_not_in_input"))
    assert tampered(
        lambda o: o["next_practice_set"].append(
            {
                "topic": "lattice_flux",
                "recommended_count": 1,
                "focus_note": "x",
                "source_refs": [{"artifact_id": "art_northbridge_paper_1", "version": 1, "page": 1}],
            }
        )
    )
