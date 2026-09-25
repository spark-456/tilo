"""FR-MTR-01 (PRD 14.5): "Credit unit and prices from config with date and
source" -- acceptance test: "Price change needs a pull request; ledger uses
the new price from its effective date." PRD 14.1: "1 credit = US$0.005 at
standard (non-promotional) list prices from config/prices.yaml ... The unit
stays stable when providers run promotions." PRD 6.4 PL-06: "Prices come
from config/prices.yaml with a date and source" -- "Ledger reconciliation
... uses the same file." PRD 3.1 PR-9: "Deterministic where it must be":
pricing is a file change, never a runtime mutation.

se-spec.md "## P8-01" fixes the acceptance tests verbatim:
- two prices files at different effective dates (temporary files, fake
  prices): a step before the second date is priced at the old price, one
  on or after it at the new one;
- committed entries keep their price date and source;
- status: unset refuses to price, while record_usage still records;
- config/prices.yaml loads and refuses to price every profile;
- there is no mutation API.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
import yaml
from _metering_testlib import (
    PRICES_V1,
    PRICES_V2,
    REPO_ROOT,
    build_treasury,
    metering_config,
    prices_version,
    write_metering_config,
    write_prices_file,
)
from tilo_metering import InMemoryFlagStore, MeteringConfig, PriceBook, Treasury, UnpricedError, Usage


def _at(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, 12, 0, tzinfo=UTC)


def test_FR_MTR_01_two_price_versions_priced_by_effective_date(tmp_path):
    """A step before the second version's effective_date is priced at the
    old rate; one on or after it (inclusive) at the new rate."""
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
    """PriceBook.quote raises UnpricedError when 'no version is effective
    yet' -- refuse, never guess."""
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
    """PRD 14.1: 1 credit = US$0.005. credits = (tokens_in*input +
    tokens_out*output) / 1e6 / credit_usd."""
    v1_path = write_prices_file(tmp_path, "prices_v1.yaml", PRICES_V1)
    book = PriceBook.load(v1_path)
    usage = Usage(profile="widget", tokens_in=1_000_000, tokens_out=1_000_000)

    credits = book.credits(usage, at=_at(2026, 3, 1))

    # (1_000_000*1.0 + 1_000_000*2.0) / 1e6 / 0.005 = 3.0 / 0.005 = 600
    assert credits == pytest.approx(600.0)
    assert book.credit_usd == pytest.approx(0.005)


def test_FR_MTR_01_committed_entries_keep_their_price_effective_date_and_source(tmp_path):
    """ "An entry is never re-priced after it is written" -- two runs, each
    committed under a different price version, must each keep the date and
    source that priced them, not the latest version in the book."""
    v1_path = write_prices_file(tmp_path, "prices_v1.yaml", PRICES_V1)
    v2_path = write_prices_file(tmp_path, "prices_v2.yaml", PRICES_V2)
    book = PriceBook.load(v1_path, v2_path)
    config_path = write_metering_config(tmp_path, metering_config())
    treasury = Treasury(config=MeteringConfig.load(config_path), prices=book, flags=InMemoryFlagStore())

    treasury.open_run("r_price_early", user_id="u_price", org_id="org_price", approved=1000)
    treasury.open_run("r_price_late", user_id="u_price", org_id="org_price", approved=1000)

    usage = Usage(profile="widget", tokens_in=1_000_000, tokens_out=0)

    early_reservation = treasury.reserve("r_price_early", "s1", estimate=1.0, at=_at(2026, 3, 1))
    treasury.commit_usage(early_reservation, usage, at=_at(2026, 3, 1))

    late_reservation = treasury.reserve("r_price_late", "s1", estimate=3.0, at=_at(2026, 9, 1))
    treasury.commit_usage(late_reservation, usage, at=_at(2026, 9, 1))

    commits = {e.run: e for e in treasury.ledger if e.kind == "commit"}

    assert commits["r_price_early"].price_effective_date == "2026-01-01"
    assert commits["r_price_early"].price_source == PRICES_V1["source"]
    assert commits["r_price_late"].price_effective_date == "2026-06-01"
    assert commits["r_price_late"].price_source == PRICES_V2["source"]


def test_FR_MTR_01_unset_status_refuses_to_price_but_record_usage_still_records(tmp_path):
    """record_usage "meters recorded usage only. It always works, even with
    unset prices, and appends a usage entry with credits=None." (see-spec.md
    Treasury bullet list)."""
    unset_prices = prices_version(status="unset", profiles={"widget": {"input": None, "output": None}})
    prices_path = write_prices_file(tmp_path, "prices_unset.yaml", unset_prices)
    book = PriceBook.load(prices_path)
    usage = Usage(profile="widget", tokens_in=100, tokens_out=100)

    with pytest.raises(UnpricedError):
        book.quote("widget", at=_at(2026, 3, 1))
    with pytest.raises(UnpricedError):
        book.credits(usage, at=_at(2026, 3, 1))

    treasury, _flags = build_treasury(tmp_path, prices=unset_prices)
    treasury.open_run("r_unset", user_id="u_unset", org_id="org_unset", approved=100)

    treasury.record_usage("r_unset", usage, at=_at(2026, 3, 1))

    usage_entries = [e for e in treasury.ledger if e.kind == "usage" and e.run == "r_unset"]
    assert len(usage_entries) == 1
    assert usage_entries[0].credits is None
    assert usage_entries[0].usage == usage


def test_FR_MTR_01_repo_prices_yaml_loads_and_refuses_every_profile():
    """ "Prices are never invented": the real config/prices.yaml stays
    status: unset (se-spec.md #13) until the user pastes real list prices
    in, so PriceBook must refuse to price every profile it lists."""
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
    """ "It is immutable: no setters, no environment overrides, no runtime
    API that changes a price. A price change is a file change, which means
    a pull request." There is no mutation API."""
    v1_path = write_prices_file(tmp_path, "prices_v1.yaml", PRICES_V1)
    book = PriceBook.load(v1_path)

    for blocked_name in ("set", "set_price", "update", "override", "mutate", "set_env_override", "save"):
        assert not hasattr(book, blocked_name), f"PriceBook must expose no mutation API, found `{blocked_name}`"

    with pytest.raises(AttributeError):
        book.credit_usd = 0.01
