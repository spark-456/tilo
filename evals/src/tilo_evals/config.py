"""EvalsConfig: the eval harness's own settings (EFF-07; PRD 19.1, 6.6). Local stub for issue #8:
rejects a missing file, an unknown/missing key or a bad value, never falls back to an invented value."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


def _nonneg(v: Any, kind: type | tuple[type, ...] = int) -> bool:
    typed = isinstance(v, kind) and not isinstance(v, bool)  # a separate name keeps v: Any for mypy
    return typed and v >= 0


_VALID: dict[str, Callable[[Any], bool]] = {
    "credit_cap": lambda v: isinstance(v, dict) and all(_nonneg(n) for n in v.values()),
    "deploy_gate_repeats": _nonneg,
    "cost_regression_threshold": lambda v: _nonneg(v, (int, float)),
    "groups": lambda v: isinstance(v, dict) and all(_nonneg(n) for n in v.values()),
}


class EvalsConfigError(Exception):
    """Missing file, an unknown/missing top-level key, or a value of the wrong type or below zero."""


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
        if unknown := set(raw) - set(_VALID):
            raise EvalsConfigError(f"{p}: unknown key(s) {sorted(unknown)}")
        if missing := set(_VALID) - set(raw):
            raise EvalsConfigError(f"{p}: missing key(s) {sorted(missing)}")
        if bad := [k for k, ok in _VALID.items() if not ok(raw[k])]:
            raise EvalsConfigError(f"{p}: {bad} must be non-negative (a number for the threshold, else integers)")
        raw["cost_regression_threshold"] = float(raw["cost_regression_threshold"])
        return EvalsConfig(**raw)  # keys == _VALID == EvalsConfig's field names
