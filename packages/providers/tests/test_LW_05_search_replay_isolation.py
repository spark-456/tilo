"""LW-05 / SEC-15: a replay decision overrides the process live switch."""

import pytest
from tilo_providers.replay import ReplayMissError
from tilo_providers.search import SearchRecordReplayProvider


def test_LW_05_force_replay_never_constructs_live_search(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LIVE", "1")
    monkeypatch.setenv("TILO_RECORD", "1")
    calls = []
    provider = SearchRecordReplayProvider("search-test", lambda: calls.append(1), tmp_path, force_replay=True)
    with pytest.raises(ReplayMissError):
        provider.search("public papers")
    assert not calls and not list(tmp_path.rglob("*.json"))
