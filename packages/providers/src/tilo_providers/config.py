"""tilo_providers.config — provider-layer config loader (PRD 6.4, 6.6 EFF-03,
17.2 NFR-25, 14.1 Credits). Loads config/models.yaml + config/prices.yaml,
validates each against tilo_contracts (+ the optional expected_output.yaml, PL-03), and fails loudly with
ProviderConfigError: denied model id (PL-07); a role naming an unknown
profile; a role with no fallback profile (NFR-25); a profile with no price entry; a status "set" prices
file with a null price, effective_date or source. price() never invents a
price: an unset status, or any null price field, raises (PL-06)."""

from __future__ import annotations

import fnmatch
import json
import os
import warnings
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError
from tilo_contracts import ProvidersModels, ProvidersPrices, ProvidersProfile, ProvidersRole

from tilo_providers.interfaces import Capability

# packages/providers/src/tilo_providers/config.py -> repo root is 4 parents up
# (same depth as tilo_providers.prompts.DEFAULT_PROMPTS_ROOT).
_REPO_ROOT = Path(__file__).resolve().parents[4]


class ProviderConfigError(Exception):
    """Config failed to parse/validate, or failed a start-up check (PL-06, PL-07, NFR-25)."""


# Dev-only fakes (CL-INT-5): never counted as conforming for a real role (PL-05), never deployed or live (EFF-01).
DEV_DIRECTOR_MODEL = "fake-director"
DEV_ONLY_MODELS = frozenset({DEV_DIRECTOR_MODEL, "fake-search"})  # fake-search: LW-05, config/models.dev.yaml


def refuse_dev_only(profile_id: str, env: Mapping[str, str] | None = None) -> None:
    """Presence, not truthiness: Cloud Run can set a variable to an empty string (the fake safety provider's rule)."""
    env = os.environ if env is None else env
    if "K_SERVICE" in env or "CLOUD_RUN_JOB" in env or env.get("LIVE") == "1":
        raise ProviderConfigError(
            f"EFF-01: refusing dev-only profile {profile_id!r} in live mode or when deployed "
            "(K_SERVICE or CLOUD_RUN_JOB set)"
        )


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
    cached_input: float | None = None  # US$ per 1M cached input tokens; None: priced at `input` (ADR-0029 decision 2)
    unit: str | None = None  # the unit_price unit (query, ...) and its US$ per 1,000, charged on top (decision 1)
    per_1k: float | None = None
    valid_until: str | None = None  # last day (UTC) a promotional rate holds (decision 4)
    audio_input: float | None = None  # US$ per 1M audio input tokens; None: the profile has no audio price (ADR-0027)


# ADR-0029 decision 3: the env variable that sets where each adapter sends, and its default.
_LOCATION_ENV = {
    "google": ("GOOGLE_LOCATION", "global"),
    "model_armor": ("TILO_MODEL_ARMOR_LOCATION", "asia-southeast1"),
}
# LIVE-GLOBAL-1 (14 Oct 2026, user-approved): the adapters whose rates depend on where they send, so the only ones
# the sheet's `region` must match. Model Armor has one price everywhere and is served only regionally, while Gemini
# 3.x is served only on the global endpoint, so one region cannot hold both.
_REGION_PRICED = frozenset({"google"})


@dataclass(frozen=True)
class ProvidersConfig:  # the loaded, validated provider-layer config (PRD 6.4)
    models: ProvidersModels
    prices: ProvidersPrices
    # PL-03 / EFF-03: output tokens a call of a role is reserved for (`config/expected_output.yaml`, checked at load)
    expected_output: Mapping[str, int] = field(default_factory=dict)

    @property
    def roles(self) -> dict[str, ProvidersRole]:
        return self.models.roles

    @property
    def profiles(self) -> dict[str, ProvidersProfile]:
        return self.models.profiles

    def price(self, profile_id: str, *, at: date | None = None) -> ProfilePriceQuote:
        """`at` (a UTC date) enforces `valid_until`: after it the profile is refused (ADR-0029 decision 4). Left None
        (replay, dev, tests) no expiry is checked: a replay uses its recorded dates."""
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
        if at is not None and quote.valid_until is not None and at.isoformat() > quote.valid_until:
            raise ProviderConfigError(
                f"PL-06: profile {profile_id!r} is priced only through valid_until {quote.valid_until}; update "
                "config/prices.yaml before metering live"
            )
        fee = quote.unit_price
        return ProfilePriceQuote(
            quote.input,
            quote.output,
            self.prices.effective_date,
            self.prices.source,
            quote.cached_input,
            fee.unit if fee else None,
            fee.per_1k if fee else None,
            quote.valid_until,
            quote.audio_input,
        )

    def cost_usd(
        self,
        profile_id: str,
        tokens_in: int,
        tokens_out: int,
        *,
        cached: int = 0,
        units: int = 0,
        audio: int = 0,
        at: date | None = None,
    ) -> float:
        """The one cost formula (ADR-0029 decision 1): tokens at their rates, cached ones at `cached_input` (else
        `input`), audio ones at `audio_input` (LW-06; refused if the profile has none, never priced at `input`),
        plus units * per_1k / 1,000. Cached and audio tokens are parts of `tokens_in` and do not overlap."""
        quote = self.price(profile_id, at=at)
        cached_rate = quote.input if quote.cached_input is None else quote.cached_input
        if audio and quote.audio_input is None:
            raise ProviderConfigError(f"PL-06: profile {profile_id!r} has no audio_input price: {audio} audio tokens")
        if cached + audio > tokens_in:
            raise ValueError("cached and audio tokens are parts of the input tokens: together at most tokens_in")
        tokens = (tokens_in - cached - audio) * quote.input + cached * cached_rate + tokens_out * quote.output
        tokens += audio * (quote.audio_input or 0.0)
        usd = tokens / 1e6
        if units:
            if quote.per_1k is None:
                raise ProviderConfigError(
                    f"PL-06: profile {profile_id!r} has no unit_price: {units} units cannot be priced"
                )
            usd += units * quote.per_1k / 1000
        return usd

    def check_live(self, env: Mapping[str, str] | None = None) -> None:
        """Refuses live metering that would use the wrong rates (ADR-0029 decisions 3 and 4): a profile whose adapter
        sends to a location other than the sheet's `region` (`google` reads GOOGLE_LOCATION; only adapters whose rates
        depend on the location are checked, `_REGION_PRICED`), or whose promotion has ended. An unset
        sheet is left alone: it already refuses every live price (`price`), and has no region or date to check."""
        if self.prices.status != "set":
            return
        env = os.environ if env is None else env
        region, today = self.prices.region, datetime.now(UTC).date()
        for profile_id, profile in self.profiles.items():
            where = _LOCATION_ENV.get(profile.provider) if profile.provider in _REGION_PRICED else None
            if region is not None and where is not None and env.get(where[0], where[1]) != region:
                raise ProviderConfigError(
                    f"PL-06: refusing live metering: profile {profile_id!r} sends to {env.get(where[0], where[1])!r} "
                    f"({where[0]}) but config/prices.yaml quotes {region!r}; set {where[0]}={region}"
                )
            if profile_id in self.prices.profiles:
                self.price(profile_id, at=today)

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
    would only be caught here, at load time.

    1.4.0 (ADR-0041 BK-12) adds `credential: org`, the one marker of an org-only profile: openai_compat only (the
    else branch), never with `api_key_env` (the then branch) and always with `base_url` (`dependentRequired`)."""
    for profile_id, profile in models.profiles.items():
        if profile.provider != "openai_compat" and (profile.base_url is not None or profile.api_key_env is not None):
            raise ProviderConfigError(
                f"PL-02: profile {profile_id!r} has provider {profile.provider!r} but declares "
                "base_url/api_key_env -- only an openai_compat profile may (contracts/providers.schema.json "
                "$defs.profile)"
            )
        if profile.credential is None and "credential" not in profile.model_fields_set:
            continue  # a Tilo profile; an explicit `credential: null` is not (the schema's const is "org", never null)
        if (
            profile.credential != "org"
            or profile.provider != "openai_compat"
            or profile.api_key_env is not None
            or profile.base_url is None
        ):
            raise ProviderConfigError(
                f"BK-12: profile {profile_id!r} has credential 'org', which needs provider openai_compat, a fixed "
                "base_url and no api_key_env (contracts/providers.schema.json $defs.profile)"
            )


def _validate_startup_rules(models: ProvidersModels, prices: ProvidersPrices) -> None:
    for profile_id, profile in models.profiles.items():
        if profile.model in DEV_ONLY_MODELS:
            refuse_dev_only(profile_id)
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
        for profile_id in sorted(profiles_used_by(role)):
            if models.profiles[profile_id].credential is not None:  # ADR-0041 BK-12: an org profile is org-only
                raise ProviderConfigError(f"BK-12: role {role_id!r} names profile {profile_id!r}, which is org-only")
        _validate_unit_price_rules(role_id, role, models, prices)


def _validate_unit_price_rules(
    role_id: str, role: ProvidersRole, models: ProvidersModels, prices: ProvidersPrices
) -> None:
    """ADR-0029 decisions 1 and 7 (the `roles` description in the schema): a role whose profiles carry a unit_price
    states reserve_units; the `search` role states it, runs only grounded profiles and, while prices are set, only
    profiles with a `query` unit_price."""
    used = sorted(profiles_used_by(role))
    fees = {p: prices.profiles[p].unit_price for p in used if p in prices.profiles}
    if role.reserve_units is None and any(fee is not None for fee in fees.values()):
        raise ProviderConfigError(
            f"ADR-0029: role {role_id!r} runs profiles with a unit_price but states no reserve_units"
        )
    if role_id != "search":
        return
    if role.reserve_units is None:
        raise ProviderConfigError("LW-05: the search role must state reserve_units (queries reserved before a call)")
    for profile_id in used:
        if Capability.GROUNDING.value not in models.profiles[profile_id].caps:
            raise ProviderConfigError(f"LW-05: search profile {profile_id!r} does not declare the grounding capability")
        fee = fees.get(profile_id)
        if prices.status == "set" and (fee is None or fee.unit != "query"):
            raise ProviderConfigError(f"LW-05: search profile {profile_id!r} needs a unit_price with unit 'query'")


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
    for profile_id, quote in prices.profiles.items():  # a date or absent, in an unset file too (ADR-0029 decision 4)
        if "valid_until" in quote.model_fields_set and quote.valid_until is None:
            raise ProviderConfigError(f"ADR-0029: {prices_path} profile {profile_id!r} has a null valid_until")
    if prices.status != "set":
        return
    if prices.effective_date is None:
        raise ProviderConfigError(f"PL-06: {prices_path} has status 'set' but effective_date is null")
    if prices.source is None:
        raise ProviderConfigError(f"PL-06: {prices_path} has status 'set' but source is null")
    for profile_id, quote in prices.profiles.items():
        fields = quote.model_fields_set
        if quote.valid_until is not None and quote.valid_until < prices.effective_date:
            raise ProviderConfigError(
                f"ADR-0029: {prices_path} profile {profile_id!r} valid_until {quote.valid_until} is before "
                f"effective_date {prices.effective_date}"
            )
        if "cached_input" in fields and quote.cached_input is None:
            raise ProviderConfigError(
                f"PL-06: {prices_path} has status 'set' but profile {profile_id!r} has a null cached_input"
            )
        if quote.unit_price is not None and quote.unit_price.per_1k is None:
            raise ProviderConfigError(
                f"PL-06: {prices_path} has status 'set' but profile {profile_id!r} has a null per_1k"
            )
        if quote.input is None:
            raise ProviderConfigError(
                f"PL-06: {prices_path} has status 'set' but profile {profile_id!r} has a null input price"
            )
        if quote.output is None:
            raise ProviderConfigError(
                f"PL-06: {prices_path} has status 'set' but profile {profile_id!r} has a null output price"
            )


def _load_expected_output(path: Path, models: ProvidersModels) -> dict[str, int]:
    """PL-03 / EFF-03: `config/expected_output.yaml` (`roles: {role: tokens}`), next to the models file, is the size a
    call is reserved for before it is made (the full `max_output_tokens` stays the hard cap). It is not a field of the
    role because contracts/providers.schema.json closes the role object. Optional; one file serves every models file,
    so a role the loaded models file lacks is ignored. Each size is an integer from 1 up to the role's own cap."""
    if not path.is_file():
        return {}
    roles = _load_yaml_mapping(path).get("roles")
    if not isinstance(roles, dict):
        raise ProviderConfigError(f"expected_output: {path} must have a `roles` mapping of role id to tokens")
    for role_id, tokens in roles.items():
        cap = models.roles[role_id].max_output_tokens if role_id in models.roles else None
        if isinstance(tokens, bool) or not isinstance(tokens, int) or tokens < 1 or (cap is not None and tokens > cap):
            raise ProviderConfigError(
                f"expected_output: {path} role {role_id!r} must be an integer from 1 up to its max_output_tokens "
                f"({cap}), got {tokens!r}"
            )
    return {role_id: tokens for role_id, tokens in roles.items() if role_id in models.roles}


def profiles_used_by(role: ProvidersRole) -> set[str]:
    return {role.primary, *([role.fallback] if role.fallback else []), *(role.cascade or ())}


def _validate_conformance(models: ProvidersModels, conformance_dir: Path) -> None:
    """PL-05: a failing profile cannot serve a role; a missing result warns (refused if required)."""
    for role_id, role in models.roles.items():
        for profile_id in sorted(profiles_used_by(role)):
            path = conformance_dir / f"{profile_id}.json"
            where = f"PL-05: role {role_id!r} profile {profile_id!r} conformance result {path}"
            if models.profiles[profile_id].model in DEV_ONLY_MODELS:  # a result file for a dev fake never counts
                if os.environ.get("TILO_REQUIRE_CONFORMANCE") == "1":
                    raise ProviderConfigError(f"{where}: a dev-only fake never conforms")
                warnings.warn(f"{where} is a dev-only fake -- allowed in dev", stacklevel=2)
                continue
            if not path.is_file() and os.environ.get("TILO_REQUIRE_CONFORMANCE") != "1":
                warnings.warn(f"{where} is missing -- allowed in dev", stacklevel=2)
                continue
            try:  # a missing file here means TILO_REQUIRE_CONFORMANCE=1
                passed = json.loads(path.read_text(encoding="utf-8")).get("result") == "pass"
            except (OSError, ValueError, AttributeError) as error:
                raise ProviderConfigError(f"{where} is missing or unreadable: {error}") from error
            if not passed:
                raise ProviderConfigError(f"{where} is failing")


def load_providers_config(
    models_path: Path | str,
    prices_path: Path | str,
    conformance_dir: Path | str | None = None,
    expected_output_path: Path | str | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> ProvidersConfig:
    """Loads, validates and start-up-checks the two config files; raises
    ProviderConfigError loudly rather than starting on a bad config. With `LIVE=1` in `env` (default: the process
    environment) it also refuses live metering at the wrong region or past a promotion (`check_live`)."""
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

    expected = _load_expected_output(
        Path(expected_output_path) if expected_output_path else models_path.parent / "expected_output.yaml", models
    )
    config = ProvidersConfig(models=models, prices=prices, expected_output=expected)
    if (os.environ if env is None else env).get("LIVE") == "1":
        config.check_live(env)
    return config
