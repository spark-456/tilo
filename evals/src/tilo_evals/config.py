"""EvalsConfig: the eval harness's own settings (EFF-07; PRD 19.1, 6.6). Local stub for issue #8."""

import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class CappedError(Exception):
    def __init__(self, msg: str) -> None:  # capped at 500 characters, so no input builds a huge message
        super().__init__(msg if len(msg) <= 500 else msg[:485] + " ...[truncated]")


class _NoAliasLoader(yaml.SafeLoader):  # no aliases: ~300 bytes of chained ones expand to 10**7 nodes
    def compose_node(self, parent: Any, index: Any) -> Any:
        if self.check_event(yaml.AliasEvent):
            raise yaml.YAMLError("YAML aliases are not allowed")
        return super().compose_node(parent, index)


def read_yaml(path: Path, error: type[Exception]) -> Any:
    """Parse a UTF-8 YAML file; any read, decode, parse, alias or nesting failure becomes `error` naming the path."""
    try:
        return yaml.load(path.read_text(encoding="utf-8"), Loader=_NoAliasLoader) or {}
    except (OSError, UnicodeDecodeError, yaml.YAMLError, RecursionError, ValueError) as exc:
        raise error(f"{path}: not a readable UTF-8 YAML file: {exc}") from exc


def is_number(v: Any, kind: Any = int, low: float = 0) -> bool:  # never a bool; a finite float, no overflow
    return not isinstance(v, bool) and isinstance(v, kind) and low <= v <= sys.float_info.max


_VALID: dict[str, Callable[[Any], bool]] = {
    "credit_cap": lambda v: isinstance(v, dict) and all(is_number(n) for n in v.values()),
    "deploy_gate_repeats": lambda v: is_number(v, low=1),
    "cost_regression_threshold": lambda v: is_number(v, (int, float)),
    "groups": lambda v: isinstance(v, dict) and all(is_number(n) for n in v.values()),
}


class EvalsConfigError(CappedError):
    """Missing or unreadable file, an unknown/missing top-level key, or a bad value."""


@dataclass(frozen=True)
class EvalsConfig:
    credit_cap: dict[str, int]
    deploy_gate_repeats: int
    cost_regression_threshold: float
    groups: dict[str, int]

    @staticmethod
    def load(path: str = "config/evals.yaml") -> "EvalsConfig":
        if not isinstance(raw := read_yaml(Path(path), EvalsConfigError), dict):
            raise EvalsConfigError(f"{path}: must be a mapping")
        if odd := set(raw) ^ set(_VALID):
            raise EvalsConfigError(f"{path}: unknown or missing key(s) {sorted(odd, key=str)}")
        if bad := [k for k, ok in _VALID.items() if not ok(raw[k])]:
            raise EvalsConfigError(f"{path}: {bad} must be finite: ints >= 0 (repeats >= 1), threshold a number >= 0")
        raw["cost_regression_threshold"] = float(raw["cost_regression_threshold"])
        return EvalsConfig(**raw)  # keys == _VALID == EvalsConfig's field names
