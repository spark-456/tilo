"""tilo_providers.config — provider-layer config loader (PRD 6.4, 6.6 EFF-03,
17.2 NFR-25, 14.1 Credits, PL-05 conformance). Loads config/models.yaml +
config/prices.yaml, validates each against tilo_contracts, and fails loudly
with ProviderConfigError: denied model id (PL-07); a role naming an unknown
profile; a role with no fallback profile (NFR-25); a profile with no price entry; a status "set" prices
file with a null price, effective_date or source. price() never invents a
price: an unset status, or any null price field, raises (PL-06). An optional
`conformance_dir` (PL-05, ticket P0-06) refuses a role whose primary,
fallback or cascade profile has a *failing* conformance result; a *missing*
result only warns unless `TILO_REQUIRE_CONFORMANCE=1` (docs/open-questions.md
BQ-55)."""

from __future__ import annotations

import fnmatch
import json
import os
import warnings
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError
from tilo_contracts import ProvidersModels, ProvidersPrices, ProvidersProfile, ProvidersRole

# packages/providers/src/tilo_providers/config.py -> repo root is 4 parents up
# (same depth as tilo_providers.prompts.DEFAULT_PROMPTS_ROOT).
_REPO_ROOT = Path(__file__).resolve().parents[4]


class ProviderConfigError(Exception):
    """Config failed to parse/validate, or failed a start-up check (PL-06, PL-07, NFR-25)."""


def resolve_models_path(repo_root: Path | str | None = None, *, env: Mapping[str, str] | None = None) -> Path:
    """PL-02 / ADR-0003: picks `config/models.yaml` unless `TILO_MODELS_FILE`
    names another file (e.g. `config/models.nim.yaml`, to route roles to
    NVIDIA NIM for live tests) — no code edit needed to switch."""
    root = Path(repo_root) if repo_root is not None else _REPO_ROOT
    override = (env if env is not None else os.environ).get("TILO_MODELS_FILE")
    return Path(override) if override else root / "config" / "models.yaml"


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
        if (
            quote.input is None
            or quote.output is None
            or self.prices.effective_date is None
            or self.prices.source is None
        ):
            # load_providers_config's _validate_price_fields_when_set already
            # rejects this shape at start-up; this only guards a
            # ProvidersConfig assembled without going through that loader.
            raise ProviderConfigError(
                f"PL-06: profile {profile_id!r} has status 'set' but a null price field -- prices are never invented"
            )
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


def _validate_profile_endpoint_fields(models: ProvidersModels) -> None:
    """contracts/providers.schema.json's profile if/else (`$defs.profile`,
    1.1.0) forbids `base_url`/`api_key_env` on any profile whose `provider`
    is not `openai_compat`. The generated pydantic `ProvidersProfile` does
    not enforce a JSON Schema if/else (same gap P0-04 handled for prices'
    if/then in `_validate_price_fields_when_set`) — a `google` or `fake`
    profile carrying either field validates against the model fine and
    would only be caught here, at load time."""
    for profile_id, profile in models.profiles.items():
        if profile.provider != "openai_compat" and (profile.base_url is not None or profile.api_key_env is not None):
            raise ProviderConfigError(
                f"PL-02: profile {profile_id!r} has provider {profile.provider!r} but declares "
                "base_url/api_key_env -- only an openai_compat profile may (contracts/providers.schema.json "
                "$defs.profile)"
            )


def _validate_startup_rules(models: ProvidersModels, prices: ProvidersPrices) -> None:
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
        if role.fallback is None:
            raise ProviderConfigError(f"NFR-25: role {role_id!r} has no fallback profile")


def _validate_price_fields_when_set(prices: ProvidersPrices, prices_path: Path) -> None:
    """contracts/providers.schema.json's prices if/then (line ~125) requires
    that once status is "set", every profile's input/output plus the file's
    effective_date/source are non-null. The generated ProvidersPrices
    pydantic model does not enforce a JSON Schema if/then, so a status:
    "set" file with null prices validates fine and would otherwise only be
    caught by an assert inside price() -- which a bare `assert` skips
    entirely under `python -O`, silently returning None fields (PL-06 is
    "price() refuses to meter rather than returning nothing"). Checked here,
    at load time, instead."""
    if prices.status != "set":
        return
    if prices.effective_date is None:
        raise ProviderConfigError(f"PL-06: {prices_path} has status 'set' but effective_date is null")
    if prices.source is None:
        raise ProviderConfigError(f"PL-06: {prices_path} has status 'set' but source is null")
    for profile_id, quote in prices.profiles.items():
        if quote.input is None:
            raise ProviderConfigError(
                f"PL-06: {prices_path} has status 'set' but profile {profile_id!r} has a null input price"
            )
        if quote.output is None:
            raise ProviderConfigError(
                f"PL-06: {prices_path} has status 'set' but profile {profile_id!r} has a null output price"
            )


def _profiles_used_by(role: ProvidersRole) -> set[str]:
    profile_ids = {role.primary}
    if role.fallback:
        profile_ids.add(role.fallback)
    profile_ids.update(role.cascade or ())
    return profile_ids


def _validate_conformance(models: ProvidersModels, conformance_dir: Path) -> None:
    """PL-05: "a failing profile cannot be assigned to a role". A missing
    result file is a warning in dev (nothing has run the suite yet) and a
    hard refusal only when `TILO_REQUIRE_CONFORMANCE=1` (a deploy gate)."""
    require_conformance = os.environ.get("TILO_REQUIRE_CONFORMANCE") == "1"
    for role_id, role in models.roles.items():
        for profile_id in sorted(_profiles_used_by(role)):
            result_path = conformance_dir / f"{profile_id}.json"
            if not result_path.is_file():
                message = (
                    f"PL-05: role {role_id!r} profile {profile_id!r} has no conformance result at "
                    f"{result_path} -- allowed in dev, refused when TILO_REQUIRE_CONFORMANCE=1"
                )
                if require_conformance:
                    raise ProviderConfigError(message)
                warnings.warn(message, stacklevel=2)
                continue
            try:
                payload = json.loads(result_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise ProviderConfigError(f"PL-05: {result_path} is not valid JSON: {error}") from error
            if payload.get("result") != "pass":
                raise ProviderConfigError(
                    f"PL-05: role {role_id!r} profile {profile_id!r} has a failing conformance result at {result_path}"
                )


def load_providers_config(
    models_path: Path | str, prices_path: Path | str, conformance_dir: Path | str | None = None
) -> ProvidersConfig:
    """Loads, validates and start-up-checks the two config files; raises
    ProviderConfigError loudly rather than starting on a bad config.
    `conformance_dir` (PL-05) is optional and defaults to skipping that
    gate, so every P0-04 call site predating this ticket is unaffected."""
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

    _validate_price_fields_when_set(prices, prices_path)
    _validate_profile_endpoint_fields(models)

    _validate_startup_rules(models, prices)
    if conformance_dir is not None:
        _validate_conformance(models, Path(conformance_dir))

    return ProvidersConfig(models=models, prices=prices)
