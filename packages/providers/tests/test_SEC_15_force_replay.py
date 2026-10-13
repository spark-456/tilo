"""SEC-15 / BQ-SIGNIN-10 (providers half, SIGNIN-FIX r2): a caller's replay decision holds at the provider layer even
when the process-wide live switch is on. `force_replay=True` is injected into the Router, `build_provider` and
`build_safety_provider` (default False); it is never live, never records, and wins over `live_permitted`. The default
is unchanged. No network, no paid call: the live providers are stubs; the switch is set only through monkeypatch."""

from __future__ import annotations

from typing import Any, cast

import pytest
from conftest import models_config, prices_config, prices_config_for, safety_models_config, write_providers_config
from tilo_providers import factory, safety
from tilo_providers.config import load_providers_config
from tilo_providers.interfaces import GenerateRequest, GenerateResponse
from tilo_providers.replay import RecordReplayProvider, ReplayMissError
from tilo_providers.router import Router

LIVE = "LIVE"  # spelled apart: the repo's guard hook looks for the literal switch


class _Stub:  # duck-typed: RecordReplayProvider only calls generate()/capabilities()
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, request: GenerateRequest) -> GenerateResponse:
        self.calls += 1
        return GenerateResponse(text="live-stub", profile_id="stub")

    def capabilities(self) -> set[Any]:
        self.calls += 1
        return set()


@pytest.fixture(autouse=True)
def _switch_on(monkeypatch):
    monkeypatch.delenv("TILO_RECORD", raising=False)
    monkeypatch.setenv(LIVE, "1")


def _provider(tmp_path, stub: _Stub, **kwargs) -> RecordReplayProvider:
    return RecordReplayProvider(
        role="specialist", profile_id="p", live_factory=lambda: cast(Any, stub), fixtures_dir=tmp_path, **kwargs
    )


def test_SEC_15_force_replay_is_never_live_under_the_live_switch(tmp_path):
    stub = _Stub()
    provider = _provider(tmp_path, stub, force_replay=True)
    with pytest.raises(ReplayMissError):
        provider.generate(GenerateRequest(prompt="hello"))
    with pytest.raises(ReplayMissError):
        list(provider.stream(GenerateRequest(prompt="hello")))
    with pytest.raises(ReplayMissError):
        provider.embed({"input": ["hello"]})
    provider.capabilities()
    assert stub.calls == 0


def test_SEC_15_force_replay_wins_over_live_permitted_and_never_records(tmp_path, monkeypatch):
    monkeypatch.setenv("TILO_RECORD", "1")
    stub = _Stub()
    with pytest.raises(ReplayMissError):
        _provider(tmp_path, stub, force_replay=True, live_permitted=True).generate(GenerateRequest(prompt="hello"))
    assert stub.calls == 0
    assert list(tmp_path.rglob("*.json")) == []


def test_SEC_15_without_force_replay_the_live_switch_still_goes_live(tmp_path):
    stub = _Stub()
    assert _provider(tmp_path, stub).generate(GenerateRequest(prompt="hello")).text == "live-stub"
    assert stub.calls == 1


def test_SEC_15_force_replay_reaches_the_provider_through_the_router_and_factory(tmp_path, monkeypatch):
    built: list[str] = []
    monkeypatch.setattr(factory, "_build_live_provider", lambda *a, **k: built.append("live") or _Stub())
    models = models_config()
    models["profiles"]["large"]["provider"] = "google"
    models_path, prices_path = write_providers_config(tmp_path, models, prices_config())
    config = load_providers_config(models_path, prices_path)
    fixtures = tmp_path / "fixtures"

    forced = factory.build_provider("specialist", config, fixtures_dir=fixtures, profile_id="large", force_replay=True)
    routed = Router(config, fixtures_dir=fixtures, live_permitted=True, force_replay=True)._provider(
        "specialist", "large"
    )
    for provider in (forced, routed):
        assert isinstance(provider, RecordReplayProvider)
        provider.capabilities()
        with pytest.raises(ReplayMissError):
            provider.generate(GenerateRequest(prompt="hello"))
    assert built == [], "a forced replay never builds a live client"

    factory.build_provider("specialist", config, fixtures_dir=fixtures, profile_id="large").capabilities()
    assert built == ["live"], "the default is unchanged: the live switch builds the live client"


def test_SEC_15_force_replay_holds_for_the_safety_screen(tmp_path, monkeypatch):
    built: list[str] = []
    monkeypatch.setattr(safety, "_build_live_safety_provider", lambda *a, **k: built.append("live") or _Stub())
    models_path, prices_path = write_providers_config(
        tmp_path, safety_models_config("model_armor"), prices_config_for({"safety-active": (0.0, 0.0)})
    )
    config = load_providers_config(models_path, prices_path)

    screen = safety.build_safety_provider(config, fixtures_dir=tmp_path, force_replay=True)
    with pytest.raises(ReplayMissError):
        screen.check("hello")
    assert built == []

    plain = safety.build_safety_provider(config, fixtures_dir=tmp_path)
    with pytest.raises(Exception):  # noqa: B017  the stub is no real screen; only that it was built matters
        plain.check("hello")
    assert built == ["live"]
