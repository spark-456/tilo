"""Metering errors (PRD 14.1, 14.5). Refuse, never guess."""

from __future__ import annotations

from pathlib import Path

import yaml


class MeteringConfigError(Exception):
    """A metering config is missing, invalid, or has daily_usd_hard < daily_usd_soft."""


class UnpricedError(Exception):
    """A PriceBook cannot quote or price a profile at a given time."""


def read_yaml(path: str | Path) -> object:
    """Parse a YAML file; unreadable or malformed files raise MeteringConfigError."""
    try:
        return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise MeteringConfigError(f"{path}: cannot read YAML: {exc}") from exc
