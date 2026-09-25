"""Metering errors and the shared file and number checks (PRD 14.1, 14.5). Refuse, never guess."""

import sys
from pathlib import Path

import yaml


class MeteringConfigError(Exception):
    """A metering or prices file is missing, unreadable or invalid."""


class UnpricedError(Exception):
    """A PriceBook cannot price a profile at a given time."""


def read_yaml(path: str | Path) -> object:
    try:  # ValueError covers UnicodeDecodeError and a null byte in the path
        return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except (OSError, ValueError, yaml.YAMLError, RecursionError) as exc:
        raise MeteringConfigError(f"{path}: cannot read YAML: {exc}") from exc


def number(value: object) -> float:
    """The one check for prices, caps, limits and ratios: int or float (not bool), finite, float-sized."""
    if isinstance(value, int | float) and not isinstance(value, bool) and abs(value) <= sys.float_info.max:
        return float(value)
    raise ValueError(f"expected a finite number within float range, got {value!r:.40}")
