"""Owner's live retest, 21 Oct 15:23 IST: one read-back per request, one fixed line per failed attempt, nothing else.

Live, a spoken yes arrived as a partial caption before its final one. The live loop asked the model about the partial
("yes, add it") while the read-back was still waiting, so the model proposed the same action again (a second read-back)
or improvised ("I had a technical hiccup, shall we try again?"), and every extra read-back meant another yes and
another failure line. A yes or no to a waiting read-back, or a second caption of one Tilo already took, is never a
question; the same proposal is read back once; after a failed action Tilo says its fixed line only, reworded if it
fails again. And a reply mentions the agenda only when the question did."""

import asyncio
import json

from test_MTG_ACTIONS_1_bot_actions import _brain, _session

from bot import action_talk
from bot.brain import FAILED_QUIET_S, QUICK_PROMPT
from bot.captions import Utterance
from bot.meeting_actions import ActionResult
from bot.mock_llm import ScriptedLLM

PROPOSE = {"reply": None, "action": {"name": "add_agenda_item", "args": {"title": "Demo video"}}}


def _waiting(b):
    b.pending_action = action_talk.PendingAction("Asha Rao", None, "add_agenda_item", {"title": "Demo video"})
    return b.pending_action


def test_ONE_READBACK_a_partial_caption_of_the_yes_is_not_a_question_while_the_read_back_waits():
    b, llm = _brain({"reply": "Sure, adding it now!"})
    _waiting(b)
    partial = Utterance("Asha Rao", "Yes, add it please", 20.0)
    assert b.question_in(partial) is None
    assert b.quick_reply([partial], 20.0) is None and llm.calls == []  # the model is never asked about a yes


def test_ONE_READBACK_a_second_caption_of_a_yes_already_taken_is_not_a_question(monkeypatch, tmp_path):
    s = _session(monkeypatch, tmp_path, type("A", (), {"run": lambda self, *a: ActionResult(True, "done", {})})())
    pending = _waiting(s.brain)

    async def run():
        s.record(Utterance("Asha Rao", "Yes.", 20.0))
        await asyncio.sleep(0.2)

    asyncio.run(run())
    assert s.brain.pending_action is None and s.said == [action_talk.result_line(pending, True, "done", {})]
    assert s.brain.question_in(Utterance("Asha Rao", "Yes, add it please", 20.5)) is None  # the final caption
    assert s.brain.question_in(Utterance("Asha Rao", "What else is left to do today?", 21.0)) is not None


def test_ONE_READBACK_the_same_proposal_from_the_partial_and_the_final_caption_is_read_back_once():
    b, llm = _brain(PROPOSE, PROPOSE)
    first = b.quick_reply([Utterance("Asha Rao", "add demo video to the agenda", 10.0)], 10.0)
    assert first is not None and first.text == 'Add "Demo video" to this meeting\'s agenda?'
    key = b.pending_action.key
    again = b.quick_reply([Utterance("Asha Rao", "Could you put demo video on this meeting's agenda?", 11.5)], 11.5)
    assert len(llm.calls) == 2 and again is None and b.pending_action.key == key  # the yes still matches the first


def test_ONE_READBACK_after_a_failed_action_the_model_does_not_improvise_but_a_new_request_is_read_back():
    b, _ = _brain({"reply": "I had a technical hiccup there, shall we try again?"}, PROPOSE)
    b.action_failed_at = 30.0
    assert b.quick_reply([Utterance("Asha Rao", "what happened with that one", 33.0)], 33.0) is None
    retry = b.quick_reply([Utterance("Asha Rao", "please try adding demo video again", 36.0)], 36.0)
    assert retry is not None and retry.text.startswith('Add "Demo video"')
    b.llm = ScriptedLLM([json.dumps({"reply": "It's a quarter past three."})])
    later = 30.0 + FAILED_QUIET_S + 1
    assert b.quick_reply([Utterance("Asha Rao", "what time is it right now", later)], later) is not None


def test_ONE_READBACK_one_failure_line_per_attempt_never_the_same_words_twice_in_a_row(monkeypatch, tmp_path):
    calls = []
    s = _session(
        monkeypatch,
        tmp_path,
        type("A", (), {"run": lambda self, *a: calls.append(a) or ActionResult(False, "unavailable", {})})(),
    )

    async def attempt(t):
        _waiting(s.brain)
        s.record(Utterance("Asha Rao", "yes", t))
        await asyncio.sleep(0.2)

    async def run():
        for t in (20.0, 40.0, 60.0):
            await attempt(t)

    asyncio.run(run())
    assert len(calls) == 3 and len(s.said) == 3  # one line per attempt
    assert all(a != b for a, b in zip(s.said, s.said[1:], strict=False))
    assert all("nothing was changed" in line.lower() or "didn't go through" in line.lower() for line in s.said)
    assert s.brain.action_failed_at > -1e9  # the quiet window after a failure is open


def test_ONE_READBACK_a_reply_mentions_the_agenda_only_when_the_question_did():
    remark = "I can't browse the internet or read repositories. There's no agenda set for this meeting yet."
    b, _ = _brain({"reply": remark}, {"reply": remark}, actions=False)
    msg = b.quick_reply([Utterance("Asha Rao", "can you check our GitHub repository", 10.0)], 10.0)
    assert msg is not None and msg.text == "I can't browse the internet or read repositories."
    asked = b.quick_reply([Utterance("Asha Rao", "is there an agenda and can you read the repo", 30.0)], 30.0)
    assert asked is not None and "agenda" in asked.text
    assert "one short sentence" in QUICK_PROMPT
