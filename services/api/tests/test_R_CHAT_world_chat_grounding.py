"""R-CHAT: world chat answers use the world's recorded story, steps, and artifact names."""

from __future__ import annotations

import json

from _api_lib import WORLD
from _mroom_a1_lib import D2_SECRET, STREAM, Scripted, layout, make_env, reply_json
from tilo_api.meeting_room_reply import MAX_LINE, MAX_LINES, ground


def test_R_CHAT_world_record_adds_story_step_summaries_and_artifact_names_within_caps():
    events = [json.loads(line) for line in STREAM.read_text(encoding="utf-8").splitlines() if line.strip()]

    record = ground(layout(), events, "A_s1")

    assert record is not None
    context = "\n".join(line[3] for line in record.lines)
    assert "You asked Tilo to triage your inbox and answer the supplier." in context
    assert "The Director planned 2 units: triage the inbox, then reply to the supplier." in context
    assert "step U1" in context
    assert "artifact Triage list" in context
    assert D2_SECRET not in context
    assert len(record.lines) <= MAX_LINES
    assert all(len(summary) <= MAX_LINE for _, _, _, summary in record.lines)


def test_P0_AGENT_CHAT_a_failed_world_still_answers_from_its_record_with_the_fake_provider(tmp_path):
    model = Scripted(lambda record: reply_json(text="The recorded triage step completed [seq: 18]."))
    env = make_env(tmp_path, model=model)
    env.store.events[WORLD][-1] = {
        **env.store.events[WORLD][-1],
        "type": "world.failed",
        "data": {"reason": "The next step stopped.", "unit": "U2"},
    }

    room = env.convene(lead="A_dir", agents=[]).json()["room_id"]
    reply = env.ask(room, "What was completed before this stopped?", to="A_dir").json()["reply"]

    assert reply["outcome"] == "answered"
    assert reply["text"] == "The recorded triage step completed [seq: 18]."
    assert any("triage" in line[3].lower() for line in model.records[0].lines)
