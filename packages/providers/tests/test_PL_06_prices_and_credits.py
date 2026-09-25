"""PL-06 (PRD 6.4): "Prices come from config/prices.yaml with a date and
source" -- "Ledger reconciliation (section 14) uses the same file." PRD
14.1: 1 credit = US$0.005, so credits = USD / 0.005.

Ticket P0-04 section 3: "if a profile's price status is unset, price()
refuses to meter live calls (raises a clear error) rather than returning
zero. Never invent prices."
"""

from __future__ import annotations

import math

import pytest
from conftest import models_config, prices_config, write_providers_config
from hypothesis import given
from hypothesis import strategies as st
from tilo_providers.config import ProviderConfigError, load_providers_config


def test_PL_06_price_unset_status_refuses_to_meter(tmp_path):
    models_path, prices_path = write_providers_config(tmp_path, models_config(), prices_config(set_=False))
    config = load_providers_config(models_path, prices_path)

    with pytest.raises(ProviderConfigError) as excinfo:
        config.price("large")

    message = str(excinfo.value).lower()
    assert "large" in message, f"PL-06: refusal must name the profile, got: {excinfo.value}"
    assert "unset" in message, f"PL-06: refusal must say prices are unset (not silently zero), got: {excinfo.value}"


def test_PL_06_price_set_status_returns_price_with_effective_date_and_source(tmp_path):
    prices = prices_config(set_=True)
    models_path, prices_path = write_providers_config(tmp_path, models_config(), prices)
    config = load_providers_config(models_path, prices_path)

    quote = config.price("large")

    assert quote.input == pytest.approx(prices["profiles"]["large"]["input"])
    assert quote.output == pytest.approx(prices["profiles"]["large"]["output"])
    assert quote.effective_date == prices["effective_date"], "PL-06: price must carry effective_date"
    assert quote.source == prices["source"], "PL-06: price must carry source"


def test_PL_06_status_set_with_null_price_field_raises_at_load(tmp_path):
    """contracts/providers.schema.json's prices if/then (status "set" implies
    non-null input/output/effective_date/source) is not enforced by the
    generated pydantic model alone -- the loader must check it explicitly
    and raise ProviderConfigError naming the profile, not load a config that
    would later make price() invent a price or crash under `python -O`."""
    prices = prices_config(set_=True)
    prices["profiles"]["large"]["input"] = None
    models_path, prices_path = write_providers_config(tmp_path, models_config(), prices)

    with pytest.raises(ProviderConfigError) as excinfo:
        load_providers_config(models_path, prices_path)

    message = str(excinfo.value).lower()
    assert "large" in message, f"PL-06: refusal must name the profile, got: {excinfo.value}"
    assert "set" in message


def test_PL_06_price_for_unknown_profile_raises(tmp_path):
    prices = prices_config(set_=True)
    models_path, prices_path = write_providers_config(tmp_path, models_config(), prices)
    config = load_providers_config(models_path, prices_path)

    with pytest.raises(ProviderConfigError):
        config.price("ghost-profile")


def test_PL_06_credits_computed_as_usd_over_credit_usd(tmp_path):
    prices = prices_config(set_=True)
    models_path, prices_path = write_providers_config(tmp_path, models_config(), prices)
    config = load_providers_config(models_path, prices_path)

    assert config.credits(1.0) == pytest.approx(1.0 / 0.005)  # PRD 14.1: 1 credit = US$0.005
    assert config.credits(0.005) == pytest.approx(1.0)
    assert config.credits(0.0) == pytest.approx(0.0)


@pytest.fixture(scope="module")
def priced_config(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("pl06_prices")
    prices = prices_config(set_=True)
    models_path, prices_path = write_providers_config(tmp_path, models_config(), prices)
    return load_providers_config(models_path, prices_path), prices["credit_usd"]


@given(usd=st.floats(min_value=0, max_value=1_000_000, allow_nan=False, allow_infinity=False))
def test_PL_06_credits_matches_usd_over_credit_usd_for_any_amount(priced_config, usd):
    """Property test (PRD 14.1 invariant): credits() is exactly usd /
    credit_usd for any non-negative USD amount, not an approximation that
    only happens to hold for the handful of values above."""
    config, credit_usd = priced_config
    assert math.isclose(config.credits(usd), usd / credit_usd, rel_tol=1e-9, abs_tol=1e-12)
