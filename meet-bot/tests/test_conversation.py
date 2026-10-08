"""CV-01: Tilo talks like a person when spoken to: any topic, no keywords, no question mark needed."""

import json

import pytest
from test_ui import session  # noqa: F401

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


# -- CV-02: bad microphones. Whoever is alone with Tilo is talking to it, whatever the recogniser makes of the words ----
def test_CV_02_a_person_alone_with_tilo_is_always_addressed_however_garbled_the_words():
    b, _ = brain('{"reply": "Why did the chicken cross the road?"}')
    b.sole_human = True
    q = b.question_in(said("Please, tell me your joy.", 30))  # "joke" heard as "joy": no name, no question mark
    assert q is not None and q.addressed
    assert b.question_in(said("Yes.", 31)) is None  # a fragment says nothing to answer
    b.sole_human = False
    assert (
        b.question_in(said("Please, tell me your joy.", 40)) is None
    )  # with others present, people talk among themselves


def test_CV_02_the_conversation_window_runs_from_the_last_exchange_and_lasts_30_seconds():
    b, _ = brain('{"reply": "Sure."}')
    b.quick_reply([said("Tilo, what is next?", 10)], 12)  # an addressed question opens the conversation
    assert b.question_in(said("tell me, John, a joke", 35)).addressed  # 25 s later: still talking to Tilo
    assert (
        b.question_in(said("tell me about it", 60)) is None or not b.question_in(said("tell me about it", 60)).addressed
    )


def test_CV_02_the_prompt_tells_the_model_to_repair_misheard_words():
    assert "misheard" in QUICK_PROMPT and "joke" in QUICK_PROMPT and "only_person_here" in QUICK_PROMPT


def test_CV_02_the_payload_says_when_one_person_is_alone_with_tilo():
    b, llm = brain('{"reply": "Sure."}')
    b.sole_human = True
    b.quick_reply([said("Please tell me your joy", 5)], 6)
    assert '"only_person_here": true' in llm.calls[0][1]


def test_CV_02_a_partial_and_a_reworded_final_are_one_question():
    b, llm = brain('{"reply": "Four items."}')
    b.quick_reply([said("What is on the agenda for the Q3?", 10.4)], 11)  # the live partial
    final = said("Hello. What is on the agenda for Q3?", 10.0)  # the committed final: reworded, earlier start
    assert not b.has_pending_question([final])
    repeat = said("What is on the agenda for the Q3?", 40)  # asked again half a minute later
    assert b.has_pending_question([final, repeat])


def test_CV_02_a_voice_the_plan_refuses_is_remembered_between_meetings(tmp_path):
    import asyncio

    from bot.tts import FallbackTTS, TTSError

    class Refused:
        name, sample_rate, calls = "eleven", 24000, 0

        async def stream(self, text):
            Refused.calls += 1
            raise TTSError("ElevenLabs refused text-to-speech: check your plan/credits (paid_plan_required)")
            yield b""

    class Backup:
        name, sample_rate = "espeak", 22050

        async def stream(self, text):
            yield b"\x00\x01"

    async def speak(tts):
        return [c async for c in tts.stream("hi")]

    state = tmp_path / "tts_state.json"
    asyncio.run(speak(FallbackTTS(Refused(), Backup(), state_path=state, voice_key="v1")))
    assert Refused.calls == 1 and state.exists()
    asyncio.run(speak(FallbackTTS(Refused(), Backup(), state_path=state, voice_key="v1")))  # a new meeting
    assert Refused.calls == 1  # the refused voice was not tried again
    asyncio.run(speak(FallbackTTS(Refused(), Backup(), state_path=state, voice_key="other-voice")))
    assert Refused.calls == 2  # a different voice is worth trying


def test_CV_02_the_people_panel_is_not_read_while_a_reply_is_being_delivered(session):  # noqa: F811
    import asyncio

    from test_ui import FakeBrowser

    s = session
    s.br = FakeBrowser([[]])
    s.delivering = True
    calls = []
    original = s.br.participants

    async def counting():
        calls.append(1)
        return await original()

    s.br.participants = counting
    asyncio.run(s._status_step())
    assert calls == []  # reading it opens the People panel over the chat that is being typed into
    s.delivering = False
    asyncio.run(s._status_step())
    assert calls == [1]


def test_CV_02_the_session_tells_the_brain_when_one_person_is_alone_with_tilo(session):  # noqa: F811
    import asyncio

    from test_ui import FakeBrowser

    s = session
    s.br = FakeBrowser([[]])  # its participants() lists exactly one other person
    asyncio.run(s._status_step())
    assert s.brain.sole_human is True
