"""Metering errors (PRD 14.1, 14.5). Refuse, never guess: a config that
cannot be validated, or a price that cannot be found, raises rather than
falling back to an invented value."""

from __future__ import annotations


class MeteringConfigError(Exception):
    """`config/metering.yaml` (or a stub of the same shape) is missing,
    has an unknown key, an out-of-range value, or daily_usd_hard < daily_usd_soft."""


class UnpricedError(Exception):
    """A `PriceBook` cannot quote or price a profile at a given time: the
    profile is unknown, no version is effective yet, the selected version's
    status is "unset", or its price for that profile is null."""
