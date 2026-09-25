"""EvalsConfig: the eval harness's own settings (EFF-07; PRD 19.1, 6.6 "Lean
evals"). A local stub for contract-change issue #8 -- config/evals.yaml is
not yet a contracts/ schema, so this module validates it by hand and rejects
unknown keys and out-of-range values, the same discipline
tilo_metering.MeteringConfig applies to config/metering.yaml (issue #7).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

PASS_KINDS: tuple[str, ...] = ("smoke", "full", "gate")
GROUPS: tuple[str, ...] = (
    "E-PLAN",
    "E-RES",
    "E-DOC",
    "E-MAIL",
    "E-CHN",
    "E-ROUTE",
    "E-HAND",
    "E-RED",
)
_REQUIRED_KEYS = {"credit_cap", "deploy_gate_repeats", "cost_regression_threshold", "groups"}


class EvalsConfigError(Exception):
    """Raised when config/evals.yaml is missing, has an unknown key, is
    missing a required key, or holds an out-of-range value."""


@dataclass(frozen=True)
class EvalsConfig:
    credit_cap: dict[str, int]
    deploy_gate_repeats: int
    cost_regression_threshold: float
    groups: dict[str, int]

    @staticmethod
    def load(path: str = "config/evals.yaml") -> EvalsConfig:
        config_path = Path(path)
        if not config_path.is_file():
            raise EvalsConfigError(f"missing eval config: {config_path}")
        raw: Any = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise EvalsConfigError(f"{config_path}: must be a mapping")

        unknown = set(raw) - _REQUIRED_KEYS
        if unknown:
            raise EvalsConfigError(f"{config_path}: unknown key(s) {sorted(unknown)}")
        missing = _REQUIRED_KEYS - set(raw)
        if missing:
            raise EvalsConfigError(f"{config_path}: missing key(s) {sorted(missing)}")

        credit_cap = raw["credit_cap"]
        if not isinstance(credit_cap, dict) or set(credit_cap) != set(PASS_KINDS):
            raise EvalsConfigError(f"{config_path}: credit_cap must have exactly {PASS_KINDS}")
        for kind, value in credit_cap.items():
            if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
                raise EvalsConfigError(f"{config_path}: credit_cap.{kind} must be a positive number")

        deploy_gate_repeats = raw["deploy_gate_repeats"]
        if not isinstance(deploy_gate_repeats, int) or isinstance(deploy_gate_repeats, bool) or deploy_gate_repeats < 1:
            raise EvalsConfigError(f"{config_path}: deploy_gate_repeats must be a positive integer")

        threshold = raw["cost_regression_threshold"]
        if not isinstance(threshold, (int, float)) or isinstance(threshold, bool) or not (0 < threshold < 1):
            raise EvalsConfigError(f"{config_path}: cost_regression_threshold must be between 0 and 1")

        groups = raw["groups"]
        if not isinstance(groups, dict) or set(groups) != set(GROUPS):
            raise EvalsConfigError(f"{config_path}: groups must have exactly {GROUPS}")
        for group, count in groups.items():
            if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                raise EvalsConfigError(f"{config_path}: groups.{group} must be a non-negative integer")

        return EvalsConfig(
            credit_cap=dict(credit_cap),
            deploy_gate_repeats=deploy_gate_repeats,
            cost_regression_threshold=float(threshold),
            groups=dict(groups),
        )
