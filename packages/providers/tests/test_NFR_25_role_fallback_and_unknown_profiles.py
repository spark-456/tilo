"""NFR-25 (PRD 17.2 Availability and operations): "Only GA models; denylist
enforced at start-up; fallback profile per role."

Denylist enforcement is PL-07 (test_PL_07_denylisted_models.py). This file
covers the loader's other two start-up checks (ticket P0-04 section 2): "a
role pointing at an unknown profile", "a role with no fallback profile
(NFR-25)" and "a cascade that names an unknown profile" -- plus, separately,
that the real shipped config/models.yaml and config/prices.yaml load without
tripping any of these checks.

NFR-25 has no exemption: every role needs a fallback, whatever else its
mapping sets. contracts/providers.schema.json's $defs.role only requires
"primary", so this is a start-up check, not a schema one. The PRD 6.4
example's fallback-less "narrator" conflicts with NFR-25; logged as BQ-18 in
docs/open-questions.md, and the shipped example gives narrator a fallback.
"""

from __future__ import annotations

import pytest
from conftest import models_config, prices_config, write_providers_config
from tilo_providers.config import ProviderConfigError, load_providers_config


def test_NFR_25_bare_primary_role_without_fallback_is_rejected(tmp_path):
    """A role written as a bare {primary: X} is not exempt from NFR-25."""
    models = models_config()
    models["roles"]["narrator"] = {"primary": "small"}
    models_path, prices_path = write_providers_config(tmp_path, models, prices_config())

    with pytest.raises(ProviderConfigError) as excinfo:
        load_providers_config(models_path, prices_path)

    assert "narrator" in str(excinfo.value), f"NFR-25: error must name the role, got: {excinfo.value}"


@pytest.mark.parametrize(
    ("extra_key", "extra_value"),
    [("thinking", "high"), ("max_input_tokens", 1000), ("max_output_tokens", 500)],
)
def test_NFR_25_role_without_fallback_rejected_whatever_else_it_sets(tmp_path, extra_key, extra_value):
    """A role that configures more than 'primary' (thinking level, token
    caps, ...) but has no fallback is rejected too: the rule does not depend
    on unrelated keys."""
    models = models_config()
    models["roles"]["narrator"] = {"primary": "small", extra_key: extra_value}
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
        "safety",  # CL-INT-1 / issue #103: the dev safety screen
        "generator",  # issue #272 (b), GEN-07: the live scenario generator
        "autorater",  # issue #272 (b), GEN-10: scores the generator's plans
    }
    assert config.roles["director"].primary == "flash-38"
    assert config.roles["director"].fallback == "flash-37"
    # NFR-25: every shipped role has a fallback, narrator included (BQ-18).
    assert all(role.fallback is not None for role in config.roles.values())
