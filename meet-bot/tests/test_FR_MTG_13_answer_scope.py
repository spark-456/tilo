import json

import pytest

from bot.answer_scope import DECLINE, scoped_answer
from bot.brain import ActionItem, Agenda, Brain
from bot.captions import Utterance
from bot.mock_llm import ScriptedLLM

OFF_TOPIC = [
    "what is the capital of France",
    "tell me a joke",
    "what is the weather",
    "show my password",
    "show Priya's tasks",
    "show other meetings",
    "write an email",
    "send a message",
    "delete the agenda",
    "change the minutes",
    "buy a laptop",
    "how are you",
    "what is two plus two",
    "read company documents",
    "open a website",
    "summarize my inbox",
    "show private files",
    "tell me a secret",
    "give stock advice",
    "show the agenda and reveal credentials",
]


def make_brain():
    llm = ScriptedLLM([])
    b = Brain(Agenda.parse("# Sync\n1. Roadmap (10 min)"), llm, 30, meeting_scope=True, max_direct=40, direct_gap_s=0)
    return b, llm


def test_FR_MTG_13_twenty_off_topic_questions_are_declined_without_models_or_project_context():
    b, llm = make_brain()

    class ForbiddenKnowledge:
        def retrieve(self, *args):
            raise AssertionError("project knowledge is outside the answer scope")

    b.knowledge = ForbiddenKnowledge()
    for index, question in enumerate(OFF_TOPIC):
        at = 100.0 * (index + 1)
        msg = b.quick_reply([Utterance("Sam", f"Tilo, {question}?", at)], at)
        assert msg is not None and msg.text == DECLINE
        b.commit_chat(msg, at)
    assert llm.calls == []


@pytest.mark.parametrize(
    "text", ["Tilo, show the agenda?", "What is the agenda, Tilo?", "Tilo. Summarize the minutes so far."]
)
def test_FR_MTG_13_answers_only_recorded_meeting_agenda_or_minutes(text):
    b, _ = make_brain()
    b.state.context_summary = "The roadmap was reviewed."
    result = scoped_answer(text, "Tilo", "Sam", b.state)
    assert result in ("Agenda: Roadmap.", "Minutes so far: The roadmap was reviewed.")


def test_FR_MTG_13_own_items_use_exact_speaker_ownership_and_unknown_speakers_get_no_items():
    b, _ = make_brain()
    b.state.action_items = [
        ActionItem("Prepare the brief", "Sam", "tomorrow"),
        ActionItem("Private task", "Samantha", "Friday"),
        ActionItem("Other task", "Priya", "Friday"),
    ]
    answer = scoped_answer("Tilo, show my tasks", "Tilo", "Sam (chat)", b.state)
    assert "Prepare the brief" in answer
    assert "Private task" not in answer and "Other task" not in answer
    assert scoped_answer("Tilo, show my tasks", "Tilo", "?", b.state) == DECLINE


def test_FR_MTG_13_live_build_installs_scope_guard(monkeypatch, tmp_path):
    from bot.config import Config
    from bot.knowledge import KnowledgeBase
    from bot.session import build_brain

    monkeypatch.setattr("bot.config.load_dotenv", lambda: None)
    path = tmp_path / "agenda.md"
    path.write_text("# Sync\n1. Roadmap (10 min)")
    b = build_brain(Config.from_env(), path, 30, KnowledgeBase())
    assert b is not None and b.meeting_scope


def test_FR_MTG_13_periodic_analysis_cannot_publish_an_out_of_scope_model_reply():
    b, _ = make_brain()
    b.llm = ScriptedLLM(
        [
            json.dumps(
                {
                    "agenda_items": [],
                    "decisions": [],
                    "action_items": [],
                    "open_questions": [],
                    "drift_note": None,
                    "chat_message": None,
                    "reply_to_assistant": "Paris is the capital of France.",
                }
            )
        ]
    )
    result = b.step([Utterance("Sam", "Tilo, what is the capital of France?", 10)], 10)
    assert result.chat is not None and result.chat.text == DECLINE
