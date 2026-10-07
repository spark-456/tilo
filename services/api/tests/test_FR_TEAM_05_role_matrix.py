"""FR-TEAM-05: the 8 x 4 role matrix the Team page shows is the rules the engine enforces (config/team_rules.yaml
`capabilities`, read by tilo_api.team_rules). Where the engine has an enforcement point the test drives it."""

import pytest
from tilo_api.team_rules import ROLES, load_capabilities, role_can, set_switch

AT = "2026-10-08T10:00:00.000Z"


def test_FR_TEAM_05_matrix_is_eight_capabilities_by_four_roles():
    caps = load_capabilities()
    assert len(caps) == 8
    assert all(set(c.roles) <= set(ROLES) for c in caps.values())
    assert len(ROLES) == 4


def test_FR_TEAM_05_only_the_owner_changes_tool_access_and_invites():
    for key in ("change_tool_access", "invite_people"):
        assert [r for r in ROLES if role_can(r, key)] == ["Owner"]


def test_FR_TEAM_05_set_switch_tools_follows_the_matrix_for_every_role():
    state = {"tools": True}
    for role in ROLES:
        if role_can(role, "change_tool_access"):
            assert set_switch(state, "tools", False, actor="u", actor_role=role, at=AT)[0]["tools"] is False
        else:
            with pytest.raises(PermissionError):
                set_switch(state, "tools", False, actor="u", actor_role=role, at=AT)


def test_FR_TEAM_05_unknown_role_or_capability_is_refused():
    with pytest.raises(KeyError):
        role_can("Owner", "nope")
    assert role_can("Nobody", "see_the_ledger") is False
