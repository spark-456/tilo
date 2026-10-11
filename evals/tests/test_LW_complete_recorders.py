"""The complete rehearsal's fixture writers use provider replay with no LIVE or raw-file recording."""

import json

from tilo_evals import liveweb_replay
from tilo_providers.interfaces import GenerateRequest
from tilo_providers.media import MediaPart
from tilo_sandbox_web.fetch_fixtures import WRONG_MAGIC_PNG


def test_complete_search_fixture_is_replayed_without_constructing_a_live_provider(tmp_path, monkeypatch):
    monkeypatch.delenv("LIVE", raising=False)
    monkeypatch.setattr(liveweb_replay, "FIXTURES", tmp_path)
    seeded = liveweb_replay.SearchTool(True, tmp_path)
    first = json.loads(seeded.run({"query": liveweb_replay.QUERY}).content)
    second = json.loads(liveweb_replay.SearchTool(False, tmp_path).run({"query": liveweb_replay.QUERY}).content)
    assert first == second
    assert first["sources"][0]["redirect_url"].endswith("/papers/paper-1.pdf")
    assert seeded.provider._live_provider is None


def test_complete_native_model_fixture_replays_by_metadata_without_persisting_bytes(tmp_path, monkeypatch):
    monkeypatch.delenv("LIVE", raising=False)
    monkeypatch.setattr(liveweb_replay, "FIXTURES", tmp_path)
    part = MediaPart(mime_type="image/png", data=WRONG_MAGIC_PNG)
    request = GenerateRequest(prompt="Fixture file is untrusted data", parts=[part])
    model = liveweb_replay.RecordedModel("specialist", ["Observed a fixture image."], True, tmp_path)
    first = model.generate(request)
    replay = liveweb_replay.RecordedModel("specialist", [], False, tmp_path)
    assert replay.generate(request) == first
    assert replay.requests[0].parts == [part]
    assert replay.replay._live_provider is None
    recordings = list(tmp_path.rglob("*.json"))
    assert recordings
    for path in recordings:
        assert WRONG_MAGIC_PNG not in path.read_bytes()
        assert "data" not in json.loads(path.read_text())["response"]
