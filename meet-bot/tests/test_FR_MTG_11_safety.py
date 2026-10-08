"""FR-MTG-11 security follow-ups, offline: the bot refuses the dev fakes in a real meeting (F1), caps provider calls per
meeting (F2) and refuses TILO_RECORD (F6). No network, no key, no docker."""

import asyncio
import logging

import pytest
from test_FR_MTG_11_providers import Scripted, router_for
from tilo_providers.errors import QuotaError
from tilo_providers.meeting import CallCounter, MeetingCaps
from tilo_providers.speech import FakeSpeechProvider

from bot import guards
from bot import main as bot_main
from bot import providers as P
from bot.brain import LLMUnavailable
from bot.llm_fast import FastLLM
from bot.tts import FallbackTTS, TTSError


@pytest.fixture(autouse=True)
def _quiet_main(monkeypatch):
    monkeypatch.setattr(bot_main, "setup_logging", lambda *a, **k: None)  # main() would rewire the root log handlers
    monkeypatch.setattr(bot_main, "IN_CONTAINER", False)


def set_caps(model=200, speech=400) -> CallCounter:
    counter = CallCounter(MeetingCaps(model, speech))
    P.set_call_counter(counter)
    return counter


def run(coro):
    return asyncio.run(coro)


# -- F1: no fakes in a real meeting ------------------------------------------------------------------------------------
@pytest.mark.parametrize("command", ["start", "join https://meet.example/abc-defg-hij"])
def test_FR_MTG_11_start_and_join_refuse_the_dev_fakes_without_the_live_switch(monkeypatch, capsys, command):
    called: list[list[str]] = []
    monkeypatch.setattr(bot_main, "_compose_run", lambda args: called.append(args) or 0)
    assert bot_main.main(command.split()) == 2
    assert called == [] and "refuse the dev fakes" in capsys.readouterr().out


def test_FR_MTG_11_start_and_join_run_when_the_user_set_the_live_switch(monkeypatch):
    monkeypatch.setenv("LIVE", "1")
    called: list[list[str]] = []
    monkeypatch.setattr(bot_main, "_compose_run", lambda args: called.append(args) or 0)
    assert bot_main.main(["join", "https://meet.example/abc-defg-hij"]) == 0
    assert called and called[0][0] == "join"


def test_FR_MTG_11_the_live_switch_does_not_excuse_a_dev_config_override(monkeypatch, capsys):
    monkeypatch.setenv("LIVE", "1")
    monkeypatch.setenv("TILO_MODELS_FILE", "config/models.dev.yaml")
    monkeypatch.setattr(bot_main, "_compose_run", lambda args: pytest.fail("must not start"))
    assert bot_main.main(["start"]) == 2 and "dev config" in capsys.readouterr().out


def test_FR_MTG_11_inside_the_container_the_same_refusal_applies(monkeypatch, capsys):
    monkeypatch.setattr(bot_main, "IN_CONTAINER", True)
    assert bot_main.main(["join", "https://meet.example/abc-defg-hij"]) == 2
    assert "refuse the dev fakes" in capsys.readouterr().out


def test_FR_MTG_11_the_offline_modes_keep_the_fakes(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("OUT_DIR", str(tmp_path))  # an absolute path replaces meet-bot/out
    assert guards.is_live() is False
    assert bot_main.main(["run-mock"]) == 0  # run-mock opens no call: the keyword stub, no provider
    assert "brain steps" in capsys.readouterr().out


# -- F6: no recording ------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("command", [["doctor"], ["run-mock"], ["start"], ["retranscribe"]])
def test_FR_MTG_11_the_bot_refuses_to_start_with_tilo_record_set(monkeypatch, capsys, command):
    monkeypatch.setenv("LIVE", "1")
    monkeypatch.setenv("TILO_RECORD", "1")
    assert bot_main.main(command) == 2
    assert "TILO_RECORD" in capsys.readouterr().out


def test_FR_MTG_11_building_a_router_with_tilo_record_set_is_refused_too(monkeypatch):
    monkeypatch.setenv("TILO_RECORD", "1")
    with pytest.raises(guards.BotRefused):
        P.make_router()


# -- F2: a cap on provider calls per meeting ----------------------------------------------------------------------------
def test_FR_MTG_11_the_shipped_cap_comes_from_config_meeting_yaml():
    P.reset_call_counter()
    counter = P.call_counter()
    assert (counter.caps.max_model_calls, counter.caps.max_speech_calls) == (200, 400)
    assert P.call_counter() is counter  # one counter per bot process, which is one meeting


def test_FR_MTG_11_the_analysis_model_stops_at_the_cap_without_calling_the_provider(caplog):
    set_caps(model=2)
    provider = Scripted("{}")
    llm = P.ProviderLLM(router_for(provider))
    assert llm.generate("s", "p") == "{}" and llm.generate("s", "p") == "{}"
    with caplog.at_level(logging.WARNING, logger="bot.providers"), pytest.raises(LLMUnavailable, match="call cap"):
        llm.generate("s", "p")
    with pytest.raises(LLMUnavailable):
        llm.generate("s", "p")
    assert len(provider.requests) == 2  # the paid call was never made
    assert len([r for r in caplog.records if "call cap" in r.getMessage()]) == 1  # logged once, not per refusal


def test_FR_MTG_11_every_retry_attempt_of_the_analysis_model_counts():
    counter = set_caps(model=10)
    provider = Scripted(QuotaError("429"), QuotaError("429"), "{}")
    P.ProviderLLM(router_for(provider), sleep=lambda s: None).generate("s", "p")
    assert counter.used["model"] >= 3


def test_FR_MTG_11_a_retry_loop_cannot_pass_the_cap():
    counter = set_caps(model=2)
    provider = Scripted(QuotaError("429"))
    llm = P.ProviderLLM(router_for(provider), sleep=lambda s: None, max_attempts=10)
    with pytest.raises(LLMUnavailable):
        llm.generate("s", "p")
    assert counter.used["model"] == 2 and len(provider.requests) <= 4  # one router call may use the role's fallback


def test_FR_MTG_11_the_fast_path_stops_at_the_cap_with_unavailable_and_no_second_try():
    counter = set_caps(model=1)
    provider = Scripted("Hi |there.")
    llm = FastLLM(lambda: P.ProviderFastClient(router_for(provider)), first_token_s=5)
    assert run(llm.generate("sys", "q")) == "Hi there."
    with pytest.raises(LLMUnavailable, match="call cap"):
        run(llm.generate("sys", "q"))
    assert counter.used["model"] == 1 and len(provider.requests) == 1


def test_FR_MTG_11_speech_to_text_stops_at_the_cap_and_names_the_cap(caplog):
    set_caps(speech=1)
    speech = P.ProviderSpeech(FakeSpeechProvider())
    assert speech.text(b"RIFF" + bytes(40))
    with caplog.at_level(logging.WARNING, logger="bot.providers"), pytest.raises(LLMUnavailable, match="call cap"):
        speech.text(b"RIFF" + bytes(40))
    assert any("call cap" in r.getMessage() for r in caplog.records)


def test_FR_MTG_11_the_voice_stops_at_the_cap_with_a_permanent_error_so_the_local_voice_takes_over(tmp_path):
    set_caps(speech=1)
    cloud = P.ProviderTTS()

    async def collect(tts, text="Hello there"):
        return [c async for c in tts.stream(text)]

    assert run(collect(cloud))
    with pytest.raises(TTSError) as exc:
        run(collect(cloud))
    assert exc.value.permanent is True

    class Local:
        name, sample_rate = "local", 24000

        async def stream(self, text: str):
            yield b"\x00\x01"

    tts = FallbackTTS(cloud, Local(), tmp_path / "state.json", "fake/Fake")
    assert run(collect(tts)) == [b"\x00\x01"]  # the meeting goes on with the local voice


def test_FR_MTG_11_speech_and_model_calls_are_counted_separately():
    counter = set_caps(model=1, speech=1)
    P.ProviderLLM(router_for(Scripted("{}"))).generate("s", "p")
    P.ProviderSpeech(FakeSpeechProvider()).text(b"RIFF" + bytes(40))
    assert counter.used == {"model": 1, "speech": 1}


def test_FR_MTG_11_a_cap_in_config_that_is_not_a_positive_number_fails_start_up(tmp_path, monkeypatch):
    bad = tmp_path / "meeting.yaml"
    bad.write_text("meeting:\n  max_model_calls: 0\n  max_speech_calls: 5\n", encoding="utf-8")
    monkeypatch.setenv("TILO_MEETING_FILE", str(bad))
    P.reset_call_counter()
    with pytest.raises(Exception, match="max_model_calls"):
        P.call_counter()


def test_FR_MTG_11_the_cap_file_is_selected_from_config_unless_overridden(monkeypatch):
    assert P.meeting_file().name == "meeting.yaml" and P.meeting_file().parent.name == "config"
    monkeypatch.setenv("TILO_MEETING_FILE", "/elsewhere/meeting.yaml")
    assert "elsewhere" in str(P.meeting_file())
