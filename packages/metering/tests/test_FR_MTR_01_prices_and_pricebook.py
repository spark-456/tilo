"""FR-MTR-01 (PRD 14.5, 14.1, 6.4 PL-06): 1 credit = US$0.005 with a price date and source; refuse, never guess."""

from datetime import UTC, datetime

import pytest
import yaml
from _metering_testlib import PRICES_V1, PRICES_V2, REPO_ROOT, metering_config, write_yaml
from tilo_metering import InMemoryFlagStore, MeteringConfig, MeteringConfigError, PriceBook, UnpricedError
from tilo_metering.prices import PriceQuote, Usage

_MAR, _JUN, _SEP = (datetime(2026, month, 1, 12, tzinfo=UTC) for month in (3, 6, 9))


def _book(tmp_path, *docs: dict) -> PriceBook:
    return PriceBook.load(*(write_yaml(tmp_path, f"prices_{i}.yaml", doc) for i, doc in enumerate(docs)))


def test_FR_MTR_01_two_price_versions_priced_by_effective_date(tmp_path):
    """Before the second version's effective_date: old rate. On or after it: new rate."""
    book = _book(tmp_path, PRICES_V1, PRICES_V2)
    assert book.quote("widget", at=_MAR) == PriceQuote("widget", 1.0, 2.0, "2026-01-01", PRICES_V1["source"])
    for at in (_JUN, _SEP):
        assert book.quote("widget", at=at) == PriceQuote("widget", 3.0, 6.0, "2026-06-01", PRICES_V2["source"])


def test_FR_MTR_01_refuses_rather_than_guesses(tmp_path):
    """A set v1 then an unset v2 with a date: from v2's date refuse, never fall back to v1's price.
    Also refuse before any version is effective, and for an unknown profile."""
    book = _book(tmp_path, PRICES_V1, {**PRICES_V2, "status": "unset", "source": None})
    assert book.quote("widget", at=_MAR).input == pytest.approx(1.0)
    for profile, at in (("widget", _JUN), ("widget", _SEP), ("widget", datetime(2025, 1, 1)), ("ghost", _MAR)):
        with pytest.raises(UnpricedError):
            book.quote(profile, at=at)


def test_FR_MTR_01_credits_uses_versioned_price_and_credit_usd(tmp_path):
    """credits = (tokens_in*input + tokens_out*output) / 1e6 / credit_usd."""
    book = _book(tmp_path, PRICES_V1)
    credits = book.credits(Usage(profile="widget", tokens_in=1_000_000, tokens_out=1_000_000), at=_MAR)
    assert credits == pytest.approx(600.0)  # (1e6*1.0 + 1e6*2.0) / 1e6 / 0.005
    assert book.credit_usd == pytest.approx(0.005)


def test_FR_MTR_01_repo_prices_yaml_loads_and_quotes_every_profile():
    """PL-06: config/prices.yaml is set (ADR-0029 draft, 2026-10-08), so PriceBook quotes every profile."""
    prices_path = REPO_ROOT / "config" / "prices.yaml"
    raw = yaml.safe_load(prices_path.read_text(encoding="utf-8"))
    assert raw["status"] == "set"
    assert raw["credit_usd"] == pytest.approx(0.005)  # PRD 14.1
    book = PriceBook.load(prices_path)
    assert book.credit_usd == pytest.approx(0.005)
    at = datetime(2026, 10, 8, tzinfo=UTC)
    quote = book.quote("flash-38", at=at)
    assert (quote.input, quote.output, quote.effective_date) == (0.825, 4.125, "2026-10-08")
    assert "asia-southeast1" in quote.source
    assert book.quote("lite-31", at=at).output == pytest.approx(1.65)
    for profile in raw["profiles"]:
        assert book.quote(profile, at=at).input >= 0
    with pytest.raises(UnpricedError):  # before the effective date, refuse rather than guess
        book.quote("flash-38", at=datetime(2026, 9, 1, tzinfo=UTC))


def test_FR_MTR_01_pricebook_is_deeply_immutable(tmp_path):
    """No setters, no environment overrides, no mutation API, no mutable price table."""
    book = _book(tmp_path, PRICES_V1)
    for blocked_name in ("set", "set_price", "update", "override", "mutate", "set_env_override", "save"):
        assert not hasattr(book, blocked_name), f"PriceBook must expose no mutation API, found `{blocked_name}`"
    with pytest.raises(AttributeError):
        book.credit_usd = 0.01  # type: ignore[misc]
    with pytest.raises(TypeError):
        book.versions[0].profiles["widget"] = (0.0, 0.0)  # type: ignore[index]
    assert book.quote("widget", at=_MAR).input == pytest.approx(1.0)


_BAD = [{"credit_usd": 0.05}, {"credit_usd": 0}, {"credit_usd": "0.005"}, {"effective_date": None}, {"source": None}]
_NULL_PRICE = {"profiles": {"widget": {"input": None, "output": 2.0}}}


@pytest.mark.parametrize("override", [*_BAD, _NULL_PRICE])
def test_FR_MTR_01_load_rejects_files_the_schema_rejects(tmp_path, override):
    with pytest.raises(MeteringConfigError):
        _book(tmp_path, {**PRICES_V1, **override})


def test_FR_MTR_01_load_rejects_duplicate_effective_dates(tmp_path):
    with pytest.raises(MeteringConfigError):
        _book(tmp_path, PRICES_V1, {**PRICES_V2, "effective_date": PRICES_V1["effective_date"]})


_BROKEN = {"malformed": b"a: [\n", "not-utf8": b"treasury: caf\xe9\n", "deep": b"a: " + b"[" * 2000 + b"]" * 2000}
_NUMBERS = {"400-digits": "1" + "0" * 399, "inf": ".inf", "nan": ".nan", "bool": "true", "string": "'1.5'"}
_LOADERS: dict = {"prices": (PriceBook.load, PRICES_V1, "input: 1.0")}
_LOADERS["metering"] = (MeteringConfig.load, metering_config(daily_usd_soft=15, daily_usd_hard=25), "run_credits: 300")


@pytest.mark.parametrize("loader", _LOADERS)
@pytest.mark.parametrize("case", [*_BROKEN, *_NUMBERS, "missing", "directory", "null-in-path"])
def test_FR_MTR_01_loaders_refuse_bad_files(tmp_path, loader, case):
    load, doc, field = _LOADERS[loader]
    load(write_yaml(tmp_path, "ok.yaml", doc))  # the unbroken document loads
    path = {"directory": tmp_path, "null-in-path": tmp_path / "a\0b.yaml"}.get(case, tmp_path / "bad.yaml")
    if case in _BROKEN:
        path.write_bytes(_BROKEN[case])
    elif case in _NUMBERS:
        assert field in (valid := yaml.safe_dump(doc, sort_keys=False))
        path.write_text(valid.replace(field, f"{field.split(':')[0]}: {_NUMBERS[case]}"), encoding="utf-8")
    with pytest.raises(MeteringConfigError):
        load(path)


def test_FR_MTR_01_flag_store_and_usage_reject_bad_values():
    flags = InMemoryFlagStore()
    for bad in (1, "true", None):
        with pytest.raises(TypeError):
            flags.set("replay_only", bad, reason="test")  # type: ignore[arg-type]
    assert flags.get("replay_only") is False
    flags.set("replay_only", True, reason="test")
    assert flags.get("replay_only") is True and [c[0] for c in flags.history("replay_only")] == [True]
    for tokens in (True, 1.0, "1", None):
        with pytest.raises(TypeError):
            Usage("widget", tokens, 0)  # type: ignore[arg-type]
    for tokens_in, tokens_out in ((-1, 0), (0, -1), (0, 10**400)):
        with pytest.raises(ValueError):
            Usage("widget", tokens_in, tokens_out)
