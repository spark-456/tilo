"""GEN-06: visual teams are planned from configuration, with one bounded revision."""

import copy

import pytest
from tilo_planning.compiler import _with_deliver
from tilo_planning.deliverable_teams import with_design_team


def unit(ident="U1", kind="research", role="specialist", deps=()):
    return dict(
        id=ident,
        unit_type=kind,
        title="Evidence",
        role=role,
        district="D1",
        skills=[],
        connectors=[],
        actions=[],
        depends_on=list(deps),
    )


@pytest.mark.parametrize("fmt", ["pptx", "docx", "landing", "app"])
def test_GEN_06_visual_plan_has_two_designers_review_and_one_revision(fmt):
    brief = {"deliverables": [{"format": fmt, "title": "Finished work"}]}
    original = [unit()]
    before = copy.deepcopy(original)
    plan = with_design_team(_with_deliver(original, brief), brief)
    design = [u for u in plan if u["unit_type"].startswith("design_")]
    assert [u["unit_type"] for u in design] == [
        "design_layout",
        "design_content",
        "design_review",
        "design_revise_layout",
        "design_revise_content",
    ]
    assert [u["role"] for u in design] == ["specialist", "specialist", "verifier", "specialist", "specialist"]
    review = design[2]
    assert review["depends_on"] == [u["id"] for u in design[:2]]
    assert all(review["id"] in u["depends_on"] for u in design[3:])
    writer = next(u for u in plan if u["unit_type"] == "deliver")
    assert all(u["id"] in writer["depends_on"] for u in design[3:])
    assert original == before
    assert len({u["id"] for u in plan}) == len(plan)
    assert with_design_team(plan, brief) == plan


def test_GEN_06_plain_outputs_keep_their_existing_team():
    brief = {"deliverables": [{"format": "csv"}]}
    plan = _with_deliver([unit()], brief)
    assert with_design_team(plan, brief) == plan
