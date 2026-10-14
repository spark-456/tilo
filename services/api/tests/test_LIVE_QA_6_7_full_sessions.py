"""QA-6/7: full sign-in access uses stored authority; links remain world-bound."""

import pytest
from _agt15_api_lib import EXPERT_B, LEAD_A, OWNER, SKILL_ID, client, decision, make_proposals, url, write_skill
from _mroom_a1_lib import make_env
from tilo_api import app, deps


@pytest.mark.parametrize("world_id", [None, "w_other"])
def test_QA_6_full_owner_reads_world_proposals_without_expert_write_authority(tmp_path, world_id):
    root = tmp_path / "skills"
    write_skill(root)
    proposals = make_proposals(root)
    made = proposals.propose(decision=decision(), skill_id=SKILL_ID, proposer=LEAD_A)
    who = deps.Principal(OWNER, "owner", world_id, full_session=True)
    signed_in = client(proposals, who)
    assert signed_in.get(url()).json() == {"proposals": [made]}
    assert signed_in.get(url(f"/{made['id']}")).status_code == 200
    assert signed_in.post(url(f"/{made['id']}/approve"), json={}).status_code == 403
    assert proposals.get(made["id"])["status"] == "proposed"


def test_QA_6_full_expert_uses_current_owner_assignment(tmp_path):
    root = tmp_path / "skills"
    write_skill(root)
    proposals = make_proposals(root)
    made = proposals.propose(decision=decision(), skill_id=SKILL_ID, proposer=LEAD_A)
    who = deps.Principal(EXPERT_B, "owner", None, full_session=True)
    signed_in = client(proposals, who)
    assert signed_in.get(url()).status_code == 200
    assert signed_in.post(url(f"/{made['id']}/approve"), json={}).status_code == 200
    assert client(proposals, who, team_leads=[]).get(url()).status_code == 404


@pytest.mark.parametrize(
    "who",
    [
        deps.Principal("u_stranger", "owner", None, full_session=True),
        deps.Principal(OWNER, "owner", "w_other"),
        deps.Principal(OWNER, "owner", None, full_session=True, demo_session=True),
        deps.Principal(OWNER, "owner", None, channel="email", full_session=True),
    ],
)
def test_QA_6_other_user_link_demo_and_email_crossworld_are_404(tmp_path, who):
    root = tmp_path / "skills"
    write_skill(root)
    assert client(make_proposals(root), who).get(url()).status_code == 404


@pytest.mark.parametrize("world_id", [None, "w_other"])
def test_QA_7_full_owner_can_convene_read_and_adjourn(tmp_path, world_id):
    env = make_env(tmp_path)
    app.dependency_overrides[deps.get_current_principal] = lambda: deps.Principal(
        OWNER, "owner", world_id, full_session=True
    )
    room = env.convene()
    assert room.status_code == 201
    room_id = room.json()["room_id"]
    assert env.get(room_id).status_code == 200
    assert env.adjourn(room_id).status_code == 200


def test_QA_7_full_team_member_uses_current_team_role(tmp_path):
    env = make_env(tmp_path, team_roles={"u_mem": "Member"})
    who = deps.Principal("u_mem", "owner", None, districts=("D1",), full_session=True)
    app.dependency_overrides[deps.get_current_principal] = lambda: who
    assert env.convene().status_code == 201
    assert env.convene(lead="A_dir", agents=["A_l1"]).status_code == 403


@pytest.mark.parametrize(
    "who",
    [
        deps.Principal("u_stranger", "owner", None, full_session=True),
        deps.Principal(OWNER, "owner", "w_other"),
        deps.Principal(OWNER, "owner", None, full_session=True, demo_session=True),
        deps.Principal(OWNER, "owner", None, channel="email", full_session=True),
    ],
)
def test_QA_7_other_user_link_demo_and_email_crossworld_are_404(tmp_path, who):
    env = make_env(tmp_path)
    room_id = env.convene().json()["room_id"]
    app.dependency_overrides[deps.get_current_principal] = lambda: who
    assert env.get(room_id).status_code == 404
    assert env.convene().status_code == 404
