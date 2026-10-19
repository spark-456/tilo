"""P0_HALL_ASK: a room answer can cite the world's real story and result."""

from __future__ import annotations

import json

from _mroom_a1_lib import STREAM, Scripted, layout, make_env, reply_json
from tilo_api.meeting_room_reply import answer, ground


def test_P0_HALL_ASK_worker_sees_plan_step_artifact_and_final_result_within_caps():
    events = [json.loads(line) for line in STREAM.read_text(encoding="utf-8").splitlines() if line.strip()]
    plan = layout()
    plan["semantic"]["levels"][0]["districts"][0]["buildings"][0]["name"] = "Mail Room"
    record = ground(plan, events, "A_s1")
    assert record is not None
    context = "\n".join(row[3] for row in record.lines)
    assert "triage your inbox" in context
    assert "planned 2 units" in context
    assert "plan U1: Mail Room" in context
    assert "Triage list" in context
    assert "triaging 12 emails" in context
    assert "1 reply sent and 12 emails triaged" in context
    assert len(record.lines) <= 60
    assert all(len(row[3]) <= 300 for row in record.lines)


def test_P0_HALL_ASK_world_level_answer_cites_a_recorded_run_unit(tmp_path):
    model = Scripted(lambda _: reply_json(units=["U1"], text="The Director planned two steps [seq: 4]."))
    env = make_env(tmp_path, model=model)
    room = env.convene(lead="A_dir", agents=[]).json()["room_id"]
    reply = env.ask(room, "What was the plan?", to="A_dir").json()["reply"]
    assert reply["outcome"] == "answered"
    assert reply["text"] == "The Director planned two steps [seq: 4]."


def test_P0_HALL_ASK_unstarted_world_says_start_without_model_call():
    model = Scripted()
    record = ground(layout(), [], "A_l1")
    assert record is not None

    class Clear:
        def check(self, text, **kw):
            return {"flagged": False, "reason": None}

    reply = answer(model, record, "What happened?", "quick", safety=Clear(), redact=lambda x: x, budget=5)
    assert reply.outcome == "declined"
    assert reply.text == "This world has no record yet. Select Start to begin."
    assert model.prompts == []
