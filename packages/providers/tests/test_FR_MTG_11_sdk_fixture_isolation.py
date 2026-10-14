"""Keep the original voice acceptance nodes independent of SDK fixture order."""

import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest
from _fake_genai_sdk import install

ROOT = Path(__file__).resolve().parents[3]
NODES = (
    "packages/providers/tests/test_FR_MTG_11_voice.py::"
    "test_FR_MTG_11_the_returned_audio_is_capped_by_the_config_not_by_trust",
    "packages/providers/tests/test_FR_MTG_11_gemini_live_voice.py::"
    "test_FR_MTG_11_PL_02_priced_live_path_opens_one_sdk_session_with_the_configured_model_and_voice",
)


@pytest.mark.parametrize("nodes", [NODES, NODES[::-1]], ids=["voice-then-live", "live-then-voice"])
def test_FR_MTG_11_PL_02_original_voice_nodes_are_order_independent(nodes):
    env = dict(os.environ, GOOGLE_LOCATION="asia-southeast1")
    env.pop("LIVE", None)
    env.pop("TILO_RECORD", None)
    result = subprocess.run(
        [sys.executable, "-m", "pytest", *nodes, "-q", "-p", "no:cacheprovider"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("present", [False, True], ids=["absent", "cached"])
def test_FR_MTG_11_PL_02_fake_sdk_restores_cache_and_namespace(monkeypatch, present):
    import google  # noqa: PLC0415

    names = ("google.genai", "google.genai.types", "google.genai.errors")
    previous = {name: ModuleType(name) for name in names}
    if present:
        for name, module in previous.items():
            monkeypatch.setitem(sys.modules, name, module)
        monkeypatch.setattr(google, "genai", previous["google.genai"], raising=False)
    else:
        for name in names:
            monkeypatch.delitem(sys.modules, name, raising=False)
        monkeypatch.delattr(google, "genai", raising=False)

    with pytest.MonkeyPatch.context() as sdk_patch:
        install(sdk_patch)
        assert google.genai is sys.modules["google.genai"]
        assert google.genai.types is sys.modules["google.genai.types"]
        assert google.genai.errors is sys.modules["google.genai.errors"]
    if present:
        assert all(sys.modules[name] is previous[name] for name in names)
        assert google.genai is previous["google.genai"]
    else:
        assert all(name not in sys.modules for name in names)
        assert not hasattr(google, "genai")
