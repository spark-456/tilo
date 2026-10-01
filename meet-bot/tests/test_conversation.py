"""CV-01: Tilo talks like a person when spoken to: any topic, no keywords, no question mark needed."""

import json

import pytest

from bot.brain import QUICK_PROMPT, Agenda, Brain, question_in
from bot.captions import Utterance
from bot.mock_llm import ScriptedLLM

AGENDA = Agenda.parse("# Sync\n1. Roadmap (10 min)\n2. Hiring (5 min)\n")


def said(text, t=10.0, who="Sam"):
    return Utterance(who, text, t)


def brain(*replies, **kw):
    llm = ScriptedLLM(list(replies))
    return Brain(AGENDA, llm, 30, bot_name="Tilo", **kw), llm


@pytest.mark.parametrize(
    "text",
    [
        "Hey Tilo, tell me a joke",
        "Tilo how are you doing today",
        "Tillo, what do you think about that",  # a common mishearing of the name
        "Okay so can you explain it Tilo",
        "Tilo",  # called by name alone
    ],
)
def test_CV_01_being_called_by_name_is_enough_no_question_mark_needed(text):
    q = question_in(said(text), "Tilo")
    assert q is not None and q.addressed


@pytest.mark.parametrize(
    "text",
    [
        "I told Tilo about the budget yesterday afternoon",  # talking about Tilo, not to it
        "We should ship the beta in October",
        "Priya, can you take the pricing page",
    ],
)
def test_CV_01_talk_between_people_is_not_addressed(text):
    assert question_in(said(text), "Tilo", "addressed") is None


def test_CV_01_typed_chat_of_any_kind_is_addressed():
    chat = Utterance("Sam (chat)", "how are you", 5.0)
    q = question_in(chat, "Tilo")
    assert q is not None and q.addressed


def test_CV_01_a_general_question_is_answered_by_the_model_and_not_refused():
    b, llm = brain('{"reply": "Paris."}')
    msg = b.quick_reply([said("Tilo, what is the capital of France?")], 12)
    assert msg and msg.text == "Paris." and b.last_quick_source == "model"
    assert '"addressed_to_assistant": true' in llm.calls[0][1]


def test_CV_01_small_talk_gets_an_answer_without_the_name_when_typed():
    b, _ = brain('{"reply": "Doing well, thanks for asking."}')
    msg = b.quick_reply([Utterance("Sam (chat)", "how are you", 5.0)], 6)
    assert msg and msg.text.startswith("Doing well")


def test_CV_01_a_long_chatty_reply_is_shortened_not_dropped():
    two = "A" * 200 + ". " + "B" * 200 + "."  # two sentences, 400 characters: over the limit together
    b, _ = brain(json.dumps({"reply": two}))
    msg = b.quick_reply([said("Tilo, tell me about the history of Rome")], 12)
    assert msg and msg.text == "A" * 200 + "."


def test_CV_01_a_follow_up_right_after_a_reply_needs_no_name():
    b, _ = brain('{"reply": "Because it is the cheapest."}')
    first = said("Tilo, which plan should we pick?", 10)
    b.commit_chat(b.quick_reply([first], 12), 12)
    assert question_in(said("and why is that?", 20), "Tilo", "addressed") is None  # no memory without the Brain
    follow = said("and why is that?", 20)
    assert b.question_in(follow).addressed  # within the window after Tilo's reply
    assert b.question_in(said("tell me more", 21)).addressed  # a request, no question mark
    assert b.question_in(said("we should ship it in October", 22)) is None  # people talking to each other
    late = b.question_in(said("and why is that now?", 60))
    assert late is not None and not late.addressed  # a minute later it is overheard talk again


def test_CV_01_the_prompt_separates_conversation_from_overheard_talk():
    assert "addressed_to_assistant is true" in QUICK_PROMPT and "addressed_to_assistant is false" in QUICK_PROMPT
    assert "general knowledge" in QUICK_PROMPT and "untrusted" in QUICK_PROMPT
    assert "Yes?" in QUICK_PROMPT  # called by name alone


def test_CV_01_an_overheard_general_question_is_still_not_answered():
    b, _ = brain('{"reply": null}')
    assert b.quick_reply([said("What is the capital of France do you think?")], 12) is None  # not aimed at Tilo


def test_CV_01_statements_wait_a_little_longer_than_questions_before_answering():
    from bot.session import LiveSession

    assert LiveSession.idle_needed("Tilo, what is next?", 0.5) == 0.5
    assert LiveSession.idle_needed("Tilo tell me a joke", 0.5) == pytest.approx(1.3)


def test_CV_01_the_default_reply_budget_fits_a_conversation(monkeypatch):
    from bot.config import Config

    monkeypatch.setattr("bot.config.load_dotenv", lambda path=None: None)
    monkeypatch.delenv("MAX_DIRECT_REPLIES", raising=False)
    assert Config.from_env().max_direct_replies >= 40
