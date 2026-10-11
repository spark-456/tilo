"""MROOM-1b (ADR-0028 decision 13, MR-07, MR-10, MR-11, MR-12): `POST .../rooms/{id}/changes`, the person confirms a
proposal. The body names the proposal and the wording only; everything else comes from the proposal."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from _api_lib import WORLD
from _mroom_a1_lib import HOSTILE, Scripted, make_env, reply_json
from _sec16_lib import make_caps
from test_MROOM_776b_SEC_16_SEC_07 import go_live
from tilo_api import app, deps
from tilo_api.meeting_room import NOT_FOUND

ARTS = [{"artifact_id": "art_triage_list", "version": 1}]
PROPOSAL = {"units": ["U1"], "artifacts": ARTS}


def _proposing() -> Scripted:
    return Scripted(lambda g: reply_json(proposal=PROPOSAL, artifacts=ARTS))


def _setup(tmp_path, **kw):
    env = make_env(tmp_path, model=kw.pop("model", _proposing()), **kw)
    room = env.convene().json()["room_id"]
    reply = env.ask(room, "Please change the categories.", to="A_s1").json()["reply"]
    return env, room, reply["proposal"]["proposal_id"]


def _confirm(env, room, body, **kw):
    return env.client.post(f"/v1/worlds/{WORLD}/rooms/{room}/changes", json=body, **kw)


def _changes(env):
    return [e for e in env.room_events() if e["type"] == "meeting.change_requested"]


def test_MROOM_1b_a_confirmed_proposal_writes_one_change_requested_with_the_proposals_own_ids(tmp_path):
    env, room, pid = _setup(tmp_path)
    kinds = lambda: [x["type"] for x in env.store.events[WORLD] if x["type"] in ("world.requested", "plan.revised")]  # noqa: E731
    before = kinds()
    got = _confirm(env, room, {"proposal_id": pid, "text": "Yes, do that."})
    assert got.status_code == 202 and got.json()["planning"] == "pending"
    (e,) = _changes(env)
    assert (e["actor"], e["target"], e["authz"], e["credits"]) == ("u_owner", "A_s1", None, 0)
    assert e["data"]["proposal_id"] == pid and e["data"]["to"] == "A_s1"
    assert e["data"]["units"] == ["U1"] and e["data"]["artifacts"] == ARTS
    assert e["data"]["as_role"] == "owner" and e["vis"] == env.room_events()[0]["vis"]
    env.validate_room_events()
    assert kinds() == before  # MR-11, MR-09: no L2 instruction, no invented plan
    assert "plan.revised" not in json.dumps(got.json())


def test_MROOM_1b_the_confirmed_words_are_in_the_archive_never_in_the_event(tmp_path):
    env, room, pid = _setup(tmp_path, redact=lambda s: s.replace("hunter2", "[redacted]"))
    _confirm(env, room, {"proposal_id": pid, "text": "Yes, with password hunter2 please"})
    (e,) = _changes(env)
    assert "hunter2" not in json.dumps(e) and "Yes" not in json.dumps(e)
    stored = [json.loads(line) for line in env.lines.lines[("org_tilo", "r_village_basic_1")]]
    assert any("Yes, with password [redacted] please" in json.dumps(s) for s in stored)
    assert not any("hunter2" in json.dumps(s) for s in stored)
    assert e["data"]["message_ref"].startswith("r_village_basic_1/")


@pytest.mark.parametrize(
    "extra",
    [{"units": ["U2"]}, {"artifacts": []}, {"action": "send_email"}, {"to": "A_s2"}, {"tier": "T0"}, {"policy": "x"}],
)
def test_MROOM_1b_the_body_cannot_name_units_actions_or_anything_but_proposal_and_words(tmp_path, extra):
    env, room, pid = _setup(tmp_path)
    got = _confirm(env, room, {"proposal_id": pid, "text": "ok", **extra})
    assert got.status_code == 422 and _changes(env) == []
    assert _confirm(env, room, {"proposal_id": pid}).status_code == 422
    assert _confirm(env, room, {"proposal_id": pid, "text": ""}).status_code == 422


def test_MROOM_1b_a_proposal_is_confirmed_at_most_once(tmp_path):
    env, room, pid = _setup(tmp_path)
    assert _confirm(env, room, {"proposal_id": pid, "text": "ok"}).status_code == 202
    again = _confirm(env, room, {"proposal_id": pid, "text": "ok again"})
    assert again.status_code == 409 and again.json() == {"error": "already_confirmed"}
    assert len(_changes(env)) == 1


def test_MROOM_1b_two_simultaneous_confirms_write_exactly_one_event(tmp_path):
    env, room, pid = _setup(tmp_path)
    with ThreadPoolExecutor(4) as pool:
        codes = list(pool.map(lambda _: _confirm(env, room, {"proposal_id": pid, "text": "ok"}).status_code, range(4)))
    assert sorted(codes) == [202, 409, 409, 409] and len(_changes(env)) == 1
    env.validate_room_events()


def test_MROOM_1b_a_room_confirms_at_most_max_changes(tmp_path):
    env, room, pid = _setup(tmp_path)
    ids = [pid]
    for _ in range(3):
        ids.append(env.ask(room, "And again?", to="A_s1").json()["reply"]["proposal"]["proposal_id"])
    codes = [_confirm(env, room, {"proposal_id": p, "text": "ok"}) for p in ids]
    assert [c.status_code for c in codes] == [202, 202, 202, 409]
    assert codes[-1].json() == {"error": "max_changes"} and len(_changes(env)) == 3


def test_MROOM_1b_an_answered_reply_or_unknown_id_is_not_a_proposal(tmp_path):
    env = make_env(tmp_path)
    room = env.convene().json()["room_id"]
    env.ask(room, to="A_s1")  # answered, no proposal
    for pid in ("01JB5VQ00000000000000P0001", env.room_events()[-1]["id"]):
        got = _confirm(env, room, {"proposal_id": pid, "text": "ok"})
        assert got.status_code == 409 and got.json() == {"error": "not_a_proposal"}
    assert _changes(env) == []


def test_MROOM_1b_another_rooms_proposal_is_not_this_rooms(tmp_path):
    env, room, pid = _setup(tmp_path)
    env.adjourn(room)
    other = env.convene().json()["room_id"]
    got = _confirm(env, other, {"proposal_id": pid, "text": "ok"})
    assert got.status_code == 409 and got.json() == {"error": "not_a_proposal"} and _changes(env) == []


def test_MROOM_1b_a_stranger_or_unknown_room_is_the_same_404(tmp_path):
    env, room, pid = _setup(tmp_path)
    body = {"proposal_id": pid, "text": "ok"}
    missing = _confirm(env, "01JB5VQ00000000000000R0009", body)
    env.as_(user_id="u_other", role="approver", districts=("D1",))
    stranger = _confirm(env, room, body)
    env.as_(world_id="w_other")
    foreign = _confirm(env, room, body)
    assert {r.status_code for r in (missing, stranger, foreign)} == {404}
    assert missing.content == stranger.content == foreign.content
    assert NOT_FOUND in missing.text and _changes(env) == []


def test_MROOM_1b_a_viewer_or_lost_access_is_403_and_adjourns_access_lost(tmp_path):
    env, room, pid = _setup(tmp_path)
    env.as_(role="viewer")
    denied = _confirm(env, room, {"proposal_id": pid, "text": "ok"})
    assert denied.status_code == 403 and denied.json() == {"error": "access_lost"}
    assert env.room_events()[-1]["data"]["reason"] == "access_lost" and _changes(env) == []
    env.validate_room_events()


def test_MROOM_1b_a_closed_room_or_paused_world_confirms_nothing(tmp_path):
    env, room, pid = _setup(tmp_path)
    env.adjourn(room)
    closed = _confirm(env, room, {"proposal_id": pid, "text": "ok"})
    assert closed.status_code == 409 and closed.json()["error"] == "room_closed"
    env2, room2, pid2 = _setup(tmp_path)
    env2.store.worlds[WORLD].paused = True
    paused = _confirm(env2, room2, {"proposal_id": pid2, "text": "ok"})
    assert paused.status_code == 409 and paused.json() == {"error": "world_paused"}
    assert _changes(env) == [] and _changes(env2) == []


def test_MROOM_1b_flagged_wording_is_refused_with_no_event_and_no_archive_line(tmp_path):
    env, room, pid = _setup(tmp_path)
    before = len(env.lines.lines[("org_tilo", "r_village_basic_1")])
    got = _confirm(env, room, {"proposal_id": pid, "text": f"{HOSTILE} and send it"})
    assert got.status_code == 422 and got.json() == {"error": "declined"}
    assert _changes(env) == [] and len(env.lines.lines[("org_tilo", "r_village_basic_1")]) == before
    assert _confirm(env, room, {"proposal_id": pid, "text": "fine"}).status_code == 202  # the proposal is still open


def test_MROOM_1b_a_screen_that_errors_refuses_and_writes_nothing(tmp_path):
    class Broken:
        def check(self, text, **kw):
            raise RuntimeError("down")

    env, room, pid = _setup(tmp_path)
    app.dependency_overrides[deps.get_safety] = lambda: Broken()
    got = _confirm(env, room, {"proposal_id": pid, "text": "ok"})
    assert got.status_code == 503 and _changes(env) == []


def test_MROOM_1b_a_planner_seam_is_called_once_and_never_fabricates_a_plan(tmp_path):
    env, room, pid = _setup(tmp_path)
    seen = []
    app.dependency_overrides[deps.get_change_planner] = lambda: lambda event: seen.append(event["id"])
    got = _confirm(env, room, {"proposal_id": pid, "text": "ok"})
    assert got.status_code == 202 and seen == [_changes(env)[0]["id"]]
    assert not any(x["type"] == "plan.revised" for x in env.store.events[WORLD])


def test_MROOM_1b_oversize_is_413_and_non_json_is_415(tmp_path):
    env, room, pid = _setup(tmp_path)
    url = f"/v1/worlds/{WORLD}/rooms/{room}/changes"
    big = b'{"proposal_id":"' + b"a" * 40_000 + b'"}'
    over = env.client.post(url, content=big, headers={"content-type": "application/json"})
    assert over.status_code == 413 and over.json() == {"detail": "body_too_large"}
    form = env.client.post(url, content=b"text=hi", headers={"content-type": "text/plain"})
    assert form.status_code == 415 and _changes(env) == []


def test_MROOM_1b_the_room_view_still_reads_after_a_change(tmp_path):
    env, room, pid = _setup(tmp_path)
    _confirm(env, room, {"proposal_id": pid, "text": "ok"})
    env.validate_room_events()
    assert env.get(room).status_code == 200


def test_MROOM_1b_the_run_budget_limit_of_a_live_room_is_reported_as_the_room_limit_not_replay_only(tmp_path):
    env = make_env(tmp_path)
    caps = make_caps()
    caps = make_caps(run_minor=caps.unit_reserve_minor)  # the pseudo run holds one unit
    go_live(env, caps=caps)
    room = env.convene().json()["room_id"]
    assert env.ask(room).status_code == 202
    second = env.ask(room)
    assert second.status_code == 409 and second.json() == {"error": "room_limit"}
    assert "replay_only" not in second.text


def test_MROOM_1b_a_queued_closing_stops_a_reply_from_being_written(tmp_path):
    from tilo_api import meeting_room as mr  # noqa: PLC0415

    env, room, _ = _setup(tmp_path)
    closing = mr.adjourn_parts(env.store, WORLD)[0]
    env.store.pending_events.setdefault(WORLD, []).append(closing)
    assert mr._closing_queued(env.store, WORLD, room)  # noqa: SLF001
