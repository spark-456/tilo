"""The free Gemini key is throttled (first live meeting: calls took 0.7 s to 15 s and some failed with 429), so the
answers to people come first and the notes loop stays out of their way."""

import pytest
from test_ui import session  # noqa: F401  (fixture reused)

from bot.config import Config
from bot.session import LiveSession


def test_QUOTA_the_notes_loop_waits_while_a_question_is_being_answered_and_for_30s_after():
    allowed = LiveSession.analysis_allowed
    assert allowed(now=100.0, quick_running=True, last_question_at=99.0) is False
    assert allowed(now=100.0, quick_running=False, last_question_at=90.0) is False  # a conversation is going
    assert allowed(now=119.0, quick_running=False, last_question_at=90.0) is False
    assert allowed(now=120.1, quick_running=False, last_question_at=90.0) is True
    assert allowed(now=5.0, quick_running=False, last_question_at=-1e9) is True  # no question yet


def test_QUOTA_the_first_token_deadline_is_configurable_and_defaults_to_6_seconds(monkeypatch):
    monkeypatch.setattr("bot.config.load_dotenv", lambda path=None: None)
    monkeypatch.delenv("FAST_FIRST_TOKEN_SECONDS", raising=False)
    assert Config.from_env().fast_first_token_s == 6
    monkeypatch.setenv("FAST_FIRST_TOKEN_SECONDS", "3.5")
    assert Config.from_env().fast_first_token_s == 3.5


def test_QUOTA_the_session_builds_the_fast_client_with_that_deadline(session, monkeypatch):  # noqa: F811
    monkeypatch.setenv("GEMINI_API_KEY", "k-" + "z9" * 8)
    assert session._build_fast().first_token_s == pytest.approx(session.cfg.fast_first_token_s)
