"""RT-05: typed, offline embeddings and loader-checked retrieval config."""

from __future__ import annotations

import json
import math
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from pydantic import ValidationError
from tilo_contracts import ProvidersProfile
from tilo_providers.config import ProviderConfigError, load_providers_config
from tilo_providers.factory import build_provider
from tilo_providers.fake import FakeModelProvider
from tilo_providers.interfaces import EmbedRequest, EmbedResponse
from tilo_providers.memory_config import load_memory_config
from tilo_providers.replay import RecordReplayProvider, embed_recording_key
from tilo_providers.router import Router

ROOT = Path(__file__).resolve().parents[3]


def test_RT_05_embed_request_and_response_are_bounded_and_typed():
    request = EmbedRequest(texts=["first", "second"], task="document", dimensions=768)
    assert request.texts == ["first", "second"]
    for values in (
        {"texts": [], "task": "query", "dimensions": 768},
        {"texts": ["x"] * 65, "task": "query", "dimensions": 768},
        {"texts": ["x"], "task": "other", "dimensions": 768},
        {"texts": ["x"], "task": "query", "dimensions": 63},
        {"texts": ["x"], "task": "query", "dimensions": 2049},
        {"texts": ["x"], "task": "query", "dimensions": 768, "secret": "no"},
    ):
        with pytest.raises(ValidationError):
            EmbedRequest.model_validate(values)
    with pytest.raises(ValidationError):
        EmbedResponse(vectors=[[0.1]], profile_id="fake", usage=None, secret="no")


def test_RT_05_fake_embed_is_seeded_unit_length_and_task_sensitive():
    fake = FakeModelProvider(profile_id="embed-fake")
    request = EmbedRequest(texts=["alpha", "beta"], task="document", dimensions=64)
    result = fake.embed(request)
    assert isinstance(result, EmbedResponse)
    assert result == fake.embed(request)
    assert result.profile_id == "embed-fake"
    assert len(result.vectors) == 2
    assert all(len(vector) == 64 and math.isclose(math.dist(vector, [0.0] * 64), 1.0) for vector in result.vectors)
    assert result.vectors[0] != result.vectors[1]
    assert result.vectors[0] != fake.embed(request.model_copy(update={"task": "query"})).vectors[0]


def test_RT_05_embed_role_and_memory_config_are_offline_and_checked(tmp_path):
    configs = [
        load_providers_config(ROOT / f"config/models{name}.yaml", ROOT / "config/prices.yaml")
        for name in ("", ".dev", ".gemini", ".nim")
    ]
    for selected in configs:
        role = selected.roles["embed"]
        assert role.primary == role.fallback == "embed-fake"
        assert selected.profiles[role.primary].provider == "fake"
        assert selected.price(role.primary).input == selected.price(role.primary).output == 0
    memory = load_memory_config(ROOT / "config/memory.yaml")
    assert (memory.vector.dimensions, memory.vector.k, memory.embed.batch_max) == (768, 5, 64)
    bad = tmp_path / "memory.yaml"
    bad.write_text("vector: {dimensions: 12, k: 5}\nembed: {batch_max: 65}\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_memory_config(bad)
    with pytest.raises(ProviderConfigError, match="live embedding model is not configured"):
        build_provider("embed", configs[0], fixtures_dir=tmp_path, live_permitted=True)


def test_RT_05_router_and_replay_keep_typed_embed_result(tmp_path, monkeypatch):
    monkeypatch.delenv("LIVE", raising=False)
    config = load_providers_config(ROOT / "config/models.dev.yaml", ROOT / "config/prices.yaml")
    request = EmbedRequest(texts=["hello"], task="query", dimensions=64)
    result = Router(config, fixtures_dir=tmp_path).embed("embed", request)
    assert isinstance(result.embedding, EmbedResponse)
    assert result.embedding.profile_id == "embed-fake"
    assert [attempt.profile_id for attempt in result.attempts] == ["embed-fake"]

    key = embed_recording_key("embed", "recorded", request)
    recording = tmp_path / "model-recordings/embed" / f"embed-{key}.json"
    recording.parent.mkdir(parents=True)
    expected = EmbedResponse(vectors=[[1.0] + [0.0] * 63], profile_id="recorded")
    recording.write_text(json.dumps({"embedding": expected.model_dump()}), encoding="utf-8")
    replay = RecordReplayProvider(
        role="embed", profile_id="recorded", live_factory=lambda: pytest.fail("network called"), fixtures_dir=tmp_path
    )
    assert replay.embed(request) == expected


def test_RT_05_google_adapter_maps_task_and_dimensions_without_network():
    from tilo_providers.google_adapter import GoogleModelProvider

    calls = []

    def embed_content(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(embeddings=[SimpleNamespace(values=[1.0] + [0.0] * 63)])

    profile = ProvidersProfile.model_validate(
        {"provider": "google", "model": "fake-model", "context": 1000, "caps": []}
    )
    provider = GoogleModelProvider(
        profile,
        "recorded",
        "fake-project",
        "global",
        client=SimpleNamespace(models=SimpleNamespace(embed_content=embed_content)),
    )
    result = provider.embed(EmbedRequest(texts=["question"], task="query", dimensions=64))
    assert result == EmbedResponse(vectors=[[1.0] + [0.0] * 63], profile_id="recorded")
    assert calls[0]["contents"] == ["question"]
    assert calls[0]["config"].output_dimensionality == 64
    assert calls[0]["config"].task_type == "RETRIEVAL_QUERY"


def test_RT_05_openai_adapter_maps_task_dimensions_and_usage(monkeypatch):
    from tilo_providers.openai_compat_adapter import OpenAICompatModelProvider

    monkeypatch.setenv("RT05_FAKE_KEY", "fake-" + "local-test-token")
    calls = []

    def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={"data": [{"embedding": [1.0] + [0.0] * 63}], "usage": {"total_tokens": 3}})

    profile = ProvidersProfile.model_validate(
        {"provider": "openai_compat", "model": "fake-model", "context": 1000, "caps": []}
    )
    provider = OpenAICompatModelProvider(
        profile, "recorded", "https://mock.example/v1", "RT05_FAKE_KEY", transport=httpx.MockTransport(handler)
    )
    result = provider.embed(EmbedRequest(texts=["note"], task="document", dimensions=64))
    assert result == EmbedResponse(vectors=[[1.0] + [0.0] * 63], profile_id="recorded", usage={"total_tokens": 3})
    assert calls == [{"model": "fake-model", "input": ["note"], "dimensions": 64, "input_type": "document"}]
