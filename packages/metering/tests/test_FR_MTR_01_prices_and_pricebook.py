"""FR-MTR-01 (PRD 14.5, 14.1, 6.4 PL-06): 1 credit = US$0.005 at standard
prices, with a date and source; a price change is a file change, never a
runtime mutation. P8-01a builds only PriceBook/PriceQuote/Usage/UnpricedError;
the Treasury-needing tests stay on tests/P8-01 for P8-01b/c."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
import yaml
from _metering_testlib import PRICES_V1, PRICES_V2, REPO_ROOT, write_prices_file
from tilo_metering import PriceBook, UnpricedError, Usage


def _at(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, 12, 0, tzinfo=UTC)


def test_FR_MTR_01_two_price_versions_priced_by_effective_date(tmp_path):
    """Before the second version's effective_date: old rate. On or after it: new rate."""
    v1_path = write_prices_file(tmp_path, "prices_v1.yaml", PRICES_V1)
    v2_path = write_prices_file(tmp_path, "prices_v2.yaml", PRICES_V2)
    book = PriceBook.load(v1_path, v2_path)

    before = book.quote("widget", at=_at(2026, 3, 1))
    on_boundary = book.quote("widget", at=_at(2026, 6, 1))
    after = book.quote("widget", at=_at(2026, 9, 1))

    assert before.input == pytest.approx(1.0)
    assert before.output == pytest.approx(2.0)
    assert before.effective_date == "2026-01-01"
    assert before.source == PRICES_V1["source"]

    for quote in (on_boundary, after):
        assert quote.input == pytest.approx(3.0)
        assert quote.output == pytest.approx(6.0)
        assert quote.effective_date == "2026-06-01"
        assert quote.source == PRICES_V2["source"]


def test_FR_MTR_01_quote_before_any_version_effective_refuses(tmp_path):
    """Refuse, never guess: no version effective yet."""
    v1_path = write_prices_file(tmp_path, "prices_v1.yaml", PRICES_V1)
    book = PriceBook.load(v1_path)

    with pytest.raises(UnpricedError):
        book.quote("widget", at=_at(2025, 1, 1))


def test_FR_MTR_01_quote_unknown_profile_refuses(tmp_path):
    v1_path = write_prices_file(tmp_path, "prices_v1.yaml", PRICES_V1)
    book = PriceBook.load(v1_path)

    with pytest.raises(UnpricedError):
        book.quote("ghost-profile", at=_at(2026, 3, 1))


def test_FR_MTR_01_credits_uses_versioned_price_and_credit_usd(tmp_path):
    """credits = (tokens_in*input + tokens_out*output) / 1e6 / credit_usd."""
    v1_path = write_prices_file(tmp_path, "prices_v1.yaml", PRICES_V1)
    book = PriceBook.load(v1_path)
    usage = Usage(profile="widget", tokens_in=1_000_000, tokens_out=1_000_000)

    credits = book.credits(usage, at=_at(2026, 3, 1))

    # (1_000_000*1.0 + 1_000_000*2.0) / 1e6 / 0.005 = 3.0 / 0.005 = 600
    assert credits == pytest.approx(600.0)
    assert book.credit_usd == pytest.approx(0.005)


def test_FR_MTR_01_repo_prices_yaml_loads_and_refuses_every_profile():
    """Prices are never invented: config/prices.yaml stays status: unset,
    so PriceBook must refuse to price every profile it lists."""
    prices_path = REPO_ROOT / "config" / "prices.yaml"
    raw = yaml.safe_load(prices_path.read_text(encoding="utf-8"))
    assert raw["status"] == "unset", "config/prices.yaml must stay unset until real prices are pasted in"
    assert raw["credit_usd"] == pytest.approx(0.005)  # PRD 14.1

    book = PriceBook.load(prices_path)
    assert book.credit_usd == pytest.approx(0.005)
    now = datetime.now(tz=UTC)
    for profile in raw["profiles"]:
        with pytest.raises(UnpricedError):
            book.quote(profile, at=now)


def test_FR_MTR_01_pricebook_has_no_mutation_api(tmp_path):
    """Immutable: no setters, no environment overrides, no mutation API."""
    v1_path = write_prices_file(tmp_path, "prices_v1.yaml", PRICES_V1)
    book = PriceBook.load(v1_path)

    for blocked_name in ("set", "set_price", "update", "override", "mutate", "set_env_override", "save"):
        assert not hasattr(book, blocked_name), f"PriceBook must expose no mutation API, found `{blocked_name}`"

    with pytest.raises(AttributeError):
        book.credit_usd = 0.01
