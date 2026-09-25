"""NFR-25 (PRD 17.2 Availability and operations): "Only GA models; denylist
enforced at start-up; fallback profile per role."

Denylist enforcement is PL-07 (test_PL_07_denylisted_models.py). This file
covers the loader's other two start-up checks (ticket P0-04 section 2): "a
role pointing at an unknown profile", "a role with no fallback profile
(NFR-25)" and "a cascade that names an unknown profile" -- plus, separately,
that the real shipped config/models.yaml and config/prices.yaml load without
tripping any of these checks.

Ambiguity resolved (see conftest.BASE_MODELS's comment and the report):
contracts/providers.schema.json's $defs.role has no explicit "single_profile"
flag, so "marked single-profile by the schema" is read as "the role dict's
only key is 'primary'" -- the exact shape config/models.yaml's own
"narrator" role already ships.
"""

from __future__ import annotations

import pytest
from conftest import models_config, prices_config, write_providers_config
from tilo_providers.config import ProviderConfigError, load_providers_config


def test_NFR_25_single_profile_role_without_fallback_is_accepted(tmp_path):
    models = models_config()
    assert set(models["roles"]["narrator"]) == {"primary"}, "fixture must stay single-profile (only 'primary')"
    models_path, prices_path = write_providers_config(tmp_path, models, prices_config())

    config = load_providers_config(models_path, prices_path)

    assert "narrator" in config.roles
    assert config.roles["narrator"].primary == "small"
    assert getattr(config.roles["narrator"], "fallback", None) is None


@pytest.mark.parametrize(
    ("extra_key", "extra_value"),
    [("thinking", "high"), ("max_input_tokens", 1000), ("max_output_tokens", 500)],
)
def test_NFR_25_role_without_fallback_rejected_when_not_single_profile(tmp_path, extra_key, extra_value):
    """A role that configures more than bare 'primary' (thinking level, token
    caps, ...) but still has no fallback is NOT exempt from NFR-25 -- only a
    role shaped exactly like {"primary": ...} and nothing else is."""
    models = models_config()
    models["roles"]["narrator"][extra_key] = extra_value
    models_path, prices_path = write_providers_config(tmp_path, models, prices_config())

    with pytest.raises(ProviderConfigError) as excinfo:
        load_providers_config(models_path, prices_path)

    assert "narrator" in str(excinfo.value), f"NFR-25: error must name the role, got: {excinfo.value}"


@pytest.mark.parametrize(
    ("role", "field"),
    [("director", "primary"), ("director", "fallback"), ("specialist", "cascade")],
    ids=["primary", "fallback", "cascade"],
)
def test_NFR_25_role_referencing_unknown_profile_rejected(tmp_path, role, field):
    models = models_config()
    if field == "cascade":
        models["roles"][role]["cascade"] = ["ghost-profile", "small"]
    else:
        models["roles"][role][field] = "ghost-profile"
    models_path, prices_path = write_providers_config(tmp_path, models, prices_config())

    with pytest.raises(ProviderConfigError) as excinfo:
        load_providers_config(models_path, prices_path)

    message = str(excinfo.value)
    assert "ghost-profile" in message, f"NFR-25: error must name the unknown profile, got: {message!r}"
    assert role in message, f"NFR-25: error must name the offending role, got: {message!r}"


def test_PRD_6_4_shipped_config_loads(repo_root):
    """The real config/models.yaml and config/prices.yaml (ticket P0-02)
    must load through the same loader without tripping PL-07 or NFR-25."""
    config = load_providers_config(repo_root / "config" / "models.yaml", repo_root / "config" / "prices.yaml")

    assert set(config.roles) == {
        "director",
        "lead",
        "specialist",
        "verifier",
        "writer",
        "narrator",
        "autopilot",
    }
    assert config.roles["director"].primary == "flash-38"
    assert config.roles["director"].fallback == "flash-37"
    # narrator ships with no fallback (single-profile: only "primary").
    assert getattr(config.roles["narrator"], "fallback", None) is None
