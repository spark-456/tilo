"""LW-06 (ADR-0029 decision 1, ADR-0027): the PriceBook prices audio input tokens at `audio_input` instead of `input`,
apart from cached tokens, and refuses to price audio on a profile that has no `audio_input` rate (it never prices
audio at the text rate: lite-31's audio rate is double its text rate)."""

from datetime import UTC, datetime

import pytest
from _metering_testlib import REPO_ROOT, write_yaml
from tilo_metering import PriceBook, UnpricedError
from tilo_metering.prices import Usage

_OCT = datetime(2026, 10, 8, 12, tzinfo=UTC)


def _book(tmp_path) -> PriceBook:
    rates = {"input": 1.0, "output": 2.0, "cached_input": 0.1}
    doc = {
        "status": "set",
        "effective_date": "2026-10-01",
        "source": "Fake price sheet for tests.",
        "currency": "USD",
        "credit_usd": 0.005,
        "profiles": {"hears": {**rates, "audio_input": 3.0}, "deaf": rates},
    }
    return PriceBook.load(write_yaml(tmp_path, "prices.yaml", doc))


def test_LW_06_audio_tokens_are_priced_at_audio_input_and_the_rest_at_input(tmp_path):
    book = _book(tmp_path)
    assert book.quote("hears", at=_OCT).audio_input == 3.0 and book.quote("deaf", at=_OCT).audio_input is None
    usage = Usage("hears", tokens_in=1_000_000, tokens_out=500_000, tokens_audio=400_000)
    # (600k * 1.0 + 400k * 3.0 + 500k * 2.0) / 1e6 = 2.8 USD
    assert book.credits(usage, at=_OCT) == pytest.approx(2.8 / 0.005)


def test_LW_06_audio_and_cached_tokens_are_separate_parts_of_the_input(tmp_path):
    book = _book(tmp_path)
    usage = Usage("hears", tokens_in=1_000_000, tokens_out=0, tokens_cached=300_000, tokens_audio=200_000)
    assert book.credits(usage, at=_OCT) == pytest.approx((500_000 * 1.0 + 300_000 * 0.1 + 200_000 * 3.0) / 1e6 / 0.005)
    with pytest.raises(ValueError, match="together"):
        Usage("hears", tokens_in=100, tokens_out=0, tokens_cached=60, tokens_audio=60)
    with pytest.raises(ValueError):
        Usage("hears", tokens_in=100, tokens_out=0, tokens_audio=101)
    with pytest.raises(TypeError):
        Usage("hears", tokens_in=100, tokens_out=0, tokens_audio=1.5)  # type: ignore[arg-type]


def test_LW_06_audio_on_a_profile_with_no_audio_rate_is_refused_not_priced_at_input(tmp_path):
    book = _book(tmp_path)
    with pytest.raises(UnpricedError, match="audio_input"):
        book.credits(Usage("deaf", tokens_in=100, tokens_out=0, tokens_audio=1), at=_OCT)
    assert book.credits(Usage("deaf", tokens_in=100, tokens_out=0), at=_OCT) > 0, "no audio tokens: priced as before"


def test_LW_06_the_shipped_price_sheet_prices_lite_audio_and_flash_has_no_audio_rate():
    book = PriceBook.load(REPO_ROOT / "config" / "prices.yaml")
    assert book.quote("lite-31", at=_OCT).audio_input == 0.55
    assert book.quote("flash-38", at=_OCT).audio_input is None
