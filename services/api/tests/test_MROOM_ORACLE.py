"""MROOM-ORACLE: an org role alone must not reveal another world's existence."""

import pytest
from _api_lib import OWNER, WORLD
from _mroom_a1_lib import make_env
from tilo_api import app, deps


@pytest.mark.parametrize("world_id", [None, "w_other"])
@pytest.mark.parametrize(
    ("team_role", "districts"),
    [("Member", ()), ("Member", ("D_other",)), ("Approver", ("D_other",)), (None, ("D1",))],
)
def test_MROOM_ORACLE_unrelated_org_member_matches_stranger_on_every_route(tmp_path, world_id, team_role, districts):
    env = make_env(tmp_path, team_roles={"u_org": team_role} if team_role else {})
    room = env.convene().json()["room_id"]
    before = list(env.store.events[WORLD])
    body = {"lead": "A_l1", "agents": ["A_s1"]}
    routes = [
        ("POST", "", body),
        ("GET", f"/{room}", None),
        ("POST", f"/{room}/turns", {"to": "A_s1", "text": "What did you do?", "mode": "quick"}),
        ("POST", f"/{room}/adjourn", None),
    ]
    for method, suffix, payload in routes:
        responses = []
        for user in ("u_stranger", "u_org"):
            principal = deps.Principal(user, "approver", world_id, districts=districts, full_session=True)
            app.dependency_overrides[deps.get_current_principal] = lambda p=principal: p
            for target in (WORLD, "w_unknown"):
                response = env.client.request(method, f"/v1/worlds/{target}/rooms{suffix}", json=payload)
                assert response.status_code == 404
                responses.append(response.content)
        assert len(set(responses)) == 1
    assert env.store.events[WORLD] == before
    assert env.lines.lines == {} and env.model.prompts == []


@pytest.mark.parametrize("team_role", ["Owner", "Member", "Approver"])
def test_MROOM_ORACLE_cross_world_owner_and_scoped_team_roles_still_work(tmp_path, team_role):
    env = make_env(tmp_path, team_roles={"u_team": team_role})
    principal = deps.Principal(
        OWNER if team_role == "Owner" else "u_team",
        "owner" if team_role == "Owner" else "approver",
        None,
        districts=() if team_role == "Owner" else ("D1",),
        full_session=True,
    )
    app.dependency_overrides[deps.get_current_principal] = lambda: principal
    created = env.convene()
    assert created.status_code == 201
    assert created.json()["as_role"] == team_role.lower()
    room = created.json()["room_id"]
    assert env.get(room).status_code == 200
    assert env.ask(room).status_code == 202
    assert env.adjourn(room).status_code == 200
