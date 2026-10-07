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


# ---- security review of #625: a malformed or loosened capabilities row must fail closed ----
import tilo_api.team_rules as tr  # noqa: E402

_ROW = '  - {{key: {key}, label: "L", roles: {roles}}}\n'


def _yaml(tmp_path, rows):
    p = tmp_path / "t.yaml"
    p.write_text("capabilities:\n" + "".join(_ROW.format(key=k, roles=r) for k, r in rows), encoding="utf-8")
    return p


def _full(tmp_path, tools="[Owner]", invite="[Owner]"):
    return _yaml(tmp_path, [("change_tool_access", tools), ("invite_people", invite)])


@pytest.mark.parametrize(
    "roles",
    [
        "{Owner: true, Approver: false}",
        "{Owner: yes, Approver: no}",
        '""',
        "Owner",
        "null",
        "[[Owner]]",
        "[true]",
        "[Owner, Owner]",
        "[Boss]",
        "[Owner, 1]",
    ],
)
def test_FR_TEAM_05_malformed_roles_cell_is_refused(tmp_path, roles):
    with pytest.raises(ValueError):
        load_capabilities(_full(tmp_path, tools=roles))


def test_FR_TEAM_05_key_and_label_must_be_strings(tmp_path):
    p = tmp_path / "t.yaml"
    p.write_text("capabilities:\n  - {key: 5, label: L, roles: [Owner]}\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_capabilities(p)


@pytest.mark.parametrize("key", ["change_tool_access", "invite_people"])
def test_FR_TEAM_05_owner_only_capabilities_cannot_be_granted_to_another_role(tmp_path, key):
    kw = {"tools": "[Owner, Approver]"} if key == "change_tool_access" else {"invite": "[Owner, Approver]"}
    with pytest.raises(ValueError):
        load_capabilities(_full(tmp_path, **kw))


def test_FR_TEAM_05_missing_owner_only_row_is_a_load_error(tmp_path):
    with pytest.raises(ValueError):
        load_capabilities(_yaml(tmp_path, [("invite_people", "[Owner]")]))


def test_FR_TEAM_05_set_switch_keeps_the_owner_floor_even_if_config_is_loosened(tmp_path, monkeypatch):
    p = _full(tmp_path, tools="[Owner, Approver]")
    monkeypatch.setattr(tr, "_CONFIG", p)
    with pytest.raises(ValueError):
        set_switch({"tools": True}, "tools", False, actor="u", actor_role="Approver", at=AT)
