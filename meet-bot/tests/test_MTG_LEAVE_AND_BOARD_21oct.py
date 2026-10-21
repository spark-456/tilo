"""Owner's live call, 21 Oct 19:17 IST: leave ignored, team board read back as personal, chatter after a "no".

(1) "Tilo leaev", "Alright, you may leave" (typed) got "I will remain here": only the exact "Tilo, leave" was a command.
    Leaving is now the model's intent (GEN-06: no word lists), however it is worded or misspelled, from a line put to
    Tilo: one goodbye line, then Tilo leaves once it has been said.
(2) The model's board came back as "Team" or "team board" and Tilo read back "your personal board". The board the person
    named is kept, and the prompt says to take it from what they said or from Tilo's own last question.
(3) After "no", "Okay, I won't." stands alone: the model does not add "Understood, I will not add ..." after it.
Also: a model reply with text around its JSON is still read, and a failed quick reply leaves a stage line that names the
failure type only (live, the typed pin request got "I couldn't get that just now" with no trace of why)."""

import asyncio
import json
import logging

from test_MTG_ACTIONS_1_bot_actions import _brain, _session

from bot import action_talk
from bot.brain import GOODBYE_LINE, QUICK_PROMPT, QUICK_PROMPT_ACTIONS, Question, chat_utterance, parse_json_reply
from bot.captions import Utterance
from bot.mock_llm import ScriptedLLM

LEAVE = {"reply": None, "leave": True}


def test_LEAVE_a_typed_misspelled_request_to_leave_gets_one_goodbye_and_marks_the_leave():
    b, _ = _brain(LEAVE)
    msg = b.quick_reply([chat_utterance("Sacheev", "Tilo leaev", 10.0)], 10.0)
    assert msg is not None and msg.text == GOODBYE_LINE and b.leave_wanted is True


def test_LEAVE_a_spoken_permission_to_leave_one_on_one_is_a_leave():
    b, _ = _brain(LEAVE)
    msg = b.quick_reply([Utterance("Sacheev", "Alright, you may leave now", 10.0)], 10.0)
    assert msg is not None and msg.text == GOODBYE_LINE and b.leave_wanted is True


def test_LEAVE_an_overheard_line_never_makes_tilo_leave():
    b, _ = _brain(LEAVE, sole=False)
    q = Question("Priya Nair", "I have to leave soon", 10.0, False)
    assert b._quick_message(json.dumps(LEAVE), [], 10.0, q) is None and b.leave_wanted is False


def test_LEAVE_the_prompt_asks_the_model_for_the_leave_intent_in_both_modes():
    for prompt in (QUICK_PROMPT, QUICK_PROMPT_ACTIONS):
        assert '"leave": true' in prompt


def test_LEAVE_the_session_leaves_only_after_the_goodbye_was_delivered(monkeypatch, tmp_path):
    s = _session(monkeypatch, tmp_path, None)
    delivered = []

    def deliver(msg, done=None, turn=None):
        assert s.leave_requested is False  # not before the goodbye goes out
        delivered.append(msg.text)
        if done:
            done(True, {"outcome": "ok", "first_output_s": 0.1, "chat_typing_s": 0.1})

    s._queue_delivery = deliver
    s.brain.llm = ScriptedLLM([json.dumps(LEAVE)])
    s.brain.leave_wanted = False

    async def run():
        msg = s.brain.quick_reply([chat_utterance("Sacheev", "Tilo leaev", 10.0)], 10.0)
        task = asyncio.get_running_loop().create_future()
        task.set_result((msg, 0.2, {"question": "q", "detected": 0.0, "first_seen": 0.0, "stt_final": None}))
        await s._finish_quick(task)

    asyncio.run(run())
    assert delivered == [GOODBYE_LINE] and s.leave_requested is True


def test_BOARD_the_board_the_model_names_is_kept_however_it_is_written():
    for board, want in (("team", "team"), ("Team", "team"), ("team board", "team"), ("the team board", "team")):
        raw = {"name": "create_pin", "args": {"title": "Unfinished demo video", "board": board}}
        assert action_talk.proposal(raw, "Sacheev", one_on_one=True).args["board"] == want, board
    for board in ("personal", "Personal board", None, "my board"):
        raw = {"name": "create_pin", "args": {"title": "x", "board": board}}
        assert action_talk.proposal(raw, "Sacheev", one_on_one=True).args["board"] == "personal", board
    assert "recent_exchanges" in action_talk.ACTIONS_TEXT  # the board named in Tilo's own last question counts


def test_NO_after_a_no_only_the_one_line_is_said(monkeypatch, tmp_path):
    s = _session(monkeypatch, tmp_path, type("A", (), {"run": lambda self, *a: None})())
    s.brain.pending_action = action_talk.PendingAction("Asha Rao", None, "create_pin", {"title": "x", "board": "team"})
    s.record(Utterance("Asha Rao", "No.", 20.0))
    assert s.said == ["Okay, I won't."]
    s.brain.llm = ScriptedLLM([json.dumps({"reply": "Understood, I will not add it to the team board."})])
    later = s.brain_elapsed() + 5.0
    assert s.brain.quick_reply([Utterance("Asha Rao", "Don't put that on the board", later)], later) is None


def test_JSON_a_reply_with_text_around_its_json_is_still_read():
    assert parse_json_reply('Sure! {"reply": "Paris."} Hope that helps.') == {"reply": "Paris."}
    assert parse_json_reply('```json\n{"reply": null, "leave": true}\n```') == {"reply": None, "leave": True}


def test_JSON_a_failed_quick_reply_leaves_a_stage_line_with_the_failure_type_only(caplog):
    b, _ = _brain()
    b.llm = ScriptedLLM(["not json at all"])
    with caplog.at_level(logging.WARNING, logger="bot.cloud_run"):
        b.quick_reply([chat_utterance("Sacheev", "Can you pin up the secret plan to the team board?", 10.0)], 10.0)
    lines = [r.getMessage() for r in caplog.records if r.name == "bot.cloud_run"]
    assert lines == ["stage quick_failed reason=JSONDecodeError"]
