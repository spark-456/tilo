"""FR-MTR-01 (PRD 14.5, 14.1, 6.4 PL-06): 1 credit = US$0.005 with a price date and source; refuse, never guess."""

from datetime import UTC, datetime

import pytest
import yaml
from _metering_testlib import PRICES_V1, PRICES_V2, REPO_ROOT, _prices, build_treasury, metering_config, write_yaml
from tilo_metering import InMemoryFlagStore, MeteringConfig, MeteringConfigError, PriceBook, Treasury, UnpricedError
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


def test_FR_MTR_01_repo_prices_yaml_loads_and_refuses_every_profile():
    """Prices are never invented: config/prices.yaml stays unset, so PriceBook refuses every profile."""
    prices_path = REPO_ROOT / "config" / "prices.yaml"
    raw = yaml.safe_load(prices_path.read_text(encoding="utf-8"))
    assert raw["status"] == "unset", "config/prices.yaml must stay unset until real prices are pasted in"
    assert raw["credit_usd"] == pytest.approx(0.005)  # PRD 14.1
    book = PriceBook.load(prices_path)
    assert book.credit_usd == pytest.approx(0.005)
    for profile in raw["profiles"]:
        with pytest.raises(UnpricedError):
            book.quote(profile, at=datetime.now(tz=UTC))


def test_FR_MTR_01_committed_entries_keep_their_price_effective_date_and_source(tmp_path):
    """An entry is never re-priced after it is written: two runs, each committed under a different
    price version, keep the date and source that priced them, not the book's latest version."""
    book = _book(tmp_path, PRICES_V1, PRICES_V2)
    config = MeteringConfig.load(write_yaml(tmp_path, "metering.yaml", metering_config()))
    treasury = Treasury(config=config, prices=book, flags=InMemoryFlagStore())
    treasury.open_run("r_early", user_id="u", org_id="org", approved=1000)
    treasury.open_run("r_late", user_id="u", org_id="org", approved=1000)
    usage = Usage(profile="widget", tokens_in=1_000_000, tokens_out=0)

    early = treasury.reserve("r_early", "s1", estimate=1.0, at=_MAR)
    treasury.commit_usage(early, usage, at=_MAR)
    late = treasury.reserve("r_late", "s1", estimate=3.0, at=_SEP)
    treasury.commit_usage(late, usage, at=_SEP)

    commits = {e.run: e for e in treasury.ledger if e.kind == "commit"}
    assert commits["r_early"].price_effective_date == "2026-01-01"
    assert commits["r_early"].price_source == PRICES_V1["source"]
    assert commits["r_late"].price_effective_date == "2026-06-01"
    assert commits["r_late"].price_source == PRICES_V2["source"]


def test_FR_MTR_01_unset_status_refuses_to_price_but_record_usage_still_records(tmp_path):
    """record_usage meters recorded usage only: it always works, even with unset prices, and
    appends a usage entry with credits=None."""
    unset = _prices(None, None, None, None, status="unset")
    book = PriceBook.load(write_yaml(tmp_path, "unset.yaml", unset))
    usage = Usage(profile="widget", tokens_in=100, tokens_out=100)
    with pytest.raises(UnpricedError):
        book.credits(usage, at=_MAR)

    treasury, _flags = build_treasury(tmp_path, prices=unset)
    treasury.open_run("r_unset", user_id="u", org_id="org", approved=100)
    treasury.record_usage("r_unset", usage, at=_MAR)

    entries = [e for e in treasury.ledger if e.kind == "usage" and e.run == "r_unset"]
    assert len(entries) == 1
    assert entries[0].credits is None
    assert entries[0].usage == usage


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
