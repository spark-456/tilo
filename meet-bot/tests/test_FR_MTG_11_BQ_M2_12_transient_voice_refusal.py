"""FR-MTG-11 (M2b), SEC-16, BQ-M2-12, ADR-0042 decision 8: one refused Live reply must not end the Live voice.

The meter names why it refused in a fixed word (`last_refusal`); the adapter turns a TRANSIENT word (hold_open,
unavailable, a timeout, an unreachable API, 429, a 5xx that is not the contract's `not_configured`) into a refusal the
fallback voice retries on the next reply, bounded by `voice.live.max_consecutive_refusals` in `config/voice.yaml`; a
PERMANENT word (capped, replay_only, meeting_limit, not_attending, the contract's other errors, anything unknown) falls
back for the rest of THIS meeting and is not written to the state file, which is keyed by voice and not by person or
attend; facts about the instance (no meter, a replay miss, no price approval) are still remembered for a day.
No refused reserve ever reaches a Live session. A fake API and fake sessions: no network, no SDK, no paid call."""

import asyncio
import json
from pathlib import Path

import httpx
import pytest
import yaml
from test_FR_MTG_11_BQ_M2_4_MV_bot_voice_meter import BASE, CLAIM, MEETING, TOKEN, Api, meter_for
from tilo_providers.gemini_live_voice_adapter import GeminiLiveVoiceProvider

from bot.providers import ProviderTTS, load_voice_config, repo_root
from bot.tts import FallbackTTS, TTSError
from bot.voice_meter import RemoteLiveVoiceMeter

ROOT = repo_root()
REPLY = "The release is Friday."


def _config(tmp_path: Path, bound: int = 3):
    raw = yaml.safe_load((ROOT / "config" / "voice.yaml").read_text(encoding="utf-8"))
    raw["voice"]["live"].update(enabled=True, price_approved=True, max_consecutive_refusals=bound)
    path = tmp_path / "voice.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return load_voice_config(path, models_path=ROOT / "config" / "models.yaml")


def _live_provider(config, meter, opened, *, factory=True, fixtures_dir=None):
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    rate = config.sample_rate

    class Session:
        async def send_client_content(self, **kwargs):
            return None

        async def receive(self):
            usage = SimpleNamespace(prompt_token_count=12, response_token_count=30, total_token_count=42)
            part = SimpleNamespace(
                inline_data=SimpleNamespace(data=b"\x01\x02" * 64, mime_type=f"audio/pcm;rate={rate}")
            )
            content = SimpleNamespace(interrupted=False, model_turn=SimpleNamespace(parts=[part]), turn_complete=True)
            yield SimpleNamespace(usage_metadata=usage, server_content=content)

    @asynccontextmanager
    async def connect(settings):
        opened.append(1)
        yield Session()

    return GeminiLiveVoiceProvider(
        config, fixtures_dir=fixtures_dir, session_factory=connect if factory else None, meter=meter
    )


class Backup:
    """The local voice: records the replies it spoke."""

    name, sample_rate = "local-test", 22050

    def __init__(self):
        self.spoken: list[str] = []

    async def stream(self, text):
        self.spoken.append(text)
        yield b"\x00\x00" * 8


def _fallback(tmp_path, meter, opened, *, bound=3, state=None, **kwargs):
    config = _config(tmp_path, bound)
    primary = ProviderTTS(provider=_live_provider(config, meter, opened, **kwargs), config=config)
    backup = Backup()
    state = state if state is not None else tmp_path / "out" / ".tts_state.json"
    return FallbackTTS(primary, backup, state, f"{config.vendor}/{config.voice}"), backup, state


def _speak(tts, text=REPLY):
    async def go():
        return [piece async for piece in tts.stream(text)]

    return asyncio.run(go())


def _answers(*steps):
    """A reserve route that answers in order, then repeats the last: each step is (status, body) or an exception."""
    calls = []

    def route(request):
        step = steps[min(len(calls), len(steps) - 1)]
        calls.append(request)
        if isinstance(step, Exception):
            raise step
        return httpx.Response(step[0], json=step[1])

    return route


LIVE = (200, {"decision": "live"})
HOLD_OPEN = (200, {"decision": "replay", "reason": "hold_open"})
CAPPED = (200, {"decision": "replay", "reason": "capped"})


# -- the meter names why ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("answer", "word"),
    [
        (HOLD_OPEN, "hold_open"),
        ((200, {"decision": "replay", "reason": "unavailable"}), "unavailable"),
        (CAPPED, "capped"),
        ((200, {"decision": "replay", "reason": "replay_only"}), "replay_only"),
        ((200, {"decision": "replay", "reason": "meeting_limit"}), "meeting_limit"),
        ((401, {"error": "unauthenticated"}), "unauthenticated"),
        ((403, {"error": "forbidden"}), "forbidden"),
        ((409, {"error": "not_attending"}), "not_attending"),
        ((409, {"error": "key_used"}), "key_used"),
        ((409, {"error": "no_hold"}), "no_hold"),
        ((422, {"error": "invalid_request"}), "invalid_request"),
        ((503, {"error": "not_configured"}), "not_configured"),  # tilo-api's own settings: not a blip
        ((503, {}), "server_error"),  # an infrastructure 503 has no contract body
        ((500, {"detail": "boom"}), "server_error"),
        ((502, {"detail": "x" * 3000}), "server_error"),  # a long error page: the status decides
        ((429, {"detail": "slow down"}), "rate_limited"),
        ((404, {"detail": "Not Found"}), "refused"),
        ((307, {"detail": "elsewhere"}), "refused"),
        ((200, {"decision": "maybe"}), "off_contract"),
        ((200, {"decision": "live", "reason": "capped"}), "off_contract"),
        ((200, {"decision": "live", "pad": "x" * 2000}), "oversize"),
        (lambda request: httpx.Response(200, content=b"<html>ok</html>"), "malformed"),
        (httpx.ReadTimeout("slow"), "timeout"),
        (httpx.ConnectTimeout("late"), "timeout"),
        (httpx.ConnectError("no route"), "unreachable"),
        (httpx.RemoteProtocolError("reset"), "unreachable"),
        (RuntimeError("anything at all"), "error"),
    ],
)
def test_FR_MTG_11_BQ_M2_12_the_meter_names_why_it_refused_in_a_fixed_word(answer, word):
    if isinstance(answer, Exception):
        answer = _answers(answer)
    meter = meter_for(Api(reserve=answer))
    assert meter.reserve() is None
    assert meter.last_refusal == word


def test_FR_MTG_11_BQ_M2_12_no_identity_token_is_a_word_and_no_request():
    def no_identity(audience):
        raise OSError("metadata server unreachable")

    api = Api()
    meter = meter_for(api, token_for=no_identity)
    assert meter.reserve() is None and meter.last_refusal == "no_token" and api.calls == []


def test_FR_MTG_11_BQ_M2_12_a_live_answer_clears_the_word_and_the_word_is_never_a_secret():
    route = _answers(HOLD_OPEN, LIVE)
    meter = meter_for(Api(reserve=route))
    assert meter.last_refusal is None
    assert meter.reserve() is None and meter.last_refusal == "hold_open"
    assert meter.reserve() is not None and meter.last_refusal is None
    assert CLAIM not in repr(meter) and TOKEN not in repr(meter)


def test_FR_MTG_11_BQ_M2_12_a_refusal_word_is_a_closed_vocabulary_even_for_a_hostile_body():
    body = {"error": f"{CLAIM} {TOKEN}"}  # off the contract's error enum: the status decides, the text is dropped
    meter = meter_for(Api(reserve=(409, body)))
    assert meter.reserve() is None
    assert meter.last_refusal == "refused"


# -- one blip does not end the Live voice ------------------------------------------------------------------------------
def test_FR_MTG_11_BQ_M2_12_a_transient_refusal_speaks_local_for_that_reply_and_live_resumes_on_the_next(tmp_path):
    api, opened = Api(reserve=_answers(HOLD_OPEN, LIVE)), []
    voice, backup, state = _fallback(tmp_path, meter_for(api), opened)
    assert _speak(voice, "first") and backup.spoken == ["first"] and opened == []  # local, and no Live call
    assert _speak(voice, "second") and backup.spoken == ["first"] and opened == [1]  # Live again
    assert len(api.reserves) == 2 and len(api.closes) == 1 and api.closes[0][1]["outcome"] == "settled"
    assert not state.exists()  # nothing remembered, for the meeting or for a day


def test_FR_MTG_11_BQ_M2_12_an_unreachable_meter_and_a_timeout_are_transient_too(tmp_path):
    route = _answers(httpx.ConnectError("no route"), httpx.ReadTimeout("slow"), LIVE)
    api, opened = Api(reserve=route), []
    voice, backup, state = _fallback(tmp_path, meter_for(api), opened, bound=5)
    for text in ("one", "two"):
        _speak(voice, text)
    assert backup.spoken == ["one", "two"] and opened == []
    _speak(voice, "three")
    assert backup.spoken == ["one", "two"] and opened == [1] and not state.exists()


def test_FR_MTG_11_BQ_M2_12_a_transient_refusal_never_becomes_an_unmetered_live_call(tmp_path):
    api, opened = Api(reserve=_answers(HOLD_OPEN, HOLD_OPEN, HOLD_OPEN, HOLD_OPEN)), []
    voice, backup, _ = _fallback(tmp_path, meter_for(api), opened, bound=10)
    for n in range(4):
        _speak(voice, f"reply {n}")
    assert opened == [] and len(backup.spoken) == 4  # every reply is the local voice, none went Live
    assert api.closes == []  # nothing was held, so nothing is released or settled


def test_FR_MTG_11_BQ_M2_12_n_consecutive_transient_refusals_stop_the_live_voice_for_the_meeting(tmp_path):
    api, opened = Api(reserve=_answers(HOLD_OPEN)), []
    voice, backup, state = _fallback(tmp_path, meter_for(api), opened, bound=3)
    for n in range(7):
        _speak(voice, f"reply {n}")
    assert len(backup.spoken) == 7 and opened == []
    assert len(api.reserves) == 3  # the third refusal in a row stopped it; the meter was never asked again
    assert not state.exists()  # this meeting only: the file is for facts about the instance


def test_FR_MTG_11_BQ_M2_12_a_good_reserve_between_blips_resets_the_count(tmp_path):
    api, opened = Api(reserve=_answers(HOLD_OPEN, LIVE, HOLD_OPEN, LIVE, HOLD_OPEN, LIVE)), []
    voice, backup, _ = _fallback(tmp_path, meter_for(api), opened, bound=2)
    for n in range(6):
        _speak(voice, f"reply {n}")
    assert opened == [1, 1, 1] and len(backup.spoken) == 3 and len(api.reserves) == 6


# -- a permanent refusal still falls back, for the meeting ----------------------------------------------------------------
@pytest.mark.parametrize(
    "answer",
    [
        CAPPED,
        (200, {"decision": "replay", "reason": "replay_only"}),
        (200, {"decision": "replay", "reason": "meeting_limit"}),
        (409, {"error": "not_attending"}),
        (403, {"error": "forbidden"}),
        (503, {"error": "not_configured"}),
        (200, {"decision": "maybe"}),
    ],
)
def test_FR_MTG_11_BQ_M2_12_a_permanent_refusal_falls_back_for_the_meeting_and_is_asked_once(tmp_path, answer):
    api, opened = Api(reserve=answer), []
    voice, backup, state = _fallback(tmp_path, meter_for(api), opened)
    for n in range(3):
        _speak(voice, f"reply {n}")
    assert len(backup.spoken) == 3 and opened == []
    assert len(api.reserves) == 1  # remembered for the meeting: no more questions
    assert not state.exists()  # a person's cap or an attend's claim is no fact about the instance


def test_FR_MTG_11_BQ_M2_12_the_provider_tts_marks_transient_not_permanent_and_never_remembers_a_meter_refusal(
    tmp_path,
):
    for answer, permanent in ((HOLD_OPEN, False), (CAPPED, True)):
        config, opened = _config(tmp_path), []
        tts = ProviderTTS(provider=_live_provider(config, meter_for(Api(reserve=answer)), opened), config=config)
        with pytest.raises(TTSError) as caught:
            _speak(tts)
        assert caught.value.permanent is permanent and caught.value.remember is False and opened == []
        assert CLAIM not in str(caught.value) and TOKEN not in str(caught.value)


def test_FR_MTG_11_BQ_M2_12_a_500_is_no_longer_permanent(tmp_path):
    config, opened = _config(tmp_path), []
    tts = ProviderTTS(provider=_live_provider(config, meter_for(Api(reserve=(500, {}))), opened), config=config)
    with pytest.raises(TTSError) as caught:
        _speak(tts)
    assert caught.value.permanent is False and opened == []


# -- what is still remembered, and what the file never holds -------------------------------------------------------------
def test_FR_MTG_11_BQ_M2_12_a_fact_about_the_instance_is_still_remembered_and_the_file_holds_no_secret(tmp_path):
    api, opened = Api(), []
    # no session factory, no live switch, no recording: the adapter's own NotConfigured (a replay miss)
    voice, backup, state = _fallback(tmp_path, meter_for(api), opened, factory=False, fixtures_dir=tmp_path)
    _speak(voice, "first")
    assert backup.spoken == ["first"] and state.exists()
    written = state.read_text(encoding="utf-8")
    keys = [b["key"] for _, b, _ in api.calls]
    assert CLAIM not in written and TOKEN not in written and BASE not in written and MEETING not in written
    assert not any(key in written for key in keys)
    assert set(json.loads(written)) == {"voice", "at", "reason"}
    again, backup2, _ = _fallback(tmp_path, meter_for(api), opened, factory=False, fixtures_dir=tmp_path, state=state)
    _speak(again, "second")
    assert backup2.spoken == ["second"] and opened == [] and api.calls == []  # remembered: not even tried


def test_FR_MTG_11_BQ_M2_12_the_error_codes_the_bot_knows_are_the_contracts_and_the_words_are_the_providers():
    from tilo_providers.voice import PERMANENT_REFUSALS, REFUSAL_REASONS

    from bot import voice_meter

    schema = json.loads((ROOT / "contracts" / "meeting_voice_meter.schema.json").read_text(encoding="utf-8"))
    assert voice_meter._ERROR_CODES == set(schema["$defs"]["error"]["properties"]["error"]["enum"])
    replay = set(schema["$defs"]["reserve_answer"]["properties"]["reason"]["enum"])
    assert replay <= REFUSAL_REASONS and voice_meter._ERROR_CODES <= PERMANENT_REFUSALS


def test_FR_MTG_11_BQ_M2_12_the_bot_still_holds_no_ledger_code_and_the_meter_imports_no_provider_layer():
    source = (Path(__file__).resolve().parents[1] / "bot" / "voice_meter.py").read_text(encoding="utf-8")
    assert "from tilo_providers" not in source and "import tilo_providers" not in source
    assert isinstance(meter_for(Api()), RemoteLiveVoiceMeter)
