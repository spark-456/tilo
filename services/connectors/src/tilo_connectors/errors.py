"""tilo_connectors.errors — the two exceptions the public API raises (tests/API.md)."""

from __future__ import annotations


class OutboxRefused(Exception):
    """Enqueue/cancel refusals — tests/API.md "Errors"."""


class MissingGrant(Exception):
    """SEC-03: no valid Grant for this send — tests/API.md "Errors"."""
