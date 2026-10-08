"""A throttled project is slow (first live meeting: calls took 0.7 s to 15 s and some failed with 429), so the
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


def test_QUOTA_the_session_builds_the_fast_client_with_that_deadline(session):  # noqa: F811
    assert session._build_fast().first_token_s == pytest.approx(session.cfg.fast_first_token_s)


def test_START_admitting_someone_triggers_the_start_check_at_once(session):  # noqa: F811
    s = session
    s.next_status_at = s.clock.now() + 50
    s._on_admitted("Sam")
    assert s.next_status_at <= s.clock.now()  # no waiting for the next 6 s check: speech right after admission counts
    rows = (s.out_dir / "events.jsonl").read_text(encoding="utf-8")
    assert "participant.admitted" in rows and "Sam" in rows


def test_START_the_check_before_the_meeting_starts_runs_often():
    from bot.session import STATUS_EVERY_S

    assert STATUS_EVERY_S <= 3.0
