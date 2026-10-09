"""COST-FAST-2 (PRD 6.6 "deterministic first", EFF-*): an approach whose `skips` overshoot the room that FR-INT-15 gap
lines leave (5 minus the gaps) is trimmed in code, never sent back to the Director. The rule: keep the first `room`
skips of each approach in the model's own order and drop the tail. Stable, idempotent, no input mutation. Other rule
breaks (PG-07/08/09) still get their one repair call."""

from __future__ import annotations

import copy
import itertools
import json

import pytest
from _planning_contracts_lib import (
    ScriptedCall,
    ScriptedModelProvider,
    assert_valid_approach,
    build_test_router,
    load_approaches_fixture,
    load_brief_fixture,
    sample_event_base,
)
from test_FR_INT_15_approaches_and_plan_name_the_gaps import THREE, make_gaps
from tilo_planning.approaches import (
    ApproachProposalError,
    check_distinct,
    problems,
    propose_approaches,
    trim_skips,
)
from tilo_planning.brief import complete_brief


def _brief() -> dict:
    return complete_brief(load_brief_fixture("valid_market_scan"))


def _payload(name: str, skips: list[list[str]]) -> dict:
    payload = copy.deepcopy(load_approaches_fixture(name))
    for approach, listed in zip(payload["approaches"], skips, strict=False):
        approach["skips"] = listed
    return payload


def _run(tmp_path, replies: list[dict], gaps=()):
    provider = ScriptedModelProvider("large", [ScriptedCall(text=json.dumps(r)) for r in replies])
    router = build_test_router(tmp_path, provider)
    result = propose_approaches(_brief(), router=router, base=sample_event_base(), seq=2, gaps=gaps)
    return result, provider


def test_COST_FAST_2_skips_over_room_make_one_model_call_not_two(tmp_path):
    gaps = make_gaps(*THREE)  # room 2
    over = _payload("distinct_three", [["a", "b", "c", "d", "e"], ["x"], []])

    result, provider = _run(tmp_path, [over], gaps)

    assert len(provider.calls) == 1, "the old path made a second (repair) call here"
    assert len(result.runs) == 1
    lines = [g.skip_line() for g in gaps]
    assert result.approaches[0]["skips"] == [*lines, "a", "b"]
    assert result.approaches[1]["skips"] == [*lines, "x"]


def test_COST_FAST_2_trim_keeps_leading_skips_in_order_and_is_idempotent():
    approaches = _payload("distinct_three", [["a", "b", "c", "d"], ["z"], []])["approaches"]
    before = copy.deepcopy(approaches)

    once = trim_skips(approaches, 2)

    assert approaches == before, "the input is not mutated"
    assert [a["skips"] for a in once] == [["a", "b"], ["z"], []]
    assert trim_skips(once, 2) == once
    assert trim_skips(approaches, 5) == approaches, "within the room: unchanged"


def test_COST_FAST_2_same_input_gives_same_output(tmp_path):
    gaps = make_gaps(*THREE[:2])  # room 3
    over = _payload("distinct_three", [["a", "b", "c", "d", "e"], ["f", "g", "h", "i"], []])

    first, _ = _run(tmp_path / "one", [over], gaps)
    second, _ = _run(tmp_path / "two", [over], gaps)

    assert first.approaches == second.approaches


@pytest.mark.parametrize("gap_count", [0, 1, 2, 3])
def test_COST_FAST_2_trimmed_output_always_validates(tmp_path, repo_root, registry, gap_count):
    gaps = make_gaps(*THREE[:gap_count])
    room = 5 - gap_count
    for lengths in itertools.product((0, 2, 3, 5), repeat=3):
        reply = _payload("distinct_three", [[f"s{i}" for i in range(n)] for n in lengths])
        result, provider = _run(tmp_path / f"{gap_count}-{'-'.join(map(str, lengths))}", [reply], gaps)

        assert len(provider.calls) == 1, lengths
        assert 2 <= len(result.approaches) <= 3 and check_distinct(result.approaches)
        assert not problems(result.approaches), lengths
        for approach in result.approaches:
            assert_valid_approach(repo_root, registry, approach)
        for approach, n in zip(result.approaches, lengths, strict=True):
            assert len(approach["skips"]) == gap_count + min(n, room)


def test_COST_FAST_2_a_distinctness_break_still_gets_exactly_one_repair_call(tmp_path):
    gaps = make_gaps(*THREE)
    bad = _payload("indistinct_pair", [["a", "b", "c"], [], []])
    good = _payload("distinct_three", [["a", "b", "c"], [], []])

    result, provider = _run(tmp_path, [bad, good], gaps)

    assert len(provider.calls) == 2 and len(result.runs) == 2
    assert "PG-08" in provider.calls[1].prompt
    assert "skips:" not in provider.calls[1].prompt, "the repair no longer lists skips problems"
    assert all(len(a["skips"]) == 5 for a in result.approaches[:1])


def test_COST_FAST_2_a_still_broken_set_after_the_trim_and_repair_is_rejected(tmp_path):
    bad = _payload("indistinct_pair", [[], []])

    with pytest.raises(ApproachProposalError, match="still break the rules after one repair"):
        _run(tmp_path, [bad, bad])
