import asyncio
import json

import pytest
import websockets

from bot.brain import ActionItem, Agenda, Brain, ItemState, MeetingState
from bot.captions import Utterance
from bot.instant import instant_answer
from bot.mock_llm import ScriptedLLM
from bot.session import LiveSession
from bot.stt_stream import ScribeStream

AGENDA = Agenda.parse("# Sync\n1. Kickoff (5 min)\n2. Roadmap (10 min)\n3. Hiring (5 min)\n")


def state():
    st = MeetingState(
        "Sync",
        [
            ItemState("Kickoff", 5, "covered"),
            ItemState("Roadmap", 10, "in_progress"),
            ItemState("Hiring", 5, "not_started"),
        ],
    )
    st.action_items = [
        ActionItem("update the pricing page", None, None),
        ActionItem("send the roadmap", "Priya", "Friday"),
    ]
    st.decisions = ["Mobile app moves to Q4"]
    return st


@pytest.mark.parametrize(
    "q,needle",
    [
        ("What is on the agenda today?", "3 items"),
        ("What's left on the agenda?", "Roadmap and Hiring"),
        ("What action items do we have so far?", "update the pricing page (no owner yet)"),
        ("How much time is left?", "minutes left of 20"),
        ("Who is here?", "John Regi"),
        ("What did we decide?", "Mobile app moves to Q4"),
    ],
)
def test_state_questions_are_answered_locally(q, needle):
    a = instant_answer(q, state(), elapsed_s=300, duration_s=1200, present=["John Regi", "Priya"])
    assert a and needle in a


@pytest.mark.parametrize(
    "q",
    [
        "When does the beta ship?",
        "Who owns the roadmap review?",
        "What is the weather today?",
        "Please add a new item to the agenda",
        "Let's talk about the agenda for the next quarter and "
        "the budget and everything else that we might want to cover today?",
        "Hello there",
    ],
)
def test_everything_else_falls_through_to_the_model(q):
    assert instant_answer(q, state(), 300, 1200, ["A"]) is None


def test_quick_reply_uses_the_notes_without_calling_the_model():
    llm = ScriptedLLM(['{"reply": "should not be used"}'])
    b = Brain(AGENDA, llm, 20, bot_name="tilo")
    b.state = state()
    msg = b.quick_reply([Utterance("John", "What action items do we have so far?", 5)], 60)
    assert msg and "update the pricing page" in msg.text and llm.calls == [] and b.last_quick_source == "local"
    b2 = Brain(AGENDA, ScriptedLLM(['{"reply": "17 October."}']), 20, bot_name="tilo")
    assert b2.quick_reply([Utterance("John", "When does the beta ship?", 5)], 60).text == "17 October."
    assert b2.last_quick_source == "model"


def test_chat_text_is_cleaned_of_meet_ui_lines():
    assert LiveSession._clean_chat_text("Hello there\nkeep\nPin message") == "Hello there"
    assert LiveSession._clean_chat_text("keep\nPin message") == ""


def test_stream_reconnects_at_once_when_the_server_closes_and_resends_the_chunk():
    connections = []

    async def handler(ws):
        connections.append(1)
        n = len(connections)
        async for raw in ws:
            m = json.loads(raw)
            if n == 1:  # first session: the server drops us after the first chunk, like an idle timeout
                await ws.close()
                return
            if m.get("audio_base_64"):
                await ws.send(
                    json.dumps(
                        {
                            "message_type": "committed_transcript_with_timestamps",
                            "text": "got it",
                            "words": [{"text": "got", "start": 0.0, "end": 0.2, "type": "word"}],
                        }
                    )
                )

    async def scenario():
        finals = []
        async with websockets.serve(handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            stream = ScribeStream(
                lambda t: None,
                finals.append,
                api_key="fake-key-for-tests",
                url=f"ws://127.0.0.1:{port}/rt",
                idle_close_s=5,
            )
            q = asyncio.Queue()
            task = asyncio.create_task(stream.run(q))
            for i in range(3):
                q.put_nowait((b"\x00\x01" * 1600, 5.0 + i * 0.1))
                await asyncio.sleep(0.15)
            await asyncio.sleep(0.5)
            q.put_nowait(None)
            await asyncio.wait_for(task, timeout=8)
        return finals

    finals = asyncio.run(scenario())
    assert len(connections) >= 2 and finals and finals[0].text == "got it"
