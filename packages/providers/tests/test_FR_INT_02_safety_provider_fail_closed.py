"""FR-INT-02 / CC-SP-47 builder tests: the safety layer fails closed on
config it cannot honour, on native files the replay layer cannot screen, and
on the not-yet-built Model Armor adapter (ADR-0003: mocks and recordings only)."""

from __future__ import annotations

from typing import Any

import pytest
from conftest import prices_config_for, safety_models_config, write_providers_config
from tilo_providers.config import ProviderConfigError, load_providers_config
from tilo_providers.errors import ProviderError, RequestError
from tilo_providers.replay import ReplayMissError
from tilo_providers.safety import SafetyRecordReplayProvider, build_safety_provider, safety_recording_key

pytestmark = pytest.mark.usefixtures("block_non_local_sockets")


@pytest.fixture(autouse=True)
def _no_live(monkeypatch):
    monkeypatch.delenv("LIVE", raising=False)
    monkeypatch.delenv("TILO_RECORD", raising=False)


def _config(tmp_path, models: dict):
    return load_providers_config(
        *write_providers_config(tmp_path, models, prices_config_for({"safety-active": (0.0, 0.0)}))
    )


def test_FR_INT_02_factory_refuses_a_config_without_a_safety_role(tmp_path):
    models = safety_models_config("fake")
    models["roles"] = {"other": models["roles"]["safety"]}
    with pytest.raises(ProviderConfigError, match="safety"):
        build_safety_provider(_config(tmp_path, models), fixtures_dir=tmp_path)


def test_FR_INT_02_factory_refuses_an_unknown_safety_provider(tmp_path):
    with pytest.raises(ProviderConfigError, match="mystery"):
        build_safety_provider(_config(tmp_path, safety_models_config("mystery")), fixtures_dir=tmp_path)


def test_FR_INT_02_model_armor_live_stub_refuses_instead_of_passing(tmp_path, monkeypatch):
    provider = build_safety_provider(_config(tmp_path, safety_models_config("model_armor")), fixtures_dir=tmp_path)
    monkeypatch.setenv("LIVE", "1")
    with pytest.raises(ProviderConfigError, match="not built yet"):
        provider.check("hello")


def test_FR_INT_02_replay_refuses_unsupported_media_before_any_lookup(tmp_path):
    provider = SafetyRecordReplayProvider("safety", "model-armor-1", _unexpected, tmp_path)
    with pytest.raises(RequestError, match="image/gif"):
        provider.check("", content=b"gif-bytes", mime_type="image/gif")
    with pytest.raises(RequestError):
        provider.check("", content=b"pdf-bytes")  # content without a media type


def test_FR_INT_02_native_file_records_by_digest_and_never_writes_raw_bytes(tmp_path, monkeypatch):
    seen: list[dict[str, Any]] = []

    class _NativeLive:
        def check(self, text: str, **kwargs: Any) -> dict:
            seen.append(kwargs)
            return {"flagged": True, "reason": "hidden instruction in image"}

    content = b"raw-png-bytes-that-must-not-be-recorded"
    monkeypatch.setenv("LIVE", "1")
    monkeypatch.setenv("TILO_RECORD", "1")
    SafetyRecordReplayProvider("safety", "model-armor-1", _NativeLive, tmp_path).check(
        "", content=content, mime_type="image/png"
    )
    assert seen == [{"content": content, "mime_type": "image/png"}]
    (recording,) = tmp_path.rglob("*.json")
    assert recording.stem == safety_recording_key("safety", "model-armor-1", "", content=content, mime_type="image/png")
    assert content.decode() not in recording.read_text(encoding="utf-8")

    monkeypatch.delenv("LIVE")
    replayer = SafetyRecordReplayProvider("safety", "model-armor-1", _unexpected, tmp_path)
    assert replayer.check("", content=content, mime_type="image/png")["flagged"] is True
    with pytest.raises(ReplayMissError):
        replayer.check("", content=content + b"!", mime_type="image/png")


def test_FR_INT_02_a_malformed_live_result_fails_closed(tmp_path, monkeypatch):
    class _Sloppy:
        def check(self, text: str, **kwargs: Any) -> dict:
            return {"flagged": "no"}

    monkeypatch.setenv("LIVE", "1")
    with pytest.raises(ProviderError):
        SafetyRecordReplayProvider("safety", "model-armor-1", _Sloppy, tmp_path).check("hello")


def _unexpected() -> Any:
    raise AssertionError("replay mode must not construct a live safety provider")
