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


# -- follow-ups after the security re-check ------------------------------------------------------------------------
def _bad_meeting_yaml(tmp_path, monkeypatch):
    bad = tmp_path / "meeting.yaml"
    bad.write_text("meeting:\n  max_model_calls: 0\n  max_speech_calls: 5\n", encoding="utf-8")
    monkeypatch.setenv("TILO_MEETING_FILE", str(bad))
    P.reset_call_counter()


def _live_session(tmp_path, monkeypatch):
    from bot.config import Config
    from bot.session import LiveSession

    monkeypatch.setattr("bot.config.load_dotenv", lambda path=None: None)
    monkeypatch.setenv("OUT_DIR", str(tmp_path / "out"))
    monkeypatch.setenv("CONTEXT_DIR", str(tmp_path / "ctx"))
    return LiveSession(
        Config.from_env(), "join", "https://meet.example/abc-defg-hij", None, 30, False, [], False, False, []
    )


def test_FR_MTG_11_a_bad_meeting_config_fails_start_up_with_a_clear_error_not_mid_meeting(tmp_path, monkeypatch):
    _bad_meeting_yaml(tmp_path, monkeypatch)
    with pytest.raises(guards.BotRefused, match="max_model_calls"):
        P.start_up_check(allow_fakes=True)


def test_FR_MTG_11_the_session_checks_the_meeting_config_before_it_opens_a_browser(tmp_path, monkeypatch):
    session = _live_session(tmp_path, monkeypatch)  # built with the good config
    _bad_meeting_yaml(tmp_path, monkeypatch)
    monkeypatch.setattr("bot.session.MeetBrowser", lambda *a, **k: pytest.fail("joined before the start-up check"))
    with pytest.raises(guards.BotRefused, match="max_model_calls"):
        run(session.run())


def test_FR_MTG_11_start_up_builds_the_one_counter_the_calls_share():
    P.reset_call_counter()
    P.start_up_check(allow_fakes=True)
    assert P.call_counter().used == {"model": 0, "speech": 0}


def test_FR_MTG_11_a_run_is_refused_when_the_resolved_profiles_are_fakes():
    assert "fake" in (P.resolved_fakes_refusal() or "")  # dev config: meeting, meeting_fast, speech and voice are fakes
    with pytest.raises(guards.BotRefused, match="fake"):
        P.start_up_check()


def test_FR_MTG_11_a_fake_profile_in_a_file_with_an_innocent_name_is_still_refused(tmp_path, monkeypatch):
    config = tmp_path / "models-real-looking.yaml"
    config.write_text((P.repo_root() / "config" / "models.dev.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setenv("TILO_MODELS_FILE", str(config))
    refusal = P.resolved_fakes_refusal()  # the roles resolve to fakes whatever the file is called
    assert refusal and "meeting" in refusal and "fake" in refusal
    monkeypatch.setenv("LIVE", "1")
    assert guards.fakes_refusal() is None  # the file-name check alone is fooled by the name


def test_FR_MTG_11_a_fake_speech_vendor_is_refused_even_when_the_models_are_real(tmp_path, monkeypatch):
    monkeypatch.setenv("LIVE", "1")
    monkeypatch.setenv("GOOGLE_LOCATION", "global")  # match the shipped Gemini price quote; no provider call
    speech = tmp_path / "speech-x.yaml"
    speech.write_text((P.repo_root() / "config" / "speech.dev.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setenv("TILO_SPEECH_FILE", str(speech))
    refusal = P.resolved_fakes_refusal()
    assert refusal and "speech" in refusal


def test_FR_MTG_11_the_shipped_live_config_resolves_to_no_fakes(monkeypatch):
    monkeypatch.setenv("LIVE", "1")
    monkeypatch.setenv("GOOGLE_LOCATION", "global")
    assert P.resolved_fakes_refusal() is None


def test_FR_MTG_11_live_model_region_mismatch_stays_fail_closed(monkeypatch):
    monkeypatch.setenv("LIVE", "1")
    monkeypatch.setenv("GOOGLE_LOCATION", "asia-southeast1")
    refusal = P.resolved_fakes_refusal()
    assert refusal and "PL-06" in refusal and "GOOGLE_LOCATION=global" in refusal


def test_FR_MTG_11_the_dev_file_name_check_ignores_case(monkeypatch):
    monkeypatch.setenv("LIVE", "1")
    monkeypatch.setenv("TILO_VOICE_FILE", "config/voice.DEV.yaml")
    assert "TILO_VOICE_FILE" in (guards.fakes_refusal() or "")


def test_FR_MTG_11_a_start_up_refusal_in_the_container_exits_2_with_the_message(monkeypatch, capsys):
    monkeypatch.setattr(bot_main, "IN_CONTAINER", True)
    monkeypatch.setenv("LIVE", "1")

    async def refuse(*a, **k):
        raise guards.BotRefused("the meeting config is bad")

    monkeypatch.setattr("bot.session.run_live", refuse)
    assert bot_main.main(["join", "https://meet.example/abc-defg-hij"]) == 2
    assert "the meeting config is bad" in capsys.readouterr().out


class _LocalVoice:
    name, sample_rate = "local", 24000

    async def stream(self, text: str):
        yield b"\x00\x01"


async def _collect(tts, text="Hello there"):
    return [c async for c in tts.stream(text)]


def test_FR_MTG_11_the_cap_refusal_lasts_for_this_meeting_only_and_is_never_written_to_disk(tmp_path):
    set_caps(speech=1)
    state = tmp_path / "state.json"
    tts = FallbackTTS(P.ProviderTTS(), _LocalVoice(), state, "fake/Fake")
    assert run(_collect(tts))[0] != b"\x00\x01"  # the first reply is the cloud voice
    assert run(_collect(tts)) == [b"\x00\x01"]  # at the cap: the local voice
    assert run(_collect(tts)) == [b"\x00\x01"]  # and it stays so for this meeting
    assert not state.exists()  # nothing is remembered for the next meeting
    set_caps(speech=5)
    assert FallbackTTS(P.ProviderTTS(), _LocalVoice(), state, "fake/Fake")._primary_dead is False


def test_FR_MTG_11_a_refused_voice_is_still_remembered_for_a_day(tmp_path):
    class Refused:
        name, sample_rate = "cloud", 24000

        async def stream(self, text: str):
            raise TTSError("not on this plan", permanent=True)
            yield b""

    state = tmp_path / "state.json"
    assert run(_collect(FallbackTTS(Refused(), _LocalVoice(), state, "v"))) == [b"\x00\x01"]
    assert state.exists()


def test_FR_MTG_11_the_config_comment_says_one_count_per_router_call():
    text = (P.repo_root() / "config" / "meeting.yaml").read_text(encoding="utf-8")
    assert "every attempt" not in text and "router call" in text


def test_FR_MTG_11_hybrid_logs_the_speech_cap_once_not_for_every_segment(tmp_path, monkeypatch, caplog):
    set_caps(speech=1)
    session = _live_session(tmp_path, monkeypatch)
    session.buffer.append(bytes(32000 * 10))

    async def go():
        for k in range(4):
            session.seg_q.put_nowait((k * 2.0, k * 2.0 + 1.5))
        task = asyncio.create_task(session._stt_worker())
        for _ in range(100):
            if session.seg_q.empty():
                break
            await asyncio.sleep(0.02)
        await asyncio.sleep(0.1)
        task.cancel()

    with caplog.at_level(logging.WARNING, logger="bot.session"):
        run(go())
    assert len([r for r in caplog.records if "could not be transcribed" in r.getMessage()]) == 1
