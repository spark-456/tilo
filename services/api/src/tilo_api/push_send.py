"""The API half of sending a web push (FR-CHN-17f; PRD 6.2, 16; SEC-03). The outbox lives here, so the one thing that
runs a `send_push` entry is `PushRpcAdapter.execute_side_effect`, which only `Outbox.dispatch_due()` calls, with its
grant. The VAPID secret is tilo-channels' alone, so the adapter hands the already authorised notice, with the owner's
devices, to `POST /internal/push/send` over an OIDC ID token (`ChannelsPushRpc`, `TILO_CHANNELS_URL`, https `*.run.app`
only, no redirect, 9 s). The notice text is fixed by code from the card's kind and carries no content; the tap path
is built from the card id. A device the push service says is gone is removed; every device is tried; the entry is
retried only when none took it, and refused for good when the owner has no device.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import httpx
from tilo_channels.web_push import (
    PushRefused,
    PushSubscription,
    PushUndelivered,
    path_for,
)

from tilo_api.meeting_host_rpc import _URL, metadata_id_token

TIMEOUT_S = 9.0  # inside the 10 s hand-off bound of config/web_push.yaml
TITLES = {  # fixed text by code: a lock screen shows no content of a card, mail or model
    "gate": "A send is waiting for your approval",
    "blocked": "Something is blocked and needs you",
}
DEFAULT_TITLE = "Something is waiting for you"
_KEY_RE = re.compile(r"^push:(u_[0-9A-Za-z_]{1,48}):([a-z_]{1,32})-([A-Za-z0-9_-]{1,64})\Z")


class PushRpcError(Exception):
    """tilo-channels did not answer usefully (static): the outbox retries within its bounds."""


class ChannelsPushRpc:
    def __init__(
        self,
        base_url: str,
        *,
        token_for: Callable[[str], str] = metadata_id_token,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if _URL.fullmatch(base_url) is None:
            raise ValueError("TILO_CHANNELS_URL must be an https Cloud Run address")
        self._base, self._token_for, self._transport = base_url, token_for, transport

    def __repr__(self) -> str:
        return "ChannelsPushRpc()"

    def deliver(self, devices: Sequence[PushSubscription], notice: Mapping[str, str]) -> tuple[int, list[int]]:
        """(devices that took it, positions the push service said are gone)."""
        body = {
            "devices": [{"endpoint": d.endpoint, "keys": {"p256dh": d.p256dh, "auth": d.auth}} for d in devices],
            **notice,
        }
        try:
            token = self._token_for(self._base)
            with httpx.Client(transport=self._transport, timeout=TIMEOUT_S, follow_redirects=False) as client:
                res = client.post(
                    f"{self._base}/internal/push/send", json=body, headers={"Authorization": f"Bearer {token}"}
                )
            data = res.json() if res.status_code == 200 else None
        except Exception:  # noqa: BLE001 - never the library's text: it can hold a url
            raise PushRpcError("tilo-channels was not reachable") from None
        if (
            not isinstance(data, dict)
            or type(data.get("delivered")) is not int
            or not isinstance(data.get("gone"), list)
        ):
            raise PushRpcError("tilo-channels did not accept the notice")
        gone = [i for i in data["gone"] if type(i) is int and 0 <= i < len(devices)]
        return data["delivered"], gone


class PushRpcAdapter:
    """The outbox adapter for `send_push` in tilo-api. `final_error` is the outbox's `SideEffectRefused`."""

    def __init__(self, *, subscriptions: Any, rpc: ChannelsPushRpc, final_error: type[Exception] = PushRefused) -> None:
        self._subs, self._rpc, self._final = subscriptions, rpc, final_error

    def execute_side_effect(self, entry: Mapping[str, Any], grant: Any) -> None:
        grant.verify(entry["idempotency_key"])  # raises unless the outbox minted it for exactly this entry
        found = _KEY_RE.match(str(entry["idempotency_key"]))
        if entry.get("action_type") != "send_push" or found is None:
            raise self._final("not a push entry")
        owner, kind, card = found.groups()
        devices = self._subs.for_user(owner)
        if not devices:
            raise self._final("no device to send to")
        notice = {"title": TITLES.get(kind, DEFAULT_TITLE), "body": "", "tag": f"{kind}-{card}", "path": path_for(card)}
        try:
            delivered, gone = self._rpc.deliver(devices, notice)
        except PushRpcError:
            raise PushUndelivered("tilo-channels did not take the notice") from None
        for position in gone:
            self._subs.remove(owner, devices[position].endpoint)
        if delivered == 0:
            if gone and len(gone) == len(devices):
                raise self._final("every device is gone")
            raise PushUndelivered("no device took the notice")
