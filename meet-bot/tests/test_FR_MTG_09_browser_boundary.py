"""Offline acceptance checks for the bot's account, disclosure, shutdown and privacy boundaries."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.browser import CHROMIUM_ARGS, JoinFailed, MeetBrowser, NotLoggedIn
from bot.captions import Utterance
from bot.session import LiveSession


def browser(tmp_path, email="bot@example.test"):
    cfg = SimpleNamespace(bot_email=email, debug_dir=tmp_path, profile_dir=tmp_path / "profile")
    return MeetBrowser(cfg)


@pytest.mark.parametrize("label", [None, "Google Account: Other (other@example.test)", "Google Account: Unknown"])
def test_FR_MTG_09_unreadable_or_wrong_account_refuses_without_address_in_error(tmp_path, caplog, label):
    bot = browser(tmp_path)
    button = None if label is None else SimpleNamespace(get_attribute=AsyncMock(return_value=label))
    bot.find = AsyncMock(return_value=button)
    with pytest.raises(NotLoggedIn) as error:
        asyncio.run(bot.check_account())
    assert "@" not in str(error.value)
    assert "@" not in caplog.text


def test_FR_MTG_09_matching_dedicated_account_passes_without_logging_address(tmp_path, caplog):
    bot = browser(tmp_path)
    button = SimpleNamespace(get_attribute=AsyncMock(return_value="Google Account: Tilo (BOT@example.test)"))
    bot.find = AsyncMock(return_value=button)
    asyncio.run(bot.check_account())
    assert bot.account_name == "Tilo"
    assert "@" not in caplog.text


def test_FR_MTG_09_account_configuration_required_before_account_read(tmp_path):
    bot = browser(tmp_path, email="")
    bot.find = AsyncMock()
    with pytest.raises(NotLoggedIn):
        asyncio.run(bot.check_account())
    bot.find.assert_not_awaited()


@pytest.mark.parametrize("suffix", ["/extra", "?debug=1", "#fragment"])
def test_FR_MTG_01_meet_link_shape_is_exact_and_refusal_does_not_echo_link(tmp_path, suffix):
    bot = browser(tmp_path)
    bot.page = SimpleNamespace(goto=AsyncMock())
    url = "https://" + "meet.google.com" + "/abc-defg-hij" + suffix
    with pytest.raises(JoinFailed) as error:
        asyncio.run(bot.open_meeting(url))
    bot.page.goto.assert_not_awaited()
    assert url not in str(error.value)


def test_FR_MTG_09_signed_in_chromium_keeps_sandbox():
    assert "--no-sandbox" not in CHROMIUM_ARGS


def test_FR_MTG_01_browser_diagnostics_do_not_persist_account_page_or_meet_link(tmp_path):
    bot = browser(tmp_path)
    bot.page = SimpleNamespace(screenshot=AsyncMock(), evaluate=AsyncMock())
    asyncio.run(bot.shot("prejoin"))
    asyncio.run(bot._dump("account"))
    bot.page.screenshot.assert_not_awaited()
    bot.page.evaluate.assert_not_awaited()
    assert list(tmp_path.iterdir()) == []


def test_FR_MTG_01_transcript_waits_for_successful_disclosure():
    session = LiveSession.__new__(LiveSession)
    session.intro_sent = False
    session.store = SimpleNamespace(append=lambda utterance: pytest.fail("captured before disclosure"))
    session.events = SimpleNamespace(emit=lambda *a, **k: pytest.fail("event before disclosure"))
    session.timeline = SimpleNamespace(record=lambda *a, **k: pytest.fail("trace before disclosure"))
    session.record(Utterance("Participant", "Private words", 1.0))


def test_FR_MTG_01_local_event_sink_never_emits_a_meet_link(tmp_path, capsys):
    from bot.events import EventSink

    sink = EventSink(tmp_path / "events.jsonl", "meeting", echo=True)
    url = "https://" + "meet.google.com" + "/abc-defg-hij"
    event = sink.emit("meeting.joined", url=url)
    assert url not in (tmp_path / "events.jsonl").read_text()
    assert url not in capsys.readouterr().out
    assert "url" not in event


def test_FR_MTG_10_participant_chat_leave_requests_shutdown_without_recording():
    from collections import Counter

    session = LiveSession.__new__(LiveSession)
    session.br = SimpleNamespace(read_chat=AsyncMock(return_value=[("Person", "Tilo leave")]))
    session.chat_seen = Counter()
    session.ignore, session.own_texts = set(), set()
    session.leave_requested = False
    session.record = lambda *a, **k: pytest.fail("leave command must terminate before capture")
    asyncio.run(session._read_chat())
    assert session.leave_requested


def test_FR_MTG_09_auto_admit_and_host_browser_creation_refuse_before_opening(monkeypatch):
    from bot.guards import BotRefused

    monkeypatch.setattr("bot.session.start_up_check", lambda: None)

    session = LiveSession.__new__(LiveSession)
    session.mode, session.auto_admit = "start", False
    with pytest.raises(BotRefused):
        asyncio.run(session.run())
    session.mode, session.auto_admit = "join", True
    with pytest.raises(BotRefused):
        asyncio.run(session.run())


def test_FR_MTG_01_formatted_exception_logs_remove_meet_links():
    import logging

    from bot.config import SafeFormatter

    url = "https://meet.google.com/abc-defg-hij"
    try:
        raise RuntimeError(url)
    except RuntimeError:
        import sys

        record = logging.LogRecord("bot", logging.ERROR, "", 0, "failed %s", (url,), sys.exc_info())
    assert url not in SafeFormatter("%(message)s").format(record)


@pytest.mark.parametrize("disclosed", [True, False])
def test_FR_MTG_01_live_session_discloses_before_audio_and_captions(monkeypatch, tmp_path, disclosed):
    from bot.config import Config
    from bot.guards import BotRefused

    monkeypatch.setattr("bot.config.load_dotenv", lambda path=None: None)
    monkeypatch.setenv("OUT_DIR", str(tmp_path / "out"))
    monkeypatch.setenv("CONTEXT_DIR", str(tmp_path / "context"))
    monkeypatch.setenv("AGENDA_PATH", str(tmp_path / "absent.md"))
    monkeypatch.setattr("bot.session.start_up_check", lambda: None)
    order = []

    class Browser:
        account_name, page = None, None
        open_meeting, join = AsyncMock(), AsyncMock(return_value=False)
        enable_captions = AsyncMock(return_value=True)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            pass

    async def disclosure(*args):
        order.append("disclosure")
        return disclosed

    async def mark_audio():
        order.append("audio")

    async def mark_captions():
        order.append("captions")

    async def loop():
        order.append("loop")

    monkeypatch.setattr("bot.session.MeetBrowser", lambda *a, **k: Browser())
    monkeypatch.setattr("bot.session.CaptionReader", lambda *a, **k: SimpleNamespace(start=mark_captions))
    session = LiveSession(Config.from_env(), "join", "", None, None, False, [], False, False, [])
    session._setup_voice, session._prewarm = lambda: None, lambda: None
    session._post, session._start_audio, session._loop = disclosure, mark_audio, loop
    session._shutdown = AsyncMock()
    if disclosed:
        asyncio.run(session.run())
        assert order == ["disclosure", "audio", "captions", "loop"]
    else:
        with pytest.raises(BotRefused):
            asyncio.run(session.run())
        assert order == ["disclosure"]
    session._shutdown.assert_awaited_once()


def test_FR_MTG_01_summary_and_latency_files_remove_pasted_meet_links(tmp_path):
    from bot.brain import Brain
    from bot.clock import SystemClock
    from bot.timing import Timeline
    from bot.trace import TurnTrace

    url = "https://meet.google.com/abc-defg-hij"
    brain = Brain.__new__(Brain)
    brain.state = SimpleNamespace(to_dict=lambda: {"decisions": [url]})
    brain.policy = SimpleNamespace(sent=0, direct_sent=0)
    brain.summary_markdown = lambda *a: url
    brain.write_outputs(tmp_path)
    Timeline(tmp_path / "latency.jsonl").record("answer", reply=url)
    trace = TurnTrace(tmp_path / "turns.jsonl", SystemClock())
    trace.finish(trace.new_turn("Person", url, 0), "spoken")
    for path in tmp_path.iterdir():
        assert url not in path.read_text(), path.name
