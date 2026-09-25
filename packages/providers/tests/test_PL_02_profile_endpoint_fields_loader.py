"""PL-02 / security review fix (P0-05, ticket item 4): `contracts/
providers.schema.json` `$defs.profile` (1.1.0, ADR-0002) allows `base_url`/
`api_key_env` only when `provider == "openai_compat"` (an `if`/`else`). The
generated pydantic `ProvidersProfile` does not enforce a JSON Schema
`if`/`else` -- the same gap ticket P0-04 handled for the prices `if`/`then`
(`test_PL_06_prices_and_credits.py`, `_validate_price_fields_when_set`) --
so a `google` or `fake` profile carrying either field would otherwise load
straight through `tilo_providers.config.load_providers_config` with no
error. Checked by hand at load time, in
`tilo_providers.config._validate_profile_endpoint_fields`.
"""

from __future__ import annotations

import pytest
from conftest import models_config, prices_config, write_providers_config
from tilo_providers.config import ProviderConfigError, load_providers_config


@pytest.mark.parametrize("provider", ["google", "fake"])
@pytest.mark.parametrize(
    ("extra_key", "extra_value"),
    [("base_url", "https://example.com/v1"), ("api_key_env", "SOME_API_KEY")],
)
def test_PL_02_loader_rejects_base_url_or_api_key_env_on_a_non_openai_compat_profile(
    tmp_path, provider, extra_key, extra_value
):
    models = models_config()
    models["profiles"]["large"]["provider"] = provider
    models["profiles"]["large"][extra_key] = extra_value
    models_path, prices_path = write_providers_config(tmp_path, models, prices_config())

    with pytest.raises(ProviderConfigError) as excinfo:
        load_providers_config(models_path, prices_path)

    message = str(excinfo.value)
    assert "large" in message, f"error must name the offending profile, got: {message}"
    assert extra_key in message, f"error must name the rejected field, got: {message}"


def test_PL_02_loader_accepts_base_url_and_api_key_env_on_an_openai_compat_profile(tmp_path, monkeypatch):
    """The positive case: the same fields, on a profile whose provider is
    openai_compat, must load fine -- this check is provider-scoped, not a
    blanket ban."""
    models = models_config()
    models["profiles"]["large"]["provider"] = "openai_compat"
    models["profiles"]["large"]["base_url"] = "https://integrate.api.nvidia.com/v1"
    models["profiles"]["large"]["api_key_env"] = "SOME_API_KEY"
    models_path, prices_path = write_providers_config(tmp_path, models, prices_config())

    config = load_providers_config(models_path, prices_path)

    assert config.profiles["large"].base_url == "https://integrate.api.nvidia.com/v1"
    assert config.profiles["large"].api_key_env == "SOME_API_KEY"
