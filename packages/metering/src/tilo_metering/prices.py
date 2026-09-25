"""PriceBook (PRD 14.1, 14.5, FR-MTR-01): 1 credit = US$0.005, versioned
by effective_date. Refuse rather than guess an unpriced quote."""

from __future__ import annotations

from collections import namedtuple
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import yaml
from tilo_contracts import ProvidersPrices

from .errors import UnpricedError


@dataclass(frozen=True)
class Usage:
    """What one step consumed."""

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


# status, effective_date (date | None), source (str | None), profiles ({name: (input, output)}).
_PriceVersion = namedtuple("_PriceVersion", "status effective_date source profiles")


def _utc_date(at: datetime) -> date:
    return at.date() if at.tzinfo is None else at.astimezone(UTC).date()


def _load_version(path: Path) -> tuple[float, _PriceVersion]:
    prices = ProvidersPrices(**(yaml.safe_load(path.read_text(encoding="utf-8")) or {}))
    effective_date = date.fromisoformat(prices.effective_date) if prices.effective_date else None
    profiles = {name: (p.input, p.output) for name, p in prices.profiles.items()}
    return prices.credit_usd, _PriceVersion(prices.status, effective_date, prices.source, profiles)


@dataclass(frozen=True)
class PriceBook:
    """Versions from providers.schema.json $defs.prices files. No setters,
    no environment overrides: a price change is a file change."""

    credit_usd: float
    versions: tuple[_PriceVersion, ...]

    @classmethod
    def load(cls, *paths: str | Path) -> PriceBook:
        if not paths:
            raise ValueError("PriceBook.load requires at least one prices file")
        loaded = [_load_version(Path(p)) for p in paths]
        credit_usds = {c for c, _ in loaded}
        if len(credit_usds) > 1:
            raise ValueError(f"prices files disagree on credit_usd: {sorted(credit_usds)}")
        return cls(credit_usd=credit_usds.pop(), versions=tuple(v for _, v in loaded))

    def _selected_version(self, at: datetime) -> _PriceVersion:
        at_date = _utc_date(at)
        effective = [v for v in self.versions if v.status == "set" and v.effective_date and v.effective_date <= at_date]
        if not effective:
            raise UnpricedError(f"no priced version is effective at {at_date.isoformat()}")
        return max(effective, key=lambda v: v.effective_date)

    def quote(self, profile: str, at: datetime) -> PriceQuote:
        version = self._selected_version(at)
        if profile not in version.profiles:
            raise UnpricedError(f"unknown profile {profile!r}")
        input_price, output_price = version.profiles[profile]
        if input_price is None or output_price is None:
            raise UnpricedError(f"profile {profile!r} has no price at {_utc_date(at).isoformat()}")
        return PriceQuote(profile, input_price, output_price, version.effective_date.isoformat(), version.source)

    def credits(self, usage: Usage, at: datetime) -> float:
        quote = self.quote(usage.profile, at)
        cost_usd = (usage.tokens_in * quote.input + usage.tokens_out * quote.output) / 1_000_000
        return cost_usd / self.credit_usd
