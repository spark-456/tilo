"""FR-MTR-01 (PRD 14.5, 14.1, 6.4 PL-06): 1 credit = US$0.005 at standard prices,
with a date and source; refuse rather than guess. Treasury tests stay on tests/P8-01 for P8-01b/c."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
import yaml
from _metering_testlib import PRICES_V1, PRICES_V2, REPO_ROOT, write_prices_file
from tilo_metering import MeteringConfig, MeteringConfigError, PriceBook, UnpricedError, Usage


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


def test_FR_MTR_01_newest_unset_version_refuses(tmp_path):
    """Greatest effective_date <= at wins even if unset: refuse, don't fall back to a stale price."""
    v1_path = write_prices_file(tmp_path, "prices_v1.yaml", PRICES_V1)
    v2_path = write_prices_file(tmp_path, "prices_v2.yaml", {**PRICES_V2, "status": "unset", "source": None})
    book = PriceBook.load(v1_path, v2_path)
    with pytest.raises(UnpricedError):
        book.quote("widget", at=_at(2026, 9, 1))


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
    assert credits == pytest.approx(600.0)  # (1e6*1.0 + 1e6*2.0) / 1e6 / 0.005
    assert book.credit_usd == pytest.approx(0.005)


def test_FR_MTR_01_repo_prices_yaml_loads_and_refuses_every_profile():
    """Prices are never invented: config/prices.yaml stays unset, so PriceBook refuses every profile."""
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


_BAD = [{"credit_usd": 0.05}, {"credit_usd": 0}, {"credit_usd": "0.005"}, {"effective_date": None}, {"source": None}]
_NULL_PRICE = {"profiles": {"widget": {"input": None, "output": 2.0}}}


@pytest.mark.parametrize("override", [*_BAD, _NULL_PRICE])
def test_FR_MTR_01_load_rejects_files_the_schema_rejects(tmp_path, override):
    with pytest.raises(MeteringConfigError):
        PriceBook.load(write_prices_file(tmp_path, "bad.yaml", {**PRICES_V1, **override}))


def test_FR_MTR_01_load_rejects_duplicate_effective_dates(tmp_path):
    other = {**PRICES_V2, "effective_date": PRICES_V1["effective_date"]}
    with pytest.raises(MeteringConfigError):
        PriceBook.load(write_prices_file(tmp_path, "a.yaml", PRICES_V1), write_prices_file(tmp_path, "b.yaml", other))


def test_FR_MTR_01_loaded_prices_are_deeply_immutable(tmp_path):
    book = PriceBook.load(write_prices_file(tmp_path, "prices_v1.yaml", PRICES_V1))
    with pytest.raises(TypeError):
        book.versions[0].profiles["widget"] = (0.0, 0.0)  # type: ignore[index]
    assert book.quote("widget", at=_at(2026, 3, 1)).input == pytest.approx(1.0)


def test_FR_MTR_01_usage_rejects_negative_token_counts():
    for tokens_in, tokens_out in ((-1, 0), (0, -1)):
        with pytest.raises(ValueError):
            Usage("widget", tokens_in, tokens_out)


@pytest.mark.parametrize("load", [PriceBook.load, MeteringConfig.load])
def test_FR_MTR_01_loaders_refuse_malformed_yaml(tmp_path, load):
    (bad := tmp_path / "bad.yaml").write_text("a: [\n", encoding="utf-8")
    with pytest.raises(MeteringConfigError):
        load(bad)


@pytest.mark.parametrize("name", ["nope.yaml", "."])
def test_FR_MTR_01_pricebook_refuses_missing_prices_file(tmp_path, name):
    with pytest.raises(MeteringConfigError):
        PriceBook.load(tmp_path / name)
