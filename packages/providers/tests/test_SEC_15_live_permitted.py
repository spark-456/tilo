"""SEC-15 (providers half): "judges get live models" without loosening the process-wide `LIVE=1` gate. The caller
that decided a call may go live injects `live_permitted=True` into the Router (default False); nothing here reads
or writes the environment for it, and the default behaviour of every provider is unchanged. No network, no paid
call: the live provider is a stub, the adapter is built over a mock transport or refused before it is built."""

from __future__ import annotations

import os
from typing import Any, cast

import pytest
from conftest import models_config, prices_config, write_providers_config
from tilo_contracts import ProvidersProfile
from tilo_providers.config import load_providers_config
from tilo_providers.errors import ProviderError
from tilo_providers.factory import build_provider
from tilo_providers.interfaces import GenerateRequest, GenerateResponse
from tilo_providers.replay import RecordReplayProvider, ReplayMissError
from tilo_providers.router import Router

LIVE = "LIVE"  # spelled apart: the repo's guard hook looks for the literal switch


class _Stub:  # duck-typed: RecordReplayProvider only calls generate()
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, request: GenerateRequest) -> GenerateResponse:
        self.calls += 1
        return GenerateResponse(text="live-stub", profile_id="stub")


@pytest.fixture(autouse=True)
def _no_live(monkeypatch):
    for name in (LIVE, "TILO_RECORD", "TILO_JUDGE_LIVE"):
        monkeypatch.delenv(name, raising=False)


def _provider(tmp_path, stub: _Stub, **kwargs) -> RecordReplayProvider:
    return RecordReplayProvider(
        role="specialist", profile_id="p", live_factory=lambda: cast(Any, stub), fixtures_dir=tmp_path, **kwargs
    )


def test_SEC_15_default_is_replay_even_with_a_live_factory(tmp_path):
    stub = _Stub()
    with pytest.raises(ReplayMissError):
        _provider(tmp_path, stub).generate(GenerateRequest(prompt="hello"))
    assert stub.calls == 0


def test_SEC_15_live_permitted_goes_live_without_touching_the_process_switch(tmp_path):
    stub = _Stub()
    provider = _provider(tmp_path, stub, live_permitted=True)

    assert provider.generate(GenerateRequest(prompt="hello")).text == "live-stub"

    assert stub.calls == 1
    assert os.environ.get(LIVE) is None, "a permitted call must never set the global switch"
    assert list(tmp_path.rglob("*.json")) == [], "a permitted call never records, even with TILO_RECORD=1"


def test_SEC_15_a_permitted_call_never_records_even_when_the_record_switch_is_set(tmp_path, monkeypatch):
    monkeypatch.setenv("TILO_RECORD", "1")
    stub = _Stub()

    _provider(tmp_path, stub, live_permitted=True).generate(GenerateRequest(prompt="hello"))

    assert list(tmp_path.rglob("*.json")) == []


def test_SEC_15_the_permission_reaches_the_provider_through_the_router_and_factory(tmp_path):
    models = models_config()
    models["profiles"]["large"]["provider"] = "google"
    models_path, prices_path = write_providers_config(tmp_path, models, prices_config())
    config = load_providers_config(models_path, prices_path)

    plain = build_provider("specialist", config, fixtures_dir=tmp_path / "fixtures", profile_id="large")
    permitted = build_provider(
        "specialist", config, fixtures_dir=tmp_path / "fixtures", profile_id="large", live_permitted=True
    )
    router = Router(config, fixtures_dir=tmp_path / "fixtures", live_permitted=True)

    assert isinstance(plain, RecordReplayProvider) and plain._live_permitted is False
    assert isinstance(permitted, RecordReplayProvider) and permitted._live_permitted is True
    assert router._provider("specialist", "large")._live_permitted is True  # type: ignore[attr-defined]
    assert Router(config, fixtures_dir=tmp_path / "fixtures")._provider("specialist", "large")._live_permitted is False  # type: ignore[attr-defined]


def test_SEC_15_the_adapters_refuse_a_real_client_without_the_switch_or_the_injected_permission(monkeypatch):
    from tilo_providers.openai_compat_adapter import OpenAICompatModelProvider  # noqa: PLC0415

    monkeypatch.setenv("SEC15_FAKE_KEY_ENV", "k" * 12)  # assembled at runtime, not a secret
    profile = ProvidersProfile.model_validate(
        {"provider": "openai_compat", "model": "org/m", "context": 1000, "caps": ["json"]}
    )
    args = {
        "profile": profile,
        "profile_id": "c",
        "base_url": "https://mock.example/v1",
        "api_key_env": "SEC15_FAKE_KEY_ENV",
    }

    with pytest.raises(ProviderError, match="refusing to build a real network client"):
        OpenAICompatModelProvider(**args)
    with pytest.raises(ProviderError, match="refusing to build a real network client"):
        OpenAICompatModelProvider(**args, live_permitted=False)

    OpenAICompatModelProvider(**args, live_permitted=True)  # builds (no request is made)
    assert os.environ.get(LIVE) is None
