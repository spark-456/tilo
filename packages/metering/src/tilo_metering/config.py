"""`MeteringConfig` (PRD 14.1, 14.5): a frozen, validated view of
`config/metering.yaml`. Local stub for contract-change issue #7 (se-spec.md
"## 0. Rules for every SE ticket") until S0 lands the schema in batch
CC-SE; the shape and demo defaults are fixed there. A missing file raises
`MeteringConfigError`; it never falls back to invented values."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from .errors import MeteringConfigError

_SECTIONS = ("treasury", "caps", "spend", "reconciliation")


@dataclass(frozen=True)
class TreasurySettings:
    reserve_margin: float
    request_at: float


@dataclass(frozen=True)
class Caps:
    run_credits: float | None
    user_day_credits: float | None
    org_day_credits: float | None


@dataclass(frozen=True)
class SpendCaps:
    daily_usd_soft: float
    daily_usd_hard: float


@dataclass(frozen=True)
class Reconciliation:
    tolerance: float
    billing_services: tuple[str, ...]


def _section(raw: dict, name: str, allowed: tuple[str, ...]) -> dict:
    if name not in raw:
        raise MeteringConfigError(f"config/metering.yaml: missing section '{name}'")
    section = raw[name]
    if not isinstance(section, dict):
        raise MeteringConfigError(f"config/metering.yaml: section '{name}' must be a mapping")
    unknown = set(section) - set(allowed)
    if unknown:
        raise MeteringConfigError(f"config/metering.yaml: unknown key(s) in '{name}': {sorted(unknown)}")
    missing = set(allowed) - set(section)
    if missing:
        raise MeteringConfigError(f"config/metering.yaml: missing key(s) in '{name}': {sorted(missing)}")
    return section


def _positive_or_none(value: object, field: str) -> float | None:
    if value is None:
        return None
    if not isinstance(value, int | float) or isinstance(value, bool) or value <= 0:
        raise MeteringConfigError(f"config/metering.yaml: '{field}' must be a positive number or null, got {value!r}")
    return float(value)


def _in_range(value: object, field: str, *, low: float, high: float) -> float:
    if not isinstance(value, int | float) or isinstance(value, bool) or not (low <= value <= high):
        raise MeteringConfigError(f"config/metering.yaml: '{field}' must be in [{low}, {high}], got {value!r}")
    return float(value)


@dataclass(frozen=True)
class MeteringConfig:
    treasury: TreasurySettings
    caps: Caps
    spend: SpendCaps
    reconciliation: Reconciliation

    @classmethod
    def load(cls, path: str | Path = "config/metering.yaml") -> MeteringConfig:
        path = Path(path)
        if not path.is_file():
            raise MeteringConfigError(f"config/metering.yaml not found at {path}")
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise MeteringConfigError(f"{path}: must be a mapping at the top level")
        unknown = set(raw) - set(_SECTIONS)
        if unknown:
            raise MeteringConfigError(f"{path}: unknown top-level key(s) {sorted(unknown)}")

        treasury_raw = _section(raw, "treasury", ("reserve_margin", "request_at"))
        caps_raw = _section(raw, "caps", ("run_credits", "user_day_credits", "org_day_credits"))
        spend_raw = _section(raw, "spend", ("daily_usd_soft", "daily_usd_hard"))
        reconciliation_raw = _section(raw, "reconciliation", ("tolerance", "billing_services"))

        treasury = TreasurySettings(
            reserve_margin=_in_range(treasury_raw["reserve_margin"], "treasury.reserve_margin", low=0.0, high=5.0),
            request_at=_in_range(treasury_raw["request_at"], "treasury.request_at", low=0.0, high=1.0),
        )
        caps = Caps(
            run_credits=_positive_or_none(caps_raw["run_credits"], "caps.run_credits"),
            user_day_credits=_positive_or_none(caps_raw["user_day_credits"], "caps.user_day_credits"),
            org_day_credits=_positive_or_none(caps_raw["org_day_credits"], "caps.org_day_credits"),
        )
        daily_usd_soft = _in_range(spend_raw["daily_usd_soft"], "spend.daily_usd_soft", low=0.0, high=1e9)
        daily_usd_hard = _in_range(spend_raw["daily_usd_hard"], "spend.daily_usd_hard", low=0.0, high=1e9)
        if daily_usd_hard < daily_usd_soft:
            raise MeteringConfigError(
                f"{path}: spend.daily_usd_hard ({daily_usd_hard}) must be >= spend.daily_usd_soft ({daily_usd_soft})"
            )
        spend = SpendCaps(daily_usd_soft=daily_usd_soft, daily_usd_hard=daily_usd_hard)

        billing_services = reconciliation_raw["billing_services"]
        if not isinstance(billing_services, list) or not all(isinstance(s, str) for s in billing_services):
            raise MeteringConfigError(f"{path}: reconciliation.billing_services must be a list of strings")
        reconciliation = Reconciliation(
            tolerance=_in_range(reconciliation_raw["tolerance"], "reconciliation.tolerance", low=0.0, high=1.0),
            billing_services=tuple(billing_services),
        )

        return cls(treasury=treasury, caps=caps, spend=spend, reconciliation=reconciliation)
