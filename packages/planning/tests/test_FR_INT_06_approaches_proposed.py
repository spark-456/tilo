"""FR-INT-06 (PRD 7.1): "2-3 approaches that differ on at least 2 of 5 dimensions (depth,
sources, parallelism, verification, output format), each with time range, credit range, risks
and what it skips." Acceptance test: "Deterministic distinctness check passes on 100% of eval
tasks." Cross-reference rules (plan.rules.md): PG-08 (distinctness), PG-09 (ranges ordered),
PG-12 (2 to 3 approaches).

Design (this ticket -- `tilo_planning.approaches` does not exist yet): the Director role proposes
raw approach candidates through `tilo_providers.router.Router` (canned fixture outputs only,
PL-01/EFF-01), each candidate already shaped like `plan.schema.json#/$defs/approach` (id, label,
summary, dimensions, time, credits, risks, skips) -- the same shape as the real PlanGraph fixture
`contracts/fixtures/plan/valid/three_approaches_policy_gate.json`. Whether the set is pairwise
distinct is a deterministic code check, `check_distinct` (PG-08: every pair differs on >= 2 of
the 5 `dimensions` keys), never the model's job. A candidate set that fails distinctness is
repaired or rejected in code -- never returned as-is (ticket brief). Both paths are scripted: a
Director that repeats the indistinct pair after the one PG-08 repair call is rejected with
`ApproachProposalError` (two provider calls, not router exhaustion); one that answers with a distinct
set on the repair call is returned.

Public interface (this ticket's own design, from the PRD 7.1 FR-INT-06 row plus
`contracts/plan.schema.json` and `contracts/plan.rules.md` PG-08/PG-09):
`tilo_planning.approaches.propose_approaches`, `.check_distinct`, `.ApproachProposalError`,
`.ApproachesResult`.
"""

from __future__ import annotations

import json

import pytest
from _planning_contracts_lib import (
    ScriptedCall,
    ScriptedModelProvider,
    assert_valid_approach,
    assert_valid_event,
    build_test_router,
    load_approaches_fixture,
    load_brief_fixture,
    sample_event_base,
)
from tilo_planning.approaches import ApproachProposalError, check_distinct, propose_approaches
from tilo_planning.brief import complete_brief


def _brief() -> dict:
    return complete_brief(load_brief_fixture("valid_market_scan"))


def _router(tmp_path, payload: dict):
    provider = ScriptedModelProvider("large", [ScriptedCall(text=json.dumps(payload))])
    return build_test_router(tmp_path, provider)


def test_FR_INT_06_two_to_three_distinct_approaches_proposed_from_brief(tmp_path, repo_root, registry):
    payload = load_approaches_fixture("distinct_three")
    router = _router(tmp_path, payload)

    result = propose_approaches(_brief(), router=router, base=sample_event_base(), seq=2)

    assert 2 <= len(result.approaches) <= 3, "FR-INT-06/PG-12: 2 to 3 approaches"
    for approach in result.approaches:
        assert_valid_approach(repo_root, registry, approach)
        assert approach["time"]["min_s"] <= approach["time"]["max_s"], "PG-09: time range ordered"
        assert approach["credits"]["min"] <= approach["credits"]["max"], "PG-09: credit range ordered"
        assert "risks" in approach and "skips" in approach

    assert check_distinct(result.approaches), "PG-08: every pair must differ on >= 2 of 5 dimensions"

    assert result.event is not None
    assert result.event["type"] == "plan.approaches_proposed"
    assert result.event["data"]["approach_count"] == len(result.approaches)
    assert_valid_event(repo_root, registry, result.event)


def test_FR_INT_06_check_distinct_requires_at_least_two_of_five_dimensions_to_differ():
    base_dims = {
        "depth": "standard",
        "sources": 5,
        "parallelism": 2,
        "verification": "standard",
        "output_format": "pdf",
    }
    identical = {**base_dims}
    one_dim_different = {**base_dims, "output_format": "docx"}
    two_dims_different = {**base_dims, "output_format": "docx", "depth": "deep"}

    def _approach(dims: dict) -> dict:
        return {
            "id": "x",
            "label": "X",
            "summary": "x",
            "dimensions": dims,
            "time": {"min_s": 1, "max_s": 2},
            "credits": {"min": 1, "max": 2},
            "risks": [],
            "skips": [],
        }

    assert check_distinct([_approach(base_dims), _approach(identical)]) is False
    assert check_distinct([_approach(base_dims), _approach(one_dim_different)]) is False
    assert check_distinct([_approach(base_dims), _approach(two_dims_different)]) is True


def test_FR_INT_06_indistinct_candidate_pair_is_repaired_or_rejected_never_returned_as_is(
    tmp_path, repo_root, registry
):
    payload = load_approaches_fixture("indistinct_pair")  # differs on 1 of 5 dimensions only
    # The Director repeats the same indistinct set when asked once more: the PG-08 repair path runs, then rejects.
    reply = ScriptedCall(text=json.dumps(payload))
    provider = ScriptedModelProvider("large", [reply, reply])
    router = build_test_router(tmp_path, provider)

    with pytest.raises(ApproachProposalError, match="still break the rules after one repair"):
        propose_approaches(_brief(), router=router, base=sample_event_base(), seq=2)

    assert len(provider.calls) == 2, "FR-INT-06: one proposal, then exactly one repair call (PG-08)"
    assert "PG-08: a and b differ on 1 of 5 dimensions" in provider.calls[1].prompt, "the repair names the problem"


def test_FR_INT_06_indistinct_candidate_pair_is_repaired_when_the_second_reply_is_distinct(
    tmp_path, repo_root, registry
):
    first = load_approaches_fixture("indistinct_pair")
    second = load_approaches_fixture("distinct_three")
    provider = ScriptedModelProvider(
        "large", [ScriptedCall(text=json.dumps(first)), ScriptedCall(text=json.dumps(second))]
    )

    result = propose_approaches(_brief(), router=build_test_router(tmp_path, provider), base=sample_event_base(), seq=2)

    assert len(provider.calls) == 2 and len(result.runs) == 2, "the repair is recorded as a second run"
    assert check_distinct(result.approaches), "PG-08: a returned set is pairwise distinct"
    for approach in result.approaches:
        assert_valid_approach(repo_root, registry, approach)
