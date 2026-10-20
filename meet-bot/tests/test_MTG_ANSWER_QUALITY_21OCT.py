"""Owner feedback 21 Oct on the live bot (00028): "Its working but its not answering certain things properly and
repeats answers". Live call tdc-ofqv-qfg: one question answered two or three times (live partial, final caption and
the typed copy), "Sorry, I didn't catch that" for a fragment, an invented agenda, and "As an AI"."""

import json

from bot.brain import Agenda, Brain
from bot.captions import Utterance
from bot.instant import instant_answer
from bot.mock_llm import ScriptedLLM
from bot.session import LiveSession
from bot.wake import WakeSettings


def _brain(*replies, placeholder=False):
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
    b.agenda_placeholder = placeholder
    return b, llm


def _ask(b, speaker, text, t):
    msg = b.quick_reply([Utterance(speaker, text, t)], t)
    if msg is not None:
        b.commit_chat(msg, t)
    return msg


def test_QUALITY_a_question_is_answered_once_whatever_copy_of_it_arrives_next():
    b, llm = _brain("Yes, I can hear you.", "Paris is the capital of France.", "Again.", "Again.", "Again.")
    assert _ask(b, "Sam (chat)", "Can you hear me?", 10).text == "Yes, I can hear you."
    assert _ask(b, "Sam", "can you hear me", 14) is None  # the spoken copy of the typed question
    assert _ask(b, "Sam", "What is the capital of France?", 30).text == "Paris is the capital of France."
    assert _ask(b, "Sam", "so what is the capital of France", 33) is None  # a longer caption of the same question
    assert _ask(b, "Sam", "capital of France?", 36) is None  # a shorter one
    assert len(llm.calls) == 2


def test_QUALITY_the_same_question_asked_again_later_is_answered_again():
    b, _ = _brain("Paris.", "Still Paris.")
    assert _ask(b, "Sam", "What is the capital of France?", 10).text == "Paris."
    assert _ask(b, "Sam", "What is the capital of France?", 45).text == "Still Paris."  # past the 20 s window


def test_QUALITY_a_fragment_gets_silence_not_sorry_unless_tilo_was_called_by_name():
    b, _ = _brain("[[UNCLEAR]]", "[[UNCLEAR]]")
    assert _ask(b, "Sam", "what is the um", 10) is None
    named = _ask(b, "Sam", "Tilo, um what is the", 40)
    assert named is not None and "catch" in named.text


def test_QUALITY_no_as_an_ai_and_first_person():
    b, _ = _brain("As an AI, I don't have a country, but the capital of France is Paris.")
    msg = _ask(b, "Sam", "What is your capital, France?", 10)
    assert msg is not None and not msg.text.lower().startswith("as an ai")
    assert "Paris" in msg.text


def test_QUALITY_placeholder_agenda_is_never_invented():
    b, llm = _brain(placeholder=True)
    msg = _ask(b, "Sam", "What's the agenda today?", 120)
    assert msg is not None and "no agenda" in msg.text.lower() and "minute" not in msg.text.lower()
    assert llm.calls == []
    assert "no agenda" in instant_answer("what is the agenda", b.state, 120, 2700, [], agenda_set=False).lower()


def test_QUALITY_short_partials_without_a_question_mark_wait_longer_before_they_count():
    assert LiveSession.idle_needed("what is the", 1.0) > LiveSession.idle_needed("what is the capital of France", 1.0)
    assert LiveSession.idle_needed("Tilo, what is next?", 0.5) == 0.5


def test_QUALITY_tilos_own_speech_captioned_back_is_not_input():
    assert LiveSession.echoes_own_speech("81 + 81 is 162. 81 plus 81 equals 16.", ["81 plus 81 equals 162."])
    assert LiveSession.echoes_own_speech("the capital of France is Paris", ["The capital of France is Paris."])
    assert not LiveSession.echoes_own_speech("what is the capital of Spain?", ["The capital of France is Paris."])
    assert not LiveSession.echoes_own_speech("can you hear me", [])
