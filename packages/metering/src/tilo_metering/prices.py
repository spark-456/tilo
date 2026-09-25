"""`PriceBook` (PRD 14.1, 14.5, FR-MTR-01): "1 credit = US$0.005 at
standard list prices from config/prices.yaml, with date and source."
Immutable, versioned by `effective_date`; a price change is a file change
(a pull request), never a runtime mutation. Refuse, never guess: an
unpriced profile or moment raises `UnpricedError`."""

from __future__ import annotations

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


@dataclass(frozen=True)
class _PriceVersion:
    status: str
    effective_date: date | None
    source: str | None
    profiles: dict[str, tuple[float | None, float | None]]


def _utc_date(at: datetime) -> date:
    return at.date() if at.tzinfo is None else at.astimezone(UTC).date()


@dataclass(frozen=True)
class PriceBook:
    """A book of prices files (`contracts/providers.schema.json`
    `$defs.prices`, each validated through `tilo_contracts.ProvidersPrices`),
    each one version keyed by its `effective_date`. No setters, no
    environment overrides, no runtime API that changes a price."""

    credit_usd: float
    versions: tuple[_PriceVersion, ...]

    @classmethod
    def load(cls, *paths: str | Path) -> PriceBook:
        if not paths:
            raise ValueError("PriceBook.load requires at least one prices file")
        versions: list[_PriceVersion] = []
        credit_usd: float | None = None
        for raw_path in paths:
            path = Path(raw_path)
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            prices = ProvidersPrices(**raw)
            if credit_usd is None:
                credit_usd = prices.credit_usd
            elif prices.credit_usd != credit_usd:
                raise ValueError(f"{path}: credit_usd {prices.credit_usd} disagrees with {credit_usd}")
            effective_date = date.fromisoformat(prices.effective_date) if prices.effective_date else None
            profiles = {name: (p.input, p.output) for name, p in prices.profiles.items()}
            versions.append(
                _PriceVersion(
                    status=prices.status, effective_date=effective_date, source=prices.source, profiles=profiles
                )
            )
        assert credit_usd is not None
        return cls(credit_usd=credit_usd, versions=tuple(versions))

    def _selected_version(self, at: datetime) -> _PriceVersion:
        at_date = _utc_date(at)
        effective = [
            v
            for v in self.versions
            if v.status == "set" and v.effective_date is not None and v.effective_date <= at_date
        ]
        if not effective:
            raise UnpricedError(f"no priced version is effective at {at_date.isoformat()}")
        return max(effective, key=lambda v: v.effective_date or date.min)

    def quote(self, profile: str, at: datetime) -> PriceQuote:
        version = self._selected_version(at)
        if profile not in version.profiles:
            raise UnpricedError(f"unknown profile {profile!r}")
        input_price, output_price = version.profiles[profile]
        if input_price is None or output_price is None:
            raise UnpricedError(
                f"profile {profile!r} has no price in the version effective at {_utc_date(at).isoformat()}"
            )
        assert version.effective_date is not None and version.source is not None
        return PriceQuote(
            profile=profile,
            input=input_price,
            output=output_price,
            effective_date=version.effective_date.isoformat(),
            source=version.source,
        )

    def credits(self, usage: Usage, at: datetime) -> float:
        quote = self.quote(usage.profile, at)
        cost_usd = (usage.tokens_in * quote.input + usage.tokens_out * quote.output) / 1_000_000
        return cost_usd / self.credit_usd
