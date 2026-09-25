"""PriceBook (PRD 14.1, 14.5, FR-MTR-01): 1 credit = US$0.005, versioned by effective_date. Refuse, never guess."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType

from tilo_contracts import ProvidersPrices

from .errors import MeteringConfigError, UnpricedError, read_yaml

CREDIT_USD = 0.005  # contracts/providers.schema.json $defs.prices.credit_usd const


@dataclass(frozen=True)
class Usage:
    profile: str
    tokens_in: int
    tokens_out: int

    def __post_init__(self) -> None:
        if self.tokens_in < 0 or self.tokens_out < 0:
            raise ValueError(f"token counts must be >= 0: {self}")


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
class _Version:
    status: str
    effective_date: str | None
    source: str | None
    profiles: Mapping[str, tuple[float | None, float | None]]


def _load_version(path: str | Path) -> _Version:
    try:
        v = ProvidersPrices.model_validate(read_yaml(path), strict=True)
    except (ValueError, TypeError) as exc:
        raise MeteringConfigError(f"{path}: not a valid prices file: {exc}") from exc
    if v.credit_usd != CREDIT_USD:
        raise MeteringConfigError(f"{path}: credit_usd must be {CREDIT_USD}, got {v.credit_usd}")
    prices = {k: (p.input, p.output) for k, p in v.profiles.items()}
    if v.status == "set" and (v.effective_date is None or v.source is None or None in sum(prices.values(), ())):
        raise MeteringConfigError(f"{path}: a set prices file needs effective_date, source and every price")
    return _Version(v.status, v.effective_date, v.source, MappingProxyType(prices))


@dataclass(frozen=True)
class PriceBook:
    """Versions from providers.schema.json $defs.prices files. No setters,
    no environment overrides: a price change is a file change."""

    credit_usd: float
    versions: tuple[_Version, ...]

    @classmethod
    def load(cls, *paths: str | Path) -> PriceBook:
        if not paths:
            raise ValueError("PriceBook.load requires at least one prices file")
        versions = tuple(_load_version(p) for p in paths)
        dates = [v.effective_date for v in versions if v.effective_date is not None]
        if len(dates) != len(set(dates)):
            raise MeteringConfigError(f"prices files share an effective_date: {sorted(dates)}")
        return cls(credit_usd=CREDIT_USD, versions=versions)

    def _selected_version(self, at: datetime) -> _Version:
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
        price_in, price_out = version.profiles.get(profile, (None, None))
        if price_in is None or price_out is None:
            raise UnpricedError(f"profile {profile!r} has no price at {_utc_date(at)}")
        effective_date, source = version.effective_date, version.source
        assert effective_date is not None and source is not None
        return PriceQuote(profile, price_in, price_out, effective_date, source)

    def credits(self, usage: Usage, at: datetime) -> float:
        quote = self.quote(usage.profile, at)
        cost_usd = (usage.tokens_in * quote.input + usage.tokens_out * quote.output) / 1_000_000
        return cost_usd / self.credit_usd
