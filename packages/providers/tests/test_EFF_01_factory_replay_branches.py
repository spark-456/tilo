"""EFF-01 / PL-02 (PRD 6.6 "Record and replay", PRD 6.4): branch coverage for
the live-provider factory (`openai_compat`, misconfigured and unknown
providers) and for `RecordReplayProvider`'s stream/embed/capabilities/price
paths. Existing code, so these pass today; each asserts the behaviour a
caller sees, with a fake live provider injected (no network, no real call).
Fake secrets are assembled at runtime.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from conftest import build_providers_config, models_config, prices_config
from tilo_providers.config import ProviderConfigError
from tilo_providers.errors import ProviderError
from tilo_providers.factory import build_provider
from tilo_providers.interfaces import Capability, GenerateRequest, GenerateResponse, ModelProvider
from tilo_providers.replay import RecordReplayProvider, ReplayMissError, embed_recording_key, recording_key

KEY_ENV = "TILO_TEST_COMPAT_KEY"
FAKE_KEY = "sk-" + "x" * 20  # assembled at runtime, never a real credential


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("LIVE", raising=False)
    monkeypatch.delenv("TILO_RECORD", raising=False)


def _config(**profile_overrides: Any):
    models = models_config()
    models["profiles"]["large"].update({"provider": "openai_compat", "caps": ["json", "tools"], **profile_overrides})
    return build_providers_config(models, prices_config())


def _compat_config():
    return _config(base_url="https://mock.compat.example/v1", api_key_env=KEY_ENV)


class _Live(ModelProvider):
    """Fake live provider: scripted stream chunks, canned embedding, a redact()
    that scrubs FAKE_KEY like a real adapter holding that key would."""

    def __init__(self, chunks: list[GenerateResponse] | None = None, embedding: Any = None) -> None:
        self.chunks = chunks or []
        self.embedding = embedding
        self.stream_calls = 0
        self.embed_calls = 0

    def generate(self, request: GenerateRequest) -> GenerateResponse:
        return GenerateResponse(text="live", profile_id="large")

    def stream(self, request: GenerateRequest):
        self.stream_calls += 1
        yield from self.chunks

    def embed(self, request: Any) -> Any:
        self.embed_calls += 1
        return self.embedding

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    def capabilities(self) -> set[Capability]:
        return {Capability.VISION}

    def price(self):
        raise NotImplementedError

    def redact(self, text: str) -> str:
        return text.replace(FAKE_KEY, "[redacted]")


def _replayer(tmp_path, live: ModelProvider | None = None, caps: set[Capability] | None = None):
    def factory():
        assert live is not None, "a replay-only provider must never build the live provider"
        return live

    return RecordReplayProvider(
        role="director", profile_id="large", live_factory=factory, fixtures_dir=tmp_path, capabilities=caps
    )


def _chunk(**fields: Any) -> GenerateResponse:
    return GenerateResponse(profile_id="large", **fields)


# --- factory._build_live_provider -----------------------------------------


def test_EFF_01_openai_compat_profile_builds_the_adapter_lazily_under_live(tmp_path, monkeypatch):
    from tilo_providers.openai_compat_adapter import OpenAICompatModelProvider  # noqa: PLC0415

    provider = build_provider("director", _compat_config(), fixtures_dir=tmp_path)
    assert isinstance(provider, RecordReplayProvider)
    assert provider.capabilities() == {Capability.JSON, Capability.TOOLS}  # replay: declared caps, no adapter built

    monkeypatch.setenv("LIVE", "1")
    monkeypatch.setenv(KEY_ENV, FAKE_KEY)
    assert provider.capabilities() == {Capability.JSON, Capability.TOOLS}  # live: the adapter's own answer
    live = provider._live()  # the production live_factory closure's product
    assert isinstance(live, OpenAICompatModelProvider)
    assert provider._live() is live, "the live provider is built once and reused"


def test_EFF_01_openai_compat_adapter_receives_the_injected_live_permission(tmp_path, monkeypatch):
    """SEC-15: the factory hands `live_permitted` to the adapter, which refuses to build without LIVE=1 otherwise."""
    from tilo_providers.openai_compat_adapter import OpenAICompatModelProvider  # noqa: PLC0415

    monkeypatch.setenv(KEY_ENV, FAKE_KEY)
    permitted = build_provider("director", _compat_config(), fixtures_dir=tmp_path, live_permitted=True)
    assert isinstance(permitted._live(), OpenAICompatModelProvider)

    refused = build_provider("director", _compat_config(), fixtures_dir=tmp_path)
    with pytest.raises(ProviderError, match="refusing to build a real network client"):
        refused._live()


@pytest.mark.parametrize("missing", ["base_url", "api_key_env"])
def test_PL_02_openai_compat_profile_without_endpoint_fields_names_pl_02_and_the_profile(
    tmp_path, monkeypatch, missing
):
    fields = {"base_url": "https://mock.compat.example/v1", "api_key_env": KEY_ENV}
    del fields[missing]
    provider = build_provider("director", _config(**fields), fixtures_dir=tmp_path)
    monkeypatch.setenv("LIVE", "1")

    with pytest.raises(ProviderConfigError) as excinfo:
        provider.capabilities()

    message = str(excinfo.value)
    assert "PL-02" in message
    assert "'large'" in message
    assert "base_url" in message
    assert "api_key_env" in message


def test_EFF_01_unknown_provider_fails_when_the_call_goes_live(tmp_path, monkeypatch):
    provider = build_provider("director", _config(provider="mystery_cloud"), fixtures_dir=tmp_path)
    assert provider.capabilities() == {Capability.JSON, Capability.TOOLS}, "replay never needs the adapter"

    monkeypatch.setenv("LIVE", "1")
    with pytest.raises(ValueError, match=r"PL-02: unknown provider 'mystery_cloud' for profile 'large'"):
        provider.capabilities()


# --- replay.py: stream -----------------------------------------------------


def test_EFF_01_replayed_stream_yields_the_recorded_turn_as_one_chunk(tmp_path, monkeypatch):
    request = GenerateRequest(prompt="hi")
    monkeypatch.setenv("LIVE", "1")
    monkeypatch.setenv("TILO_RECORD", "1")
    _replayer(tmp_path, _Live()).generate(request)  # live generate() records "live"
    monkeypatch.delenv("LIVE")
    monkeypatch.delenv("TILO_RECORD")

    chunks = list(_replayer(tmp_path).stream(request))

    assert [c.text for c in chunks] == ["live"], "replay yields one chunk; the live provider is never built"


def test_EFF_01_replayed_stream_miss_raises_replay_miss_error(tmp_path):
    with pytest.raises(ReplayMissError, match="EFF-01"):
        list(_replayer(tmp_path).stream(GenerateRequest(prompt="never recorded")))


def test_EFF_01_live_stream_passes_chunks_through_and_writes_nothing_without_record(tmp_path, monkeypatch):
    monkeypatch.setenv("LIVE", "1")
    live = _Live(chunks=[_chunk(text="a"), _chunk(text="b")])

    chunks = list(_replayer(tmp_path, live).stream(GenerateRequest(prompt="hi")))

    assert [c.text for c in chunks] == ["a", "b"]
    assert live.stream_calls == 1
    assert list(tmp_path.rglob("*.json")) == []


def test_EFF_01_recorded_stream_joins_text_tool_calls_and_last_usage_then_replays(tmp_path, monkeypatch):
    request = GenerateRequest(prompt="hi")
    call = {"name": "lookup", "args": {"q": "x"}}
    usage = {"input_tokens": 3, "output_tokens": 5, "total_tokens": 8}
    live = _Live(
        chunks=[
            _chunk(text="hel", usage={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}),
            _chunk(tool_calls=[call]),
            _chunk(text="lo", usage=usage),
        ]
    )
    monkeypatch.setenv("LIVE", "1")
    monkeypatch.setenv("TILO_RECORD", "1")
    list(_replayer(tmp_path, live).stream(request))

    path = tmp_path / "model-recordings" / "director" / f"{recording_key('director', 'large', request)}.json"
    recorded = json.loads(path.read_text(encoding="utf-8"))["response"]
    assert recorded == {"text": "hello", "profile_id": "large", "tool_calls": [call], "usage": usage}

    monkeypatch.delenv("LIVE")
    monkeypatch.delenv("TILO_RECORD")
    assert list(_replayer(tmp_path).stream(request)) == [GenerateResponse.model_validate(recorded)]


def test_EFF_01_recorded_tool_call_only_stream_has_no_text_and_no_usage(tmp_path, monkeypatch):
    request = GenerateRequest(prompt="hi")
    monkeypatch.setenv("LIVE", "1")
    monkeypatch.setenv("TILO_RECORD", "1")
    list(_replayer(tmp_path, _Live(chunks=[_chunk(tool_calls=[{"name": "t", "args": {}}])])).stream(request))

    path = tmp_path / "model-recordings" / "director" / f"{recording_key('director', 'large', request)}.json"
    recorded = json.loads(path.read_text(encoding="utf-8"))["response"]
    assert recorded == {"profile_id": "large", "tool_calls": [{"name": "t", "args": {}}]}


# --- replay.py: embed ------------------------------------------------------


def test_EFF_01_embed_replay_miss_names_the_embed_key_and_never_goes_live(tmp_path):
    request = {"input": ["never recorded"]}
    key = embed_recording_key("director", "large", request)

    with pytest.raises(ReplayMissError) as excinfo:
        _replayer(tmp_path).embed(request)

    assert key in str(excinfo.value)
    assert "EFF-01" in str(excinfo.value)


def test_EFF_01_live_embed_without_record_returns_the_embedding_and_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("LIVE", "1")
    live = _Live(embedding=[[0.25, 0.5]])

    assert _replayer(tmp_path, live).embed({"input": ["a"]}) == [[0.25, 0.5]]
    assert live.embed_calls == 1
    assert list(tmp_path.rglob("*.json")) == []


def test_EFF_01_embed_record_then_replay_round_trip_redacts_echoed_secrets(tmp_path, monkeypatch):
    request = {"input": ["a"]}
    live = _Live(embedding={"vector": [0.25, 0.5], "model": f"echo-{FAKE_KEY}"})
    monkeypatch.setenv("LIVE", "1")
    monkeypatch.setenv("TILO_RECORD", "1")
    _replayer(tmp_path, live).embed(request)

    path = (
        tmp_path / "model-recordings" / "director" / f"embed-{embed_recording_key('director', 'large', request)}.json"
    )
    text = path.read_text(encoding="utf-8")
    assert FAKE_KEY not in text, "PRD 16.1 rule 4: the secret must not reach the recording"
    assert text.endswith("\n")

    monkeypatch.delenv("LIVE")
    monkeypatch.delenv("TILO_RECORD")
    assert _replayer(tmp_path).embed(request) == {"vector": [0.25, 0.5], "model": "echo-[redacted]"}
    assert live.embed_calls == 1, "replay must not call the live provider again"


# --- replay.py: capabilities, price, tokens ---------------------------------


def test_EFF_01_capabilities_replay_uses_declared_caps_and_live_asks_the_provider(tmp_path, monkeypatch):
    provider = _replayer(tmp_path, _Live(), caps={Capability.JSON})
    assert provider.capabilities() == {Capability.JSON}

    monkeypatch.setenv("LIVE", "1")
    assert provider.capabilities() == {Capability.VISION}


def test_EFF_01_record_replay_price_is_not_a_provider_concern(tmp_path):
    with pytest.raises(NotImplementedError, match="PL-06"):
        _replayer(tmp_path).price()
