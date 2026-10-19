"""FR-INT-15 (supplement 2026-10-05 section 4, "Best effort before refusal"): "A safe request outside what Tilo can
fully do gets best effort first: it does what it can, says plainly what it could not do and offers alternatives. A
hard refusal is only for safety or policy (FR-INT-12)." Acceptance: "Eval: 20 partly-out-of-scope briefs each deliver
the possible part and name the rest; 0 hard refusals among them."

The eval: `fixtures/best_effort_set.yaml` (20 partly-out-of-scope cases, plus refusal and no-possible-part controls)
run through the real `extract_brief`, `propose_approaches` and `compile_plan` behind a real `Router` over a scripted
Director (EFF-01: no paid call, no network, no LIVE). "Deliver the possible part" = the brief is unchanged and a valid
PlanGraph is compiled for it. "Name the rest" = every gap is on `ExtractionResult.gaps` with its configured reason and
alternative and is the first line of every approach's `skips` ("Not done: {part}. {reason}"), also in the delivered
plan. "0 hard refusals" = no `TaskRefused`, no refusal category. Interface: `API_FR_INT_15.md`; the HTTP side is
`services/api/tests/test_FR_INT_15_intake_gaps.py`.
"""

from __future__ import annotations

import pytest
from _fr_int_15_lib import (
    CAP,
    GAP_IDS,
    OWNER,
    REFUSAL_IDS,
    StageDirector,
    case_reply,
    load_best_effort_set,
    make_router,
)
from _plan_validator_lib import build_fake_connectors, build_fake_policies, build_risk_table
from _planning_contracts_lib import assert_valid_brief, sample_event_base
from tilo_planning.approaches import propose_approaches
from tilo_planning.brief import extract_brief
from tilo_planning.compiler import PlanInputs, compile_plan
from tilo_planning.plangraph import validate_plan


def modules():
    import tilo_planning.gaps as gaps  # noqa: PLC0415
    import tilo_planning.refusal as refusal  # noqa: PLC0415

    return gaps, refusal


def config_texts():
    gaps, _ = modules()
    return {c.id: (c.reason, c.alternative) for c in gaps.load_gap_policy().categories}


def line(gap) -> str:
    return gap.skip_line()


def director_for(cases: list[dict]) -> StageDirector:
    return StageDirector({case["task"]: case_reply(case) for case in cases})


def plan_inputs(approaches: list[dict]) -> PlanInputs:
    return PlanInputs(
        approaches=approaches,
        owner=OWNER,
        skills={},
        connectors=build_fake_connectors(),
        risk_table=build_risk_table(),
        policies=build_fake_policies(),
    )


# --- the fixture itself: the pinned spread of the 20 ---


def test_FR_INT_15_the_best_effort_set_has_the_pinned_spread():
    data = load_best_effort_set()
    cases = data["partly_out_of_scope"]

    assert [c["id"] for c in cases] == [f"BE-{n:02d}" for n in range(1, 21)], "exactly 20 cases, BE-01..BE-20"
    assert all(1 <= len(c["deliverables"]) <= 3 and 1 <= len(c["gaps"]) <= 3 for c in cases)
    assert all(g["category"] in GAP_IDS for c in cases for g in c["gaps"])
    for gap_id in GAP_IDS:
        assert sum(any(g["category"] == gap_id for g in c["gaps"]) for c in cases) >= 2, f"{gap_id} in under 2 cases"
    assert sum(len(c["gaps"]) >= 2 for c in cases) >= 5
    assert sum(len(c["gaps"]) == 3 for c in cases) >= 2
    assert any(len({g["category"] for g in c["gaps"]}) < len(c["gaps"]) for c in cases), "a repeated category"
    assert any(len(g["part"]) == 60 for c in cases for g in c["gaps"]), "one part is exactly 60 characters"
    assert all(len(g["part"]) <= 60 for c in cases for g in c["gaps"])
    assert len({d["format"] for c in cases for d in c["deliverables"]}) >= 4
    tasks = [c["task"] for g in data.values() for c in g]
    assert len(set(tasks)) == len(tasks) and not any(a != b and a in b for a in tasks for b in tasks)

    refuse, nothing = data["must_refuse"], data["nothing_possible"]
    assert len(refuse) >= 6 and [c["id"] for c in refuse] == [f"BR-{n:02d}" for n in range(1, len(refuse) + 1)]
    assert len(nothing) >= 2 and [c["id"] for c in nothing] == [f"BN-{n:02d}" for n in range(1, len(nothing) + 1)]
    assert all(c["expect"] in REFUSAL_IDS for c in refuse)
    assert sum(c["out_of_policy"] is not None and all(g["category"] in GAP_IDS for g in c["gaps"]) for c in refuse) >= 2
    assert sum(c["out_of_policy"] is None and c["gaps"][0]["category"] in REFUSAL_IDS for c in refuse) >= 1
    assert (
        sum(
            c["out_of_policy"] is None and len(c["gaps"]) > 3 and c["gaps"][3]["category"] in REFUSAL_IDS
            for c in refuse
        )
        >= 1
    ), "a refusal id after three valid gaps"
    assert any(c["out_of_policy"] is not None and any(g["category"] in REFUSAL_IDS for g in c["gaps"]) for c in refuse)


# --- the acceptance: 20 delivered, 0 hard refusals ---


def test_FR_INT_15_each_of_20_partly_out_of_scope_briefs_delivers_the_possible_part_and_names_the_rest(
    repo_root, registry
):
    gaps_module, refusal = modules()
    cases = load_best_effort_set()["partly_out_of_scope"]
    assert len(cases) == 20
    texts = config_texts()
    director = director_for(cases)
    router = make_router(director)
    delivered = hard_refusals = 0

    for case in cases:
        label = case["id"]
        try:
            result = extract_brief(case["task"], router=router)
        except refusal.TaskRefused:
            hard_refusals += 1
            continue
        want = [(g["category"], g["part"]) for g in case["gaps"]]

        # 1. the possible part is the brief; every gap is named, with configured text only
        assert [(g.category, g.part) for g in result.gaps] == want, label
        for g in result.gaps:
            assert (g.reason, g.alternative) == texts[g.category], label
        assert_valid_brief(repo_root, registry, result.brief)
        assert "out_of_scope" not in result.brief and "out_of_policy" not in result.brief, label
        assert result.brief["deliverables"] == case["deliverables"], label

        # 2. every approach starts with the gap lines, in order
        approaches = propose_approaches(result.brief, router=router, base=sample_event_base(), seq=2, gaps=result.gaps)
        n = len(result.gaps)
        for approach in approaches.approaches:
            assert approach["skips"][:n] == [line(g) for g in result.gaps], label
            assert len(approach["skips"]) <= 5, label
            assert all(s.startswith("Not done: ") for s in approach["skips"][:n]), label

        # 3. a valid plan is compiled for the possible part and still names the rest
        inputs = plan_inputs(approaches.approaches)
        plan = compile_plan(result.brief, inputs.approaches[0], CAP, inputs, router=router).plan
        assert (
            validate_plan(
                plan,
                risk_table=inputs.risk_table,
                connectors=inputs.connectors,
                skills=frozenset(),
                policies=inputs.policies,
                owner=OWNER,
            )  # fmt: skip
            == []
        ), label
        assert plan["units"][-1]["unit_type"] == "deliver", label
        for approach in plan["approaches"]:
            assert approach["skips"][:n] == [line(g) for g in result.gaps], label
        delivered += 1

    assert hard_refusals == 0, f"{hard_refusals} hard refusals among the 20"
    assert delivered == 20, f"{delivered} of 20 delivered"


def test_FR_INT_15_a_partly_out_of_scope_brief_is_never_a_refusal_nor_carries_a_category():
    gaps_module, refusal = modules()
    cases = load_best_effort_set()["partly_out_of_scope"]
    router = make_router(director_for(cases))

    for case in cases:
        try:
            result = extract_brief(case["task"], router=router)
        except Exception as exc:  # noqa: BLE001
            pytest.fail(f"{case['id']}: {type(exc).__name__}")
        assert result.gaps, case["id"]
        assert not any(g.category in REFUSAL_IDS for g in result.gaps), case["id"]
        assert "category" not in result.brief, case["id"]


def test_FR_INT_15_the_possible_part_is_the_brief_the_model_wrote_unchanged():
    cases = load_best_effort_set()["partly_out_of_scope"]
    director = director_for(cases)
    router = make_router(director)

    for case in cases:
        result = extract_brief(case["task"], router=router)
        want = case_reply(case)
        assert result.brief["goal"] == want["goal"], case["id"]
        assert result.brief["deliverables"] == want["deliverables"], case["id"]
        assert result.brief["audience"] == want["audience"], case["id"]
        assert result.ambiguous_fields == want["ambiguous_fields"], case["id"]


def test_FR_INT_15_the_person_reads_only_configured_text_beside_the_cleaned_label():
    """The model names a part; the words about what Tilo cannot do are code and config (PRD 16.3, BQ-INT15-6)."""
    cases = load_best_effort_set()["partly_out_of_scope"]
    router = make_router(director_for(cases))
    texts = config_texts()

    for case in cases:
        result = extract_brief(case["task"], router=router)
        for g in result.gaps:
            reason, alternative = texts[g.category]
            assert g.skip_line() == f"Not done: {g.part}. {reason}", case["id"]
            assert g.as_dict() == {
                "category": g.category, "part": g.part, "reason": reason, "alternative": alternative,
            }, case["id"]  # fmt: skip
            assert list(g.as_dict()) == ["category", "part", "reason", "alternative"]
            assert len(g.skip_line()) <= 200, case["id"]
            assert alternative.strip() and alternative != reason, "an alternative is offered for every gap"


def test_FR_INT_15_best_effort_costs_no_extra_model_call():
    """Gaps ride on the existing brief call (EFF): a gap task makes the same three calls as a task with none."""
    cases = load_best_effort_set()["partly_out_of_scope"]
    plain = "Prepare the weekly supplier summary for the Linden operations lead."
    director = StageDirector({case["task"]: case_reply(case) for case in cases}, default=case_reply(cases[0]))
    director.briefs[plain] = {**case_reply(cases[0]), "out_of_scope": []}

    def flow(task: str) -> list[str]:
        director.calls.clear()
        router = make_router(director)
        result = extract_brief(task, router=router)
        approaches = propose_approaches(result.brief, router=router, base=sample_event_base(), seq=2, gaps=result.gaps)
        inputs = plan_inputs(approaches.approaches)
        compile_plan(result.brief, inputs.approaches[0], CAP, inputs, router=router)
        return director.kinds()

    assert flow(cases[0]["task"]) == ["brief", "approaches", "plan"]
    assert flow(plain) == ["brief", "approaches", "plan"]
    assert flow(cases[9]["task"]) == ["brief", "approaches", "plan"]  # three gaps: still no extra call


# --- the controls: a refusal still refuses, and nothing-possible is not a refusal ---


def test_FR_INT_15_refusal_cases_still_refuse_100_percent_with_the_configured_text():
    gaps_module, refusal = modules()
    cases = load_best_effort_set()["must_refuse"]
    policy = refusal.load_refusal_policy()
    by_id = {c.id: c for c in policy.categories}
    director = StageDirector(
        {case["task"]: case_reply(case, deliverables=[{"title": "Summary", "format": "pdf"}]) for case in cases}
    )
    router = make_router(director)

    refused = 0
    for case in cases:
        before = len(director.calls)
        with pytest.raises(refusal.TaskRefused) as raised:
            extract_brief(case["task"], router=router)
        want = by_id[case["expect"]]
        assert raised.value.category == want.id, case["id"]
        assert (raised.value.reason, raised.value.alternative) == (want.reason, want.alternative), case["id"]
        assert len(director.calls) == before + 1, f"{case['id']}: a refusal costs one Director call"
        refused += 1

    assert refused == len(cases) >= 6, "100% refused"


def test_FR_INT_15_a_mixed_safe_and_unsafe_task_is_refused_in_full_never_partly_run():
    """BQ-INT15-3: a refusal id anywhere wins over the safe part; FR-INT-12's '100% refused' holds only if no refused
    task partly runs. The safe part has a deliverable and valid gaps, and still nothing comes back but the refusal."""
    gaps_module, refusal = modules()
    cases = load_best_effort_set()["must_refuse"]
    router = make_router(
        StageDirector({c["task"]: case_reply(c, deliverables=[{"title": "Summary", "format": "pdf"}]) for c in cases})
    )

    for case in cases:
        with pytest.raises(refusal.TaskRefused):
            extract_brief(case["task"], router=router)  # no brief, no gaps, no NothingPossible


def test_FR_INT_15_a_task_with_no_possible_part_is_nothing_possible_not_a_refusal_after_one_call():
    gaps_module, refusal = modules()
    cases = load_best_effort_set()["nothing_possible"]
    lead = gaps_module.load_gap_policy().nothing_possible
    texts = config_texts()
    director = StageDirector({case["task"]: case_reply(case, deliverables=[]) for case in cases})
    router = make_router(director)

    for case in cases:
        before = len(director.calls)
        with pytest.raises(gaps_module.NothingPossible) as raised:
            extract_brief(case["task"], router=router)

        exc = raised.value
        assert not isinstance(exc, refusal.TaskRefused), case["id"]
        assert len(director.calls) == before + 1, f"{case['id']}: the brief call only; no approaches or plan call"
        assert exc.message == lead, case["id"]
        assert [(g.category, g.part) for g in exc.gaps] == [(g["category"], g["part"]) for g in case["gaps"]], case[
            "id"
        ]
        for g in exc.gaps:
            assert (g.reason, g.alternative) == texts[g.category], case["id"]
        assert str(exc) == "nothing possible: " + ", ".join(g["category"] for g in case["gaps"]), case["id"]
        assert case["task"] not in str(exc)
