import json
import os

import pytest

from bot.brain import Agenda, Brain, GeminiLLM
from bot.captions import Utterance

pytestmark = pytest.mark.skipif(not os.environ.get("GEMINI_API_KEY"), reason="GEMINI_API_KEY not set")


def test_real_gemini_returns_valid_state():
    agenda = Agenda.parse("# Sync\n1. Roadmap (10 min)\n2. Hiring (5 min)\n")
    brain = Brain(agenda, GeminiLLM(), 15)
    lines = [
        Utterance("Alex", "Let's review the roadmap. Search is the top item for Q3.", 20.0),
        Utterance("Sam", "I'll send the roadmap doc to everyone.", 60.0),
    ]
    res = brain.step(lines, 90)
    assert res.ok, res.error
    assert brain.state.items[0].status in ("in_progress", "covered")
    json.dumps(brain.state.to_dict())
