"""21 Oct: the stored meeting transcript had none of Tilo's replies (16 utterances, all the owner's), so the minutes
summarised only the questions. Delivered replies go into the exported transcript under "Tilo", in time order, while
the brain still never reads them back (they are not in the session store)."""

import asyncio
import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock

from bot import cloud_worker
from bot.captions import Utterance
from bot.cloud_worker import transcript_from_items


def _session(monkeypatch, tmp_path):
    from bot.config import Config
    from bot.session import LiveSession

    monkeypatch.setattr("bot.config.load_dotenv", lambda path=None: None)
    monkeypatch.setenv("OUT_DIR", str(tmp_path / "out"))
    monkeypatch.setenv("CONTEXT_DIR", str(tmp_path / "ctx"))
    return LiveSession(
        Config.from_env(), "join", "https://meet.example/abc-defg-hij", None, 30, False, [], False, False, []
    )


def test_TRANSCRIPT_REPLIES_a_delivered_reply_is_kept_for_the_transcript_but_not_for_the_brain(monkeypatch, tmp_path):
    s = _session(monkeypatch, tmp_path)
    s.intro_sent = True
    s.br = SimpleNamespace(shot=AsyncMock())
    s.chat = SimpleNamespace(send=AsyncMock(return_value=True))
    s.start = s.clock.now() - 10.0  # ten seconds into the call
    s.store.append(Utterance("Sam", "What is the capital of France?", 5.0))
    ok, _ = asyncio.run(s._deliver(SimpleNamespace(kind="direct_reply", text="The capital of France is Paris.")))
    assert ok
    assert [(u.speaker, u.text) for u in s.replies] == [("Tilo", "The capital of France is Paris.")]
    assert all(u.speaker != "Tilo" for u in s.store.items)  # the brain never reads its own replies
    out = transcript_from_items("mt_x", [*s.store.items, *s.replies])
    assert [u["speaker"] for u in out["utterances"]] == ["Sam", "Tilo"]


def test_TRANSCRIPT_REPLIES_an_undelivered_reply_is_not_in_the_transcript(monkeypatch, tmp_path):
    s = _session(monkeypatch, tmp_path)
    s.intro_sent = True
    s.br = SimpleNamespace(shot=AsyncMock())
    s.chat = SimpleNamespace(send=AsyncMock(return_value=False))
    asyncio.run(s._deliver(SimpleNamespace(kind="direct_reply", text="Never heard.")))
    assert s.replies == []


def test_TRANSCRIPT_REPLIES_the_cloud_export_includes_the_replies():
    assert 'getattr(session, "replies"' in inspect.getsource(cloud_worker.attend_meeting)
