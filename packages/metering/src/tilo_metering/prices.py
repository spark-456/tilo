"""PriceBook (PRD 14.1, 14.5, FR-MTR-01): 1 credit = US$0.005, versioned by effective_date. Refuse, never guess."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Self

from tilo_contracts import ProvidersPrices

from .errors import MeteringConfigError, UnpricedError, number, read_yaml

CREDIT_USD = 0.005  # contracts/providers.schema.json $defs.prices.credit_usd
MAX_TOKENS = 10**15  # keeps tokens * price inside float range in credits()


@dataclass(frozen=True)
class Usage:
    """One call. `tokens_cached` is a part of `tokens_in` served from the provider's prompt cache (ADR-0029 decision 2);
    `units` counts the profile's `unit_price` unit, for example the search queries a grounded call ran (decision 1).
    `tokens_audio` (LW-06) is the audio part of `tokens_in`, priced at `audio_input`, apart from `tokens_cached`."""

    profile: str
    tokens_in: int
    tokens_out: int
    tokens_cached: int = 0
    units: int = 0
    tokens_audio: int = 0

    def __post_init__(self) -> None:
        for tokens in (self.tokens_in, self.tokens_out, self.tokens_cached, self.units, self.tokens_audio):
            if isinstance(tokens, bool) or not isinstance(tokens, int):
                raise TypeError(f"token counts must be ints, got {type(tokens).__name__}")
            if not 0 <= tokens <= MAX_TOKENS:
                raise ValueError(f"token counts must be in 0..{MAX_TOKENS}")
        if self.tokens_cached > self.tokens_in:
            raise ValueError("cached tokens are a part of the input tokens: tokens_cached must be <= tokens_in")
        if self.tokens_cached + self.tokens_audio > self.tokens_in:
            raise ValueError("cached and audio tokens are parts of the input tokens: together at most tokens_in")


@dataclass(frozen=True)
class PriceQuote:
    profile: str
    input: float
    output: float
    effective_date: str
    source: str
    cached_input: float | None = None  # None: cached tokens are priced at `input` (overstates, never understates)
    unit: str | None = None  # the unit_price unit (query, minute, character, image), with per_1k its US$ per 1,000
    per_1k: float | None = None
    valid_until: str | None = None
    region: str | None = None  # the provider location the rates were quoted for (checked by tilo_providers at start-up)
    audio_input: float | None = None  # US$ per 1M audio input tokens; None: no audio price (LW-06 refuses audio)


@dataclass(frozen=True)
class _Rate:
    input: float | None
    output: float | None
    cached_input: float | None
    unit: str | None
    per_1k: float | None
    valid_until: str | None
    audio_input: float | None = None


@dataclass(frozen=True)
class _Version:
    status: str
    effective_date: str | None
    source: str | None
    profiles: Mapping[str, _Rate]
    region: str | None = None


def _load_version(path: str | Path) -> _Version:
    try:
        v = ProvidersPrices.model_validate(read_yaml(path), strict=True)
        rates = {}
        for name, p in v.profiles.items():
            fee = p.unit_price
            rates[name] = _Rate(
                p.input,
                p.output,
                p.cached_input,
                fee.unit if fee else None,
                fee.per_1k if fee else None,
                p.valid_until,
                p.audio_input,
            )
            fields = p.model_fields_set
            if v.status == "set" and (
                ("cached_input" in fields and p.cached_input is None) or (fee and fee.per_1k is None)
            ):
                raise ValueError(f"profile {name!r}: a set prices file holds no null cached_input or per_1k")
            if "valid_until" in fields and p.valid_until is None:
                raise ValueError(f"profile {name!r}: valid_until is a date, never null")
            if p.valid_until is not None and v.effective_date is not None and p.valid_until < v.effective_date:
                raise ValueError(f"profile {name!r}: valid_until {p.valid_until} is before effective_date")
        flat = [x for r in rates.values() for x in (r.input, r.output)]
        [number(v) for r in rates.values() for v in (r.cached_input, r.per_1k, r.audio_input) if v is not None]
        [number(value) for value in (v.credit_usd, *flat) if value is not None]
    except (ValueError, RecursionError) as exc:  # ValidationError is a ValueError
        raise MeteringConfigError(f"{path}: not a valid prices file: {exc}") from exc
    if v.credit_usd != CREDIT_USD:
        raise MeteringConfigError(f"{path}: credit_usd must be {CREDIT_USD}, got {v.credit_usd}")
    if v.status == "set" and None in (v.effective_date, v.source, *flat):
        raise MeteringConfigError(f"{path}: a set prices file needs effective_date, source and every price")
    return _Version(v.status, v.effective_date, v.source, MappingProxyType(rates), v.region)


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
        rate = version.profiles.get(profile)
        if version.status != "set" or rate is None or rate.input is None or rate.output is None:
            raise UnpricedError(f"profile {profile!r} has no price at {day}")
        if rate.valid_until is not None and day > rate.valid_until:  # decision 4: never fall back to an older price
            raise UnpricedError(f"profile {profile!r} has no price at {day}: its rate held until {rate.valid_until}")
        assert version.effective_date is not None and version.source is not None
        return PriceQuote(
            profile,
            rate.input,
            rate.output,
            version.effective_date,
            version.source,
            rate.cached_input,
            rate.unit,
            rate.per_1k,
            rate.valid_until,
            version.region,
            rate.audio_input,
        )

    def credits(self, usage: Usage, at: datetime) -> float:
        """Tokens at their rates (cached ones at `cached_input`, else `input`; audio ones at `audio_input`, refused
        if the profile has none) plus units * per_1k / 1,000."""
        quote = self.quote(usage.profile, at)
        cached_rate = quote.input if quote.cached_input is None else quote.cached_input
        if usage.tokens_audio and quote.audio_input is None:
            raise UnpricedError(f"profile {usage.profile!r} has no audio_input price: audio tokens cannot be priced")
        plain = usage.tokens_in - usage.tokens_cached - usage.tokens_audio
        tokens = plain * quote.input + usage.tokens_cached * cached_rate + usage.tokens_audio * (quote.audio_input or 0)
        usd = (tokens + usage.tokens_out * quote.output) / 1_000_000
        if usage.units:
            if quote.per_1k is None:
                raise UnpricedError(
                    f"profile {usage.profile!r} has no unit price: {usage.units} units cannot be priced"
                )
            usd += usage.units * quote.per_1k / 1000
        return usd / self.credit_usd
