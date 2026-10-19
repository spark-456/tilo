from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema
import yaml
from tilo_harness.skill_proposals import SkillProposals
from tilo_harness.skills import SkillRegistry
from tilo_harness.validator import repo_validator

REPO_ROOT = Path(__file__).resolve().parents[4]
SKILLS_ROOT = REPO_ROOT / "skills"
SKILL_DIR = SKILLS_ROOT / "automation" / "try-run-match"


def score_try_run(
    taught_steps: list[dict[str, Any]],
    recorded_steps: list[dict[str, Any]],
) -> dict[str, Any]:
    """Pure Python deterministic scorer for FR-SKL-03 try run match."""
    # Empty taught example edge case
    if not taught_steps:
        return {
            "status": "fail",
            "match_percent": 0.0,
            "matched_steps": [],
            "added_steps": [dict(s) for s in recorded_steps],
            "skipped_steps": [],
            "paused_ask_first_steps": [],
            "missed_ask_first_steps": [],
            "failure_reason": "empty_taught_example",
        }

    # Step matching helper: matches by verb, object, tool
    def _step_key(s: dict[str, Any]) -> tuple[str, str, str]:
        return (
            s.get("verb", "").strip().lower(),
            s.get("object", "").strip().lower(),
            s.get("tool", "").strip().lower(),
        )

    # 1. Ask-first pause enforcement: every taught step with ask_me_first=True must have paused=True in recorded_steps
    paused_steps: list[dict[str, Any]] = []
    missed_ask_first: list[dict[str, Any]] = []

    for s in taught_steps:
        if s.get("ask_me_first") is True:
            t_key = _step_key(s)
            matching_rec = [r for r in recorded_steps if _step_key(r) == t_key]
            # Must appear in recorded steps AND pause must be True
            if matching_rec and any(r.get("paused") is True for r in matching_rec):
                paused_steps.append(dict(s))
            else:
                missed_ask_first.append(dict(s))

    if missed_ask_first:
        return {
            "status": "fail",
            "match_percent": 0.0,
            "matched_steps": [],
            "added_steps": [],
            "skipped_steps": [],
            "paused_ask_first_steps": paused_steps,
            "missed_ask_first_steps": missed_ask_first,
            "failure_reason": "missed_ask_first_pause",
        }

    # 2. Sequence alignment and diff:
    # We find matched steps, added steps, and skipped steps, taking ordering into account.
    # Longest common subsequence (LCS) on step keys determines matched steps in order.
    taught_keys = [_step_key(s) for s in taught_steps]
    recorded_keys = [_step_key(s) for s in recorded_steps]

    m, n = len(taught_keys), len(recorded_keys)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(m):
        for j in range(n):
            if taught_keys[i] == recorded_keys[j]:
                dp[i + 1][j + 1] = dp[i][j] + 1
            else:
                dp[i + 1][j + 1] = max(dp[i + 1][j], dp[i][j + 1])

    # Backtrack to identify matched indices
    matched_taught_idx: set[int] = set()
    matched_rec_idx: set[int] = set()
    i, j = m, n
    while i > 0 and j > 0:
        if taught_keys[i - 1] == recorded_keys[j - 1]:
            matched_taught_idx.add(i - 1)
            matched_rec_idx.add(j - 1)
            i -= 1
            j -= 1
        elif dp[i - 1][j] >= dp[i][j - 1]:
            i -= 1
        else:
            j -= 1

    matched_steps = [dict(taught_steps[idx]) for idx in sorted(matched_taught_idx)]
    skipped_steps = [dict(taught_steps[idx]) for idx in range(m) if idx not in matched_taught_idx]
    added_steps = [dict(recorded_steps[idx]) for idx in range(n) if idx not in matched_rec_idx]

    # Score calculation:
    # Based on alignment relative to total expected operations (taught steps + additions).
    # If identical: m == n == len(matched_steps), score = 100.0%.
    # Each skipped or added step penalizes the alignment.
    total_elements = max(m, n)
    match_percent = round((len(matched_steps) / total_elements) * 100.0, 1) if total_elements > 0 else 0.0

    return {
        "status": "pass",
        "match_percent": match_percent,
        "matched_steps": matched_steps,
        "added_steps": added_steps,
        "skipped_steps": skipped_steps,
        "paused_ask_first_steps": paused_steps,
        "missed_ask_first_steps": [],
        "failure_reason": None,
    }


def check_try_run_scorer_contract(output: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    status = output.get("status")
    if status not in ("pass", "fail"):
        errors.append(f"invalid status {status!r}")

    pct = output.get("match_percent")
    if not isinstance(pct, (int, float)) or not (0.0 <= pct <= 100.0):
        errors.append(f"match_percent {pct!r} out of bounds")

    if status == "fail" and not output.get("failure_reason"):
        errors.append("fail status must provide a failure_reason")
    if status == "pass" and output.get("failure_reason") is not None:
        errors.append(f"pass status must have failure_reason=None, got {output.get('failure_reason')!r}")

    return errors


def test_FR_SKL_03_try_run_match_skill_loads_and_conforms_to_contract() -> None:
    registry = SkillRegistry(SKILLS_ROOT)
    assert registry.problems == {}
    loaded = registry.load("try-run-match")
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
        "question": "How should a try run score a missed ask-first pause?",
        "answer": "A missed ask-first pause is a hard fail, not a lower score.",
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
        skill_id="try-run-match",
        proposer="u_lead_auto",
    )
    assert proposal["to_version"] == "1.0.1"


def test_FR_SKL_03_golden_try_run_cases() -> None:
    raw = yaml.safe_load((SKILL_DIR / "skill.yaml").read_text(encoding="utf-8"))
    in_validator = jsonschema.Draft202012Validator(raw["inputs"])
    out_validator = jsonschema.Draft202012Validator(raw["outputs"])

    golden = json.loads((SKILL_DIR / "examples" / "golden_cases.json").read_text(encoding="utf-8"))
    cases = golden["cases"]
    assert len(cases) >= 6

    expected_categories = {
        "identical_run",
        "reordered_steps",
        "extra_step",
        "skipped_step",
        "missed_ask_first_pause",
        "empty_example",
    }
    actual_categories = {c["category"] for c in cases}
    assert expected_categories <= actual_categories

    for case in cases:
        in_validator.validate(case["input"])
        out_validator.validate(case["output"])

        computed = score_try_run(
            taught_steps=case["input"]["taught_steps"],
            recorded_steps=case["input"]["recorded_steps"],
        )
        assert computed["status"] == case["output"]["status"], f"Case {case['id']} status mismatch"
        assert computed["match_percent"] == case["output"]["match_percent"], f"Case {case['id']} pct mismatch"
        assert computed["failure_reason"] == case["output"]["failure_reason"], f"Case {case['id']} reason mismatch"
        assert len(computed["paused_ask_first_steps"]) == len(case["output"]["paused_ask_first_steps"])
        assert len(computed["missed_ask_first_steps"]) == len(case["output"]["missed_ask_first_steps"])
        assert len(computed["matched_steps"]) == len(case["output"]["matched_steps"])
        assert len(computed["added_steps"]) == len(case["output"]["added_steps"])
        assert len(computed["skipped_steps"]) == len(case["output"]["skipped_steps"])
