"""FR-SKL-03: test the callable scorer, never a test-local substitute or live run."""

from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
from typing import Any

import pytest


def scorer() -> Any:
    spec = importlib.util.spec_from_file_location("try_run_match_scorer", Path(__file__).parents[1] / "scorer.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.score_try_run


def taught(verb: str, ask: bool = False, *, target: str = "a note") -> dict[str, Any]:
    return {"verb": verb, "object": target, "tool": "workspace", "ask_me_first": ask}


def recorded(verb: str, paused: bool = False, *, target: str = "a note") -> dict[str, Any]:
    return {"verb": verb, "object": target, "tool": "workspace", "paused": paused}


@pytest.mark.parametrize(
    "run,percent,matched,added,skipped",
    [
        (["read", "draft", "review"], 100.0, ["read", "draft", "review"], [], []),
        (["draft", "read", "review"], 66.7, ["read", "review"], ["draft"], ["draft"]),
        (["read", "check", "draft", "review"], 75.0, ["read", "draft", "review"], ["check"], []),
        (["read", "review"], 66.7, ["read", "review"], [], ["draft"]),
    ],
)
def test_FR_SKL_03_golden_alignment_lists_exact_steps(
    run: list[str],
    percent: float,
    matched: list[str],
    added: list[str],
    skipped: list[str],
) -> None:
    example = [taught(v) for v in ["read", "draft", "review"]]
    execution = [recorded(v) for v in run]
    result = scorer()(example, execution)
    assert result == {
        "status": "pass",
        "match_percent": percent,
        "matched_steps": [taught(v) for v in matched],
        "added_steps": [recorded(v) for v in added],
        "skipped_steps": [taught(v) for v in skipped],
        "paused_ask_first_steps": [],
        "missed_ask_first_steps": [],
        "failure_reason": None,
    }


@pytest.mark.parametrize("run", [[recorded("review")], []])
def test_FR_SKL_03_missed_or_skipped_ask_first_is_a_hard_failure(run: list[dict[str, Any]]) -> None:
    step = taught("review", True)
    result = scorer()([step], run)
    assert result["status"] == "fail" and result["match_percent"] == 0.0
    assert result["failure_reason"] == "missed_ask_first_pause"
    assert result["missed_ask_first_steps"] == [step]
    assert result["paused_ask_first_steps"] == []


def test_FR_SKL_03_empty_example_has_no_match() -> None:
    execution = [recorded("read")]
    result = scorer()([], execution)
    assert result["status"] == "fail" and result["match_percent"] == 0.0
    assert result["failure_reason"] == "empty_taught_example"
    assert result["added_steps"] == execution


def test_FR_SKL_03_every_repeated_ask_first_occurrence_needs_its_own_pause() -> None:
    example = [taught("review", True), taught("review", True)]
    score = scorer()
    for execution in ([recorded("review", True)], [recorded("review", True), recorded("review")]):
        result = score(example, execution)
        assert result["status"] == "fail" and result["match_percent"] == 0.0
        assert result["paused_ask_first_steps"] == example[:1]
        assert result["missed_ask_first_steps"] == example[1:]
    result = score(example, [recorded("review", True), recorded("review", True)])
    assert result["status"] == "pass" and result["match_percent"] == 100.0
    assert result["paused_ask_first_steps"] == example


def test_FR_SKL_03_read_only_deterministic_result_does_not_alias_inputs() -> None:
    example, execution = [taught("review", True)], [recorded("review", True)]
    before = copy.deepcopy((example, execution))
    score = scorer()
    result = score(example, execution)
    assert score(example, execution) == result
    assert (example, execution) == before
    result["matched_steps"][0]["object"] = "changed"
    assert (example, execution) == before


def test_FR_SKL_03_object_identity_is_case_sensitive() -> None:
    result = scorer()([taught("read", target="FileA")], [recorded("read", target="filea")])
    assert result["match_percent"] == 0.0
    assert result["skipped_steps"] == [taught("read", target="FileA")]
    assert result["added_steps"] == [recorded("read", target="filea")]
