"""tilo_connectors.errors — the two exceptions the public API raises (tests/API.md)."""

from __future__ import annotations


class OutboxRefused(Exception):
    """Raised by Outbox.enqueue when `entry` fails outbox.schema.json, fails the OB-02
    state/scheduled_at check, or tilo_policy.check_entry says it is not authorised. Also raised
    by Outbox.cancel when the named entry is not currently "scheduled"."""


class MissingGrant(Exception):
    """Raised by a connector adapter's side-effect method when `grant` is not a valid Grant
    minted by Outbox.dispatch_due() for this exact send (SEC-03 runtime check)."""
