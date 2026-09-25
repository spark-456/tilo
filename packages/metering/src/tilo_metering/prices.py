"""PriceBook (PRD 14.1, 14.5, FR-MTR-01): 1 credit = US$0.005, versioned by effective_date. Refuse, never guess."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import yaml
from tilo_contracts import ProvidersPrices

from .errors import UnpricedError


@dataclass(frozen=True)
class Usage:
    profile: str
    tokens_in: int
    tokens_out: int


@dataclass(frozen=True)
class PriceQuote:
    profile: str
    input: float
    output: float
    effective_date: str
    source: str


def _utc_date(at: datetime) -> str:
    d = at.date() if at.tzinfo is None else at.astimezone(UTC).date()
    return d.isoformat()


@dataclass(frozen=True)
class PriceBook:
    """Versions from providers.schema.json $defs.prices files. No setters,
    no environment overrides: a price change is a file change."""

    credit_usd: float
    versions: tuple[ProvidersPrices, ...]

    @classmethod
    def load(cls, *paths: str | Path) -> PriceBook:
        if not paths:
            raise ValueError("PriceBook.load requires at least one prices file")
        versions = tuple(ProvidersPrices(**(yaml.safe_load(Path(p).read_text(encoding="utf-8")) or {})) for p in paths)
        credit_usds = {v.credit_usd for v in versions}
        if len(credit_usds) > 1:
            raise ValueError(f"prices files disagree on credit_usd: {sorted(credit_usds)}")
        return cls(credit_usd=credit_usds.pop(), versions=versions)

    def _selected_version(self, at: datetime) -> ProvidersPrices:
        at_date = _utc_date(at)
        candidates = [v for v in self.versions if v.effective_date is not None and v.effective_date <= at_date]
        if not candidates:
            raise UnpricedError(f"no priced version is effective at {at_date}")
        version = max(candidates, key=lambda v: v.effective_date or "")
        if version.status != "set":
            raise UnpricedError(f"price version effective at {at_date} is unset")
        return version

    def quote(self, profile: str, at: datetime) -> PriceQuote:
        version = self._selected_version(at)
        price = version.profiles.get(profile)
        if price is None or price.input is None or price.output is None:
            raise UnpricedError(f"profile {profile!r} has no price at {_utc_date(at)}")
        effective_date, source = version.effective_date, version.source
        assert effective_date is not None and source is not None
        return PriceQuote(profile, price.input, price.output, effective_date, source)

    def credits(self, usage: Usage, at: datetime) -> float:
        quote = self.quote(usage.profile, at)
        cost_usd = (usage.tokens_in * quote.input + usage.tokens_out * quote.output) / 1_000_000
        return cost_usd / self.credit_usd
