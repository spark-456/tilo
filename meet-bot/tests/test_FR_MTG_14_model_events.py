import pytest

from bot.brain import Agenda, Brain, LLMUnavailable
from bot.captions import Utterance


@pytest.mark.parametrize("fail", [False, True])
def test_FR_MTG_14_thinking_tracks_only_an_actual_model_call_and_clears_on_failure(fail):
    events = []

    class Model:
        def generate(self, system, prompt):
            assert events == ["model_start"]
            if fail:
                raise LLMUnavailable("offline fake")
            return '{"reply":"A recorded answer."}'

    b = Brain(Agenda.parse("# Sync\n1. Roadmap (10 min)"), Model(), 30)
    b.model_event = events.append
    b.quick_reply([Utterance("Sam", "Tilo, explain the roadmap?", 10)], 10)
    assert events == ["model_start", "model_end"]


def test_FR_MTG_14_a_local_reply_has_no_thinking_event():
    from bot.mock_llm import ScriptedLLM

    events = []
    b = Brain(Agenda.parse("# Sync\n1. Roadmap (10 min)"), ScriptedLLM([]), 30)
    b.model_event = events.append
    b.quick_reply([Utterance("Sam (chat)", "what is the agenda", 10)], 10)
    assert events == []
