"""FR-AGT-15 (Should; PRD 8.2 "Teaching", 10.5): "Promote a Team Lead answer into a proposed skill change."
Acceptance: "The proposal appears for expert review with a diff."

Harness level (`tilo_harness.skill_proposals.SkillProposals`, no HTTP): promoting a Team Lead's Decision makes a
proposal that carries a reviewable unified diff of the skill before and after, and its provenance (which answer, which
Team Lead, which run). The proposal is data: JSON-serialisable, shown for review, applied by nothing here (see
test_FR_AGT_15_never_applies_itself.py for that half).

Resolved ambiguities (PRD gives no shapes), logged in services/api/tests/API_FR_AGT_15.md:
- the change is a deterministic append to SKILL.md (the Team Lead's `guidance`, else the Decision's `answer`) plus a
  version bump in skill.yaml; no model drafts it (PRD 16.1: a model never decides authorisation);
- "which Lead": the Decision's `answered_by.ref` and `answered_by.user`; "which run": its `source.run_id`.
"""

from __future__ import annotations

import json
import re

from agt15_support import (
    BODY,
    CLOCK_NOW,
    LEAD_ID,
    LEAD_USER,
    SKILL_ID,
    added_lines,
    apply_diff_section,
    make_proposals,
    removed_lines,
    section_for,
    semver,
    team_lead_decision,
    write_skill,
)


def _propose(tmp_path, **kwargs):
    root = tmp_path / "skills"
    write_skill(root)
    proposals = make_proposals(root)
    decision = kwargs.pop("decision", None) or team_lead_decision()
    proposal = proposals.propose(decision=decision, skill_id=SKILL_ID, proposer=LEAD_USER, **kwargs)
    return root, proposals, decision, proposal


def test_FR_AGT_15_proposal_shows_diff_for_expert_review(tmp_path) -> None:
    root, proposals, decision, proposal = _propose(tmp_path, guidance="Flag any source older than 12 months as stale.")

    assert proposal["status"] == "proposed"
    assert proposal["skill_id"] == SKILL_ID and proposal["domain"] == "research"
    # it appears for review: the store lists it, open
    assert [p["id"] for p in proposals.list(status="proposed")] == [proposal["id"]]
    assert proposals.get(proposal["id"])["diff"] == proposal["diff"]

    diff = proposal["diff"]
    assert isinstance(diff, str) and diff.startswith("--- ") and "\n+++ " in diff and "\n@@ " in diff
    # SKILL.md: the diff turns the skill on disk now into exactly the proposed body, and shows the guidance as added
    before = (root / "research" / SKILL_ID / "SKILL.md").read_text(encoding="utf-8")
    assert before == BODY
    assert apply_diff_section(before, section_for(diff, "SKILL.md")) == proposal["proposed_body"].splitlines()
    assert "Flag any source older than 12 months as stale." in added_lines(diff)
    assert proposal["proposed_body"].startswith(before), "the expert's existing text is kept: a proposal appends"
    # skill.yaml: the version bump is in the diff too, so a reviewer sees what the pin will become
    assert semver(proposal["to_version"]) > semver(proposal["from_version"]) == (1, 0, 0)
    assert any(line.startswith("version:") and proposal["from_version"] in line for line in removed_lines(diff))
    assert any(line.startswith("version:") and proposal["to_version"] in line for line in added_lines(diff))


def test_FR_AGT_15_proposal_default_guidance_is_the_team_leads_answer(tmp_path) -> None:
    answer = "Prefer sources dated within the last 12 months."
    _, _, _, proposal = _propose(tmp_path, decision=team_lead_decision(answer=answer))

    assert proposal["guidance"] == answer
    assert answer in added_lines(proposal["diff"])
    assert answer in proposal["proposed_body"]


def test_FR_AGT_15_proposal_carries_provenance_answer_lead_and_run(tmp_path) -> None:
    decision = team_lead_decision(run_id="r_run_with_the_answer", world_id="w_world_x")
    _, _, _, proposal = _propose(tmp_path, decision=decision)

    prov = proposal["provenance"]
    assert prov["decision_id"] == decision["id"], "which answer"
    assert prov["card_id"] == decision["source"]["card_id"]
    assert (prov["team_lead"], prov["team_lead_user"]) == (LEAD_ID, LEAD_USER), "which Lead"
    assert (prov["world_id"], prov["run_id"]) == ("w_world_x", "r_run_with_the_answer"), "which run"
    assert prov["proposed_by"] == LEAD_USER
    assert prov["proposed_at"] == CLOCK_NOW, "time comes from the injected clock, never the model or the caller"


def test_FR_AGT_15_proposal_is_pinned_to_the_skill_it_was_made_against(tmp_path) -> None:
    root, _, _, proposal = _propose(tmp_path)
    from tilo_harness.skills import SkillRegistry

    loaded = SkillRegistry(root).load(SKILL_ID)
    assert proposal["from_version"] == loaded.version == "1.0.0"
    assert proposal["base_sha256"] == loaded.sha256, "approval is refused later if the skill has moved on (stale)"


def test_FR_AGT_15_proposal_is_plain_json_data_with_a_url_safe_id(tmp_path) -> None:
    _, proposals, _, proposal = _propose(tmp_path)

    assert re.fullmatch(r"[A-Za-z0-9_-]{1,64}", proposal["id"])
    assert json.loads(json.dumps(proposal)) == proposal, "stored as data: nothing in it is an object, a path or code"
    assert json.loads(json.dumps(proposals.get(proposal["id"]))) == proposals.get(proposal["id"])
    assert proposal["reviewed_by"] is None and proposal["reviewed_at"] is None


def test_FR_AGT_15_a_decision_that_is_not_a_team_leads_answer_is_not_promotable(tmp_path) -> None:
    from agt15_support import error_type, owner_decision

    root = tmp_path / "skills"
    write_skill(root)
    proposals = make_proposals(root)

    try:
        proposals.propose(decision=owner_decision(), skill_id=SKILL_ID, proposer="u_owner")
    except error_type() as error:
        assert error.reason == "not_team_lead_answer"
    else:
        raise AssertionError("an owner's answer is not a Team Lead's answer: it must not be promoted (PRD 8.2)")
    assert proposals.list() == []


def test_FR_AGT_15_only_the_lead_who_answered_may_promote_their_answer(tmp_path) -> None:
    from agt15_support import error_type

    root = tmp_path / "skills"
    write_skill(root)
    proposals = make_proposals(root)

    try:
        proposals.propose(decision=team_lead_decision(), skill_id=SKILL_ID, proposer="u_someone_else")
    except error_type() as error:
        assert error.reason == "not_the_answerer"
    else:
        raise AssertionError("promoting is the answering Team Lead's action (PRD 10.5), not anyone's")
    assert proposals.list() == []


def test_FR_AGT_15_a_proposal_for_another_domains_skill_is_refused(tmp_path) -> None:
    from agt15_support import error_type

    root = tmp_path / "skills"
    write_skill(root)
    proposals = make_proposals(root)

    try:
        proposals.propose(decision=team_lead_decision(domain="security"), skill_id=SKILL_ID, proposer=LEAD_USER)
    except error_type() as error:
        assert error.reason == "domain_mismatch"
    else:
        raise AssertionError("a security Team Lead's answer must not rewrite a research skill")
    assert proposals.list() == []


def test_FR_AGT_15_unknown_skill_or_malformed_decision_is_refused(tmp_path) -> None:
    from agt15_support import error_type

    root = tmp_path / "skills"
    write_skill(root)
    proposals = make_proposals(root)
    broken = team_lead_decision()
    del broken["answered_by"]["user"]  # decision.schema.json: a Team Lead's answer always names the person

    for decision, skill_id, reason in (
        (team_lead_decision(), "no_such_skill", "unknown_skill"),
        (broken, SKILL_ID, "invalid_decision"),
    ):
        try:
            proposals.propose(decision=decision, skill_id=skill_id, proposer=LEAD_USER)
        except error_type() as error:
            assert error.reason == reason
        else:
            raise AssertionError(f"{reason} must be refused")
    assert proposals.list() == []
