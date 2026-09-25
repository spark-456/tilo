"""PriceBook (PRD 14.1, 14.5, FR-MTR-01): 1 credit = US$0.005, versioned by effective_date. Refuse, never guess."""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Self

from tilo_contracts import ProvidersPrices

from .errors import MeteringConfigError, UnpricedError, number, read_yaml

CREDIT_USD = 0.005  # contracts/providers.schema.json $defs.prices.credit_usd
MAX_TOKENS = 10**15  # keeps tokens * price inside float range in credits()


@dataclass(frozen=True)
class Usage:
    profile: str
    tokens_in: int
    tokens_out: int

    def __post_init__(self) -> None:
        for tokens in (self.tokens_in, self.tokens_out):
            if isinstance(tokens, bool) or not isinstance(tokens, int):
                raise TypeError(f"token counts must be ints, got {type(tokens).__name__}")
            if not 0 <= tokens <= MAX_TOKENS:
                raise ValueError(f"token counts must be in 0..{MAX_TOKENS}")


@dataclass(frozen=True)
class PriceQuote:
    profile: str
    input: float
    output: float
    effective_date: str
    source: str


@dataclass(frozen=True)
class _Version:
    status: str
    effective_date: str | None
    source: str | None
    profiles: Mapping[str, tuple[float | None, float | None]]


def _load_version(path: str | Path) -> _Version:
    try:
        v = ProvidersPrices.model_validate(read_yaml(path), strict=True)
        prices = {k: (p.input, p.output) for k, p in v.profiles.items()}
        flat = [p for pair in prices.values() for p in pair]
        [number(value) for value in (v.credit_usd, *flat) if value is not None]
    except (ValueError, RecursionError) as exc:  # ValidationError is a ValueError
        raise MeteringConfigError(f"{path}: not a valid prices file: {exc}") from exc
    if v.credit_usd != CREDIT_USD:
        raise MeteringConfigError(f"{path}: credit_usd must be {CREDIT_USD}, got {v.credit_usd}")
    if v.status == "set" and None in (v.effective_date, v.source, *flat):
        raise MeteringConfigError(f"{path}: a set prices file needs effective_date, source and every price")
    if v.effective_date is not None:
        try:
            date.fromisoformat(v.effective_date)  # the schema's regex accepts calendar-impossible dates
        except ValueError as exc:
            raise MeteringConfigError(f"{path}: effective_date {v.effective_date!r} is not a real date: {exc}") from exc
    return _Version(v.status, v.effective_date, v.source, MappingProxyType(prices))


@dataclass(frozen=True)
class PriceBook:
    """Immutable: no setters, no environment overrides. A price change is a file change."""

    credit_usd: float
    versions: tuple[_Version, ...]

    @classmethod
    def load(cls, *paths: str | Path) -> Self:
        if not paths:
            raise ValueError("PriceBook.load requires at least one prices file")
        versions = tuple(_load_version(p) for p in paths)
        dates = [v.effective_date for v in versions if v.effective_date is not None]
        if len(dates) != len(set(dates)):
            raise MeteringConfigError(f"prices files share an effective_date: {sorted(dates)}")
        return cls(credit_usd=CREDIT_USD, versions=versions)

    def quote(self, profile: str, at: datetime) -> PriceQuote:
        """The version with the greatest effective_date <= at (UTC date) prices, whatever its status."""
        day = (at.date() if at.tzinfo is None else at.astimezone(UTC).date()).isoformat()
        effective = [v for v in self.versions if v.effective_date is not None and v.effective_date <= day]
        if not effective:
            raise UnpricedError(f"no price version is effective at {day}")
        version = max(effective, key=lambda v: v.effective_date or "")
        price_in, price_out = version.profiles.get(profile, (None, None))
        if version.status != "set" or price_in is None or price_out is None:
            raise UnpricedError(f"profile {profile!r} has no price at {day}")
        assert version.effective_date is not None and version.source is not None
        return PriceQuote(profile, price_in, price_out, version.effective_date, version.source)

    def credits(self, usage: Usage, at: datetime) -> float:
        quote = self.quote(usage.profile, at)
        value = (usage.tokens_in * quote.input + usage.tokens_out * quote.output) / 1_000_000 / self.credit_usd
        if not math.isfinite(value):
            raise UnpricedError(f"non-finite credits result for profile {usage.profile!r}")
        return value
