"""What the Gmail and Drive adapters share: declared scopes, the grant check and one HTTP call with bounded
retry (API_FR_CON_04_05.md "Errors, retries and events"). Waits go through the injected `sleep` only.
Nothing here logs; error messages are fixed text plus a status code, never a token, a body or a file name."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any

from ..errors import AdapterError, MissingGrant, SideEffectRefused
from ..outbox import Grant
from ._transport import MAX_ATTEMPTS, ProviderUnavailable, RateLimited, TransportError

if TYPE_CHECKING:
    from ..tokens import TokenBroker
    from ._transport import ApiResponse, ArtifactSource, Transport

MAX_WAIT_S = 60  # at most this much waiting in one call
_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
RESOURCE_ID = re.compile(r"[A-Za-z0-9_-]{1,256}")


def checked_id(value: Any) -> str:
    """A Google resource id safe to put in a URL path or a query; anything else is refused."""
    if not isinstance(value, str) or not RESOURCE_ID.fullmatch(value):
        raise AdapterError("not a valid resource id")
    return value


def side_effect_marker(entry: Mapping[str, Any]) -> str:
    """A pure function of (world_id, idempotency_key): the same on every retry and every instance."""
    seed = f"{entry['world_id']}\x00{entry['idempotency_key']}".encode()
    return hashlib.sha256(seed).hexdigest()[:32]


class GoogleAdapter:
    def __init__(
        self,
        *,
        declaration: Mapping[str, Any],
        broker: TokenBroker,
        transport: Transport,
        artifacts: ArtifactSource,
        owner_of: Callable[[str], str],
        clock: Callable[[], str],
        emit: Callable[[dict[str, Any]], None],
        sleep: Callable[[float], None],
        max_attempts: int = MAX_ATTEMPTS,
    ) -> None:
        self._decl = dict(declaration)
        self._broker, self._transport, self._artifacts = broker, transport, artifacts
        self._owner_of, self._clock, self._emit, self._sleep = owner_of, clock, emit, sleep
        self._max_attempts = max(1, int(max_attempts))

    @property
    def id(self) -> str:
        return str(self._decl["id"])

    def _scopes(self, *capabilities: str) -> list[str]:
        out: list[str] = []
        for capability in capabilities:
            out += [s for s in self._decl["scopes"].get(capability, []) if s not in out]
        return out

    def _batch(self, wanted: int) -> int:
        return max(1, min(int(wanted), int(self._decl.get("limits", {}).get("batch_size", wanted))))

    @staticmethod
    def _check_grant(entry: Mapping[str, Any], grant: Any) -> None:
        """SEC-03: before the broker or the transport is touched."""
        if not isinstance(grant, Grant) or grant.world_id != entry.get("world_id"):
            raise MissingGrant("grant not minted by Outbox.dispatch_due() for this exact send")
        grant.verify(entry["idempotency_key"])

    def _artifact(self, ref: Any, kind: str) -> Mapping[str, Any]:
        try:
            item = self._artifacts.get(str(ref["artifact_id"]), int(ref["version"]))
        except (KeyError, TypeError, ValueError):
            raise SideEffectRefused("the artifact cannot be found") from None
        if item.get("kind") != kind:
            raise SideEffectRefused(f"the artifact is not a {kind}")
        return item

    def _call(
        self,
        user_id: str,
        scopes: list[str],
        method: str,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
        content: bytes | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> ApiResponse:
        """One Google call. 429 and 5xx retried (a POST only on 429: a 5xx may have been carried out, so
        the outbox retries it after its earlier-attempt lookup); a 401 gets one forced refresh."""
        token = self._broker.access_token_for_adapter(user_id, self.id, required_scopes=scopes)
        refreshed, waited = False, 0
        for attempt in range(1, self._max_attempts + 1):
            last = attempt == self._max_attempts
            try:
                response = self._transport.request(
                    method,
                    url,
                    params=params,
                    headers={**(headers or {}), "authorization": f"Bearer {token}"},
                    json=json,
                    content=content,
                )
            except TransportError:
                if method != "GET" or last:
                    raise ProviderUnavailable("Google did not answer") from None
                waited += self._wait(2 ** (attempt - 1), waited)
                continue
            status = int(response.status_code)
            if 200 <= status < 300:
                return response
            if status == 401 and not refreshed:
                refreshed = True
                token = self._broker.access_token_for_adapter(
                    user_id, self.id, required_scopes=scopes, force_refresh=True
                )
                continue
            if status not in _RETRY_STATUSES:
                error = AdapterError(f"Google answered {status}")
                error.status = status
                raise error
            retry_after = _retry_after(response) if status == 429 else None
            wait = retry_after if retry_after is not None else 2 ** (attempt - 1)
            if status == 429:  # PRD 9.5: not a side effect, so authz is null
                data = {"connector": self.id, "retry_after_s": wait}
                self._emit({"type": "connection.rate_limited", "authz": None, "data": data, "user_id": user_id})
            if last or (method != "GET" and status != 429) or waited + wait > MAX_WAIT_S:
                if status == 429:
                    raise RateLimited(wait)
                raise ProviderUnavailable(f"Google answered {status}")
            waited += self._wait(wait, waited)
        raise AdapterError("Google refused the token")  # only reached when the last try was a 401

    def _json(self, user_id: str, scopes: list[str], method: str, url: str, **kw: Any) -> dict[str, Any]:
        try:
            body = self._call(user_id, scopes, method, url, **kw).json()
        except ValueError:
            raise AdapterError("Google answered without JSON") from None
        return body if isinstance(body, dict) else {}

    def _final_on_rejection(self, run: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        """In a side effect, a 400 or 404 can never succeed as written: final, not retried forever."""
        try:
            return run()
        except AdapterError as exc:
            if exc.status in (400, 404):
                raise SideEffectRefused(f"Google refused the side effect ({exc.status})") from None
            raise

    def _wait(self, seconds: int, waited: int) -> int:
        seconds = max(0, min(seconds, MAX_WAIT_S - waited))
        self._sleep(seconds)
        return seconds


def _retry_after(response: ApiResponse) -> int | None:
    value = str(response.headers.get("retry-after", "")).strip()
    return int(value) if value.isascii() and value.isdigit() else None  # an HTTP-date falls back to the backoff
