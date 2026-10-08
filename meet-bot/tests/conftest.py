"""Every meet-bot test is offline (FR-MTG-11, EFF-01): the live switch and any config override a developer has in their own
shell are removed, so `bot/providers.py` always resolves the dev config whose profiles are deterministic fakes."""

import pytest

OVERRIDES = ("LIVE", "TILO_MODELS_FILE", "TILO_SPEECH_FILE", "TILO_VOICE_FILE", "TILO_REPO_ROOT", "TILO_RECORD")


@pytest.fixture(autouse=True)
def _offline_providers(monkeypatch):
    for name in OVERRIDES:
        monkeypatch.delenv(name, raising=False)
