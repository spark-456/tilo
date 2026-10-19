"""LW-16: one recorded free run joins search, native reads, reports and an owner-only quiz."""

import pytest
from tilo_evals import liveweb_replay
from tilo_providers.replay import ReplayMissError

EXPECTED = {
    "search_outcome": "ok",
    "side_effect_refused": True,
    "native_types": ["application/pdf", "application/pdf", "image/png"],
    "native_bytes_match_archive": True,
    "report_cites_fetched_urls": True,
    "report": {"media_type": "application/pdf", "origin": "render", "magic": "%PDF-"},
    "quiz": {
        "media_type": "application/json",
        "origin": "unit",
        "answer_checked": True,
        "owner_status": 200,
        "other_owner_status": 404,
        "publisher": {"art_liveweb_1": "sandbox-web.example"},
    },
    "app_events": ["app.spec", "app.tested", "app.deployed"],
    "verifier_received_pdf": True,
    "credits": 0,
}


def test_LW_16_complete_committed_replay(monkeypatch):
    monkeypatch.delenv("LIVE", raising=False)
    assert liveweb_replay.run_complete_case() == EXPECTED


def test_LW_16_complete_fake_record_matches_replay(tmp_path, monkeypatch):
    monkeypatch.delenv("LIVE", raising=False)
    monkeypatch.setattr(liveweb_replay, "FIXTURES", tmp_path / "recordings")
    assert liveweb_replay.run_complete_case(seed=True) == EXPECTED
    assert liveweb_replay.run_complete_case() == EXPECTED


def test_LW_16_missing_recording_never_falls_back_to_live(tmp_path, monkeypatch):
    monkeypatch.setattr(liveweb_replay, "FIXTURES", tmp_path / "empty")
    # An absent specialist response fails before any source or deployed artifact exists.
    with pytest.raises(ReplayMissError):
        liveweb_replay.run_complete_case()
