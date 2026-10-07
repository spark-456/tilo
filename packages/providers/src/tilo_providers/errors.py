"""tilo_providers.errors — provider-layer error types (PL-02, PRD 6.4).
Every adapter maps its own SDK/HTTP error shape onto these four types, so
the router (P0-06) can react the same way regardless of which adapter
served the call. Messages carry only the server's own error text — never
headers, API keys or other secret material (PRD 16.1 rule 4)."""

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


class OutputTruncatedError(ProviderError):
    """The reply stopped because it hit its output-token cap (Gemini MAX_TOKENS, OpenAI-compatible `length`). Thinking
    tokens count against the cap, so a reply can be empty. Not retried or repaired: the same cap burns the same
    tokens. Counts are None when the provider reported no usage (0 when usage is present but the field is missing);
    the message names the counts and never the reply text (it can carry personal data)."""

    def __init__(self, message: str, *, output_tokens: int | None = None, thinking_tokens: int | None = None) -> None:
        super().__init__(message)
        self.output_tokens = output_tokens
        self.thinking_tokens = thinking_tokens


def truncated_message(output_tokens: int | None, thinking_tokens: int | None) -> str:
    """The OutputTruncatedError text: the known counts only, never any reply text."""
    known = [f"{n} {what}" for n, what in ((output_tokens, "output"), (thinking_tokens, "thinking")) if n is not None]
    spent = f" ({', '.join(known)} tokens used)" if known else ""
    return f"PL-02: the reply hit its max_output_tokens cap{spent}; raise the role's max_output_tokens"


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
