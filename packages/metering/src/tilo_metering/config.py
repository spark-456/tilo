"""MeteringConfig (PRD 14.1, 14.5): frozen, validated config/metering.yaml.
Local stub for contract-change #7 until S0 lands the schema (CC-SE)."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .errors import MeteringConfigError


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TreasurySettings(_Strict):
    reserve_margin: float = Field(ge=0, le=5)
    request_at: float = Field(ge=0, le=1)


class Caps(_Strict):
    run_credits: float | None = Field(ge=0)
    user_day_credits: float | None = Field(ge=0)
    org_day_credits: float | None = Field(ge=0)


class SpendCaps(_Strict):
    daily_usd_soft: float = Field(ge=0)
    daily_usd_hard: float = Field(ge=0)


class Reconciliation(_Strict):
    tolerance: float = Field(ge=0, le=1)
    billing_services: list[str]


class MeteringConfig(_Strict):
    """Rejects unknown/out-of-range keys and daily_usd_hard < daily_usd_soft."""

    treasury: TreasurySettings
    caps: Caps
    spend: SpendCaps
    reconciliation: Reconciliation

    @model_validator(mode="after")
    def _hard_at_least_soft(self) -> MeteringConfig:
        if self.spend.daily_usd_hard < self.spend.daily_usd_soft:
            raise ValueError("spend.daily_usd_hard must be >= spend.daily_usd_soft")
        return self

    @classmethod
    def load(cls, path: str | Path = "config/metering.yaml") -> MeteringConfig:
        path = Path(path)
        if not path.is_file():
            raise MeteringConfigError(f"metering config not found at {path}")
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        try:
            return cls.model_validate(raw)
        except ValidationError as exc:
            raise MeteringConfigError(f"{path}: {exc}") from exc
