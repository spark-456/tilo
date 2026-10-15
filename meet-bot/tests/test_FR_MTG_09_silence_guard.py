"""FR-MTG-09 (cost): the brain makes no model call while nobody speaks (MEETING-LOOP-DESIGN fact 4, item 4).

`Brain.step` used to call the model every 20 s from the moment the gate opened: ~135 of the 200 per-meeting model
calls in a 45 minute meeting, with the output unused on Cloud Run. A step now asks the model only when a new
settled utterance exists, or a question put to Tilo is still waiting for its answer.
"""

import json

from bot.brain import Agenda, Brain, ChatMessage
from bot.captions import Utterance
from bot.mock_llm import ScriptedLLM

AGENDA = Agenda.parse("# Sync\n1. Roadmap (10 min)\n2. Hiring (5 min)\n")


def valid(reply: str | None = None) -> str:
    return json.dumps(
        {
            "agenda_items": [],
            "decisions": [],
            "action_items": [],
            "open_questions": [],
            "drift_note": None,
            "chat_message": None,
            "reply_to_assistant": reply,
        }
    )


def said(text, t, who="Sam"):
    return Utterance(who, text, t)


def make(*replies, **kw):
    llm = ScriptedLLM(list(replies) or [valid()])
    return Brain(AGENDA, llm, 30, bot_name="Tilo", **kw), llm


def test_FR_MTG_09_thirty_silent_minutes_make_no_model_call():
    brain, llm = make()
    brain.policy.proactive = False  # as built by `build_brain` unless the operator opts in to nudges
    for tick in range(90):  # a step every 20 s for 30 minutes, nobody ever speaks
        result = brain.step([], tick * 20.0)
        assert result.ok and result.chat is None
    assert llm.calls == []


def test_FR_MTG_09_an_unchanged_transcript_is_analysed_once():
    brain, llm = make()
    window = [said("We should lock the roadmap this week", 5.0)]
    for tick in range(30):
        assert brain.step(window, 20.0 * tick).ok
    assert len(llm.calls) == 1


def test_FR_MTG_09_each_new_utterance_is_analysed_again():
    brain, llm = make()
    window = [said("We should lock the roadmap this week", 5.0)]
    brain.step(window, 20.0)
    brain.step(window, 40.0)
    window = [*window, said("Priya will draft it by Friday", 50.0, "Lee")]
    brain.step(window, 60.0)
    brain.step(window, 80.0)
    assert len(llm.calls) == 2


def test_FR_MTG_09_a_failed_analysis_is_retried_on_the_same_transcript():
    brain, llm = make("not json", "not json", "not json", valid())
    window = [said("We should lock the roadmap this week", 5.0)]
    assert not brain.step(window, 20.0).ok  # three invalid replies: the step fails
    assert brain.step(window, 40.0).ok  # the same transcript is tried again, not skipped as seen
    assert len(llm.calls) == 4


def test_FR_MTG_09_a_waiting_question_still_gets_its_answer_without_new_speech():
    brain, llm = make(valid("Four items."), valid("Four items."))
    ask = [said("Tilo, what is on the agenda?", 11.0)]
    brain.commit_chat(ChatMessage("direct_reply", "who is here", "Sam is here.", 0.5), 10.0)
    held = brain.step(ask, 12.0)
    assert held.chat is None  # inside the direct-reply gap: held back
    answered = brain.step(ask, 20.0)  # no new utterance, but the question is still waiting
    assert answered.chat is not None and answered.chat.kind == "direct_reply"
    assert answered.chat.text == "Four items."
    brain.commit_chat(answered.chat, 20.0)
    calls = len(llm.calls)
    brain.step(ask, 40.0)  # answered: silence again
    assert len(llm.calls) == calls


def test_FR_MTG_09_the_time_warning_needs_no_model_and_no_speech():
    brain, llm = make()
    result = brain.step([], 1300.0)  # 500 s left of a 30 minute meeting
    assert llm.calls == []
    assert result.chat is not None and result.chat.kind == "time_warning"
