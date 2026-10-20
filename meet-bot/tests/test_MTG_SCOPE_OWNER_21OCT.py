"""Owner decision 21 Oct (BQ-MTG-SCOPE-OWNER-1): "tilo joined but it keeps repeating the same thing whenever i ask
something without answering my questions, make it's answers more generic and reduce the safety guardrails as well".
The meeting-only answer scope is off by default (opt-in MEETING_ANSWER_SCOPE=1), general questions reach the model,
and no reply is sent twice in a row. Real safety (the provider checks, disclosure, "Tilo leave") is unchanged."""

import json

from bot.brain import NO_ANSWER_LINE, Agenda, Brain
from bot.captions import Utterance
from bot.mock_llm import ScriptedLLM
from bot.wake import WakeSettings


def _brain(replies):
    llm = ScriptedLLM([json.dumps({"reply": r}) for r in replies])
    b = Brain(
        Agenda.parse("# Sync\n1. Roadmap (10 min)"),
        llm,
        30,
        max_direct=40,
        direct_gap_s=0,
        wake_settings=WakeSettings(),
    )
    return b, llm


def test_MTG_SCOPE_OWNER_live_build_answers_generally_unless_the_operator_opts_into_the_meeting_scope(
    monkeypatch, tmp_path
):
    from bot.config import Config
    from bot.knowledge import KnowledgeBase
    from bot.session import build_brain

    monkeypatch.setattr("bot.config.load_dotenv", lambda: None)
    monkeypatch.delenv("MEETING_ANSWER_SCOPE", raising=False)
    path = tmp_path / "agenda.md"
    path.write_text("# Sync\n1. Roadmap (10 min)")
    assert build_brain(Config.from_env(), path, 30, KnowledgeBase()).meeting_scope is False
    monkeypatch.setenv("MEETING_ANSWER_SCOPE", "1")
    assert build_brain(Config.from_env(), path, 30, KnowledgeBase()).meeting_scope is True


def test_MTG_SCOPE_OWNER_a_general_question_gets_the_models_own_answer():
    b, llm = _brain(["Paris is the capital of France."])
    msg = b.quick_reply([Utterance("Sam", "Tilo, what is the capital of France?", 10)], 10)
    assert msg is not None and msg.text == "Paris is the capital of France."
    assert len(llm.calls) == 1


def test_MTG_SCOPE_OWNER_never_the_same_reply_twice_in_a_row():
    b, _ = _brain(["[[NO_ANSWER]]", "[[NO_ANSWER]]", "It is ten past four."])
    first = b.quick_reply([Utterance("Sam", "Tilo, who owns the budget?", 10)], 10)
    assert first is not None and first.text == NO_ANSWER_LINE
    b.commit_chat(first, 10)
    assert b.quick_reply([Utterance("Sam", "Tilo, and who owns hiring?", 20)], 20) is None  # not the same line again
    third = b.quick_reply([Utterance("Sam", "Tilo, what time is it?", 30)], 30)
    assert third is not None and third.text == "It is ten past four."
