"""tilo_providers.config — provider-layer config loader (PRD 6.4, 6.6 EFF-03,
17.2 NFR-25, 14.1 Credits). Loads config/models.yaml + config/prices.yaml,
validates each against tilo_contracts, and fails loudly with
ProviderConfigError: denied model id (PL-07); a role naming an unknown
profile; a role with no fallback unless its raw mapping has no key besides
"primary" (NFR-25); a profile with no price entry. price() never invents a
price: an unset status raises (PL-06)."""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError
from tilo_contracts import ProvidersModels, ProvidersPrices, ProvidersProfile, ProvidersRole

# A role mapping whose only key is "primary" is exempt from NFR-25's fallback rule.
_SINGLE_PROFILE_ROLE_KEYS = frozenset({"primary"})


class ProviderConfigError(Exception):
    """Config failed to parse/validate, or failed a start-up check (PL-06, PL-07, NFR-25)."""


@dataclass(frozen=True)
class ProfilePriceQuote:  # one profile's price plus the file's date and source (PL-06)
    input: float
    output: float
    effective_date: str
    source: str


@dataclass(frozen=True)
class ProvidersConfig:  # the loaded, validated provider-layer config (PRD 6.4)
    models: ProvidersModels
    prices: ProvidersPrices

    @property
    def roles(self) -> dict[str, ProvidersRole]:
        return self.models.roles

    @property
    def profiles(self) -> dict[str, ProvidersProfile]:
        return self.models.profiles

    def price(self, profile_id: str) -> ProfilePriceQuote:
        if profile_id not in self.prices.profiles:
            raise ProviderConfigError(f"PL-06: no price entry for profile {profile_id!r} in config/prices.yaml")
        if self.prices.status != "set":
            raise ProviderConfigError(
                f"PL-06: cannot price profile {profile_id!r}: status is 'unset' — prices are never invented"
            )
        quote = self.prices.profiles[profile_id]
        assert quote.input is not None and quote.output is not None
        assert self.prices.effective_date is not None and self.prices.source is not None
        return ProfilePriceQuote(quote.input, quote.output, self.prices.effective_date, self.prices.source)

    def credits(self, usd: float) -> float:  # PRD 14.1: 1 credit = US$0.005
        return usd / self.prices.credit_usd


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ProviderConfigError(f"could not read {path}: {error}") from error
    except yaml.YAMLError as error:
        raise ProviderConfigError(f"{path} is not valid YAML: {error}") from error
    if not isinstance(raw, dict):
        raise ProviderConfigError(f"{path} must contain a YAML mapping at the top level")
    return raw


def _validate_startup_rules(models: ProvidersModels, prices: ProvidersPrices, raw_roles: dict[str, Any]) -> None:
    for profile_id, profile in models.profiles.items():
        for deny_glob in models.rules.deny:
            if fnmatch.fnmatchcase(profile.model, deny_glob):
                raise ProviderConfigError(
                    f"PL-07: profile {profile_id!r} names denied model id {profile.model!r} "
                    f"(matches deny rule {deny_glob!r})"
                )
        if profile_id not in prices.profiles:
            raise ProviderConfigError(f"PL-06: profile {profile_id!r} has no price entry in config/prices.yaml")

    for role_id, role in models.roles.items():
        if role.primary not in models.profiles:
            raise ProviderConfigError(f"NFR-25: role {role_id!r} 'primary' names unknown profile {role.primary!r}")
        if role.fallback is not None and role.fallback not in models.profiles:
            raise ProviderConfigError(f"NFR-25: role {role_id!r} 'fallback' names unknown profile {role.fallback!r}")
        for cascade_id in role.cascade or ():
            if cascade_id not in models.profiles:
                raise ProviderConfigError(f"NFR-25: role {role_id!r} 'cascade' names unknown profile {cascade_id!r}")
        raw_role = raw_roles.get(role_id)
        is_single_profile = isinstance(raw_role, dict) and set(raw_role) == _SINGLE_PROFILE_ROLE_KEYS
        if role.fallback is None and not is_single_profile:
            raise ProviderConfigError(
                f"NFR-25: role {role_id!r} has no fallback profile (only a single-profile role — "
                "whose mapping has no key besides 'primary' — may skip one)"
            )


def load_providers_config(models_path: Path | str, prices_path: Path | str) -> ProvidersConfig:
    """Loads, validates and start-up-checks the two config files; raises
    ProviderConfigError loudly rather than starting on a bad config."""
    models_path, prices_path = Path(models_path), Path(prices_path)
    raw_models = _load_yaml_mapping(models_path)
    raw_prices = _load_yaml_mapping(prices_path)

    try:
        models = ProvidersModels.model_validate(raw_models)
    except ValidationError as error:
        raise ProviderConfigError(f"{models_path} failed schema validation: {error}") from error
    try:
        prices = ProvidersPrices.model_validate(raw_prices)
    except ValidationError as error:
        raise ProviderConfigError(f"{prices_path} failed schema validation: {error}") from error

    raw_roles = raw_models.get("roles")
    _validate_startup_rules(models, prices, raw_roles if isinstance(raw_roles, dict) else {})

    return ProvidersConfig(models=models, prices=prices)
