"""tilo_channels.web_push_sender: the production `PushSender` (FR-CHN-17c; PRD 6.2, 16; BQ-CHN17-2; SEC-REVIEW-7).

It is built only on Cloud Run (`K_SERVICE`), only when the VAPID secret NAME in `config/web_push.yaml` resolves to a
mounted value (Cloud Run exposes the secret as the environment variable named by `secret_env_name`) and a contact
subject is set: never in dev or CI, where the fake stays the default. The key is read at send time, handed to
pywebpush and dropped; it is never logged, stored or put in an exception.

Per request: the endpoint is checked as an allowed push service host again right before the call, and its resolved
addresses must all be public (a DNS answer is not trusted either); the VAPID claims carry `aud` = the endpoint's
origin, a 5 minute `exp` and `sub` = the Tilo contact (never the person's); the request goes through a session that
reads no proxy or netrc environment and follows no redirect; connect plus read time stays under `send_within_s`.
Payload encryption and the VAPID signature are pywebpush's (RFC 8291, RFC 8292). A push service's refusal becomes
`SubscriptionGone` (404 or 410: the subscription is dead) or `PushUndelivered` (429, 5xx, anything else: retriable),
always with a static message: the library's own text embeds the endpoint URL and its token.
"""

from __future__ import annotations

import ipaddress
import os
import re
import socket
import time
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import urlsplit

from tilo_channels.web_push import (
    PushConfig,
    PushSubscription,
    PushUndelivered,
    SubscriptionGone,
    VapidRef,
    endpoint_ok,
    load_config,
)

__all__ = ["VapidSender", "production_sender", "secret_env_name"]

ENV_SUBJECT = "TILO_WEBPUSH_VAPID_SUBJECT"  # `mailto:` or https URL: Tilo's contact for push services (not a secret)
_SUBJECT_RE = re.compile(r"^(mailto:[^\s@]{1,64}@[^\s@]{1,190}|https://[^\s]{1,200})\Z")
TIMEOUT_S = (3, 4)  # connect, read: 7 s in all, inside the 10 s hand-off bound of `config/web_push.yaml`
TTL_S = 3600  # a notice older than an hour is not worth showing
CLAIM_EXP_S = 300  # the VAPID token is good for five minutes


def secret_env_name(secret_name: str) -> str:
    """`webpush-vapid-private-key` is mounted as `WEBPUSH_VAPID_PRIVATE_KEY`."""
    return VapidRef(secret_name).secret_name.upper().replace("-", "_")


def _public_addresses(host: str) -> bool:
    """True only when `host` resolves and every address is a global (public) one."""
    try:
        found = {info[4][0] for info in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
        return bool(found) and all(ipaddress.ip_address(a).is_global for a in found)
    except (OSError, ValueError):
        return False


class VapidSender:
    def __init__(
        self,
        *,
        read_key: Callable[[str], str | None],
        subject: str,
        push: Callable[..., Any],
        parse_key: Callable[[str], Any] | None = None,
        session: Callable[[], Any] | None = None,
        resolves_public: Callable[[str], bool] = _public_addresses,
        config: PushConfig | None = None,
        now: Callable[[], float] = time.time,
    ) -> None:
        self._read_key, self._subject, self._push = read_key, subject, push
        self._parse_key = parse_key or _vapid
        self._session, self._public, self._now = session, resolves_public, now
        self._cfg = config or load_config()
        if sum(TIMEOUT_S) >= self._cfg.send_within_s:
            raise ValueError("the request timeout must stay under send_within_s")

    def send(self, sub: PushSubscription, payload: bytes, vapid: VapidRef) -> None:
        if not endpoint_ok(sub.endpoint, self._cfg):  # again, right before the request
            raise PushUndelivered("the endpoint is not an allowed push service address")
        parts = urlsplit(sub.endpoint)
        if not self._public(parts.hostname or ""):
            raise PushUndelivered("the endpoint does not resolve to a public address")
        key = self._read_key(vapid.secret_name)
        if not key:
            raise PushUndelivered("the VAPID key is not available")
        claims = {"sub": self._subject, "aud": f"https://{parts.hostname}", "exp": int(self._now()) + CLAIM_EXP_S}
        info = {"endpoint": sub.endpoint, "keys": {"p256dh": sub.p256dh, "auth": sub.auth}}
        extra = {"requests_session": self._session()} if self._session is not None else {}
        try:
            self._push(
                subscription_info=info,
                data=payload.decode("utf-8"),
                vapid_private_key=self._parse_key(key),
                vapid_claims=claims,
                ttl=TTL_S,
                timeout=TIMEOUT_S,
                **extra,
            )
        except Exception as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in (404, 410):
                raise SubscriptionGone("subscription expired") from None
            raise PushUndelivered("the push service did not take the notice") from None  # never `exc`: it names urls


def _vapid(key: str) -> Any:
    from py_vapid import Vapid  # noqa: PLC0415  (installed with pywebpush; never imported by dev or tests)

    return Vapid.from_pem(key.encode()) if "-----BEGIN" in key else Vapid.from_string(key)


def _plain_session() -> Any:
    """A requests session that trusts no environment (proxy, netrc, CA overrides) and follows no redirect."""
    import requests  # noqa: PLC0415

    class _Plain(requests.Session):
        def request(self, method: str, url: str, **kwargs: Any) -> Any:  # type: ignore[override]
            kwargs["allow_redirects"] = False
            return super().request(method, url, **kwargs)

    session = _Plain()
    session.trust_env = False
    session.max_redirects = 0
    return session


def production_sender(env: Mapping[str, str] | None = None) -> VapidSender | None:
    """The real sender, or None (use the fake) off Cloud Run, without the mounted key or without a valid subject."""
    env = os.environ if env is None else env
    subject = env.get(ENV_SUBJECT, "")
    secret = load_config().vapid.secret_name
    if "K_SERVICE" not in env or not _SUBJECT_RE.match(subject) or not env.get(secret_env_name(secret)):
        return None
    from pywebpush import webpush  # noqa: PLC0415

    return VapidSender(
        read_key=lambda name: env.get(secret_env_name(name)), subject=subject, push=webpush, session=_plain_session
    )
