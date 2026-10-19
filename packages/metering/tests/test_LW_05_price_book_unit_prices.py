"""LW-05 (ADR-0029 decisions 1, 2, 4): the PriceBook prices cached input tokens at `cached_input` (else `input`), adds a
fee per 1,000 units (`unit_price`, for example a grounded search query) on top of the token rates, and refuses to
quote a profile after its `valid_until`; it never falls back to an older price."""

from datetime import UTC, datetime

import pytest
from _metering_testlib import REPO_ROOT, write_yaml
from tilo_metering import MeteringConfigError, PriceBook, UnpricedError
from tilo_metering.prices import Usage

_OCT, _2027 = datetime(2026, 10, 8, 12, tzinfo=UTC), datetime(2027, 1, 1, 12, tzinfo=UTC)


def _prices(**profile: object) -> dict:
    rate = {"input": 1.0, "output": 2.0, "cached_input": 0.1, "unit_price": {"unit": "query", "per_1k": 14}}
    return {
        "status": "set",
        "effective_date": "2026-10-01",
        "source": "Fake price sheet for tests.",
        "region": "asia-southeast1",
        "currency": "USD",
        "credit_usd": 0.005,
        "profiles": {"search": {**rate, **profile}},
    }


def _book(tmp_path, doc: dict) -> PriceBook:
    return PriceBook.load(write_yaml(tmp_path, "prices.yaml", doc))


def test_LW_05_cached_tokens_are_priced_at_cached_input_and_the_rest_at_input(tmp_path):
    book = _book(tmp_path, _prices(unit_price=None))
    usage = Usage("search", tokens_in=1_000_000, tokens_out=500_000, tokens_cached=400_000)
    # (600k * 1.0 + 400k * 0.1 + 500k * 2.0) / 1e6 = 1.64 USD
    assert book.credits(usage, at=_OCT) == pytest.approx(1.64 / 0.005)
    no_cached_rate = {k: v for k, v in _prices()["profiles"]["search"].items() if k != "cached_input"}
    plain = _book(tmp_path, {**_prices(), "profiles": {"search": no_cached_rate}})
    assert plain.credits(usage, at=_OCT) == pytest.approx(2.0 / 0.005), "left out, cached tokens cost the input rate"
    assert plain.quote("search", at=_OCT).cached_input is None


def test_LW_05_a_unit_fee_is_charged_on_top_of_the_token_rates(tmp_path):
    book = _book(tmp_path, _prices())
    quote = book.quote("search", at=_OCT)
    assert (quote.unit, quote.per_1k, quote.region) == ("query", 14.0, "asia-southeast1")
    credits = book.credits(Usage("search", tokens_in=1_000_000, tokens_out=0, units=3), at=_OCT)
    assert credits == pytest.approx((1.0 + 3 * 14 / 1000) / 0.005)  # 2.8 credits a query


def test_LW_05_units_for_a_profile_without_a_unit_price_are_refused_not_guessed(tmp_path):
    book = _book(tmp_path, _prices(unit_price=None))
    assert book.credits(Usage("search", 1000, 0), at=_OCT) > 0
    with pytest.raises(UnpricedError):
        book.credits(Usage("search", 1000, 0, units=1), at=_OCT)


def test_LW_05_after_valid_until_the_book_refuses_to_quote_and_a_replay_keeps_its_recorded_date(tmp_path):
    book = _book(tmp_path, _prices(valid_until="2026-12-31"))
    assert book.quote("search", at=datetime(2026, 12, 31, 23, 59, tzinfo=UTC)).input == 1.0, "the last day still holds"
    for at in (_2027, datetime(2028, 6, 1)):
        with pytest.raises(UnpricedError, match="2026-12-31"):
            book.quote("search", at=at)
        with pytest.raises(UnpricedError):
            book.credits(Usage("search", 1, 1), at=at)
    assert book.credits(Usage("search", 1, 1), at=_OCT) > 0  # an event recorded in October is priced in October


def test_LW_05_the_book_never_falls_back_to_an_older_version_after_an_expiry(tmp_path):
    old = {**_prices(), "effective_date": "2026-01-01"}
    new = _prices(valid_until="2026-12-31")
    book = PriceBook.load(write_yaml(tmp_path, "old.yaml", old), write_yaml(tmp_path, "new.yaml", new))
    with pytest.raises(UnpricedError):
        book.quote("search", at=_2027)


@pytest.mark.parametrize(
    "profile",
    [
        {"valid_until": "2026-09-30"},  # before the file's effective_date
        {"valid_until": None},
        {"cached_input": None},  # a set file holds no null
        {"unit_price": {"unit": "query", "per_1k": None}},
        {"unit_price": {"unit": "page", "per_1k": 1}},
        {"cached_input": -1},
    ],
)
def test_LW_05_a_set_file_with_a_bad_new_field_is_refused_at_load(tmp_path, profile):
    with pytest.raises(MeteringConfigError):
        _book(tmp_path, _prices(**profile))


def test_LW_05_an_unset_file_may_hold_nulls_but_quotes_nothing(tmp_path):
    rate = {"input": None, "output": None, "cached_input": None, "unit_price": {"unit": "query", "per_1k": None}}
    doc = {**_prices(), "status": "unset", "effective_date": None, "source": None, "profiles": {"search": rate}}
    book = _book(tmp_path, doc)
    with pytest.raises(UnpricedError):
        book.quote("search", at=_OCT)


@pytest.mark.parametrize("bad", [{"tokens_cached": 2000}, {"tokens_cached": -1}, {"units": -1}, {"units": True}])
def test_LW_05_usage_counts_must_be_whole_and_cached_at_most_input(bad):
    with pytest.raises((TypeError, ValueError)):
        Usage("search", **{"tokens_in": 1000, "tokens_out": 0, **bad})


def test_LW_05_the_repo_price_sheet_quotes_the_search_profile_with_its_fee_until_the_promotion_ends():
    book = PriceBook.load(REPO_ROOT / "config" / "prices.yaml")
    quote = book.quote("search-google", at=_OCT)
    assert (quote.unit, quote.per_1k, quote.cached_input, quote.valid_until) == ("query", 14.0, 0.0825, "2026-12-31")
    one_call = Usage("search-google", tokens_in=1000, tokens_out=500, tokens_cached=200, units=2)
    usd = (800 * 0.825 + 200 * 0.0825 + 500 * 4.125) / 1e6 + 2 * 14 / 1000
    assert book.credits(one_call, at=_OCT) == pytest.approx(usd / 0.005)
    with pytest.raises(UnpricedError):
        book.quote("flash-38", at=_2027)  # the promotional rate has ended: update the file first
    assert book.quote("lite-31", at=_2027).input == 0.275, "lite-31 has no promotion"
