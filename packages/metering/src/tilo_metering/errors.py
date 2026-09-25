"""Metering errors (PRD 14.1, 14.5). Refuse, never guess."""

from __future__ import annotations


class MeteringConfigError(Exception):
    """A metering config is missing, invalid, or has daily_usd_hard < daily_usd_soft."""


class UnpricedError(Exception):
    """A PriceBook cannot quote or price a profile at a given time."""
