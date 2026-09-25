"""PL-07 (PRD 6.4): "Denylisted ids never load" -- "Start-up fails loudly if
config references a denied model."

Covers both example deny-glob shapes config/models.yaml's own `rules.deny`
uses ("gemini-2.5-*", "*-preview*"), reproduced here with the "fake-*"
family so these fixtures stay independent of the real denylist.
"""

from __future__ import annotations

import pytest
from conftest import models_config, prices_config, write_providers_config
from tilo_providers.config import ProviderConfigError, load_providers_config


@pytest.mark.parametrize(
    ("deny_glob", "denied_model"),
    [
        ("fake-legacy-*", "fake-legacy-9"),
        ("*-preview*", "fake-medium-preview-3"),
    ],
    ids=["exact-family-glob", "wildcard-preview-glob"],
)
def test_PL_07_denylisted_model_fails_startup(tmp_path, deny_glob, denied_model):
    models = models_config()
    models["profiles"]["medium"]["model"] = denied_model
    models["rules"]["deny"] = [deny_glob]
    models_path, prices_path = write_providers_config(tmp_path, models, prices_config())

    with pytest.raises(ProviderConfigError) as excinfo:
        load_providers_config(models_path, prices_path)

    message = str(excinfo.value)
    assert denied_model in message, f"PL-07: error must name the denied model id, got: {message!r}"
    assert deny_glob in message, f"PL-07: error must name the matching deny rule, got: {message!r}"


def test_PL_07_denylisted_model_is_checked_across_every_profile(tmp_path):
    """The deny check is not limited to whichever profile a role happens to
    use first -- every profile in the config is checked at start-up."""
    models = models_config()
    models["profiles"]["small"]["model"] = "fake-legacy-42"
    models_path, prices_path = write_providers_config(tmp_path, models, prices_config())

    with pytest.raises(ProviderConfigError) as excinfo:
        load_providers_config(models_path, prices_path)

    assert "fake-legacy-42" in str(excinfo.value)


def test_PL_07_config_with_no_denied_models_loads_cleanly(tmp_path):
    """Sanity check for the two tests above: the same deny rules, applied to
    a config that does not violate them, must not raise."""
    models_path, prices_path = write_providers_config(tmp_path, models_config(), prices_config())

    config = load_providers_config(models_path, prices_path)

    assert config is not None
