"""LW-05 / SEC-15: a replay decision overrides the process live switch."""

from typing import NoReturn

import pytest
from tilo_providers.replay import ReplayMissError
from tilo_providers.search import SearchRecordReplayProvider


def test_LW_05_force_replay_never_constructs_live_search(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LIVE", "1")
    monkeypatch.setenv("TILO_RECORD", "1")
    calls = []

    def forbidden_live() -> NoReturn:
        calls.append(1)
        raise AssertionError("replay constructed a live provider")

    provider = SearchRecordReplayProvider("search-test", forbidden_live, tmp_path, force_replay=True)
    with pytest.raises(ReplayMissError):
        provider.search("public papers")
    assert not calls and not list(tmp_path.rglob("*.json"))
