"""tilo_channels.web_push_sender: the production `PushSender` (FR-CHN-17b; PRD 6.2, 16; BQ-CHN17-2).

It is built only on Cloud Run (`K_SERVICE`), only when the VAPID secret NAME in `config/web_push.yaml` resolves to a
mounted value (Cloud Run exposes the secret as the environment variable named by `secret_env_name`) and a contact
subject is set: never in dev or CI, where the fake stays the default. The key is read at send time, handed to
pywebpush and dropped; it is never logged, stored or put in an exception. A push service's refusal becomes
`SubscriptionGone` (404 or 410: the subscription is dead) or `PushUndelivered` (anything else), with no endpoint,
key, payload or vendor text in the message.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Mapping
from typing import Any

from tilo_channels.web_push import PushSubscription, PushUndelivered, SubscriptionGone, VapidRef, load_config

__all__ = ["VapidSender", "production_sender", "secret_env_name"]

ENV_SUBJECT = "TILO_WEBPUSH_VAPID_SUBJECT"  # `mailto:` or https URL: who a push service can contact (not a secret)
_SUBJECT_RE = re.compile(r"^(mailto:[^\s@]{1,64}@[^\s@]{1,190}|https://[^\s]{1,200})\Z")
TIMEOUT_S = 5  # inside the 10 s hand-off bound of `config/web_push.yaml`
TTL_S = 3600  # a notice older than an hour is not worth showing


def secret_env_name(secret_name: str) -> str:
    """`webpush-vapid-private-key` is mounted as `WEBPUSH_VAPID_PRIVATE_KEY`."""
    return VapidRef(secret_name).secret_name.upper().replace("-", "_")


class VapidSender:
    def __init__(
        self,
        *,
        read_key: Callable[[str], str | None],
        subject: str,
        push: Callable[..., Any],
        parse_key: Callable[[str], Any] | None = None,
    ) -> None:
        self._read_key, self._subject, self._push = read_key, subject, push
        self._parse_key = parse_key or _vapid

    def send(self, sub: PushSubscription, payload: bytes, vapid: VapidRef) -> None:
        key = self._read_key(vapid.secret_name)
        if not key:
            raise PushUndelivered("the VAPID key is not available")
        info = {"endpoint": sub.endpoint, "keys": {"p256dh": sub.p256dh, "auth": sub.auth}}
        try:
            self._push(
                subscription_info=info,
                data=payload.decode("utf-8"),
                vapid_private_key=self._parse_key(key),
                vapid_claims={"sub": self._subject},
                ttl=TTL_S,
                timeout=TIMEOUT_S,
            )
        except Exception as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in (404, 410):
                raise SubscriptionGone("subscription expired") from None
            raise PushUndelivered("the push service did not take the notice") from None  # never `exc`: it names urls


def _vapid(key: str) -> Any:
    from py_vapid import Vapid  # noqa: PLC0415  (installed with pywebpush; never imported by dev or tests)

    return Vapid.from_pem(key.encode()) if "-----BEGIN" in key else Vapid.from_string(key)


def production_sender(env: Mapping[str, str] | None = None) -> VapidSender | None:
    """The real sender, or None (use the fake) off Cloud Run, without the mounted key or without a valid subject."""
    env = os.environ if env is None else env
    subject = env.get(ENV_SUBJECT, "")
    secret = load_config().vapid.secret_name
    if "K_SERVICE" not in env or not _SUBJECT_RE.match(subject) or not env.get(secret_env_name(secret)):
        return None
    from pywebpush import webpush  # noqa: PLC0415

    return VapidSender(read_key=lambda name: env.get(secret_env_name(name)), subject=subject, push=webpush)
