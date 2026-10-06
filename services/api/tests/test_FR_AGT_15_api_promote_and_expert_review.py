"""FR-AGT-15 (Should; PRD 8.2 "Teaching", 10.5 "Promote to skill") at the API: a Team Lead promotes their answer, the
proposal appears for expert review with a diff, an expert approves or rejects it.

Acceptance: "The proposal appears for expert review with a diff."

In-process FastAPI app over `tilo_api.skill_proposals.build_router(proposals, owner_of=)`, the real harness
`SkillProposals` on a tmp_path skills tree, a Decision double, injected principals and Team Lead records. No network, no
model, no cloud. Shapes and routes: API_FR_AGT_15.md. The security half (who may do what, what text may do) is in
test_FR_AGT_15_api_security.py.
"""

from __future__ import annotations

from _agt15_api_lib import (
    BODY,
    DECISION_ID,
    DOMAIN,
    EXPERT_B,
    LEAD_A,
    LEAD_SEC,
    SAFE_ID,
    SKILL_ID,
    W,
    client,
    make_proposals,
    principal,
    promote,
    tree_snapshot,
    url,
    write_skill,
)


def _setup(tmp_path):
    root = tmp_path / "skills"
    write_skill(root)
    return root, make_proposals(root)


def test_FR_AGT_15_api_promoted_answer_appears_for_expert_review_with_a_diff(tmp_path) -> None:
    root, proposals = _setup(tmp_path)
    before = tree_snapshot(root)

    created = promote(client(proposals, principal("team_lead", LEAD_A)), guidance="Flag sources older than 12 months.")

    assert created.status_code == 201, created.text
    made = created.json()["proposal"]
    assert made["status"] == "proposed" and SAFE_ID.match(made["id"])
    # the expert (another Team Lead of the same domain) sees it in their review list, with the diff and provenance
    expert = client(proposals, principal("team_lead", EXPERT_B))
    listed = expert.get(url())
    assert listed.status_code == 200, listed.text
    (shown,) = listed.json()["proposals"]
    assert shown["id"] == made["id"] and shown["status"] == "proposed"
    assert shown["skill_id"] == SKILL_ID and shown["domain"] == DOMAIN
    assert shown["diff"].startswith("--- ") and "\n+Flag sources older than 12 months." in shown["diff"]
    assert shown["from_version"] == "1.0.0" and shown["to_version"] != "1.0.0"
    prov = shown["provenance"]
    assert (prov["decision_id"], prov["team_lead"], prov["team_lead_user"]) == (DECISION_ID, "tl_research", LEAD_A)
    assert (prov["world_id"], prov["run_id"], prov["proposed_by"]) == (W, "r_village_basic_1", LEAD_A)
    one = expert.get(url(f"/{made['id']}"))
    assert one.status_code == 200 and one.json()["proposal"] == shown
    assert tree_snapshot(root) == before, "appearing for review changes nothing in the skill store"


def test_FR_AGT_15_api_the_proposer_sees_their_own_proposal_and_its_status(tmp_path) -> None:
    root, proposals = _setup(tmp_path)
    lead = client(proposals, principal("team_lead", LEAD_A))
    made = promote(lead).json()["proposal"]

    mine = lead.get(url())

    assert mine.status_code == 200
    assert [p["id"] for p in mine.json()["proposals"]] == [made["id"]]
    assert lead.get(url(f"/{made['id']}")).json()["proposal"]["status"] == "proposed"


def test_FR_AGT_15_api_an_expert_approves_and_only_then_the_skill_changes(tmp_path) -> None:
    root, proposals = _setup(tmp_path)
    made = promote(
        client(proposals, principal("team_lead", LEAD_A)), guidance="Flag sources older than 12 months."
    ).json()["proposal"]
    before = tree_snapshot(root)  # the state after proposing: still the old skill

    response = client(proposals, principal("team_lead", EXPERT_B)).post(url(f"/{made['id']}/approve"), json={})

    assert response.status_code == 200, response.text
    approved = response.json()["proposal"]
    assert approved["status"] == "approved" and approved["reviewed_by"] == EXPERT_B
    after = tree_snapshot(root)
    assert after != before
    body = (root / DOMAIN / SKILL_ID / "SKILL.md").read_text(encoding="utf-8")
    assert body.startswith(BODY) and "Flag sources older than 12 months." in body
    assert body == approved["proposed_body"]
    # the status is the stored one, not a response artefact
    assert (
        client(proposals, principal("team_lead", EXPERT_B)).get(url(f"/{made['id']}")).json()["proposal"]["status"]
        == "approved"
    )


def test_FR_AGT_15_api_an_expert_rejects_and_the_skill_stays(tmp_path) -> None:
    root, proposals = _setup(tmp_path)
    made = promote(client(proposals, principal("team_lead", LEAD_A))).json()["proposal"]
    before = tree_snapshot(root)
    expert = client(proposals, principal("team_lead", EXPERT_B))

    response = expert.post(url(f"/{made['id']}/reject"), json={"reason": "Too strict for blogs."})

    assert response.status_code == 200, response.text
    assert response.json()["proposal"]["status"] == "rejected"
    assert tree_snapshot(root) == before
    again = expert.post(url(f"/{made['id']}/approve"), json={})
    assert 400 <= again.status_code < 500, "a rejected proposal can never be approved afterwards"
    assert tree_snapshot(root) == before


def test_FR_AGT_15_api_a_second_approval_is_refused_and_applies_nothing_more(tmp_path) -> None:
    root, proposals = _setup(tmp_path)
    made = promote(client(proposals, principal("team_lead", LEAD_A))).json()["proposal"]
    expert = client(proposals, principal("team_lead", EXPERT_B))
    assert expert.post(url(f"/{made['id']}/approve"), json={}).status_code == 200
    after_first = tree_snapshot(root)

    second = expert.post(url(f"/{made['id']}/approve"), json={})

    assert 400 <= second.status_code < 500 and "error" in second.json()
    assert tree_snapshot(root) == after_first


def test_FR_AGT_15_api_the_review_list_holds_only_the_experts_own_domain(tmp_path) -> None:
    root, proposals = _setup(tmp_path)
    made = promote(client(proposals, principal("team_lead", LEAD_A))).json()["proposal"]
    security = client(proposals, principal("team_lead", LEAD_SEC))

    listed = security.get(url())

    assert listed.status_code == 200 and listed.json()["proposals"] == []
    hidden = security.get(url(f"/{made['id']}"))
    assert hidden.status_code == 404, "no existence oracle for another domain's proposal"


def test_FR_AGT_15_api_a_proposal_for_a_promoted_answer_of_another_world_is_not_found(tmp_path) -> None:
    from _agt15_api_lib import FakeDecisions, decision

    root, proposals = _setup(tmp_path)
    before = tree_snapshot(root)
    foreign = FakeDecisions(decision(world_id="w_some_other_world"))

    response = promote(client(proposals, principal("team_lead", LEAD_A), decisions=foreign))

    assert response.status_code == 404
    assert tree_snapshot(root) == before
    assert client(proposals, principal("team_lead", LEAD_A)).get(url()).json() == {"proposals": []}


def test_FR_AGT_15_api_unknown_decision_and_unknown_skill_are_not_found(tmp_path) -> None:
    root, proposals = _setup(tmp_path)
    lead = client(proposals, principal("team_lead", LEAD_A))

    assert lead.post(url(), json={"decision_id": "01J8Z3K4M5N6P7Q8R9S0T1V2ZZ", "skill_id": SKILL_ID}).status_code in (
        404,
        422,
    )
    assert lead.post(url(), json={"decision_id": DECISION_ID, "skill_id": "no_such_skill"}).status_code == 404
    assert lead.get(url()).json() == {"proposals": []}
