"""PREP-SLACK-1: injected Slack Web API transport, no startup/factory wiring.

Transport binds method names to https://slack.com/api/ and uses bearer headers.
Production activation requires a durable CAS ledger; this in-memory ledger is for mocks.
"""

from __future__ import annotations

import hashlib
import re
import threading
from collections.abc import Callable, Mapping
from typing import Any, Protocol

from tilo_redact import redact

from ..errors import MissingGrant, PossiblySent, SideEffectRefused
from ..outbox import Grant
from ..slack import NEEDS_APP, load_slack_declaration


class Tokens(Protocol):
    def access_token_for_adapter(
        self, user_id: str, connector: str, *, required_scopes: Any, not_before: str | None = None
    ) -> str: ...


class Artifacts(Protocol):
    def head(self, world_id: str, ref: Mapping[str, Any]) -> Mapping[str, Any]: ...

    def read(self, world_id: str, ref: Mapping[str, Any]) -> bytes: ...


class Ledger(Protocol):
    def reserve(self, key: str) -> bool: ...


class InMemorySlackLedger:
    """At-most-once mock ledger: reservations survive ambiguous responses within this instance."""

    def __init__(self) -> None:
        self._keys: set[str] = set()
        self._lock = threading.Lock()

    def reserve(self, key: str) -> bool:
        with self._lock:
            if key in self._keys:
                return False
            self._keys.add(key)
            return True


class SlackAdapter:
    def __init__(
        self,
        *,
        request: Callable[[str, str, dict[str, Any]], dict[str, Any]],
        tokens: Tokens,
        artifacts: Artifacts,
        owner_of: Callable[[str], str],
        ledger: Ledger,
        enabled: bool = False,
    ) -> None:
        self._request, self._tokens, self._artifacts = request, tokens, artifacts
        self._owner_of, self._ledger, self._enabled = owner_of, ledger, enabled
        self._declaration = load_slack_declaration()

    @property
    def id(self) -> str:
        return "slack"

    @property
    def declaration(self) -> dict[str, Any]:
        return load_slack_declaration()

    def list_channels(self, user_id: str, *, cursor: str = "") -> dict[str, Any]:
        if not self._enabled:
            raise SideEffectRefused(NEEDS_APP)
        token = self._tokens.access_token_for_adapter(user_id, "slack", required_scopes=["channels:read"])
        result = self._request(
            token,
            "conversations.list",
            {
                "types": "public_channel",
                "exclude_archived": True,
                "limit": 100,
                "cursor": cursor,
            },
        )
        if result.get("ok") is not True:
            raise SideEffectRefused("Slack could not list channels")
        return result

    def execute_side_effect(self, entry: Mapping[str, Any], grant: Grant) -> dict[str, Any]:
        if not isinstance(grant, Grant) or grant.world_id != entry.get("world_id"):
            raise MissingGrant("grant not minted by Outbox.dispatch_due()")
        grant.verify(entry["idempotency_key"])
        if not self._enabled:
            raise SideEffectRefused(NEEDS_APP)
        if (
            entry.get("connector") != "slack"
            or entry.get("action_type") != "post_message"
            or entry.get("risk_tier") != "T3"
            or entry.get("authz", {}).get("by") != "person"
            or entry.get("recipients")
            or entry.get("attachments")
        ):
            raise SideEffectRefused("Slack posting needs the person's T3 approval")
        destination = entry.get("destination")
        if not isinstance(destination, str) or re.fullmatch(r"C[A-Z0-9]{2,32}", destination) is None:
            raise SideEffectRefused("Pick a public Slack channel and invite the bot")
        head = self._artifacts.head(entry["world_id"], entry["item"])
        raw = self._artifacts.read(entry["world_id"], entry["item"])
        if (
            head.get("world_id") != entry["world_id"]
            or head.get("media_type") != "text/plain"
            or not 0 < len(raw) <= 16000
            or hashlib.sha256(raw).hexdigest() != head.get("content_sha256")
        ):
            raise SideEffectRefused("The approved Slack text is not intact")
        try:
            text = redact(raw.decode("utf-8"))
        except UnicodeDecodeError:
            raise SideEffectRefused("Slack text must be UTF-8") from None
        if len(text) > 4000:
            raise SideEffectRefused("Slack text is too long")
        token = self._tokens.access_token_for_adapter(
            self._owner_of(entry["world_id"]),
            "slack",
            required_scopes=["chat:write"],
            not_before=entry["authz"]["at"],
        )
        if not self._ledger.reserve(entry["id"]):
            raise PossiblySent("An earlier Slack post may have succeeded; check the channel")
        try:
            result = self._request(
                token,
                "chat.postMessage",
                {
                    "channel": destination,
                    "text": text,
                    "client_msg_id": entry["id"],
                    "parse": "none",
                    "mrkdwn": False,
                    "unfurl_links": False,
                    "unfurl_media": False,
                },
            )
        except Exception:
            raise PossiblySent("Slack may have received this post; check the channel before sending again") from None
        if result.get("ok") is not True:
            raise SideEffectRefused("Slack refused the post; check the bot's channel membership")
        return {"channel": result.get("channel"), "ts": result.get("ts")}


class MockSlackAdapter(SlackAdapter):
    """Use the identical guarded implementation with an injected recorded response transport."""
