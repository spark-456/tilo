"""tilo_connectors.errors — the exceptions the outbox and the adapters raise (tests/API.md, API_FR_CON_04_05.md)."""

from __future__ import annotations


class OutboxRefused(Exception):
    """Enqueue/cancel refusals — tests/API.md "Errors"."""


class MissingGrant(Exception):
    """SEC-03: no valid Grant for this send — tests/API.md "Errors"."""


class AdapterError(Exception):
    """Base of the Gmail and Drive adapter errors (re-exported by tilo_connectors.adapters).
    Its message never holds a token, a body or a full file name."""

    status: int | None = None  # the HTTP status Google answered, when there was one


class SideEffectRefused(AdapterError):
    """Final: the side effect can never succeed as written. The outbox marks the entry failed."""
