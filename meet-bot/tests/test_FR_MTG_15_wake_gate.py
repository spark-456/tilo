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
        # Owner decision 21 Oct: Meet captions mishear the name, so near-misses and a direct "assistant," count.
        "assistant, explain?",
        "Tilos, repeat?",
        "bot, explain?",
        "hello",
    ]
    unaddressed = [
        "Where is the Tilo report?",
        "tiles",
        "Tyler, what is next?",
        "What is the plan?",
        "We told Tilo about it.",
        "the Tilo report",
        "tile, repeat?",
        "Priya, explain?",
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
        ScriptedLLM(['{"reply":"A recorded answer."}'] * 13),
        30,
        max_direct=40,  # the live per-meeting answer cap (MAX_DIRECT_REPLIES)
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
    assert allowed == [False] * 12 + [True] * 13
    assert responses == 13


def test_FR_MTG_15_OWNER_21OCT_caption_mishearings_of_the_name_call_tilo_but_ordinary_speech_does_not():
    settings = WakeSettings()
    called = [
        "Tealo, what is next?",
        "Tea low, summarise",
        "T low what is next?",
        "Tilow, repeat that",
        "Theelo, who owns it?",
        "Deelo, what is next?",
        "Hey assistant what is due?",
        "Notetaker, summarise",
        "ok Tilo what did we decide?",
    ]
    ordinary = [
        "Tile the floor first.",
        "A kilo of rice please?",
        "Assistant manager said no.",
        "Bot traffic is up?",
        "Tell me later.",
        "Till Friday then.",
        "Hello everyone.",
        "We need a note taker for this.",
    ]
    assert [wake_gate(t, "A", 10, Attention(), settings).allowed for t in called] == [True] * len(called)
    assert [wake_gate(t, "A", 10, Attention(), settings).allowed for t in ordinary] == [False] * len(ordinary)


def test_FR_MTG_15_OWNER_21OCT_a_question_right_after_tilo_spoke_is_a_follow_up_from_anyone():
    settings = WakeSettings()
    assert wake_gate("and when is it due?", "B", 25, Attention(), settings, bot_spoke_at=20).allowed
    assert wake_gate("tell me more", "B", 25, Attention(), settings, bot_spoke_at=20).allowed
    assert not wake_gate("we should ship it", "B", 25, Attention(), settings, bot_spoke_at=20).allowed
    assert not wake_gate(
        "and when is it due?", "B", 20 + settings.after_reply_s + 0.1, Attention(), settings, bot_spoke_at=20
    ).allowed


def test_FR_MTG_15_OWNER_21OCT_one_on_one_every_question_or_typed_line_is_for_tilo():
    brain = Brain(Agenda.parse("# Sync\n1. Roadmap (10 min)"), ScriptedLLM([]), 30, wake_settings=WakeSettings())
    brain.sole_human = (
        True  # exactly one other person in the call (live 20 Oct 18:55: "are you able to hear my voice?")
    )
    assert brain.question_in(Utterance("A", "are you able to hear my voice?", 10)) is not None
    assert brain.question_in(Utterance("A", "what did we decide", 12)) is not None
    assert brain.question_in(Utterance("A (chat)", "hi", 14)) is not None
    assert brain.question_in(Utterance("A", "yes", 16)) is None  # a fragment says nothing to answer
    assert brain.chat_directed("can you see this?", "A", 18)
    brain.sole_human = False  # a group call keeps the name rule
    assert brain.question_in(Utterance("A", "are you able to hear my voice?", 20)) is None
    assert not brain.chat_directed("can you see this?", "A", 22)
    assert brain.chat_directed("Tilo, can you see this?", "A", 24)


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
    assert settings.after_reply_s == 15
    assert set(settings.aliases) == {
        "tilo",
        "tillo",
        "tylo",
        "teelo",
        "tilow",
        "tealo",
        "theelo",
        "deelo",
        "teelow",
        "tealow",
        "tlow",
        "chilo",
    }  # owner 21 Oct: caption mishearings of the name
    assert not wake_gate("Tyler, explain?", "A", 10, Attention(), settings).allowed
    custom = replace(settings, aliases=("tilo", "closedalias"))
    assert wake_gate("Closedalias, explain?", "A", 10, Attention(), custom).allowed
    assert not wake_gate("Tylo, explain?", "A", 10, Attention(), custom).allowed
    tree = ast.parse(inspect.getsource(module))
    imports = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    imports += [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
    assert not any("provider" in name or "llm" in name for name in imports)


def test_FR_MTG_15_live_brain_never_calls_a_model_for_an_overheard_question_or_a_late_other_speaker_followup():
    llm = ScriptedLLM(['{"reply":"A recorded answer."}'])
    brain = Brain(Agenda.parse("# Sync\n1. Roadmap (10 min)"), llm, 30, wake_settings=WakeSettings())
    brain.sole_human = False  # a group call: overheard speech never reaches a model (one-on-one: see OWNER_21OCT)
    assert brain.quick_reply([Utterance("A", "Where is the Tilo report?", 10)], 10) is None
    assert llm.calls == []
    message = brain.quick_reply([Utterance("A", "Tilo, explain the roadmap", 20)], 20)
    assert message is not None
    brain.commit_chat(message, 20)
    assert brain.quick_reply([Utterance("B", "tell me more", 36)], 36) is None  # past the 15 s after-reply window
    assert len(llm.calls) == 1
    assert brain.question_in(Utterance("B", "tell me more", 25)) is not None  # right after Tilo spoke (owner 21 Oct)
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
