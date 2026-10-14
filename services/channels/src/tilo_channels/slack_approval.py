"""PREP-SLACK-2 inert DM approval adapter; no routes, factory or live transport.

Only Outbox.dispatch_due may call this adapter. Production activation still needs
Slack app setup, a recipient binding and a durable atomic dedupe implementation.
Cards open the existing signed-link sign-in flow; Slack never answers a card.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Mapping
from typing import Any

from tilo_connectors.adapters.slack import Artifacts
from tilo_connectors.errors import MissingGrant, PossiblySent, SideEffectRefused
from tilo_connectors.outbox import Grant

from tilo_channels.card_model import card_to_neutral
from tilo_channels.dedupe import DedupeStore
from tilo_channels.links import IssuedLink, LinkService
from tilo_channels.quiet_hours import NotificationGate

FLAG = "TILO_SLACK_CHANNEL"


def render_approval(card: Mapping[str, Any], link: IssuedLink) -> str:
    """Plain text only: no interactive answers, mentions, unfurls or Slack markup."""
    model = card_to_neutral(card, link)
    text = "\n".join((*model.lines, model.open_url))
    if len(text) > 4000:
        raise ValueError("Slack approval card is too long")
    return text


class SlackApprovalAdapter:
    def __init__(
        self,
        *,
        client: Callable[[dict[str, Any]], dict[str, Any]],
        artifacts: Artifacts,
        projection: Callable[[Mapping[str, Any]], tuple[Mapping[str, Any], IssuedLink]],
        links: LinkService,
        recipient: Callable[[str, str], str],
        notifications: NotificationGate,
        dedupe: DedupeStore,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        # Explicit injection only; never reads credentials or builds a transport.
        self._enabled = (environ or {}).get(FLAG) == "1"
        self._client, self._artifacts, self._projection = client, artifacts, projection
        self._links, self._recipient = links, recipient
        self._notifications, self._dedupe = notifications, dedupe

    @property
    def id(self) -> str:
        return "slack"

    def execute_side_effect(self, entry: Mapping[str, Any], grant: Grant) -> dict[str, Any]:
        if not isinstance(grant, Grant) or grant.world_id != entry.get("world_id"):
            raise MissingGrant("grant not minted by Outbox.dispatch_due()")
        grant.verify(entry["idempotency_key"])
        if not self._enabled:
            raise SideEffectRefused("Slack approval channel is disabled")
        if (
            entry.get("connector") != "slack"
            or entry.get("action_type") != "post_message"
            or entry.get("risk_tier") != "T3"
            or entry.get("authz", {}).get("by") != "person"
            or entry.get("recipients")
            or entry.get("attachments")
        ):
            raise SideEffectRefused("Slack delivery needs the person's T3 approval")
        destination = entry.get("destination")
        if not isinstance(destination, str) or re.fullmatch(r"D[A-Z0-9]{2,32}", destination) is None:
            raise SideEffectRefused("A bound Slack DM is required")
        try:
            card, link = self._projection(entry)
            if card.get("world_id") != entry["world_id"]:
                raise ValueError("wrong world")
            if self._links.peek(link.token) != (card["id"], "open", None, link.user_id):
                raise ValueError("wrong link")
            if self._recipient(entry["world_id"], link.user_id) != destination:
                raise ValueError("wrong recipient")
            text = render_approval(card, link)
            raw = self._artifacts.read(entry["world_id"], entry["item"])
            head = self._artifacts.head(entry["world_id"], entry["item"])
            if (
                head.get("world_id") != entry["world_id"]
                or head.get("media_type") != "text/plain"
                or raw != text.encode("utf-8")
                or head.get("content_sha256") != hashlib.sha256(raw).hexdigest()
            ):
                raise ValueError("changed approval artifact")
        except Exception:
            raise SideEffectRefused("Slack approval projection is not intact") from None
        if not self._notifications.should_notify(link.user_id, card):
            raise SideEffectRefused("Slack notification held by existing notification policy")
        key = f"slack-approval:{entry['world_id']}:{entry['id']}:{destination}"
        # Keep reservations even on ambiguous or refused responses. No automatic resend.
        if not self._dedupe.claim(key, 86400):
            raise PossiblySent("An earlier Slack approval DM may have succeeded")
        try:
            result = self._client(
                {
                    "channel": destination,
                    "text": text,
                    "client_msg_id": entry["id"],
                    "parse": "none",
                    "mrkdwn": False,
                    "unfurl_links": False,
                    "unfurl_media": False,
                }
            )
            if result.get("ok") is not True or result.get("channel") != destination:
                raise ValueError("unconfirmed DM")
        except Exception:
            raise PossiblySent("Slack approval delivery is unconfirmed; check before resending") from None
        return {"channel": destination, "ts": result.get("ts")}
