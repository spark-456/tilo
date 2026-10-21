"""Owner's live test 21 Oct 09:22 (00031): the bot said "I have added the Google AI builder cup submission
requirements ... to our new meeting agenda" though it has no way to change anything, and it appended "we haven't set
an agenda yet, would you like me to note one down?" to almost every reply. The bot never claims an action it cannot
take, and the agenda is mentioned only when asked."""

import json

from bot.brain import CANT_DO_AGAIN_LINE, CANT_DO_LINE, QUICK_PROMPT, Agenda, Brain
from bot.captions import Utterance
from bot.instant import NO_AGENDA_LINE
from bot.mock_llm import ScriptedLLM
from bot.wake import WakeSettings


def _brain(*replies):
    llm = ScriptedLLM([json.dumps({"reply": r}) for r in replies])
    b = Brain(
        Agenda.parse("# Meeting\n1. Discussion and decisions (45 min)"),
        llm,
        45,
        max_direct=40,
        direct_gap_s=0,
        wake_settings=WakeSettings(),
    )
    b.sole_human = True
    b.agenda_placeholder = True
    return b, llm


def _ask(b, text, t):
    msg = b.quick_reply([Utterance("Sam", text, t)], t)
    if msg is not None:
        b.commit_chat(msg, t)
    return msg


def test_NO_FALSE_ACTIONS_a_claimed_action_is_replaced_by_cant_do_yet():
    b, _ = _brain(
        "I have added the Google AI builder cup submission requirements to our new meeting agenda.",
        "Done, I've scheduled a follow-up meeting for Friday at 3 pm.",
        "Sure, I'll pin that to your team board.",
    )
    assert _ask(b, "add the submission requirements to the agenda", 10).text == CANT_DO_LINE
    assert _ask(b, "schedule a follow-up on Friday at 3", 40).text == CANT_DO_AGAIN_LINE  # never the same line twice
    assert _ask(b, "pin this to the team board please", 70).text == CANT_DO_LINE


def test_NO_FALSE_ACTIONS_ordinary_answers_are_untouched():
    b, _ = _brain("The capital of France is Paris.", "I think the plan makes sense, but check the budget.")
    assert _ask(b, "what is the capital of France?", 10).text == "The capital of France is Paris."
    assert _ask(b, "what do you think of the plan?", 40).text == "I think the plan makes sense, but check the budget."


def test_NO_FALSE_ACTIONS_agenda_only_when_asked_and_no_offer_to_note_one():
    assert "note" not in NO_AGENDA_LINE.lower()
    assert "only when asked" in QUICK_PROMPT and "offer to note one" not in QUICK_PROMPT
    assert "cannot take actions" in QUICK_PROMPT
    b, _ = _brain("Paris.")
    assert _ask(b, "What's the agenda today?", 10).text == NO_AGENDA_LINE
