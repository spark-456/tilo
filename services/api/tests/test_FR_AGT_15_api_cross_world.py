"""FR-AGT-15, worlds are separate: a Team Lead of the same domain slug in ANOTHER world (another owner) must not list,
read, approve or reject world W's proposal, and nothing of W's skill may change (security review, blocking 1).
"""

from __future__ import annotations

import pytest
from _agt15_api_lib import (
    ASSIGNED,
    DOMAIN,
    LEAD_A,
    OWNER,
    SKILL_ID,
    TEAM_LEADS,
    W,
    client,
    make_proposals,
    principal,
    tree_snapshot,
    url,
    write_skill,
)
from _agt15_api_lib import decision as make_decision
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tilo_api import deps

W2 = "w_other_world"
OWNER2 = "u_owner_two"
LEAD_X = "u_lead_x"  # a Team Lead of `research` assigned by the OTHER world's owner
OWNERS = {W: OWNER, W2: OWNER2}
RECORDS = [
    *TEAM_LEADS,
    {"id": "tl_research_x", "user": LEAD_X, "domain": DOMAIN, "assigned_by": {"by": OWNER2, "at": ASSIGNED["at"]}},
]


def _two_world_client(proposals, who):
    import tilo_api.console as console
    import tilo_api.skill_proposals as skill_proposals

    app = FastAPI()
    app.include_router(skill_proposals.build_router(proposals, owner_of=OWNERS.get))
    app.dependency_overrides[deps.get_current_principal] = lambda: who
    app.dependency_overrides[console.get_team_leads] = lambda: list(RECORDS)
    return TestClient(app)


def _setup(tmp_path):
    root = tmp_path / "skills"
    write_skill(root)
    proposals = make_proposals(root)
    made = proposals.propose(decision=make_decision(), skill_id=SKILL_ID, proposer=LEAD_A)
    return root, proposals, made


@pytest.mark.parametrize("route", ["approve", "reject"])
def test_FR_AGT_15_api_a_same_domain_lead_of_another_world_cannot_read_or_decide_the_proposal(tmp_path, route) -> None:
    root, proposals, made = _setup(tmp_path)
    before = tree_snapshot(root)
    other = _two_world_client(proposals, principal("team_lead", LEAD_X, world_id=W2))

    listed = other.get(url(world=W2))
    assert listed.status_code == 200 and listed.json() == {"proposals": []}, "W's proposal is not in W2's list"
    assert other.get(url(f"/{made['id']}", world=W2)).status_code == 404
    decided = other.post(url(f"/{made['id']}/{route}", world=W2), json={})
    assert decided.status_code == 404, decided.text
    assert tree_snapshot(root) == before, "a Team Lead of another world must not change this world's skill"
    assert proposals.get(made["id"])["status"] == "proposed"


def test_FR_AGT_15_api_the_owning_worlds_expert_still_works_beside_the_other_world(tmp_path) -> None:
    root, proposals, made = _setup(tmp_path)
    expert = _two_world_client(proposals, principal("team_lead", "u_expert_b", world_id=W))

    assert [p["id"] for p in expert.get(url()).json()["proposals"]] == [made["id"]]
    assert expert.post(url(f"/{made['id']}/approve"), json={}).status_code == 200
    assert tree_snapshot(root) != {}


def test_FR_AGT_15_api_a_lead_of_the_other_world_cannot_reach_it_through_their_own_world_path_either(tmp_path) -> None:
    root, proposals, made = _setup(tmp_path)
    before = tree_snapshot(root)
    other = client(
        proposals, principal("team_lead", LEAD_X, world_id=W)
    )  # claims membership of W: no W record for them

    assert other.post(url(f"/{made['id']}/approve"), json={}).status_code in (403, 404)
    assert tree_snapshot(root) == before
