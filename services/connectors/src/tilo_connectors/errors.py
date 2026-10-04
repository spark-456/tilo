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


class RateLimited(AdapterError):
    """429 still answered after the attempts, or a Retry-After over 60 s. The outbox waits it out across ticks."""

    def __init__(self, retry_after_s: int) -> None:
        super().__init__(f"rate limited; retry after {retry_after_s} s")
        self.retry_after_s = retry_after_s


class ProviderUnavailable(AdapterError):
    """5xx or a TransportError, still after the attempts: ambiguous, the provider may have acted."""
