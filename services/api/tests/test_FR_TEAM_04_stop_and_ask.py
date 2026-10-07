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
            set_switch(state, key, False, actor="u_owner", at=AT)


def test_FR_TEAM_04_optional_switch_changes_and_the_change_is_logged():
    state = {k: s.default for k, s in load_switches().items()}
    new, record = set_switch(state, "weekend", True, actor="u_owner", at=AT)
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
        set_switch(state, "nope", True, actor="u", at=AT)
    with pytest.raises(TypeError):
        set_switch(state, "weekend", "yes", actor="u", at=AT)  # type: ignore[arg-type]


def test_FR_TEAM_04_a_config_that_defaults_a_must_ask_rule_off_is_refused(tmp_path):
    bad = tmp_path / "t.yaml"
    bad.write_text(yaml.safe_dump({"switches": [{"key": "spend", "default": False, "must_ask": True}]}))
    with pytest.raises(ValueError):
        load_switches(bad)
