"""FR-INT-02 / CC-SP-47 follow-ups (issue #103, plus the safety.py:152 item of #139):
corrupt recordings fail as ProviderError, recordings are written atomically, the
safety role never falls back, live reasons are mapped to a fixed category, the
media-type gate lives in the base class, and the fake is refused in any Cloud Run
environment."""

from __future__ import annotations

import json
import os
from typing import Any

import pytest
from conftest import prices_config_for, safety_models_config, write_providers_config
from tilo_providers.config import ProviderConfigError, load_providers_config
from tilo_providers.errors import ProviderError, RequestError
from tilo_providers.interfaces import SafetyProvider
from tilo_providers.replay import ReplayMissError
from tilo_providers.safety import (
    SAFETY_REASON_CATEGORIES,
    FakeSafetyProvider,
    SafetyRecordReplayProvider,
    build_safety_provider,
    safety_recording_key,
)

pytestmark = pytest.mark.usefixtures("block_non_local_sockets")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ("LIVE", "TILO_RECORD", "K_SERVICE", "CLOUD_RUN_JOB"):
        monkeypatch.delenv(name, raising=False)


def _unexpected_live() -> SafetyProvider:
    raise AssertionError("replay must not build a live provider")


def _replayer(tmp_path) -> SafetyRecordReplayProvider:
    return SafetyRecordReplayProvider("safety", "model-armor-1", _unexpected_live, tmp_path)


def _recording_path(tmp_path, text: str):
    key = safety_recording_key("safety", "model-armor-1", text)
    return tmp_path / "safety-recordings" / "safety" / f"{key}.json"


class _Live:
    def __init__(self, reason: str | None, flagged: bool = True) -> None:
        self._result = {"flagged": flagged, "reason": reason}

    def check(self, text: str, **kwargs: Any) -> dict:
        return dict(self._result)


def _record(tmp_path, monkeypatch, live: Any, text: str = "some text"):
    monkeypatch.setenv("LIVE", "1")
    monkeypatch.setenv("TILO_RECORD", "1")
    provider = SafetyRecordReplayProvider("safety", "model-armor-1", lambda: live, tmp_path)
    return provider.check(text)


# --- (1) corrupt recordings -------------------------------------------------------------------

_CORRUPT = [
    b"",
    b'{"role": "safety", "result": {"flagged": tr',  # truncated
    b"\xff\xfe\x00 not utf-8",
    b"[]",
    b'"a string"',
    b'{"role": "safety"}',  # no result
    b'{"result": null}',
    b'{"result": []}',
    b'{"result": {"flagged": true}}',
    b'{"result": {"flagged": "yes", "reason": null}}',
    b'{"result": {"flagged": false, "reason": 5}}',
]


@pytest.mark.parametrize("raw", _CORRUPT)
def test_FR_INT_02_corrupt_recording_raises_provider_error(tmp_path, raw):
    path = _recording_path(tmp_path, "hello")
    path.parent.mkdir(parents=True)
    path.write_bytes(raw)

    with pytest.raises(ProviderError) as excinfo:
        _replayer(tmp_path).check("hello")

    assert not isinstance(excinfo.value, ReplayMissError)
    assert str(path.name) in str(excinfo.value)


# --- (2) atomic recording writes --------------------------------------------------------------


def test_FR_INT_02_recording_is_written_through_a_temp_file_and_os_replace(tmp_path, monkeypatch):
    replaced: list[tuple[str, str]] = []
    real_replace = os.replace

    def spy(src, dst):
        replaced.append((str(src), str(dst)))
        assert json.loads(open(src, encoding="utf-8").read())["result"], "temp file is complete before the swap"
        assert not os.path.exists(dst), "the final name does not exist until the swap"
        return real_replace(src, dst)

    monkeypatch.setattr("tilo_providers.safety.os.replace", spy)

    _record(tmp_path, monkeypatch, _Live(None, flagged=False))

    final = _recording_path(tmp_path, "some text")
    assert [dst for _, dst in replaced] == [str(final)]
    assert replaced[0][0] != str(final)
    assert os.path.dirname(replaced[0][0]) == str(final.parent), "same directory, so the swap is atomic"
    assert [p.name for p in final.parent.iterdir()] == [final.name], "no temp file is left behind"


def test_FR_INT_02_failed_swap_leaves_the_old_recording_intact_and_no_temp_file(tmp_path, monkeypatch):
    final = _recording_path(tmp_path, "some text")
    final.parent.mkdir(parents=True)
    old = '{"result": {"flagged": false, "reason": null}}\n'
    final.write_text(old, encoding="utf-8")

    def boom(src, dst):
        raise OSError("disk gone")

    monkeypatch.setattr("tilo_providers.safety.os.replace", boom)
    with pytest.raises(OSError, match="disk gone"):
        _record(tmp_path, monkeypatch, _Live(None, flagged=False))

    assert final.read_text(encoding="utf-8") == old
    assert [p.name for p in final.parent.iterdir()] == [final.name]


# --- (3) the safety role never falls back -----------------------------------------------------


def _two_profile_config(tmp_path):
    models = safety_models_config("model_armor")
    models["profiles"]["safety-weak"] = {"provider": "fake", "model": "fake-safety-1", "context": 1, "caps": []}
    models["roles"]["safety"] = {"primary": "safety-active", "fallback": "safety-weak"}
    prices = prices_config_for({"safety-active": (0.0, 0.0), "safety-weak": (0.0, 0.0)})
    return load_providers_config(*write_providers_config(tmp_path, models, prices))


def test_FR_INT_02_safety_role_uses_only_its_primary_and_never_falls_back(tmp_path, monkeypatch):
    provider = build_safety_provider(_two_profile_config(tmp_path), fixtures_dir=tmp_path / "fixtures")

    assert isinstance(provider, SafetyRecordReplayProvider)
    assert not isinstance(provider, FakeSafetyProvider)
    # a replay miss and a refused live adapter both raise; neither is answered by the weaker profile
    with pytest.raises(ReplayMissError):
        provider.check("never recorded")
    monkeypatch.setenv("LIVE", "1")
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)  # the live adapter is built; no project -> it refuses
    with pytest.raises(ProviderConfigError, match="GOOGLE_CLOUD_PROJECT"):
        provider.check("never recorded")


def test_FR_INT_02_safety_fallback_policy_is_documented_in_the_factory():
    doc = (build_safety_provider.__doc__ or "").lower()
    assert "never falls back" in doc and "fail" in doc and "closed" in doc


# --- (4) live reason mapped to a fixed category -----------------------------------------------


@pytest.mark.parametrize(
    ("raw_reason", "category"),
    [
        ("Blocked: prompt injection detected in 'the secret plan of Acme'", "prompt_injection"),
        ("jailbreak attempt", "prompt_injection"),
        ("Sensitive data: card 4111 1111 1111 1111", "sensitive_data"),
        ("hate speech toward Jane Doe", "unsafe_content"),
        ("quota-ish gibberish from the backend, Authorization: Bearer abc", "other"),
    ],
)
def test_FR_INT_02_live_reason_is_recorded_as_a_fixed_category(tmp_path, monkeypatch, raw_reason, category):
    result = _record(tmp_path, monkeypatch, _Live(raw_reason))

    assert result == {"flagged": True, "reason": category}
    assert category in SAFETY_REASON_CATEGORIES
    text = _recording_path(tmp_path, "some text").read_text(encoding="utf-8")
    for fragment in ("Acme", "Jane", "4111", "Bearer", "backend"):
        assert fragment not in text
    monkeypatch.delenv("LIVE")
    monkeypatch.delenv("TILO_RECORD")
    assert _replayer(tmp_path).check("some text") == result


def test_FR_INT_02_unflagged_live_result_keeps_a_null_reason_and_replay_maps_old_verbatim_reasons(
    tmp_path, monkeypatch
):
    assert _record(tmp_path, monkeypatch, _Live("anything", flagged=False)) == {"flagged": False, "reason": None}
    monkeypatch.delenv("LIVE")
    monkeypatch.delenv("TILO_RECORD")
    old = _recording_path(tmp_path, "older")
    old.write_text('{"result": {"flagged": true, "reason": "verbatim: Acme plan"}}', encoding="utf-8")

    assert _replayer(tmp_path).check("older") == {"flagged": True, "reason": "other"}


# --- (5) media-type gate in the base class ----------------------------------------------------


class _Spy(SafetyProvider):
    def __init__(self) -> None:
        self.seen: list[tuple[str, bytes | None, str | None]] = []

    def _check(self, text, *, content=None, mime_type=None):
        self.seen.append((text, content, mime_type))
        return {"flagged": False, "reason": None}


@pytest.mark.parametrize(
    ("content", "mime"),
    [(b"x", "image/gif"), (b"x", None), (None, "image/png"), ("not bytes", "image/png"), (b"x", "text/html")],
)
def test_FR_INT_02_base_class_refuses_an_unscreenable_file_before_the_subclass_runs(content, mime):
    spy = _Spy()

    with pytest.raises(RequestError):
        spy.check("", content=content, mime_type=mime)  # type: ignore[arg-type]

    assert spy.seen == []


def test_FR_INT_02_base_class_passes_the_normalised_media_type_to_the_subclass():
    spy = _Spy()

    assert spy.check("t", content=b"%PDF", mime_type=" Application/PDF ") == {"flagged": False, "reason": None}
    assert spy.check("plain") == {"flagged": False, "reason": None}
    assert spy.seen == [("t", b"%PDF", "application/pdf"), ("plain", None, None)]


def test_FR_INT_02_a_subclass_cannot_skip_the_gate_by_omitting_the_hook():
    class NoHook(SafetyProvider):
        pass

    with pytest.raises(TypeError):
        NoHook()  # type: ignore[abstract]


# --- (6) the fake is refused in any Cloud Run environment -------------------------------------


@pytest.mark.parametrize(
    ("name", "value"),
    [("K_SERVICE", ""), ("K_SERVICE", "tilo-api"), ("CLOUD_RUN_JOB", ""), ("CLOUD_RUN_JOB", "tilo-worker")],
)
def test_FR_INT_02_fake_is_refused_when_a_cloud_run_variable_is_present_even_if_empty(
    tmp_path, monkeypatch, name, value
):
    config = load_providers_config(
        *write_providers_config(
            tmp_path, safety_models_config("fake"), prices_config_for({"safety-active": (0.0, 0.0)})
        )
    )
    monkeypatch.setenv(name, value)

    with pytest.raises(ProviderConfigError, match="fake"):
        build_safety_provider(config, fixtures_dir=tmp_path / "fixtures")


@pytest.mark.parametrize("flag", ["true", "0", ""])
def test_FR_INT_02_live_flag_is_read_exactly_like_the_replay_layer_reads_it(tmp_path, monkeypatch, flag):
    """Only LIVE=1 is live mode, here and in tilo_providers.replay."""
    config = load_providers_config(
        *write_providers_config(
            tmp_path, safety_models_config("fake"), prices_config_for({"safety-active": (0.0, 0.0)})
        )
    )
    monkeypatch.setenv("LIVE", flag)

    assert isinstance(build_safety_provider(config, fixtures_dir=tmp_path / "fixtures"), FakeSafetyProvider)
