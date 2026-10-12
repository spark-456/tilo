"""tilo_channels.web_push: web push notifications (FR-CHN-17; PRD 6.2, 11, 16, SEC-03; FR-SET-02, FR-HIL-13).

A subscription is stored per signed-in person (`SubscriptionStore`); a notice is a policy-decided, outbox-queued
`send_push` entry (`PushNotifier`, the same L3 flow as the daily digest) that only the outbox's own grant can send
(`WebPushAdapter`). Notification settings and quiet hours are read first and never hide a gate: a gate that is not
pushed still waits in Needs you (`PushResult.in_app` is always true). The VAPID key is a Secret Manager secret
named in `config/web_push.yaml`; this module holds the name only, makes no network call and logs nothing. The real
sender (a port, `PushSender`) is wired by the service; dev and CI use a fake. `tilo_connectors` is never imported
(BQ-158): the adapter is duck-typed to the outbox's `execute_side_effect(entry, grant)`.
"""

from __future__ import annotations

import copy
import datetime as dt
import json
import re
import threading
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol
from urllib.parse import urlsplit

import tilo_policy
import yaml
from tilo_policy.schemas import conforms, event_ok

from tilo_channels.autopilot_gate import gate_id_for
from tilo_channels.autopilot_state import Outbox, enqueue_digest, timestamp, ulid
from tilo_channels.digest import DigestArtifactPort, DigestPolicyPort, allowed_l3_decision
from tilo_channels.quiet_hours import PreferenceReader, is_quiet_hours, should_notify

__all__ = [
    "ACTION_TYPE",
    "CONFIG_PATH",
    "CONNECTOR",
    "PushConfig",
    "PushNotifier",
    "PushResult",
    "PushSender",
    "PushSubscription",
    "PushUndelivered",
    "SubscriptionGone",
    "SubscriptionRefused",
    "SubscriptionStore",
    "VapidRef",
    "WebPushAdapter",
    "load_config",
]

ACTION_TYPE = "send_push"
CONNECTOR = "web_push"  # an outbox adapter name; it is not in config/connectors.yaml (nothing for a person to connect)
CONFIG_PATH = Path(__file__).resolve().parents[4] / "config" / "web_push.yaml"
_SECRET_NAME_RE = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+){1,7}\Z")
_B64URL_RE = re.compile(r"^[A-Za-z0-9_-]+={0,2}\Z")
_ITEM_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}\Z")
_KIND_RE = re.compile(r"^[a-z][a-z_]{0,31}\Z")
_ROW_BY_KIND = {"gate": "decisions", "blocked": "decisions", "spend": "spend", "finished": "finished"}  # FR-SET-02 rows
_ROW_BY_KIND |= {"digest": "digest", "weekly": "weekly"}


class SubscriptionRefused(ValueError):
    """The subscription (untrusted browser input) or its owner is not acceptable; nothing was stored."""


class SubscriptionGone(Exception):
    """The push service says this subscription no longer exists (HTTP 404 or 410): drop it."""


class PushUndelivered(RuntimeError):
    """No live subscription took the push; the outbox retries within its bounds, then a person is told."""


@dataclass(frozen=True)
class VapidRef:
    """The NAME of the Secret Manager secret holding the VAPID private key; never the key."""

    secret_name: str

    def __post_init__(self) -> None:
        if (
            type(self.secret_name) is not str
            or len(self.secret_name) > 64
            or not _SECRET_NAME_RE.match(self.secret_name)
        ):
            raise ValueError("a VAPID key is referenced by its secret name (lower-case words joined by hyphens)")


@dataclass(frozen=True)
class PushConfig:
    vapid: VapidRef
    max_subscriptions: int
    max_endpoint_length: int
    allowed_hosts: tuple[str, ...]
    send_within_s: int
    title_max: int
    body_max: int


def load_config(path: Path = CONFIG_PATH) -> PushConfig:
    """`config/web_push.yaml`; anything malformed raises ValueError (fail closed: no push without a valid config)."""
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ValueError(f"web push config unreadable: {type(exc).__name__}") from exc
    if not isinstance(doc, dict):
        raise ValueError("web push config must be a mapping")
    names = ("max_subscriptions_per_person", "max_endpoint_length", "send_within_s", "title_max", "body_max")
    raw: list[Any] = [doc.get(k) for k in names]
    hosts = doc.get("allowed_endpoint_hosts")
    if not all(type(v) is int and v >= 1 for v in raw):
        raise ValueError("web push config limits must be positive integers")
    if not isinstance(hosts, list) or not hosts or not all(type(h) is str and "." in h for h in hosts):
        raise ValueError("allowed_endpoint_hosts must list push service host names")
    subs, endpoint_len, within, title_max, body_max = (int(v) for v in raw)
    vapid = VapidRef(str(doc.get("vapid_private_key_secret")))
    return PushConfig(vapid, subs, endpoint_len, tuple(h.lower() for h in hosts), within, title_max, body_max)


@dataclass(frozen=True)
class PushSubscription:
    """One browser's subscription. The endpoint and keys are capabilities: never in a repr, log or event."""

    endpoint: str = field(repr=False)
    p256dh: str = field(repr=False)
    auth: str = field(repr=False)


class PushSender(Protocol):  # the real one signs with the VAPID secret named by `vapid`; tests use a fake
    def send(self, sub: PushSubscription, payload: bytes, vapid: VapidRef) -> None: ...


def _valid_user(user_id: Any) -> bool:
    return type(user_id) is str and conforms("common.schema.json#/$defs/user_id", user_id)


def _endpoint_ok(endpoint: Any, cfg: PushConfig) -> bool:
    if type(endpoint) is not str or not 12 <= len(endpoint) <= cfg.max_endpoint_length:
        return False
    if not endpoint.isascii() or not endpoint.isprintable() or any(c in endpoint for c in " \\"):
        return False
    try:
        parts = urlsplit(endpoint)
        host, port = (parts.hostname or "").lower(), parts.port
    except ValueError:
        return False
    if parts.scheme != "https" or parts.username is not None or parts.password is not None or parts.fragment:
        return False
    if port not in (None, 443) or not host or parts.netloc.lower() not in (host, f"{host}:443"):
        return False
    return any(host == h or host.endswith("." + h) for h in cfg.allowed_hosts)


class SubscriptionStore:
    """Subscriptions per person, in memory (the durable store is a port the service wires). Capped, validated."""

    def __init__(self, config: PushConfig | None = None) -> None:
        self._cfg = config or load_config()
        self._by_user: dict[str, dict[str, PushSubscription]] = {}
        self._lock = threading.Lock()

    def add(self, user_id: str, raw: Mapping[str, Any]) -> PushSubscription:
        """Stores `raw` (a PushSubscription.toJSON() body) for the signed-in `user_id`; the same endpoint replaces."""
        if not _valid_user(user_id) or not isinstance(raw, Mapping):
            raise SubscriptionRefused("not a signed-in person's subscription")
        keys = raw.get("keys")
        p256dh, auth = (keys.get("p256dh"), keys.get("auth")) if isinstance(keys, Mapping) else (None, None)
        if not _endpoint_ok(raw.get("endpoint"), self._cfg):
            raise SubscriptionRefused("endpoint must be an https push service address")
        for value, lo, hi in ((p256dh, 80, 100), (auth, 20, 32)):
            if type(value) is not str or not lo <= len(value) <= hi or not _B64URL_RE.match(value):
                raise SubscriptionRefused("subscription keys are malformed")
        sub = PushSubscription(raw["endpoint"], p256dh, auth)  # type: ignore[arg-type]
        with self._lock:
            mine = self._by_user.setdefault(user_id, {})
            if sub.endpoint not in mine and len(mine) >= self._cfg.max_subscriptions:
                raise SubscriptionRefused("this person already has the most devices allowed")
            mine[sub.endpoint] = sub
        return sub

    def remove(self, user_id: str, endpoint: str) -> bool:
        with self._lock:
            return self._by_user.get(user_id, {}).pop(endpoint, None) is not None

    def for_user(self, user_id: str) -> tuple[PushSubscription, ...]:
        with self._lock:
            return tuple(self._by_user.get(user_id, {}).values())


class WebPushAdapter:
    """The outbox adapter for `send_push`: runs only when `Outbox.dispatch_due()` hands it its grant (SEC-03)."""

    def __init__(
        self,
        *,
        subscriptions: SubscriptionStore,
        sender: PushSender,
        artifacts: DigestArtifactPort,
        owner: str,
        vapid: VapidRef,
    ) -> None:
        self._subs, self._sender, self._artifacts, self._owner, self._vapid = (
            subscriptions,
            sender,
            artifacts,
            owner,
            vapid,
        )

    def execute_side_effect(self, entry: Mapping[str, Any], grant: Any) -> None:
        grant.verify(entry["idempotency_key"])  # raises unless the outbox minted it for exactly this entry
        item = entry["item"]
        if entry.get("action_type") != ACTION_TYPE or not isinstance(item, Mapping):
            raise ValueError("not a push entry")
        doc = self._artifacts.get(item["artifact_id"], item["version"])
        payload = {"title": doc["subject"], "body": doc["body_text"], "tag": item["artifact_id"]}
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        delivered = 0
        for sub in self._subs.for_user(self._owner):
            try:
                self._sender.send(sub, body, self._vapid)
            except SubscriptionGone:
                self._subs.remove(self._owner, sub.endpoint)
            else:
                delivered += 1
        if delivered == 0:
            raise PushUndelivered("no live subscription took the push")


@dataclass(frozen=True)
class PushResult:
    status: Literal["queued", "duplicate", "quiet", "off", "no_subscription", "no_policy", "refused"]
    in_app: bool = True  # the card is always in the app: a push is only an extra nudge, a gate is never hidden
    outbox_id: str | None = None


def _clean(text: Any, limit: int) -> str | None:
    if type(text) is not str:
        return None
    one_line = "".join(c if c.isprintable() else " " for c in text).strip()
    return one_line[:limit] or None


class PushNotifier:
    def __init__(
        self,
        *,
        subscriptions: SubscriptionStore,
        outbox: Outbox,
        policy: DigestPolicyPort | None,
        artifacts: DigestArtifactPort,
        emit: Callable[[dict[str, Any]], None],
        mailbox: Callable[[str], str | None],
        world_id: str,
        world_owner: str,
        run_id: str,
        preferences: PreferenceReader | Mapping[str, Any] | None = None,
        clock: Callable[[], dt.datetime] | None = None,
        config: PushConfig | None = None,
        connector: str = CONNECTOR,
        district: str = "D1",
    ) -> None:
        self._subs, self._outbox, self._policy, self._artifacts = subscriptions, outbox, policy, artifacts
        self._emit, self._mailbox, self._prefs = emit, mailbox, preferences
        self._world_id, self._world_owner, self._run_id = world_id, world_owner, run_id
        self._clock = clock or (lambda: dt.datetime.now(dt.UTC))
        self._cfg, self._connector, self._district = config or load_config(), connector, district

    def _allowed(self, user_id: str, kind: str, now: dt.datetime) -> PushResult | None:
        """A refusing result, or None when the person's notification settings let this kind reach their phone."""
        prefs = self._prefs.get(user_id) if self._prefs is not None else None
        prefs = prefs if isinstance(prefs, Mapping) else None
        try:
            if not should_notify(kind, prefs=prefs, now=now):
                return PushResult("quiet" if is_quiet_hours(prefs, now=now) else "off")
        except Exception:
            return PushResult("refused")
        rows = prefs.get("notifications") if prefs is not None else None
        row = rows.get(_ROW_BY_KIND.get(kind, "")) if isinstance(rows, Mapping) else None
        if isinstance(row, Mapping) and row.get("phone") is False:
            return PushResult("off")  # FR-SET-02: a gate not pushed still waits in Needs you
        return None

    def notify(self, user_id: str, item: Mapping[str, Any], *, world_ids: Collection[str] | None = None) -> PushResult:
        """Queues one push of `item` ({id, kind, title, body}) through the policy engine and the outbox, once."""
        owner_addr = self._mailbox(user_id) if user_id == self._world_owner else None
        if world_ids is not None and self._world_id not in world_ids:
            return PushResult("refused")
        if self._policy is None or not isinstance(item, Mapping) or not _valid_user(user_id) or owner_addr is None:
            return PushResult("refused")
        item_id, kind = item.get("id"), item.get("kind")
        title, body = _clean(item.get("title"), self._cfg.title_max), _clean(item.get("body"), self._cfg.body_max)
        if type(item_id) is not str or not _ITEM_ID_RE.match(item_id) or type(kind) is not str or not title:
            return PushResult("refused")
        if not _KIND_RE.match(kind) or not conforms("common.schema.json#/$defs/email_address", owner_addr):
            return PushResult("refused")
        now = self._clock()
        if (blocked := self._allowed(user_id, kind, now)) is not None:
            return blocked
        if not self._subs.for_user(user_id):
            return PushResult("no_subscription")
        idem_key = f"push:{user_id}:{item_id}"
        if self._outbox.get_by_idempotency_key(self._world_id, idem_key) is not None:
            return PushResult("duplicate")
        now_ms = round(now.timestamp() * 1000)
        outbox_id = ulid(now_ms)
        stored = self._artifacts.store(f"art_push_{outbox_id[:16].lower()}", title, body or "")
        facts = tilo_policy.SideEffectFacts(recipients=(owner_addr,), known_recipients=(owner_addr,))
        proposal = tilo_policy.Proposal(
            self._world_id, ACTION_TYPE, self._connector, self._district, None, facts, copy.deepcopy(stored), 0, None
        )
        try:
            decision = self._policy.decide(user_id, proposal)
            pol = self._policy.policy_for(user_id, decision.policy_id) if type(decision.policy_id) is str else None
        except Exception:
            return PushResult("no_policy")
        undo = pol.get("undo_window_s") if isinstance(pol, Mapping) else None
        checked = allowed_l3_decision(decision, now_ms, undo if type(undo) is int else 0)
        if checked is None or not isinstance(pol, Mapping) or checked[2] != 0:  # a push is never held in an undo window
            return PushResult("no_policy")
        authz, at_ms, window = checked
        pdata: dict[str, Any] = {"policy_id": decision.policy_id, "gate_id": gate_id_for(f"push_{outbox_id}")}
        pdata |= {"outbox_id": outbox_id, "action_type": ACTION_TYPE, "connector": self._connector, "destination": None}
        pdata |= {"district": self._district, "risk_tier": decision.tier, "level": "L3", "instruction_id": None}
        pdata |= {"undo_window_s": window, "item": copy.deepcopy(stored), "credits": 0}
        applied = {"type": "policy.applied", "authz": copy.deepcopy(authz), "data": pdata}
        entry: dict[str, Any] = {"id": outbox_id, "idempotency_key": idem_key, "world_id": self._world_id}
        entry |= {"run_id": self._run_id, "action_type": ACTION_TYPE, "connector": self._connector}
        entry |= {"recipients": [owner_addr], "attachments": [], "item": copy.deepcopy(stored), "destination": None}
        entry |= {"modifiers": [], "risk_tier": decision.tier, "authz": authz, "undo_window_s": window}
        entry |= {"scheduled_at": timestamp(at_ms), "state": "queued", "created_at": authz["at"]}
        if not event_ok(applied, ("policy.applied",)) or not conforms("outbox.schema.json", entry):
            return PushResult("refused")
        try:
            res = enqueue_digest(
                self._outbox, entry, policy_applied=applied, policy=pol, world_owner=self._world_owner, emit=self._emit
            )
        except Exception:
            return PushResult("refused")
        return PushResult("queued", outbox_id=outbox_id) if res is not None else PushResult("no_policy")
