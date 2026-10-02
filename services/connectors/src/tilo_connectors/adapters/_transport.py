"""The HTTP seam the Gmail and Drive adapters run on, and their error types (FR-CON-04, FR-CON-05).

The adapters never open a socket themselves: a `Transport` is injected. In dev and CI it is a fake or
a `tilo_connectors.recording.ReplayTransport` (EFF-01); a live transport is only wired under `LIVE=1`.
Error messages are fixed text plus a status code: never a token, a body or a file name.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from ..errors import AdapterError as AdapterError
from ..errors import SideEffectRefused as SideEffectRefused

MAX_ATTEMPTS = 3  # requests per HTTP call, the first one included


class TransportError(Exception):
    """Network failure or timeout: the request may or may not have reached Google."""


class ApiResponse(Protocol):
    status_code: int
    headers: Mapping[str, str]  # header names lower-case
    content: bytes

    def json(self) -> Any: ...


class Transport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        json: Any = None,
        content: bytes | None = None,
    ) -> ApiResponse: ...


class RateLimited(AdapterError):
    """429 still answered after the attempts, or a Retry-After over 60 s."""

    def __init__(self, retry_after_s: int) -> None:
        super().__init__(f"rate limited; retry after {retry_after_s} s")
        self.retry_after_s = retry_after_s


class ProviderUnavailable(AdapterError):
    """5xx or a TransportError, still after the attempts."""


class NotPicked(AdapterError):
    """A Drive file outside the readable set."""


class FileTooLarge(AdapterError):
    """A Drive download over the limit."""


class ArtifactSource(Protocol):  # P7's artifact store
    def get(self, artifact_id: str, version: int) -> Mapping[str, Any]: ...
