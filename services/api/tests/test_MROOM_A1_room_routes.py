"""MROOM-A1 (ADR-0028 decision 13, MR-01 to MR-05, MR-08, MR-12): the four routes of slice 1, per request."""

from __future__ import annotations

import json

import pytest
from _api_lib import OWNER, WORLD
from _mroom_a1_lib import CONFIG, Scripted, make_env, reply_json
from tilo_api import app, deps
from tilo_api.meeting_room_config import RoomConfig
from tilo_policy.schemas import conforms

QUESTION = "What did you do and why, with the plan for Thursday?"
ANSWER = "I triaged the inbox and handed it on because the Lead briefed me [seq: 18]."


def test_MROOM_A1_happy_path_events_are_valid_and_words_stay_in_the_archive(tmp_path):
    env = make_env(
        tmp_path,
        model=Scripted(lambda g: reply_json(text=ANSWER, artifacts=[{"artifact_id": "art_triage_list", "version": 1}])),
    )
    created = env.convene()
    assert created.status_code == 201
    room = created.json()
    assert conforms("meeting_room.schema.json", room) and room["state"] == "open" and room["as_role"] == "owner"
    turn = env.ask(room["room_id"], QUESTION)
    assert turn.status_code == 202
    assert turn.json()["reply"]["outcome"] == "answered" and turn.json()["reply"]["text"] == ANSWER
    shown = env.get(room["room_id"]).json()
    assert conforms("meeting_room.schema.json", shown)
    assert shown["turns"][0]["text"] == QUESTION and shown["credits_spent"] == pytest.approx(0.84)
    assert env.adjourn(room["room_id"]).json()["reason"] == "person"
    mine = env.room_events()
    assert [e["type"] for e in mine] == ["meeting.convened", "meeting.asked", "meeting.replied", "meeting.adjourned"]
    env.validate_room_events()
    assert all(conforms(f"events/data/{e['type']}.schema.json", e["data"]) for e in mine)
    convened, asked, replied, adjourned = mine
    assert convened["actor"] == OWNER and convened["target"] == "A_l1" and convened["vis"] == ["D1"]
    assert asked["actor"] == OWNER and asked["data"]["turn"] == 1 and asked["run_id"] == "r_village_basic_1"
    assert replied["actor"] == "A_s1" and replied["target"] == OWNER and replied["credits"] == pytest.approx(0.84)
    assert (
        replied["trace"]["model_role"] == "meeting_room"
        and replied["trace"]["archive_ref"] == replied["data"]["message_ref"]
    )
    assert adjourned["actor"] == OWNER and adjourned["data"] == {
        "room_id": room["room_id"],
        "reason": "person",
        "turns": 1,
        "credits_spent": pytest.approx(0.84),
    }
    blob = json.dumps(mine)
    assert QUESTION not in blob and ANSWER not in blob  # MR-12: refs only
    archived = [json.loads(line)["payload"]["text"] for line in env.lines.lines[("org_tilo", "r_village_basic_1")]]
    assert archived == [QUESTION, ANSWER]


def test_MROOM_A1_thinking_mode_uses_the_thinking_role(tmp_path):
    env = make_env(tmp_path)
    room = env.convene().json()
    env.ask(room["room_id"], mode="thinking")
    assert env.room_events()[-1]["trace"]["model_role"] == "meeting_room_thinking"


def test_MROOM_A1_convene_authorisation(tmp_path):
    env = make_env(tmp_path, team_roles={"u_mem": "Member", "u_view": "Viewer", "u_app": "Approver"})
    env.as_(role="viewer")
    assert env.convene().status_code == 403
    env.as_(user_id="u_view", role="approver", districts=("D1",))
    assert env.convene().status_code == 403  # a team Viewer
    env.as_(user_id="u_other", role="approver", districts=("D1",))
    assert env.convene().status_code == 403  # not in the team store
    env.as_(user_id="u_mem", role="approver", districts=("D2",))
    assert env.convene().status_code == 403  # the district is outside their view
    env.as_(user_id="u_mem", role="approver", districts=("D1",))
    assert env.convene(lead="A_dir", agents=["A_l1"]).status_code == 403  # only the owner calls the Director
    ok = env.convene()
    assert ok.status_code == 201 and ok.json()["as_role"] == "member"
    assert env.room_events()[0]["actor"] == "u_mem"


def test_MROOM_A1_demo_sessions_and_unwired_team_store_fail_closed(tmp_path):
    env = make_env(tmp_path)
    env.as_()
    app.dependency_overrides[deps.get_current_principal] = lambda: deps.Principal(
        OWNER, "owner", WORLD, demo_session=True
    )
    assert env.convene().json() == {"error": "demo_session"}
    env.as_(user_id="u_mem", role="approver", districts=("D1",))
    assert env.convene().status_code == 403  # no team store configured: no team roles, never open


def test_MROOM_A1_attendees_come_from_the_layout(tmp_path):
    env = make_env(tmp_path)
    assert env.convene(agents=["A_s9"]).status_code == 422  # another district's worker
    assert env.convene(agents=["A_l2"]).status_code == 422  # a Lead is not a district Lead's guest
    assert env.convene(lead="A_s1", agents=[]).status_code == 422  # a worker cannot be the lead
    assert env.convene(agents=["A_ghost"]).status_code == 422  # not in the layout
    assert env.convene(lead="A_dir", agents=["A_s1"]).status_code == 422  # the Director brings Leads only
    assert env.convene(lead="A_dir", agents=["A_l1", "A_l2"]).json()["agents"] == ["A_l1", "A_l2"]
    assert env.room_events()[0]["vis"] == "all"


def test_MROOM_A1_more_than_max_agents_is_refused(tmp_path):
    env = make_env(tmp_path, config=RoomConfig(2, 20, 20, 3, 600, 1, ("Owner",)))
    assert env.convene(agents=["A_s1", "A_s2"]).status_code == 422
    assert env.convene(agents=["A_s1"]).status_code == 201


def test_MROOM_A1_one_open_room_and_paused_world(tmp_path):
    env = make_env(tmp_path)
    first = env.convene().json()
    assert env.convene().json() == {"error": "room_open"}
    env.adjourn(first["room_id"])
    assert env.convene().status_code == 201
    env.store.worlds[WORLD].paused = True
    assert env.convene().json() == {"error": "world_paused"}


def test_MROOM_A1_a_stranger_gets_the_404_of_a_missing_room(tmp_path):
    env = make_env(tmp_path, team_roles={"u_mem": "Member", "u_x": "Member"})
    env.as_(user_id="u_mem", role="approver", districts=("D1",))
    room = env.convene().json()
    missing = env.get("01JB5VQ00000000000000R9999")
    env.as_(user_id="u_x", role="approver", districts=("D1",))
    for answer in (env.get(room["room_id"]), env.ask(room["room_id"]), env.adjourn(room["room_id"])):
        assert answer.status_code == 404 and answer.content == missing.content
    env.as_()  # the world's owner reads (but does not speak in) a member's room
    assert env.get(room["room_id"]).status_code == 200
    assert env.ask(room["room_id"]).status_code == 404
    env.as_(world_id="w_other")
    assert env.get(room["room_id"]).status_code == 404


def test_MROOM_A1_access_is_rechecked_and_a_lost_role_adjourns(tmp_path):
    env = make_env(tmp_path, team_roles={"u_mem": "Member"})
    env.as_(user_id="u_mem", role="approver", districts=("D1",))
    room = env.convene().json()
    assert env.ask(room["room_id"]).status_code == 202
    env.as_(user_id="u_mem", role="approver", districts=("D2",))  # their view moved away from the room's district
    denied = env.ask(room["room_id"])
    assert denied.status_code == 403 and denied.json() == {"error": "access_lost"}
    env.as_()
    assert env.get(room["room_id"]).json()["reason"] == "access_lost"
    assert env.room_events()[-1]["data"]["reason"] == "access_lost" and env.room_events()[-1]["actor"] == "system"
    env.validate_room_events()


def test_MROOM_A1_turns_count_without_gaps_with_one_in_flight(tmp_path):
    env = make_env(tmp_path)
    room = env.convene().json()
    env.ask(room["room_id"])
    env.ask(room["room_id"], to="A_s2")
    assert [t["turn"] for t in env.get(room["room_id"]).json()["turns"]] == [1, 2]
    assert env.ask(room["room_id"], to="A_s9").status_code == 422  # not at this table
    assert (
        env.client.post(
            f"/v1/worlds/{WORLD}/rooms/{room['room_id']}/turns", json={"to": "A_s1", "text": "", "mode": "quick"}
        ).status_code
        == 422
    )
    asked = [e for e in env.room_events() if e["type"] == "meeting.asked"][-1]
    env.store.events[WORLD].remove(
        [e for e in env.room_events() if e["type"] == "meeting.replied"][-1]
    )  # a crash before the reply
    assert asked["data"]["turn"] == 2 and env.ask(room["room_id"]).json() == {"error": "turn_in_flight"}
    from tilo_api import meeting_room as mr

    mr._turn_lock(room["room_id"]).acquire()  # a call still running in this process
    try:
        env.store.events[WORLD].append(
            {
                **asked,
                "id": "01JB5VQ00000000000000R7777",
                "type": "meeting.replied",
                "actor": "A_s1",
                "credits": 0,
                "data": {
                    **asked["data"],
                    "outcome": "failed",
                    "message_ref": None,
                    "units": [],
                    "artifacts": [],
                    "proposal": None,
                },
            }
        )
        assert env.ask(room["room_id"]).json() == {"error": "turn_in_flight"}
    finally:
        mr._turn_lock(room["room_id"]).release()


def test_MROOM_A1_credit_cap_refuses_the_turn_and_adjourns_capped(tmp_path):
    env = make_env(tmp_path, model=Scripted(credits=12.0, quote_value=15.0))
    room = env.convene().json()
    assert env.ask(room["room_id"]).status_code == 202  # quote 15 fits the cap of 20; the call cost 12
    refused = env.ask(room["room_id"])
    assert refused.status_code == 409 and refused.json() == {"error": "room_closed", "reason": "capped"}
    last = env.room_events()[-1]
    assert last["type"] == "meeting.adjourned" and last["data"] == {
        "room_id": room["room_id"],
        "reason": "capped",
        "turns": 1,
        "credits_spent": 12.0,
    }
    assert len([e for e in env.room_events() if e["type"] == "meeting.asked"]) == 1  # refused before any call
    assert env.ask(room["room_id"]).json()["error"] == "room_closed"
    env.validate_room_events()


def test_MROOM_A1_turn_cap_adjourns_capped(tmp_path):
    env = make_env(tmp_path, config=RoomConfig(6, 1, 20, 3, 600, 1, ("Owner",)))
    room = env.convene().json()
    assert env.ask(room["room_id"]).status_code == 202
    assert env.ask(room["room_id"]).json() == {"error": "room_closed", "reason": "capped"}


def test_MROOM_A1_idle_room_closes_on_access_and_never_blocks_a_new_one(tmp_path):
    env = make_env(tmp_path)
    room = env.convene().json()
    env.clock[0] = "2026-10-09T10:09:59.000Z"
    assert env.get(room["room_id"]).json()["state"] == "open"
    env.clock[0] = "2026-10-09T10:10:01.000Z"  # 601 s after the room's last event
    assert env.ask(room["room_id"]).json() == {"error": "room_closed", "reason": "idle"}
    assert env.room_events()[-1]["data"]["reason"] == "idle"
    env2 = make_env(tmp_path)
    env2.convene()
    env2.clock[0] = "2026-10-09T11:00:00.000Z"
    assert env2.convene().status_code == 201  # the idle room was swept first


def test_MROOM_A1_pause_all_adjourns_open_rooms_before_world_paused(tmp_path):
    env = make_env(tmp_path)
    room = env.convene().json()
    assert env.client.post(f"/worlds/{WORLD}/pause").status_code in (200, 202)
    types = [e["type"] for e in env.store.events[WORLD] if e["type"] in ("meeting.adjourned", "world.paused")]
    assert types == ["meeting.adjourned", "world.paused"]
    assert env.get(room["room_id"]).json()["reason"] == "paused"
    assert env.ask(room["room_id"]).json() == {"error": "world_paused"}


def test_MROOM_A1_stop_all_adjourns_open_rooms(tmp_path):
    env = make_env(tmp_path)
    env.convene()
    env.client.post(f"/worlds/{WORLD}/autopilot/stop")
    assert env.room_events()[-1]["data"]["reason"] == "paused"


def test_MROOM_A1_unwired_seams_answer_503_and_write_nothing(tmp_path):
    env = make_env(tmp_path)
    room = env.convene().json()
    kept = dict(app.dependency_overrides)
    for seam in (deps.get_run_archive, deps.get_redactor):  # production defaults: no archive, no redactor
        del app.dependency_overrides[seam]
        assert env.ask(room["room_id"]).status_code == 503
        app.dependency_overrides.update(kept)
    assert len(env.room_events()) == 1  # not even a meeting.asked
    assert env.ask(room["room_id"]).status_code == 202


def test_MROOM_A1_defaults_are_the_shipped_config():
    from tilo_api.meeting_room_config import load_room_config

    assert load_room_config() == CONFIG
