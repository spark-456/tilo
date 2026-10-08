"""FR-TEAM-04 / FR-ACC-01 / ADR-0027 decision 2: a changed stop-and-ask switch or tool level appends ONE registered
`team_rule.changed` event to the signed-in person's Desk world, after the compare-and-set; a no-op appends nothing;
roles, limits, invites and removals are no team rules (BQ-ADR27-3); a failed append undoes the change and answers 503
("every change is logged"). Ids and enums only: no email, no free text."""

from __future__ import annotations

import pytest
from _api_lib import validate_event
from _team_routes_lib import APPROVER, MEMBER, OWNER, state, team_api

DESK = "w_desk_owner"
STAMP = {
    "v": "1.0", "seq": 1, "ts": "2026-10-08T10:00:00.000Z", "run_id": "r_desk_owner_1", "level": None,
    "district": None, "item": None, "severity": "info", "credits": 0, "cause": None,
    "trace": {"model_role": None, "profile": None, "tokens_in": None, "tokens_out": None, "tool": None,
              "latency_ms": None, "archive_ref": None},
}  # fmt: skip


def _only(api) -> dict:  # type: ignore[no-untyped-def]
    assert len(api.writer.parts) == 1, api.writer.parts
    world, part = api.writer.parts[0]
    assert world == DESK
    validate_event({**STAMP, "world_id": world, **part})  # event.schema.json + the data schema
    assert part["type"] == "team_rule.changed" and part["actor"] == part["target"] == OWNER
    assert part["vis"] == [] and part["authz"] is None and part.get("district") is None
    assert "@" not in part["summary"] and 1 <= len(part["summary"]) <= 140
    return part


def test_FR_TEAM_04_a_switch_change_appends_one_team_rule_changed_in_the_owners_desk() -> None:
    with team_api() as api:
        assert api.put("/v1/team/switches/weekend", {"on": True}).status_code == 200
        part = _only(api)
    assert part["data"] == {"rule": "switch", "key": "weekend", "from": "off", "to": "on"}


def test_FR_TEAM_04_the_switch_from_is_the_value_in_force_and_to_is_the_new_one() -> None:
    with team_api(state(switches={"tools": True, "weekend": True, "spend": True, "share": True, "undo": True})) as api:
        assert api.put("/v1/team/switches/tools", {"on": False}).status_code == 200
        assert _only(api)["data"] == {"rule": "switch", "key": "tools", "from": "on", "to": "off"}


def test_FR_ACC_01_a_tool_level_change_appends_one_tool_access_event_from_act_when_unset() -> None:
    with team_api() as api:
        assert api.put("/v1/team/tools/gmail", {"level": "read"}).status_code == 200
        part = _only(api)
        assert part["data"] == {"rule": "tool_access", "key": "gmail", "from": "act", "to": "read"}
        api.writer.parts.clear()
        assert api.put("/v1/team/tools/gmail", {"level": "draft"}).status_code == 200
        assert _only(api)["data"]["from"] == "read"


def test_FR_TEAM_04_a_no_op_write_answers_200_and_appends_nothing() -> None:
    with team_api() as api:
        assert api.put("/v1/team/switches/weekend", {"on": False}).status_code == 200  # already off
        assert api.put("/v1/team/switches/spend", {"on": True}).status_code == 200  # Must-ask, already on
        assert api.put("/v1/team/tools/gmail", {"level": "act"}).status_code == 200  # unset is act
        assert api.writer.parts == []


def test_FR_TEAM_04_a_must_ask_switch_is_refused_and_never_logged_as_switched_off() -> None:
    with team_api() as api:
        for key in ("spend", "share", "undo"):
            assert api.put(f"/v1/team/switches/{key}", {"on": False}).status_code == 409
        assert api.writer.parts == []


def test_FR_TEAM_04_a_stored_must_ask_off_repaired_by_a_change_is_never_logged_to_off() -> None:
    stored = {"spend": False, "share": True, "undo": True, "tools": True, "weekend": False}
    with team_api(state(switches=stored)) as api:
        assert api.put("/v1/team/switches/weekend", {"on": True}).status_code == 200
        part = _only(api)
    assert part["data"]["key"] == "weekend"  # the weekend change only; the tampered spend is read as on


def test_FR_TEAM_04_roles_limits_invites_and_removals_are_no_team_rules() -> None:
    with team_api() as api:
        assert api.put(f"/v1/team/members/{MEMBER}/role", {"role": "Approver"}).status_code == 200
        assert api.put(f"/v1/team/members/{APPROVER}/limit", {"limit_minor": 5}).status_code == 200
        assert api.post("/v1/team/invites", {"email": "ann@example.com", "role": "Member"}).status_code == 201
        assert api.delete(f"/v1/team/members/{MEMBER}").status_code == 200
        assert api.writer.parts == []


def test_FR_TEAM_04_a_refused_change_appends_nothing() -> None:
    with team_api() as api:
        assert api.as_(MEMBER).put("/v1/team/switches/weekend", {"on": True}).status_code == 403
        assert api.as_(MEMBER).put("/v1/team/tools/gmail", {"level": "off"}).status_code == 403
        assert api.as_(OWNER).put("/v1/team/tools/not_a_tool", {"level": "off"}).status_code == 404
        assert api.writer.parts == []


@pytest.mark.parametrize(
    ("path", "body", "check"),
    [
        ("/v1/team/switches/weekend", {"on": True}, lambda s: s.switches.get("weekend") is not True),
        ("/v1/team/tools/gmail", {"level": "off"}, lambda s: "gmail" not in s.tools),
    ],
)
def test_FR_TEAM_04_when_the_event_cannot_be_written_the_change_is_undone_and_the_answer_is_503(
    path: str, body: dict, check
) -> None:  # type: ignore[no-untyped-def]
    with team_api() as api:
        api.writer.fail = True
        assert api.put(path, body).status_code == 503
        assert check(api.store.read()) and api.writer.parts == []
        api.writer.fail = False
        assert api.put(path, body).status_code == 200 and len(api.writer.parts) == 1  # and it can be done again


@pytest.mark.parametrize("answer", ["w_desk_somebody_else", "w_other_world", 7, ""])
def test_FR_TEAM_04_a_desk_that_is_not_the_signed_in_persons_writes_nothing_and_undoes_the_change(answer) -> None:  # type: ignore[no-untyped-def]
    with team_api() as api:
        api.desks.answer = answer
        assert api.put("/v1/team/tools/gmail", {"level": "read"}).status_code == 503
        assert api.writer.parts == [] and "gmail" not in api.store.read().tools


def test_FR_TEAM_04_a_desk_world_store_that_is_down_is_a_503_and_the_change_is_undone() -> None:
    with team_api() as api:
        api.desks.fail = True
        assert api.put("/v1/team/switches/weekend", {"on": True}).status_code == 503
        assert api.store.read().switches.get("weekend") is not True


def test_FR_TEAM_04_unwired_event_seams_are_a_503_and_change_nothing() -> None:
    from tilo_api import app, deps

    with team_api() as api:
        app.dependency_overrides.pop(deps.get_desk_worlds)
        assert api.put("/v1/team/tools/gmail", {"level": "read"}).status_code == 503
        assert "gmail" not in api.store.read().tools


def test_FR_TEAM_04_the_event_carries_only_enums_and_the_connector_id() -> None:
    with team_api() as api:
        api.put("/v1/team/tools/gmail", {"level": "off"})
        api.put("/v1/team/switches/weekend", {"on": True})
        for _world, part in api.writer.parts:
            assert set(part["data"]) == {"rule", "key", "from", "to"}
            blob = repr(part)
            assert "@" not in blob and "example.com" not in blob
