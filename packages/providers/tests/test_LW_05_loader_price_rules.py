"""LW-05 (ADR-0029 decisions 1 to 4, 7): the loader enforces what the JSON Schema cannot.
A set prices file holds no null `cached_input`, `per_1k` or `valid_until`, and no `valid_until` before its
`effective_date`. The `search` role states `reserve_units` and runs only grounded profiles with a `query` unit price;
any role whose profiles carry a unit price states `reserve_units`. Live metering is refused when the adapter's
location is not the sheet's `region`, or a promotion has ended. `price()` carries `cached_input` and the unit fee,
and `cost_usd` is the one cost formula."""

from __future__ import annotations

import copy
import pathlib
from datetime import date
from typing import Any

import pytest
import yaml
from tilo_providers.config import ProviderConfigError, load_providers_config

REPO = pathlib.Path(__file__).resolve().parents[3]
LIVE_ENV = {"LIVE": "1"}

MODELS: dict[str, Any] = {
    "example": True,
    "profiles": {
        "srch": {"provider": "google", "model": "example-search", "context": 1000, "caps": ["json", "grounding"]},
        "plain": {"provider": "google", "model": "example-plain", "context": 1000, "caps": ["json"]},
        "armor": {"provider": "model_armor", "model": "tilo-default", "context": 1000, "caps": []},
        "local": {"provider": "fake", "model": "example-fake", "context": 1000, "caps": ["grounding"]},
    },
    "roles": {
        "search": {"primary": "srch", "fallback": "srch", "reserve_units": 5, "max_output_tokens": 4096},
        "writer": {"primary": "plain", "fallback": "plain"},
        "safety": {"primary": "armor", "fallback": "armor"},
    },
    "rules": {"deny": []},
}
PRICES: dict[str, Any] = {
    "status": "set",
    "effective_date": "2026-10-01",
    "source": "Fake price sheet for tests.",
    "region": "asia-southeast1",
    "currency": "USD",
    "credit_usd": 0.005,
    "profiles": {
        "srch": {
            "input": 1.0,
            "output": 2.0,
            "cached_input": 0.1,
            "unit_price": {"unit": "query", "per_1k": 14},
            "valid_until": "2099-12-31",
        },
        "plain": {"input": 0.5, "output": 1.0},
        "armor": {"input": 0.1, "output": 0},
        "local": {"input": 0, "output": 0},
    },
}


def load(tmp_path: pathlib.Path, models: dict | None = None, prices: dict | None = None, env: dict | None = None):
    models_path, prices_path = tmp_path / "models.yaml", tmp_path / "prices.yaml"
    models_path.write_text(yaml.safe_dump(models or MODELS), encoding="utf-8")
    prices_path.write_text(yaml.safe_dump(prices or PRICES), encoding="utf-8")
    return load_providers_config(models_path, prices_path, env={} if env is None else env)


def edit(base: dict, *path: str, value: Any) -> dict:
    doc = copy.deepcopy(base)
    node = doc
    for key in path[:-1]:
        node = node[key]
    if value is ...:
        del node[path[-1]]
    else:
        node[path[-1]] = value
    return doc


def test_LW_05_the_repo_config_loads_and_its_search_role_reserves_queries():
    config = load_providers_config(REPO / "config" / "models.yaml", REPO / "config" / "prices.yaml", env={})
    assert config.roles["search"].reserve_units == 5
    quote = config.price("search-google")
    assert (quote.cached_input, quote.unit, quote.per_1k, quote.valid_until) == (0.0825, "query", 14.0, "2026-12-31")
    dev = load_providers_config(REPO / "config" / "models.dev.yaml", REPO / "config" / "prices.yaml", env={})
    assert dev.roles["search"].reserve_units and dev.price("search-fake").per_1k == 0


def test_LW_05_the_fixture_shaped_config_loads(tmp_path):
    assert load(tmp_path).roles["search"].reserve_units == 5


@pytest.mark.parametrize(
    "models",
    [
        edit(MODELS, "roles", "search", "reserve_units", value=...),
        edit(MODELS, "roles", "search", "primary", value="plain"),
        edit(MODELS, "roles", "search", "fallback", value="plain"),
        edit(MODELS, "roles", "search", "cascade", value=["plain", "srch"]),
        edit(MODELS, "roles", "writer", "primary", value="srch"),  # a unit fee needs a reservation, in every role
    ],
)
def test_LW_05_the_search_role_and_unit_fee_roles_need_reserve_units_grounding_and_a_query_price(tmp_path, models):
    with pytest.raises(ProviderConfigError, match="LW-05|ADR-0029"):
        load(tmp_path, models=models)


def test_LW_05_a_search_profile_needs_a_query_unit_price_while_prices_are_set_but_not_while_unset(tmp_path):
    no_fee = edit(PRICES, "profiles", "srch", "unit_price", value=...)
    with pytest.raises(ProviderConfigError, match="unit_price"):
        load(tmp_path, prices=no_fee)
    wrong_unit = edit(PRICES, "profiles", "srch", "unit_price", value={"unit": "image", "per_1k": 1})
    with pytest.raises(ProviderConfigError, match="query"):
        load(tmp_path, prices=wrong_unit)
    unset = {**no_fee, "status": "unset", "effective_date": None, "source": None}
    unset["profiles"] = {name: {"input": None, "output": None} for name in PRICES["profiles"]}
    assert load(tmp_path, prices=unset).prices.status == "unset"
    assert load(tmp_path, prices=unset, env={**LIVE_ENV}), "an unset sheet has no region to check; price() refuses it"


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("profiles", "srch", "cached_input"), None),
        (("profiles", "srch", "unit_price", "per_1k"), None),
        (("profiles", "srch", "valid_until"), None),
        (("profiles", "srch", "valid_until"), "2026-09-30"),  # before the file's effective_date
    ],
)
def test_LW_05_a_set_file_holds_no_null_cached_input_per_1k_or_valid_until_and_no_backdated_promotion(
    tmp_path, path, value
):
    with pytest.raises(ProviderConfigError, match="PL-06|ADR-0029"):
        load(tmp_path, prices=edit(PRICES, *path, value=value))


def test_LW_05_live_metering_is_refused_when_the_adapter_location_is_not_the_price_region(tmp_path):
    with pytest.raises(ProviderConfigError, match="asia-southeast1") as refused:
        load(tmp_path, env={**LIVE_ENV})  # GOOGLE_LOCATION unset: global (PRD 6.5)
    assert "GOOGLE_LOCATION=asia-southeast1" in str(refused.value) and "'global'" in str(refused.value)
    with pytest.raises(ProviderConfigError, match="GOOGLE_LOCATION"):
        load(tmp_path, env={**LIVE_ENV, "GOOGLE_LOCATION": "europe-west4"})
    ok = {**LIVE_ENV, "GOOGLE_LOCATION": "asia-southeast1"}
    assert load(tmp_path, env=ok)  # model_armor defaults to asia-southeast1 too
    with pytest.raises(ProviderConfigError, match="TILO_MODEL_ARMOR_LOCATION"):
        load(tmp_path, env={**ok, "TILO_MODEL_ARMOR_LOCATION": "us"})


def test_LW_05_the_region_is_not_checked_off_live_without_a_region_or_for_adapters_with_no_location(tmp_path):
    assert load(tmp_path, env={"GOOGLE_LOCATION": "global"})  # replay and dev never meter live
    assert load(tmp_path, prices=edit(PRICES, "region", value=...), env={**LIVE_ENV})
    compat = {
        "provider": "openai_compat",
        "model": "example-compat",
        "context": 1000,
        "caps": ["json", "grounding"],
        "base_url": "https://example.test/v1",
        "api_key_env": "EXAMPLE_API_KEY",
    }
    models = edit(MODELS, "profiles", "srch", value=compat)
    models["profiles"]["plain"] = {"provider": "fake", "model": "example-fake", "context": 1000, "caps": ["json"]}
    assert load(tmp_path, models=models, env={**LIVE_ENV, "GOOGLE_LOCATION": "global"})


def test_LW_05_live_metering_is_refused_after_a_promotion_ends_but_replay_is_not(tmp_path):
    expired = edit(PRICES, "profiles", "srch", "valid_until", value="2026-10-02")
    live = {**LIVE_ENV, "GOOGLE_LOCATION": "asia-southeast1"}
    with pytest.raises(ProviderConfigError, match="valid_until"):
        load(tmp_path, prices=expired, env=live)
    assert load(tmp_path, prices=expired, env={})  # a replay uses its recorded dates


def test_LW_05_price_carries_cached_input_and_unit_fee_and_refuses_an_ended_promotion(tmp_path):
    config = load(tmp_path)
    quote = config.price("srch")
    assert (quote.input, quote.cached_input, quote.unit, quote.per_1k) == (1.0, 0.1, "query", 14.0)
    assert config.price("plain").cached_input is None and config.price("plain").per_1k is None
    config.price("srch", at=date(2099, 12, 31))
    with pytest.raises(ProviderConfigError, match="valid_until|2099-12-31"):
        config.price("srch", at=date(2100, 1, 1))


def test_LW_05_cost_usd_is_the_one_formula_for_tokens_cached_tokens_and_units(tmp_path):
    config = load(tmp_path)
    usd = config.cost_usd("srch", 1_000_000, 500_000, cached=400_000, units=3)
    assert usd == pytest.approx((600_000 * 1.0 + 400_000 * 0.1 + 500_000 * 2.0) / 1e6 + 3 * 14 / 1000)
    assert config.cost_usd("plain", 1_000_000, 0, cached=1_000_000) == pytest.approx(0.5), "no cached rate: input"
    with pytest.raises(ProviderConfigError, match="unit"):
        config.cost_usd("plain", 1, 1, units=1)
