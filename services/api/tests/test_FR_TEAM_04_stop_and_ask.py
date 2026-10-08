"""FR-TEAM-04: five switches; the PRD's Must-ask rules can't be switched off; every change is logged."""

import pytest
import yaml
from tilo_api.team_rules import MustAskLocked, load_switches, set_switch

AT = "2026-10-08T10:00:00.000Z"


def test_FR_TEAM_04_there_are_exactly_five_switches_from_config():
    assert list(load_switches()) == ["spend", "share", "undo", "tools", "weekend"]


def test_FR_TEAM_04_must_ask_switches_cannot_be_turned_off():
    sw = load_switches()
    locked = [k for k, s in sw.items() if s.must_ask]
    assert {"spend", "share", "undo"} <= set(locked) and "weekend" not in locked
    state = {k: s.default for k, s in sw.items()}
    for key in locked:
        assert state[key] is True
        with pytest.raises(MustAskLocked):
            set_switch(state, key, False, actor="u_owner", actor_role="Owner", at=AT)


def test_FR_TEAM_04_optional_switch_changes_and_the_change_is_logged():
    state = {k: s.default for k, s in load_switches().items()}
    new, record = set_switch(state, "weekend", True, actor="u_owner", actor_role="Owner", at=AT)
    assert new["weekend"] is True and state["weekend"] is False
    assert record == {
        "kind": "team_rule_changed",
        "key": "weekend",
        "from": False,
        "to": True,
        "by": "u_owner",
        "at": AT,
    }


def test_FR_TEAM_04_unknown_switch_or_non_bool_is_refused():
    state = {k: s.default for k, s in load_switches().items()}
    with pytest.raises(KeyError):
        set_switch(state, "nope", True, actor="u", actor_role="Owner", at=AT)
    with pytest.raises(TypeError):
        set_switch(state, "weekend", "yes", actor="u", actor_role="Owner", at=AT)  # type: ignore[arg-type]


def test_FR_TEAM_04_a_config_that_defaults_a_must_ask_rule_off_is_refused(tmp_path):
    bad = tmp_path / "t.yaml"
    bad.write_text(yaml.safe_dump({"switches": [{"key": "spend", "default": False, "must_ask": True}]}))
    with pytest.raises(ValueError):
        load_switches(bad)


@pytest.mark.parametrize("role", ["Member", "Viewer", "Root", None])
def test_FR_TEAM_04_only_owners_and_approvers_change_switches(role):
    state = {k: s.default for k, s in load_switches().items()}
    with pytest.raises(PermissionError):
        set_switch(state, "weekend", True, actor="u", actor_role=role, at=AT)  # type: ignore[arg-type]


def test_FR_TEAM_04_tools_switch_is_owner_only():
    state = {k: s.default for k, s in load_switches().items()}
    with pytest.raises(PermissionError):
        set_switch(state, "tools", False, actor="u", actor_role="Approver", at=AT)
    assert set_switch(state, "tools", False, actor="u", actor_role="Owner", at=AT)[0]["tools"] is False
    # TEAM-ROUTES (#621): PRD 10.1 gives the Approver no policy rights, so every switch is Owner-only now (stricter)
    with pytest.raises(PermissionError):
        set_switch(state, "weekend", True, actor="u", actor_role="Approver", at=AT)
    assert set_switch(state, "weekend", True, actor="u", actor_role="Owner", at=AT)[0]["weekend"] is True


def test_FR_TEAM_04_a_config_edit_cannot_unlock_a_must_ask_rule(tmp_path):
    rows = [{"key": k, "default": True, "must_ask": False} for k in ("spend", "share", "undo", "tools")]
    cfg = tmp_path / "t.yaml"
    cfg.write_text(yaml.safe_dump({"switches": rows}))
    assert all(load_switches(cfg)[k].must_ask for k in ("spend", "share", "undo"))
