"""VA-02: question bookkeeping, typed chat, fallback lines and Scribe keyterms. Fakes only."""

import asyncio

import pytest

from bot.brain import (
    COULD_NOT_GET_LINE,
    NO_ANSWER_LINE,
    UNCLEAR_LINE,
    Agenda,
    Brain,
    Busy,
    LLMUnavailable,
    chat_utterance,
)
from bot.captions import Utterance
from bot.keyterms import build_keyterms
from bot.knowledge import KnowledgeBase
from bot.mock_llm import ScriptedLLM
from bot.stt_stream import ScribeStream

AGENDA = Agenda.parse("# Sync\nRequired: John Regi, Priya\n1. Roadmap (10 min)\n2. Hiring plan (5 min)\n")
FAKE_KEY = "el-" + "k3y9" * 6


def brain(*replies, **kw):
    llm = ScriptedLLM(list(replies))
    return Brain(AGENDA, llm, 30, bot_name="Tilo", **kw), llm


def said(text, t, who="John"):
    return Utterance(who, text, t)


def test_VA_02_a_repeated_question_is_attempted_again():
    """29 Sep: 'When does the leadership meet?' got no reply, was asked again, and was dropped because the text matched."""
    b, llm = brain('{"reply": null}', '{"reply": "Leadership meets on Friday."}')
    first = said("When does the leadership meet?", 10)
    assert b.quick_reply([first], 12) is None and len(llm.calls) == 1  # unanswerable, tried once
    assert not b.has_pending_question([first])  # the same utterance is never retried
    again = said("When does the leadership meet?", 40)
    assert b.has_pending_question([first, again])
    msg = b.quick_reply([first, again], 42)
    assert msg and msg.text == "Leadership meets on Friday." and len(llm.calls) == 2


def test_VA_02_a_partial_and_its_final_are_one_question():
    b, llm = brain('{"reply": "Friday."}')
    partial = said("When does the leadership meet?", 12.4)  # first seen as a live partial, a moment after speech began
    b.quick_reply([partial], 13)
    final = said("When does the leadership meet?", 11.9)  # the committed final carries the true start time
    assert not b.has_pending_question([final])


def test_VA_02_an_answered_question_can_be_asked_and_answered_again():
    b, llm = brain('{"reply": "The beta ships in October."}')
    q1 = said("When does the beta ship?", 10)
    msg = b.quick_reply([q1], 11)
    b.commit_chat(msg, 11)
    assert not b.has_pending_question([q1])
    q2 = said("When does the beta ship?", 60)  # nobody heard it: asked again
    msg2 = b.quick_reply([q1, q2], 62)
    assert msg2 and msg2.text == "The beta ships in October."


def test_VA_02_typed_chat_without_a_question_mark_is_answered():
    b, llm = brain('{"reply": "The beta ships on 17 October."}')
    u = chat_utterance("Sam", "When does the beta ship", 30)
    assert u.speaker == "Sam (chat)" and u.text == "When does the beta ship"
    msg = b.quick_reply([u], 31)
    assert msg and msg.text == "The beta ships on 17 October."
    assert b.last_quick_source == "model" and len(llm.calls) == 1


def test_VA_02_a_chat_message_that_is_not_a_question_gets_no_fallback():
    b, _ = brain('{"reply": null}')
    assert b.quick_reply([chat_utterance("Sam", "Design doc is at example.org/doc", 5)], 6) is None


def test_VA_02_no_answer_sentinel_gives_the_fallback_line_when_addressed():
    asked = said("Tilo, what is the budget for Q4?", 10)
    b, _ = brain('{"reply": "[[NO_ANSWER]]"}')
    msg = b.quick_reply([asked], 11)
    assert msg and msg.kind == "direct_reply" and msg.text == NO_ANSWER_LINE
    b2, _ = brain('{"reply": "[[UNCLEAR]]"}')
    assert b2.quick_reply([asked], 11).text == UNCLEAR_LINE
    b3, _ = brain('{"reply": "[[NO_ANSWER]]"}')  # typed chat is always addressed
    assert b3.quick_reply([chat_utterance("Sam", "what is the Q4 budget", 10)], 11).text == NO_ANSWER_LINE


def test_VA_02_an_unaddressed_question_never_gets_a_fallback_line():
    b, _ = brain('{"reply": "[[NO_ANSWER]]"}')
    assert b.quick_reply([said("Who should own the pricing page work?", 10)], 11) is None
    b2, _ = brain('{"reply": null}')
    assert b2.quick_reply([said("Who should own the pricing page work?", 10)], 11) is None


def test_VA_02_addressed_but_null_reply_is_not_silence():
    b, _ = brain('{"reply": null}')
    msg = b.quick_reply([said("Tilo, when is the launch?", 10)], 11)
    assert msg and msg.text == NO_ANSWER_LINE


class DownLLM:
    def generate(self, system, prompt):
        raise LLMUnavailable("down")


def test_VA_02_a_model_outage_on_an_addressed_question_is_not_silence():
    b = Brain(AGENDA, DownLLM(), 30, bot_name="Tilo")
    assert b.quick_reply([said("Tilo, when is the launch?", 10)], 11).text == COULD_NOT_GET_LINE
    b2 = Brain(AGENDA, DownLLM(), 30, bot_name="Tilo")
    assert b2.quick_reply([said("When is the launch date for this?", 10)], 11) is None


class BusyFast:
    async def generate(self, system, prompt, **kw):
        raise Busy("429")


def test_VA_02_a_busy_fast_model_gives_the_could_not_get_line_when_addressed():
    b = Brain(AGENDA, ScriptedLLM(["{}"]), 30, bot_name="Tilo", fast=BusyFast())
    msg = asyncio.run(b.aquick_reply([chat_utterance("Sam", "when does it ship", 10)], 11))
    assert msg and msg.text == COULD_NOT_GET_LINE


def test_VA_02_fallback_lines_count_against_the_reply_budget():
    b, _ = brain('{"reply": "[[NO_ANSWER]]"}')
    first = b.quick_reply([chat_utterance("Sam", "what is the budget", 10)], 11)
    b.commit_chat(first, 11)
    second = b.quick_reply([chat_utterance("Sam", "and the headcount", 12)], 13)
    assert second is None  # inside the 6 s gap between direct replies


def test_VA_02_keyterms_hold_names_titles_and_frequent_project_terms():
    kb = KnowledgeBase()
    kb.add_text("plan.md", "Kestrel ships in October. The Kestrel beta needs Kestrel docs. Lumen is the cache.", "file")
    terms = build_keyterms("Tilo", ["John Regi", "Priya"], ["Roadmap", "Hiring plan"], kb)
    assert terms[0] == "Tilo"
    assert {"John Regi", "Priya", "Roadmap", "Hiring plan", "Kestrel"} <= set(terms)
    assert terms.index("Kestrel") > terms.index("Hiring plan")  # names and titles come before document terms
    lowered = [t.lower() for t in terms]
    assert "the" not in lowered and "that" not in lowered  # common words are not keyterms
    assert "Lumen" not in terms  # mentioned once: not a frequent term


def test_VA_02_keyterms_are_unique_and_capped_at_50():
    kb = KnowledgeBase()
    kb.add_text("big.md", " ".join(f"Word{i} Word{i} Word{i}" for i in range(200)), "file")
    terms = build_keyterms("Tilo", ["Tilo", "tilo", "Priya"], [], kb)
    assert len(terms) == 50 and len({t.lower() for t in terms}) == 50


def test_VA_02_scribe_accepts_50_keyterms_and_new_ones_for_the_next_connection():
    s = ScribeStream(lambda t: None, lambda f: None, api_key=FAKE_KEY, keyterms=[f"term{i}" for i in range(80)])
    assert len(s.keyterms) == 50
    s.set_keyterms(["Tilo", "Priya"])
    assert s.keyterms == ["Tilo", "Priya"] and "keyterms=Priya" in s._full_url(True)
    assert FAKE_KEY not in s._full_url(True)


@pytest.mark.parametrize("text", ["Hi", "  spaced out  "])
def test_VA_02_chat_utterance_keeps_the_text_and_marks_the_sender_as_chat(text):
    u = chat_utterance("Sam", text, 4.2)
    assert u.speaker == "Sam (chat)" and u.text == text.strip() and u.t == 4.2
