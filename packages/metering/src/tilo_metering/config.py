"""MeteringConfig (PRD 14.1, 14.5): frozen, validated config/metering.yaml (local stub for contract change #7)."""

from pathlib import Path
from typing import Annotated, Self

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from .errors import MeteringConfigError, number, read_yaml

Num = Annotated[float, BeforeValidator(number)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TreasurySettings(_Strict):
    reserve_margin: Num = Field(ge=0, le=5)
    request_at: Num = Field(ge=0, le=1)


class Caps(_Strict):
    run_credits: Num | None = Field(ge=0)
    user_day_credits: Num | None = Field(ge=0)
    org_day_credits: Num | None = Field(ge=0)


class SpendCaps(_Strict):
    daily_usd_soft: Num = Field(ge=0)
    daily_usd_hard: Num = Field(ge=0)


class Reconciliation(_Strict):
    tolerance: Num = Field(ge=0, le=1)
    billing_services: list[str]


class MeteringConfig(_Strict):
    treasury: TreasurySettings
    caps: Caps
    spend: SpendCaps
    reconciliation: Reconciliation

    @model_validator(mode="after")
    def _hard_at_least_soft(self) -> Self:
        if self.spend.daily_usd_hard < self.spend.daily_usd_soft:
            raise ValueError("spend.daily_usd_hard must be >= spend.daily_usd_soft")
        return self

    @classmethod
    def load(cls, path: str | Path = "config/metering.yaml") -> Self:
        raw = read_yaml(path)
        try:
            return cls.model_validate(raw)
        except (ValueError, RecursionError) as exc:  # ValidationError is a ValueError
            raise MeteringConfigError(f"{path}: {exc}") from exc
