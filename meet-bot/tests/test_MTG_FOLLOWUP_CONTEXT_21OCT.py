"""Follow-ups use the call's earlier exchanges (21 Oct): "what about Germany?" after "what is the capital of France?"
must reach the model together with Tilo's own last answers, so it can answer "Berlin". Also a replay of the owner's
live call (tdc-ofqv-qfg) through the brain: one answer per question, nothing answered twice."""

import json

from bot.brain import Agenda, Brain, chat_utterance
from bot.captions import Utterance
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


def _ask(b, u, t):
    msg = b.quick_reply([u], t)
    if msg is not None:
        b.commit_chat(msg, t)
    return msg


def _payload(call):
    prompt = call[-1] if isinstance(call, tuple) else call
    return json.loads(str(prompt).split("INPUT_JSON:\n", 1)[1])


def test_FOLLOWUP_a_follow_up_question_reaches_the_model_with_the_last_answers():
    b, llm = _brain("The capital of France is Paris.", "Berlin is the capital of Germany.")
    assert _ask(b, Utterance("Sam", "What is the capital of France?", 10), 10).text == "The capital of France is Paris."
    msg = _ask(b, Utterance("Sam", "what about Germany?", 25), 25)
    assert msg is not None and msg.text == "Berlin is the capital of Germany."
    exchanges = _payload(llm.calls[1])["recent_exchanges"]
    assert exchanges[-1]["you_answered"] == "The capital of France is Paris."
    assert "capital of france" in exchanges[-1]["asked"]


def test_FOLLOWUP_owner_call_replay_gets_one_answer_per_question():
    b, llm = _brain(
        "Yes, I can hear you.",
        "The capital of France is Paris.",
        "81 plus 81 is 162.",
        "Berlin.",
    )
    events = [
        (chat_utterance("Sam", "Can you hear me?", 10), 10),
        (Utterance("Sam", "can you hear me", 13), 13),  # the spoken copy of the typed question
        (Utterance("Sam", "What is the capital of France?", 30), 30),
        (Utterance("Sam", "so what is the capital of France", 33), 33),  # a longer caption of the same question
        (Utterance("Sam", "What is 81 plus 81?", 50), 50),
        (Utterance("Sam", "81 plus 81", 53), 53),  # a shorter caption of it
        (Utterance("Sam", "What's the agenda today?", 70), 70),
        (Utterance("Sam", "what about Germany?", 90), 90),
    ]
    answers = [m.text for m in (_ask(b, u, t) for u, t in events) if m is not None]
    assert answers == [
        "Yes, I can hear you.",
        "The capital of France is Paris.",
        "81 plus 81 is 162.",
        "There's no agenda set for this meeting yet. Want me to note one?",
        "Berlin.",
    ]
    assert len(llm.calls) == 4  # the agenda answer needs no model call
