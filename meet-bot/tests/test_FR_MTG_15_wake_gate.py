import ast
import inspect
from dataclasses import replace

import pytest

from bot.brain import Agenda, Brain
from bot.captions import Utterance
from bot.mock_llm import ScriptedLLM
from bot.wake import Attention, WakeSettings, wake_gate


def test_FR_MTG_15_twenty_minute_multispeaker_replay_has_ten_responses_and_fifteen_silences():
    addressed = [
        "Tilo, what is next?",
        "What is next, Tilo?",
        "Tillo, summarize",
        "Tylo, repeat",
        "Teelo, who owns it?",
        "Tilo. What is next?",
        "Hey Tilo, remind me",
        "Tilo",
        "show the agenda Tilo",
        "hello",
    ]
    unaddressed = [
        "Where is the Tilo report?",
        "tiles",
        "Tyler, what is next?",
        "assistant, explain?",
        "What is the plan?",
        "We told Tilo about it.",
        "the Tilo report",
        "tile, repeat?",
        "Tilos, repeat?",
        "Priya, explain?",
        "bot, explain?",
        "What did Tilo say?",
        "What is due?",
        "tile",
        "okay",
    ]
    events = [(i * 48.0, "A" if i % 2 else "B", text, False) for i, text in enumerate(unaddressed + addressed)]
    events[-1] = (1200.0, "A", "hello", True)  # explicitly typed TO the bot
    attention = Attention()
    allowed = []
    brain = Brain(
        Agenda.parse("# Sync\n1. Roadmap (10 min)"),
        ScriptedLLM(['{"reply":"A recorded answer."}'] * 10),
        30,
        wake_settings=WakeSettings(),
    )
    responses = 0
    for now, speaker, text, typed in events:
        result = wake_gate(text, speaker, now, attention, WakeSettings(), typed_to_bot=typed)
        allowed.append(result.allowed)
        attention = result.attention
        reply = brain.quick_reply([Utterance(speaker + (" (chat)" if typed else ""), text, now)], now)
        if reply is not None:
            responses += 1
            brain.commit_chat(reply, now)
    assert allowed == [False] * 15 + [True] * 10
    assert responses == 10


def test_FR_MTG_15_attention_is_same_speaker_only_and_expires_at_thirty_seconds():
    settings = WakeSettings()
    state = wake_gate("Tilo, what is next?", "A", 10, Attention(), settings).attention
    assert not wake_gate("and what is next?", "B", 20, state, settings).allowed
    assert wake_gate("tell me more", "A", 40, state, settings).allowed
    assert not wake_gate("tell me more", "A", 40.001, state, settings).allowed
    assert not wake_gate("tell me more", "A", 9, state, settings).allowed
    assert not wake_gate("we should ship it", "A", 20, state, settings).allowed
    assert not wake_gate("tell me more", "", 20, state, settings).allowed
    assert wake_gate("hello", "A", 20, state, settings, typed_to_bot=True).allowed
    assert not wake_gate("hello", "A", float("nan"), state, settings, typed_to_bot=True).allowed


def test_FR_MTG_15_closed_alias_configuration_and_no_provider_or_model_import():
    import bot.wake as module
    from bot.config import load_wake_settings

    settings = load_wake_settings()
    assert settings.attention_s == 30
    assert set(settings.aliases) == {"tilo", "tillo", "tylo", "teelo"}
    assert not wake_gate("Tyler, explain?", "A", 10, Attention(), settings).allowed
    custom = replace(settings, aliases=("tilo", "closedalias"))
    assert wake_gate("Closedalias, explain?", "A", 10, Attention(), custom).allowed
    assert not wake_gate("Tylo, explain?", "A", 10, Attention(), custom).allowed
    tree = ast.parse(inspect.getsource(module))
    imports = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    imports += [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
    assert not any("provider" in name or "llm" in name for name in imports)


def test_FR_MTG_15_live_brain_never_calls_a_model_for_an_overheard_question_or_other_speaker_followup():
    llm = ScriptedLLM(['{"reply":"A recorded answer."}'])
    brain = Brain(Agenda.parse("# Sync\n1. Roadmap (10 min)"), llm, 30, wake_settings=WakeSettings())
    brain.sole_human = True  # even a sole attendee must address the deployed bot
    assert brain.quick_reply([Utterance("A", "Where is the Tilo report?", 10)], 10) is None
    assert llm.calls == []
    message = brain.quick_reply([Utterance("A", "Tilo, explain the roadmap", 20)], 20)
    assert message is not None
    brain.commit_chat(message, 20)
    assert brain.quick_reply([Utterance("B", "tell me more", 25)], 25) is None
    assert len(llm.calls) == 1
    assert brain.question_in(Utterance("A", "tell me more", 30)) is not None
    assert brain.question_in(Utterance("A", "tell me more", 51)) is None


def test_FR_MTG_15_deployed_brain_has_gate_and_proactive_chat_off_by_default(monkeypatch, tmp_path):
    from bot.config import Config
    from bot.knowledge import KnowledgeBase
    from bot.session import build_brain

    monkeypatch.setattr("bot.config.load_dotenv", lambda: None)
    monkeypatch.delenv("VOICE_NUDGES", raising=False)
    agenda = tmp_path / "agenda.md"
    agenda.write_text("# Sync\n1. Roadmap (10 min)")
    cfg = Config.from_env()
    b = build_brain(cfg, agenda, 30, KnowledgeBase())
    assert b is not None and b.wake_settings is not None
    assert b.policy.decide(b.state, 1500, 1800) is None


@pytest.mark.parametrize("bad", [0, -1, float("inf"), float("nan")])
def test_FR_MTG_15_invalid_attention_window_refuses_configuration(bad):
    with pytest.raises(ValueError):
        WakeSettings(attention_s=bad)
