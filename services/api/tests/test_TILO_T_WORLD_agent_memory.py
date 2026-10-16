"""TILO-T-WORLD step 3 (MR-06, EFF-04): an agent's "memory of its own" in a 1:1 room is its own recorded work in the
world, built by `ground()` and sent in the user turn of the room's one static-system-prompt call. Another agent's
lines never reach it, and room talk itself is not part of it."""

from __future__ import annotations

from _mroom_a1_lib import make_env


def test_TILO_T_WORLD_a_worker_is_asked_with_its_own_recorded_work_as_context(tmp_path):
    env = make_env(tmp_path)
    room = env.convene(lead="A_l1", agents=["A_s1"]).json()["room_id"]
    env.ask(room, to="A_s1")
    record = env.model.records[0]
    assert record.agent == "A_s1"
    assert record.lines, "the worker's own events are the context"
    assert all(line[0] > 0 for line in record.lines)
    prompt = env.model.prompts[0]
    assert all(str(summary)[:40] in prompt for _seq, _type, _unit, summary in record.lines[:3])


def test_TILO_T_WORLD_the_system_prompt_is_static_and_the_context_is_in_the_user_turn():
    from tilo_api.meeting_room_reply import Grounding, _prompt

    def grounding(agent: str, summary: str) -> Grounding:
        return Grounding(
            agent, "specialist", "D1", frozenset({"U1"}), frozenset(), ((1, "agent.handoff", "U1", summary),)
        )

    system_a, user_a = _prompt(
        grounding("A_s1", "alpha note"), "Why?", "quick", "", grounding("A_s1", "alpha note").lines
    )
    system_b, user_b = _prompt(
        grounding("A_s2", "beta note"), "Why?", "quick", "", grounding("A_s2", "beta note").lines
    )
    assert system_a == system_b, "EFF-04: one static system prompt for every agent and turn"
    assert "alpha note" in user_a and "alpha note" not in system_a
    assert "beta note" in user_b and "beta note" not in user_a
