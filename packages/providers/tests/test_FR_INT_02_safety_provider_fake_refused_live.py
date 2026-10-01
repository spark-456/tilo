"""FR-INT-02 / CC-SP-47 (SEC-04, PRD 16.3 item 2): the deterministic
`FakeSafetyProvider` never screens a live or deployed service. A `provider:
fake` safety profile is refused loudly when `LIVE=1` or when deployed on
Cloud Run (`K_SERVICE` set); dev and tests with neither keep the fake."""

from __future__ import annotations

import pytest
from conftest import prices_config_for, safety_models_config, write_providers_config
from tilo_providers.config import ProviderConfigError, load_providers_config
from tilo_providers.safety import FakeSafetyProvider, build_safety_provider

pytestmark = pytest.mark.usefixtures("block_non_local_sockets")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ("LIVE", "TILO_RECORD", "K_SERVICE"):
        monkeypatch.delenv(name, raising=False)


def _fake_safety_config(tmp_path):
    models = safety_models_config("fake")
    prices = prices_config_for({"safety-active": (0.0, 0.0)})
    return load_providers_config(*write_providers_config(tmp_path, models, prices))


def test_FR_INT_02_fake_safety_profile_refused_when_live(tmp_path, monkeypatch):
    config = _fake_safety_config(tmp_path)
    monkeypatch.setenv("LIVE", "1")

    with pytest.raises(ProviderConfigError, match="fake"):
        build_safety_provider(config, fixtures_dir=tmp_path / "fixtures")


def test_FR_INT_02_fake_safety_profile_refused_when_deployed(tmp_path, monkeypatch):
    config = _fake_safety_config(tmp_path)
    monkeypatch.setenv("K_SERVICE", "tilo-api")

    with pytest.raises(ProviderConfigError, match="fake"):
        build_safety_provider(config, fixtures_dir=tmp_path / "fixtures")


def test_FR_INT_02_fake_safety_profile_allowed_in_dev_and_tests(tmp_path):
    config = _fake_safety_config(tmp_path)

    provider = build_safety_provider(config, fixtures_dir=tmp_path / "fixtures")

    assert isinstance(provider, FakeSafetyProvider)
