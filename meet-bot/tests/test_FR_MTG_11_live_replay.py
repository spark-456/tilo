"""Offline guest lifecycle through LiveSession and the real Chirp streaming adapter."""

import asyncio
from types import SimpleNamespace

from tilo_providers.cloud_tts_adapter import GoogleCloudTTSProvider

from bot import cloud_worker, session
from bot.captions import CaptionBlock
from bot.providers import ProviderTTS, load_voice_config, repo_root


def test_FR_MTG_11_guest_listens_speaks_and_leaves_with_offline_chirp(monkeypatch):
    monkeypatch.delenv("LIVE", raising=False)
    monkeypatch.delenv("TILO_RECORD", raising=False)
    actions, played, requests, sessions = [], [], [], []
    chunks = [bytes(range(100)), bytes(range(100, 200))]
    voice = load_voice_config(repo_root() / "config" / "voice.yaml", models_path=repo_root() / "config" / "models.yaml")

    class Transport:
        def streaming_synthesize(self, stream, timeout=None):
            requests.extend(stream)
            actions.append("synthesize")
            return iter(SimpleNamespace(audio_content=chunk) for chunk in chunks)

    provider = GoogleCloudTTSProvider(
        voice=voice.voice,
        sample_rate=voice.sample_rate,
        project="demo-replay",
        region=voice.region,
        client=Transport(),
    )

    class Browser:
        account_name = ""
        page = object()

        def __init__(self, cfg, voice=False, face=False):
            assert cfg.guest and not cfg.bot_email and voice and face
            assert not cfg.profile_dir.exists()
            self.cfg = cfg

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
                assert text == "The release is Friday."
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
                # One longer-lived caption settles after the later speaker's caption.
                self.callback([CaptionBlock("Alice", "Release Friday")], now)
                self.callback([CaptionBlock("Alice", "Release Friday"), CaptionBlock("Bob", "Agreed")], now + 1)
                self.callback([CaptionBlock("Alice", "Release Friday")], now + 2)
                self.callback([], now + 3)
                while len(live.store.items) < 2:
                    await asyncio.sleep(0.01)
                ok, info = await live._deliver(SimpleNamespace(kind="direct_reply", text="The release is Friday."))
                assert ok and played
                self.callback([CaptionBlock("Alice", "Tilo leave")], now + 4)
                self.callback([], now + 5)

            self.task = asyncio.create_task(replay())
            sessions[0].replay_task = self.task

    def build_brain(*args):
        return None  # transcript-only meeting; the reply above supplies deterministic approved text

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
        "build_brain": build_brain,
        "setup_virtual_mic": lambda: True,
        "start_up_check": lambda: None,  # live-only guard: this browser and transport cannot reach a meeting
        "make_tts": lambda: ProviderTTS(provider=provider, config=voice),
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
    assert b"".join(played) == b"".join(chunks)
    assert requests[0]["streaming_config"]["voice"]["name"] == voice.voice
    assert requests[1]["input"]["text"] == "The release is Friday."
    assert actions.index("join") < actions.index("disclosure") < actions.index("capture") < actions.index("listen")
    assert actions.index("synthesize") < actions.index("played") < actions.index("leave") < actions.index("close")
    assert actions[-3:] == ["capture_stop", "leave", "close"]
