"""tilo_providers.errors — provider-layer error types (PL-02, PRD 6.4).

Every adapter (google, openai_compat) maps its own SDK/HTTP error shape onto
these four types, so the router (P0-06) and business code can react the same
way regardless of which adapter served the call: retry, escalate to a
fallback profile, or stop. Messages carry only the server's own error text —
never headers, API keys or other secret material (PRD 16.1 rule 4).

`map_transport_error` is the one mapping shared by every adapter's HTTP
transport (both `google-genai` and `openai_compat_adapter` send requests
over `httpx`): a timeout or connection failure always becomes the same
`RetryableError`, so the two adapters cannot drift apart on this case."""

from __future__ import annotations

import httpx


class ProviderError(Exception):
    """Base for every error a ModelProvider adapter raises."""


class QuotaError(ProviderError):
    """Rate limit or quota exceeded (HTTP 429). The router may fall back."""


class RetryableError(ProviderError):
    """Transient server-side failure (5xx, timeout, connection error). Safe to retry."""


class RequestError(ProviderError):
    """The request itself was rejected (other 4xx). Retrying unchanged will not help."""


class SafetyError(ProviderError):
    """The model or platform blocked the response on safety grounds (PRD 10.4)."""


def map_http_status(status_code: int, message: str) -> ProviderError:
    """Maps an HTTP-ish status code to a ProviderError subclass (PL-02
    conformance: 429 -> QuotaError, 5xx -> RetryableError, other 4xx ->
    RequestError). Shared by every adapter so the mapping is identical."""
    if status_code == 429:
        return QuotaError(message)
    if status_code >= 500:
        return RetryableError(message)
    return RequestError(message)


def map_transport_error(error: Exception) -> ProviderError | None:
    """Maps an `httpx` transport-level failure to `RetryableError` (timeout
    -> 504, any other connection/HTTP-framing error -> 503); `None` if
    `error` is not an `httpx.HTTPError` at all, so a caller can fall through
    to its own SDK-specific mapping."""
    if isinstance(error, httpx.TimeoutException):
        return map_http_status(504, "PL-02: request to the provider endpoint timed out")
    if isinstance(error, httpx.HTTPError):
        return map_http_status(503, "PL-02: request to the provider endpoint failed")
    return None
