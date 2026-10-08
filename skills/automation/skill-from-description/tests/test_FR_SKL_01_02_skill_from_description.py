from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import jsonschema
import yaml
from tilo_harness.skill_proposals import SkillProposals
from tilo_harness.skills import SkillRegistry
from tilo_harness.validator import repo_validator

REPO_ROOT = Path(__file__).resolve().parents[4]
SKILLS_ROOT = REPO_ROOT / "skills"
SKILL_DIR = SKILLS_ROOT / "automation" / "skill-from-description"

RISKY_VERBS = {"send", "pay", "delete", "share", "book"}


def _tokenize_grounding(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9_]+", text.lower()) if len(t) >= 3}


def _expected_trigger_from_description(description: str) -> dict[str, Any]:
    lower = description.lower()
    if "every week" in lower or "weekly" in lower or "every monday" in lower:
        return {"kind": "schedule", "cadence": "weekly"}
    if "every day" in lower or "daily" in lower or "every morning" in lower:
        return {"kind": "schedule", "cadence": "daily"}
    if "every month" in lower or "monthly" in lower or "1st of every month" in lower:
        return {"kind": "schedule", "cadence": "monthly"}
    if "when a new" in lower or "whenever " in lower:
        return {"kind": "event"}
    return {"kind": "on_request"}


def _expected_scope_from_description(description: str) -> str:
    lower = description.lower()
    if any(tok in lower for tok in ("our team", "the team", "#team", "shared team", "for the team")):
        return "team"
    return "just_me"


def check_skill_from_description_output(case_input: dict[str, Any], output: dict[str, Any]) -> list[str]:
    """Input-computable checker for FR-SKL-01 and FR-SKL-02."""
    errors: list[str] = []
    description = case_input["description"]
    desc_tokens = _tokenize_grounding(description)
    allowed_tools = set(case_input.get("connected_tools", []))

    steps = output.get("steps", [])
    if not steps:
        errors.append("steps must not be empty")

    expected_clauses = case_input.get("expected_action_clauses", [])
    if expected_clauses and len(steps) != len(expected_clauses):
        errors.append(f"step count {len(steps)} does not match input action clauses {len(expected_clauses)}")

    for idx, step in enumerate(steps):
        verb = step.get("verb", "").lower().strip()
        obj = step.get("object", "")
        tool = step.get("tool", "")
        ask_first = step.get("ask_me_first")

        if tool not in allowed_tools:
            errors.append(f"step[{idx}] uses ungrounded tool '{tool}' not in {sorted(allowed_tools)}")

        obj_tokens = _tokenize_grounding(obj)
        if not obj_tokens or not (obj_tokens & desc_tokens):
            errors.append(f"step[{idx}] object '{obj}' is invented (no lexical overlap with description)")

        is_risky = verb in RISKY_VERBS or any(rv in _tokenize_grounding(f"{verb} {obj}") for rv in RISKY_VERBS)
        if is_risky and ask_first is not True:
            errors.append(f"step[{idx}] ('{verb} {obj}') is a risky action and must have ask_me_first=True")
        if not is_risky and ask_first is not False:
            errors.append(f"step[{idx}] ('{verb} {obj}') is a read/draft action and must have ask_me_first=False")

    is_ambiguous = bool(case_input.get("is_ambiguous", False))
    question = output.get("clarifying_question")
    if is_ambiguous:
        if not isinstance(question, str) or not question.strip().endswith("?"):
            errors.append("ambiguous description must produce exactly one clarifying question ending with '?'")
        elif question.count("?") != 1:
            errors.append(f"expected exactly one clarifying question, found {question.count('?')} '?' marks")
    else:
        if question is not None:
            errors.append(f"clear description must have clarifying_question=None, got {question!r}")

    expected_trigger = _expected_trigger_from_description(description)
    actual_trigger = output.get("trigger", {})
    if actual_trigger.get("kind") != expected_trigger["kind"]:
        errors.append(f"trigger.kind {actual_trigger.get('kind')!r} != {expected_trigger['kind']!r}")
    if "cadence" in expected_trigger and actual_trigger.get("cadence") != expected_trigger["cadence"]:
        errors.append(f"trigger.cadence {actual_trigger.get('cadence')!r} != {expected_trigger['cadence']!r}")

    expected_scope = _expected_scope_from_description(description)
    if output.get("scope") != expected_scope:
        errors.append(f"scope {output.get('scope')!r} != {expected_scope!r}")

    return errors


def test_FR_SKL_01_FR_SKL_02_skill_from_description_loads_and_conforms_to_contract() -> None:
    registry = SkillRegistry(SKILLS_ROOT)
    assert registry.problems == {}
    loaded = registry.load("skill-from-description")
    assert loaded.version == "1.0.0"

    raw = yaml.safe_load((SKILL_DIR / "skill.yaml").read_text(encoding="utf-8"))
    assert raw["domain"] == "automation"
    assert raw["tools_allowed"] == []
    assert repo_validator().contract_problems("skill", raw) == []
    jsonschema.Draft202012Validator.check_schema(raw["inputs"])
    jsonschema.Draft202012Validator.check_schema(raw["outputs"])

    for section in ("When to use", "Steps", "Quality bar", "Checklist", "Pitfalls"):
        assert section in loaded.body, f"SKILL.md missing section {section}"

    proposals = SkillProposals(registry)
    decision = {
        "id": "01J9RP8V7X2K4M6N8P0Q2R4S6T",
        "org_id": "org_acme",
        "domain": "automation",
        "question": "Should booking steps always set ask_me_first to True?",
        "answer": "Always require ask_me_first=True on any step that books a meeting or resource.",
        "option_id": None,
        "answered_by": {
            "by": "team_lead",
            "ref": "tl_automation",
            "user": "u_lead_auto",
            "at": "2026-10-08T12:00:00.000Z",
        },
        "source": {
            "world_id": "w_main",
            "run_id": "r_001",
            "card_id": "01J9RP8V7X2K4M6N8P0Q2R4S6V",
        },
        "scope": {"worlds": "all", "districts": "all"},
        "created_at": "2026-10-08T12:00:00.000Z",
        "expires_at": None,
    }
    proposal = proposals.propose(
        decision=decision,
        skill_id="skill-from-description",
        proposer="u_lead_auto",
    )
    assert proposal["to_version"] == "1.0.1"


def test_FR_SKL_01_FR_SKL_02_golden_descriptions_steps_ask_first_ambiguity_and_trigger() -> None:
    raw = yaml.safe_load((SKILL_DIR / "skill.yaml").read_text(encoding="utf-8"))
    in_validator = jsonschema.Draft202012Validator(raw["inputs"])
    out_validator = jsonschema.Draft202012Validator(raw["outputs"])

    golden = json.loads((SKILL_DIR / "examples" / "golden_cases.json").read_text(encoding="utf-8"))
    cases = golden["cases"]
    assert len(cases) >= 6

    required_categories = {
        "clear",
        "ambiguous",
        "weekly_routine",
        "email_sending",
        "payment",
        "multi_tool",
    }
    seen_categories = {c["category"] for c in cases}
    assert required_categories <= seen_categories

    seen_risky_verbs: set[str] = set()
    for case in cases:
        in_validator.validate(case["input"])
        out_validator.validate(case["output"])
        errs = check_skill_from_description_output(case["input"], case["output"])
        assert errs == [], f"Case {case['id']} failed checker: {errs}"
        for step in case["output"]["steps"]:
            if step["verb"] in RISKY_VERBS:
                seen_risky_verbs.add(step["verb"])
                assert step["ask_me_first"] is True

    assert seen_risky_verbs == RISKY_VERBS


def test_FR_SKL_01_FR_SKL_02_checker_rejects_invented_steps_and_unchecked_risky_verbs() -> None:
    golden = json.loads((SKILL_DIR / "examples" / "golden_cases.json").read_text(encoding="utf-8"))
    base_case = next(c for c in golden["cases"] if c["category"] == "email_sending")

    bad_risky = json.loads(json.dumps(base_case["output"]))
    for step in bad_risky["steps"]:
        if step["verb"] == "send":
            step["ask_me_first"] = False
    errs = check_skill_from_description_output(base_case["input"], bad_risky)
    assert any("ask_me_first=True" in e for e in errs)

    invented = json.loads(json.dumps(base_case["output"]))
    invented["steps"].append(
        {
            "verb": "archive",
            "object": "unrelated payroll database tables",
            "tool": "gmail",
            "ask_me_first": False,
        }
    )
    errs_inv = check_skill_from_description_output(base_case["input"], invented)
    assert any("step count" in e or "invented" in e for e in errs_inv)
