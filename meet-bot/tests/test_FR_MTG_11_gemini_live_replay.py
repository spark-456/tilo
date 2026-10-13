"""FR-MTG-11 (M2): the same offline guest lifecycle through LiveSession passes for the Chirp streaming adapter and for
the flagged Gemini Live adapter (a fake Live session, and hand-written recordings in replay mode). The meeting, the
captions, the disclosure, the playback and the leave are identical; only the voice backend differs. No network, no
SDK, no live switch, no real audio."""

import asyncio
import dataclasses
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from tilo_providers.cloud_tts_adapter import GoogleCloudTTSProvider
from tilo_providers.gemini_live_voice_adapter import GeminiLiveVoiceProvider
from tilo_providers.voice import build_voice_provider

from bot import cloud_worker, session
from bot.captions import CaptionBlock
from bot.providers import ProviderTTS, load_voice_config, repo_root

ROOT = repo_root()
REPLY = "The release is Friday."
RECORDINGS = ROOT / "packages" / "providers" / "tests" / "fixtures"  # holds voice-live-recordings/ (synthetic)
CHUNKS = [bytes(range(100)), bytes(range(100, 200))]  # the pieces of the hand-written recording, too


def _flagged_voice(tmp_path: Path):
    raw = yaml.safe_load((ROOT / "config" / "voice.yaml").read_text(encoding="utf-8"))
    raw["voice"]["live"]["enabled"] = True  # the only change: the flag in config
    path = tmp_path / "voice.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return load_voice_config(path, models_path=ROOT / "config" / "models.yaml")


class Backend:
    """One voice backend: its config, its provider, the audio it must deliver and how to see the request it got."""

    def __init__(self, voice, provider, expected, check_request):
        self.voice, self.provider, self.expected, self.check_request = voice, provider, expected, check_request


@pytest.fixture(params=["chirp", "gemini_live_fake_session", "gemini_live_replay"])
def backend(request, tmp_path, monkeypatch):
    monkeypatch.delenv("LIVE", raising=False)
    monkeypatch.delenv("TILO_RECORD", raising=False)
    if request.param == "chirp":
        voice = load_voice_config(ROOT / "config" / "voice.yaml", models_path=ROOT / "config" / "models.yaml")
        assert voice.live is not None and not voice.live.enabled  # the shipped default
        requests = []

        class Transport:
            def streaming_synthesize(self, stream, timeout=None):
                requests.extend(stream)
                return iter(SimpleNamespace(audio_content=chunk) for chunk in CHUNKS)

        provider = GoogleCloudTTSProvider(
            voice=voice.voice,
            sample_rate=voice.sample_rate,
            project="demo-replay",
            region=voice.region,
            client=Transport(),
        )

        def check():
            assert requests[0]["streaming_config"]["voice"]["name"] == voice.voice
            assert requests[1]["input"]["text"] == REPLY

        return Backend(voice, provider, b"".join(CHUNKS), check)

    voice = _flagged_voice(tmp_path)
    assert voice.live is not None and voice.live.enabled
    if request.param == "gemini_live_replay":
        provider = build_voice_provider(voice, fixtures_dir=RECORDINGS)
        assert isinstance(provider, GeminiLiveVoiceProvider)
        return Backend(voice, provider, b"".join(CHUNKS), lambda: None)

    seen, sent = [], []

    class Live:
        @asynccontextmanager
        async def connect(self):
            yield self

        async def send_client_content(self, **kwargs):
            sent.append(kwargs)

        async def receive(self):
            for index, chunk in enumerate(CHUNKS):
                content = SimpleNamespace(
                    model_turn=SimpleNamespace(
                        parts=[
                            SimpleNamespace(inline_data=SimpleNamespace(data=chunk, mime_type="audio/pcm;rate=24000"))
                        ]
                    ),
                    turn_complete=index == len(CHUNKS) - 1,
                    interrupted=False,
                )
                yield SimpleNamespace(server_content=content, usage_metadata=None)

    def factory(settings):
        seen.append(settings)
        return Live().connect()

    provider = GeminiLiveVoiceProvider(voice, fixtures_dir=None, session_factory=factory)

    def check():
        assert seen[0].voice == voice.live.voice and seen[0].model == voice.live.model
        assert sent[0]["turns"]["parts"][0]["text"] == REPLY

    return Backend(voice, provider, b"".join(CHUNKS), check)


def test_FR_MTG_11_PL_02_guest_listens_speaks_and_leaves_on_every_voice_backend(backend, monkeypatch):
    actions, played, sessions = [], [], []
    voice = backend.voice
    spoken_from_provider = backend.provider.synthesize_stream

    def traced(*args, **kwargs):
        actions.append("synthesize")
        return spoken_from_provider(*args, **kwargs)

    monkeypatch.setattr(backend.provider, "synthesize_stream", traced)

    class Browser:
        account_name = ""
        page = object()

        def __init__(self, cfg, voice=False, face=False):
            assert cfg.guest and not cfg.bot_email and voice
            assert face
            assert not cfg.profile_dir.exists()
            self.cfg = cfg

        async def face_event(self, kind, value=0):
            pass

        async def __aenter__(self):
            actions.append("guest_context")
            return self

        async def __aexit__(self, *args):
            actions.append("close")

        async def open_meeting(self, url):
            assert url == "https://meet.google.com/abc-defg-hij"

        async def join(self):
            actions.append("join")
            return True

        async def set_mic(self, on):
            actions.append("unmute" if on else "mute")
            return True

        async def shot(self, name):
            pass

        async def enable_captions(self):
            actions.append("listen")
            return True

        async def leave(self):
            actions.append("leave")
            assert not self.cfg.profile_dir.exists()

    class Chat:
        def __init__(self, browser):
            pass

        async def send(self, text):
            if "I'm an AI assistant" in text:
                assert "out loud and in chat" in text
                actions.append("disclosure")
            else:
                assert text == REPLY
                actions.append("reply_chat")
            return True

    class Recorder:
        def __init__(self, *args, **kwargs):
            self.started_at = 0

        def start(self):
            actions.append("capture")
            return True

        def stop(self):
            actions.append("capture_stop")

    class Tap(Recorder):
        def start(self):
            return False

    class Player:
        async def play(self, stream, sample_rate, interrupted):
            assert sample_rate == voice.sample_rate
            async for chunk in stream:
                assert not interrupted()
                played.append(chunk)
            actions.append("played")
            return True

    class Reader:
        def __init__(self, page, callback, clock, unused):
            self.callback, self.clock = callback, clock

        async def start(self):
            async def replay():
                live = sessions[0]
                now = self.clock.now()
                self.callback([CaptionBlock("Alice", "Release Friday")], now)
                self.callback([CaptionBlock("Alice", "Release Friday"), CaptionBlock("Bob", "Agreed")], now + 1)
                self.callback([CaptionBlock("Alice", "Release Friday")], now + 2)
                self.callback([], now + 3)
                while len(live.store.items) < 2:
                    await asyncio.sleep(0.01)
                ok, info = await live._deliver(SimpleNamespace(kind="direct_reply", text=REPLY))
                assert ok and played
                self.callback([CaptionBlock("Alice", "Tilo leave")], now + 4)
                self.callback([], now + 5)

            self.task = asyncio.create_task(replay())
            sessions[0].replay_task = self.task

    real_class = cloud_worker.LiveSession

    def live_factory(*args):
        live = real_class(*args)
        sessions.append(live)
        return live

    monkeypatch.setattr(cloud_worker, "LiveSession", live_factory)
    for name, replacement in {
        "MeetBrowser": Browser,
        "ChatPoster": Chat,
        "CaptionReader": Reader,
        "LiveRecorder": Recorder,
        "WavTap": Tap,
        "Player": Player,
        "build_brain": lambda *args: None,  # transcript-only meeting; the reply above is deterministic approved text
        "setup_virtual_mic": lambda: True,
        "start_up_check": lambda: None,  # live-only guard: this browser and transport cannot reach a meeting
        "make_tts": lambda: ProviderTTS(provider=backend.provider, config=voice),
    }.items():
        monkeypatch.setattr(session, name, replacement)
    monkeypatch.setattr(session.LiveSession, "_prewarm", lambda self: None)

    async def run():
        result = await asyncio.wait_for(
            cloud_worker.attend_meeting("mt_replay", "https://meet.google.com/abc-defg-hij"), 3
        )
        await sessions[0].replay_task  # propagate replay assertions rather than losing task failures
        return result

    result = asyncio.run(run())
    assert result.reason == "left_on_request"
    assert [(u["id"], u["speaker"], u["text"]) for u in result["utterances"]] == [
        ("u0001", "Alice", "Release Friday"),
        ("u0002", "Bob", "Agreed"),
    ]
    assert result["utterances"][0]["t_ms"] < result["utterances"][1]["t_ms"]
    assert b"".join(played) == backend.expected
    backend.check_request()
    assert actions.index("join") < actions.index("disclosure") < actions.index("capture") < actions.index("listen")
    assert actions.index("synthesize") < actions.index("played") < actions.index("leave") < actions.index("close")
    assert actions[-3:] == ["capture_stop", "leave", "close"]


def test_FR_MTG_11_PL_01_flag_off_never_builds_the_live_adapter_and_chirp_refuses_without_the_switch():
    voice = load_voice_config(ROOT / "config" / "voice.yaml", models_path=ROOT / "config" / "models.yaml")
    off = build_voice_provider(dataclasses.replace(voice, live=None), fixtures_dir=RECORDINGS)
    assert not isinstance(off, GeminiLiveVoiceProvider)
    with pytest.raises(Exception) as refused:  # NotConfigured: no LIVE=1, so Chirp never speaks and never goes live
        off.synthesize_stream(REPLY)
    assert type(refused.value).__name__ == "NotConfigured"
