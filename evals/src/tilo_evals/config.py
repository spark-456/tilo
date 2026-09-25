"""EvalsConfig: the eval harness's own settings (EFF-07; PRD 19.1, 6.6). Local stub for issue #8:
rejects a missing or unreadable file, an unknown/missing key or a bad value, never invents a value."""

import math
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


def read_yaml(path: Path, error: type[Exception]) -> Any:
    """Parse a UTF-8 YAML file; any read, decode, parse or nesting failure becomes `error` naming the path."""
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeDecodeError, yaml.YAMLError, RecursionError, ValueError) as exc:
        raise error(f"{path}: not a readable UTF-8 YAML file: {exc}") from exc


def is_number(v: Any, kind: Any = int, low: float = 0) -> bool:
    """A finite `kind` (never a bool) that converts to float without overflow and is >= low."""
    try:
        return not isinstance(v, bool) and isinstance(v, kind) and math.isfinite(float(v)) and v >= low
    except OverflowError:
        return False


_VALID: dict[str, Callable[[Any], bool]] = {
    "credit_cap": lambda v: isinstance(v, dict) and all(is_number(n) for n in v.values()),
    "deploy_gate_repeats": lambda v: is_number(v, low=1),
    "cost_regression_threshold": lambda v: is_number(v, (int, float)),
    "groups": lambda v: isinstance(v, dict) and all(is_number(n) for n in v.values()),
}


class EvalsConfigError(Exception):
    """Missing or unreadable file, an unknown/missing top-level key, or a bad value."""


@dataclass(frozen=True)
class EvalsConfig:
    credit_cap: dict[str, int]
    deploy_gate_repeats: int
    cost_regression_threshold: float
    groups: dict[str, int]

    @staticmethod
    def load(path: str = "config/evals.yaml") -> "EvalsConfig":
        p = Path(path)
        if not p.is_file():
            raise EvalsConfigError(f"missing eval config: {p}")
        if not isinstance(raw := read_yaml(p, EvalsConfigError), dict):
            raise EvalsConfigError(f"{p}: must be a mapping")
        if odd := set(raw) ^ set(_VALID):
            raise EvalsConfigError(f"{p}: unknown or missing key(s) {sorted(odd)}")
        if bad := [k for k, ok in _VALID.items() if not ok(raw[k])]:
            raise EvalsConfigError(f"{p}: {bad} must be finite: integers >= 0 (repeats >= 1), threshold a number >= 0")
        raw["cost_regression_threshold"] = float(raw["cost_regression_threshold"])
        return EvalsConfig(**raw)  # keys == _VALID == EvalsConfig's field names
