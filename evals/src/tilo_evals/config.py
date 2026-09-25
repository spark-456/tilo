"""EvalsConfig: the eval harness's own settings (EFF-07; PRD 19.1, 6.6). Local stub for issue #8:
rejects a missing file or an unknown/missing key, never falls back to an invented value."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_REQUIRED_KEYS = {"credit_cap", "deploy_gate_repeats", "cost_regression_threshold", "groups"}


class EvalsConfigError(Exception):
    """Missing file, or an unknown/missing top-level key."""


@dataclass(frozen=True)
class EvalsConfig:
    credit_cap: dict[str, int]
    deploy_gate_repeats: int
    cost_regression_threshold: float
    groups: dict[str, int]

    @staticmethod
    def load(path: str = "config/evals.yaml") -> EvalsConfig:
        p = Path(path)
        if not p.is_file():
            raise EvalsConfigError(f"missing eval config: {p}")
        raw: Any = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise EvalsConfigError(f"{p}: must be a mapping")
        if unknown := set(raw) - _REQUIRED_KEYS:
            raise EvalsConfigError(f"{p}: unknown key(s) {sorted(unknown)}")
        if missing := _REQUIRED_KEYS - set(raw):
            raise EvalsConfigError(f"{p}: missing key(s) {sorted(missing)}")
        raw["cost_regression_threshold"] = float(raw["cost_regression_threshold"])
        return EvalsConfig(**raw)  # keys == _REQUIRED_KEYS == EvalsConfig's field names
