"""tilo_channels.web_push: web push notifications (FR-CHN-17; PRD 6.2, 11, 16, SEC-03; FR-SET-02, FR-HIL-13).

A subscription is stored per signed-in person (`SubscriptionStore`); a notice is a policy-decided, outbox-queued
`send_push` entry (`PushNotifier`, the same L3 flow as the daily digest) that only the outbox's own grant can send
(`WebPushAdapter`). Notification settings and quiet hours are read first and never hide a gate: a gate that is not
pushed still waits in Needs you (`PushResult.in_app` is always true), and `notify` never raises. A card whose content
was flagged by injection detection (or whose flag is unknown) is a T3 modifier, so the engine gates it. The text a
lock screen shows is cleaned like a quote: control and format characters out, the shared secret redactor, addresses,
phone numbers and links masked, a word-boundary cut. The payload carries a relative same-origin path built here from
the card id, never a link from content. The VAPID key is a Secret Manager secret named in `config/web_push.yaml`;
this module holds the name only, makes no network call and logs nothing. The real sender (a port, `PushSender`) is
wired by the service; dev and CI use a fake. `tilo_connectors` is never imported (BQ-158): the adapter is duck-typed
to the outbox's `execute_side_effect(entry, grant)`.
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
from tilo_people.text import clean_line
from tilo_policy.schemas import conforms, event_ok
from tilo_redact import redact as default_redact

from tilo_channels import autopilot_gate
from tilo_channels.autopilot_gate import gate_card_id, gate_id_for
from tilo_channels.autopilot_state import Outbox, timestamp
from tilo_channels.digest import DigestArtifactPort, DigestPolicyPort, allowed_l3_decision
from tilo_channels.quiet_hours import PreferenceReader, QuietHours, is_quiet_hours, should_notify

__all__ = [
    "ACTION_TYPE",
    "CONFIG_PATH",
    "CONNECTOR",
    "KINDS",
    "OPEN_PATH",
    "PushConfig",
    "PushNotifier",
    "PushRefused",
    "PushResult",
    "PushSender",
    "PushSubscription",
    "PushUndelivered",
    "SubscriptionGone",
    "SubscriptionLimit",
    "SubscriptionRefused",
    "SubscriptionStore",
    "VapidRef",
    "WebPushAdapter",
    "endpoint_ok",
    "load_config",
    "parse_subscription",
]

ACTION_TYPE = "send_push"
CONNECTOR = "web_push"  # an outbox adapter name; it is not in config/connectors.yaml (nothing for a person to connect)
CONFIG_PATH = Path(__file__).resolve().parents[4] / "config" / "web_push.yaml"
OPEN_PATH = "/park/home"  # where a tap goes: Needs you lives on Home; the service worker allowlists exactly this
KINDS = frozenset({"gate", "blocked", "spend", "finished", "digest", "weekly"})  # PRD 10.2: no consent, nudge, question
_SECRET_NAME_RE = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+){1,7}\Z")
_B64URL_RE = re.compile(r"^[A-Za-z0-9_-]+={0,2}\Z")
_ITEM_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}\Z")
_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
_HOST_RE = re.compile(
    rf"^(?=.{{1,253}}\Z){_LABEL}(?:\.{_LABEL})+\Z"
)  # LDH labels, no '%', no empty or edge-hyphen label
_MASK = re.compile(r"[^\s@]+@[^\s@]+|\S+://\S+|www\.\S+|\+?\d[\d ().-]{6,}\d")  # addresses, links, phone numbers
_ROW_BY_KIND = {"gate": "decisions", "blocked": "decisions", "spend": "spend", "finished": "finished"}  # FR-SET-02 rows
_ROW_BY_KIND |= {"digest": "digest", "weekly": "weekly"}


class SubscriptionRefused(ValueError):
    """The subscription (untrusted browser input) or its owner is not acceptable; nothing was stored."""


class SubscriptionLimit(SubscriptionRefused):
    """The person already holds the most devices allowed; nothing was stored."""


class SubscriptionGone(Exception):
    """The push service says this subscription no longer exists (HTTP 404 or 410): drop it."""


class PushUndelivered(RuntimeError):
    """No live subscription took the push; the outbox retries within its bounds, then a person is told."""


class PushRefused(Exception):
    """A final refusal (nothing to send to): the wiring passes the outbox's `SideEffectRefused` so it is not retried."""


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
    per_day: int


def load_config(path: Path = CONFIG_PATH) -> PushConfig:
    """`config/web_push.yaml`; anything malformed raises ValueError (fail closed: no push without a valid config)."""
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ValueError(f"web push config unreadable: {type(exc).__name__}") from exc
    if not isinstance(doc, dict):
        raise ValueError("web push config must be a mapping")
    names = (
        *("max_subscriptions_per_person", "max_endpoint_length", "send_within_s"),
        *("title_max", "body_max", "policy_per_day"),
    )
    raw: list[Any] = [doc.get(k) for k in names]
    hosts = doc.get("allowed_endpoint_hosts")
    if not all(type(v) is int and v >= 1 for v in raw):
        raise ValueError("web push config limits must be positive integers")
    if not isinstance(hosts, list) or not hosts or not all(type(h) is str and _HOST_RE.match(h) for h in hosts):
        raise ValueError("allowed_endpoint_hosts must list push service host names")
    subs, endpoint_len, within, title_max, body_max, per_day = (int(v) for v in raw)
    vapid = VapidRef(str(doc.get("vapid_private_key_secret")))
    return PushConfig(vapid, subs, endpoint_len, tuple(h.lower() for h in hosts), within, title_max, body_max, per_day)


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


def _canonical(endpoint: Any, cfg: PushConfig) -> str | None:
    """The endpoint with lower-case scheme and host and no default port, or None when it is not an https address on
    an allowed push service host. The host is checked as a host name (LDH labels) BEFORE the suffix test, so no
    percent-encoding, userinfo, backslash or odd label can make a different host look allowed."""
    if type(endpoint) is not str or not 12 <= len(endpoint) <= cfg.max_endpoint_length:
        return None
    if not endpoint.isascii() or not endpoint.isprintable() or any(c in endpoint for c in " \\"):
        return None
    try:
        parts = urlsplit(endpoint)
        host, port = (parts.hostname or ""), parts.port
    except ValueError:
        return None
    if parts.scheme != "https" or parts.username is not None or parts.password is not None or parts.fragment:
        return None
    if port not in (None, 443) or not _HOST_RE.match(host) or parts.netloc.lower() not in (host, f"{host}:443"):
        return None
    if not any(host == h or host.endswith("." + h) for h in cfg.allowed_hosts):
        return None
    return f"https://{host}{parts.path}" + (f"?{parts.query}" if parts.query else "")


def endpoint_ok(endpoint: Any, cfg: PushConfig | None = None) -> bool:
    return _canonical(endpoint, cfg or load_config()) is not None


def parse_subscription(raw: Any, cfg: PushConfig) -> PushSubscription:
    """A `PushSubscription.toJSON()` body as an untrusted value: raises `SubscriptionRefused`, never echoes it."""
    if not isinstance(raw, Mapping):
        raise SubscriptionRefused("not a subscription")
    keys = raw.get("keys")
    p256dh, auth = (keys.get("p256dh"), keys.get("auth")) if isinstance(keys, Mapping) else (None, None)
    endpoint = _canonical(raw.get("endpoint"), cfg)
    if endpoint is None:
        raise SubscriptionRefused("endpoint must be an https push service address")
    for value, lo, hi in ((p256dh, 80, 100), (auth, 20, 32)):
        if type(value) is not str or not lo <= len(value) <= hi or not _B64URL_RE.match(value):
            raise SubscriptionRefused("subscription keys are malformed")
    return PushSubscription(endpoint, p256dh, auth)  # type: ignore[arg-type]


class SubscriptionStore:
    """Subscriptions per person, in memory (the durable store is a port the service wires). Capped, validated, and one
    owner per endpoint: a browser that is subscribed again by someone else moves to that person (a shared browser must
    not keep delivering one person's cards to the next)."""

    def __init__(self, config: PushConfig | None = None) -> None:
        self._cfg = config or load_config()
        self._by_user: dict[str, dict[str, PushSubscription]] = {}
        self._owner: dict[str, str] = {}
        self._lock = threading.Lock()

    def add(self, user_id: str, raw: Mapping[str, Any]) -> PushSubscription:
        """Stores `raw` (a PushSubscription.toJSON() body) for the signed-in `user_id`; the same endpoint replaces."""
        if not _valid_user(user_id):
            raise SubscriptionRefused("not a signed-in person's subscription")
        sub = parse_subscription(raw, self._cfg)
        with self._lock:
            mine = self._by_user.setdefault(user_id, {})
            if sub.endpoint not in mine and len(mine) >= self._cfg.max_subscriptions:
                raise SubscriptionLimit("this person already has the most devices allowed")
            previous = self._owner.get(sub.endpoint)
            if previous is not None and previous != user_id:
                self._by_user.get(previous, {}).pop(sub.endpoint, None)
            self._owner[sub.endpoint] = user_id
            mine[sub.endpoint] = sub
        return sub

    def remove(self, user_id: str, endpoint: str) -> bool:
        with self._lock:
            found = self._by_user.get(user_id, {}).pop(endpoint, None) is not None
            if found:
                self._owner.pop(endpoint, None)
            return found

    def for_user(self, user_id: str) -> tuple[PushSubscription, ...]:
        with self._lock:
            return tuple(self._by_user.get(user_id, {}).values())

    def erase(self, user_id: str) -> int:
        """FR-MEM-09: every device of one person; returns how many went."""
        with self._lock:
            gone = self._by_user.pop(user_id, {})
            for endpoint in gone:
                self._owner.pop(endpoint, None)
            return len(gone)

    def users(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(u for u, subs in self._by_user.items() if subs)


def path_for(item_id: str) -> str:
    """The relative same-origin path a tap opens, built here from the card id and never from content."""
    return f"{OPEN_PATH}?card={item_id}"


class WebPushAdapter:
    """The outbox adapter for `send_push`: runs only when `Outbox.dispatch_due()` hands it its grant (SEC-03). It tries
    every one of the owner's devices; it raises only when none took the push (retriable), or, with nothing to send to,
    the `final_error` the wiring passes (the outbox's `SideEffectRefused`, so it is not retried)."""

    def __init__(
        self,
        *,
        subscriptions: SubscriptionStore,
        sender: PushSender,
        artifacts: DigestArtifactPort,
        owner: str,
        vapid: VapidRef,
        final_error: type[Exception] = PushRefused,
    ) -> None:
        self._subs, self._sender, self._artifacts, self._owner = subscriptions, sender, artifacts, owner
        self._vapid, self._final = vapid, final_error

    def execute_side_effect(self, entry: Mapping[str, Any], grant: Any) -> None:
        grant.verify(entry["idempotency_key"])  # raises unless the outbox minted it for exactly this entry
        item = entry["item"]
        if entry.get("action_type") != ACTION_TYPE or not isinstance(item, Mapping):
            raise ValueError("not a push entry")
        item_id = str(entry["idempotency_key"]).rsplit(":", 1)[-1]
        if not _ITEM_ID_RE.match(item_id):
            raise self._final("not a push entry")
        doc = self._artifacts.get(item["artifact_id"], item["version"])
        payload = {"title": doc["subject"], "body": doc["body_text"], "tag": item_id, "path": path_for(item_id)}
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        subs = self._subs.for_user(self._owner)
        if not subs:
            raise self._final("no device to send to")
        delivered = 0
        for sub in subs:
            try:
                self._sender.send(sub, body, self._vapid)
            except SubscriptionGone:
                self._subs.remove(self._owner, sub.endpoint)
            except Exception:  # noqa: BLE001 - one device's failure never stops the others
                continue
            else:
                delivered += 1
        if delivered == 0:
            raise PushUndelivered("no live subscription took the push")


@dataclass(frozen=True)
class PushResult:
    status: Literal["queued", "duplicate", "quiet", "off", "no_subscription", "no_policy", "refused"]
    in_app: bool = True  # the card is always in the app: a push is only an extra nudge, a gate is never hidden
    outbox_id: str | None = None


def _text(raw: Any, limit: int, redact: Callable[[str], str]) -> str | None:
    """Notice text, cleaned like a quote (PE-24, PE-29): control, format and separator characters out, secrets
    redacted, addresses, links and phone numbers masked, white space collapsed, cut on a word boundary."""
    if type(raw) is not str:
        return None
    t = " ".join(_MASK.sub("[removed]", redact(clean_line(raw))).split())
    if len(t) > limit:
        t = (t[: limit + 1].rsplit(" ", 1)[0] if " " in t[: limit + 1] else t[:limit]).rstrip()
    return t or None


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
        preferences: PreferenceReader | Mapping[str, Any] | QuietHours | None = None,
        clock: Callable[[], dt.datetime] | None = None,
        config: PushConfig | None = None,
        connector: str = CONNECTOR,
        district: str = "D1",
        redact: Callable[[str], str] = default_redact,
    ) -> None:
        self._subs, self._outbox, self._policy, self._artifacts = subscriptions, outbox, policy, artifacts
        self._emit, self._mailbox, self._prefs = emit, mailbox, preferences
        self._world_id, self._world_owner, self._run_id = world_id, world_owner, run_id
        self._clock = clock or (lambda: dt.datetime.now(dt.UTC))
        self._cfg, self._connector, self._district = config or load_config(), connector, district
        self._redact = redact
        self._lock = threading.Lock()

    def _prefs_for(self, user_id: str) -> Mapping[str, Any] | QuietHours | None:
        """Both shapes of `digest`: a mapping by user id, or one person's own settings (`quiet_hours`, ...)."""
        src = self._prefs
        if src is None or isinstance(src, QuietHours):
            return src
        if isinstance(src, Mapping) and src.keys() & {"quiet_hours", "notifications", "start", "end"}:
            return src
        found = src.get(user_id)
        return found if isinstance(found, Mapping | QuietHours) else None

    def _allowed(self, user_id: str, kind: str, now: dt.datetime) -> PushResult | None:
        """A refusing result, or None when the person's notification settings let this kind reach their phone."""
        prefs = self._prefs_for(user_id)
        if not should_notify(kind, prefs=prefs, now=now):
            return PushResult("quiet" if is_quiet_hours(prefs, now=now) else "off")
        rows = prefs.get("notifications") if isinstance(prefs, Mapping) else None
        row = rows.get(_ROW_BY_KIND.get(kind, "")) if isinstance(rows, Mapping) else None
        if isinstance(row, Mapping) and row.get("phone") is False:
            return PushResult("off")  # FR-SET-02: a gate not pushed still waits in Needs you
        return None

    def notify(self, user_id: str, item: Mapping[str, Any], *, world_ids: Collection[str] | None = None) -> PushResult:
        """Queues one push of `item` ({id, kind, title, body, flagged}) through the policy engine and the outbox,
        once. Never raises: whatever goes wrong the card is still shown in the app (call it after the card is
        stored)."""
        try:
            return self._notify(user_id, item, world_ids)
        except Exception:  # noqa: BLE001 - a push is a nudge; its failure never costs the card
            return PushResult("refused")

    def _notify(self, user_id: str, item: Mapping[str, Any], world_ids: Collection[str] | None) -> PushResult:
        if user_id != self._world_owner or not _valid_user(user_id) or self._policy is None:
            return PushResult("refused")
        if world_ids is not None and self._world_id not in world_ids:
            return PushResult("refused")
        if not isinstance(item, Mapping):
            return PushResult("refused")
        owner_addr = self._mailbox(user_id)
        item_id, kind = item.get("id"), item.get("kind")
        title = _text(item.get("title"), self._cfg.title_max, self._redact)
        body = _text(item.get("body"), self._cfg.body_max, self._redact)
        if type(item_id) is not str or not _ITEM_ID_RE.match(item_id) or kind not in KINDS or not title:
            return PushResult("refused")
        if not isinstance(owner_addr, str) or not conforms("common.schema.json#/$defs/email_address", owner_addr):
            return PushResult("refused")
        now = self._clock()
        if (blocked := self._allowed(user_id, str(kind), now)) is not None:
            return blocked
        if not self._subs.for_user(user_id):
            return PushResult("no_subscription")
        idem_key = f"push:{user_id}:{item_id}"
        with self._lock:  # a second racer in this process finds the first's entry
            if (stored := self._outbox.get_by_idempotency_key(self._world_id, idem_key)) is not None:
                return PushResult("duplicate", outbox_id=stored.get("id"))
            return self._queue(user_id, owner_addr, idem_key, title, body or "", item.get("flagged"), now)

    def _queue(
        self, user_id: str, owner_addr: str, idem_key: str, title: str, body: str, flagged: Any, now: dt.datetime
    ) -> PushResult:
        policy = self._policy
        if policy is None:
            return PushResult("refused")
        now_ms = round(now.timestamp() * 1000)
        outbox_id = gate_card_id(f"push-entry:{self._world_id}:{idem_key}")  # the same id for every racer
        stored = self._artifacts.store(f"art_push_{outbox_id[:16].lower()}", title, body)
        facts = tilo_policy.SideEffectFacts(
            recipients=(owner_addr,), known_recipients=(owner_addr,), safety_flags=flagged is not False
        )  # PRD 10.4: flagged, or not known to be clean, is a person's decision
        proposal = tilo_policy.Proposal(
            self._world_id, ACTION_TYPE, self._connector, self._district, None, facts, copy.deepcopy(stored), 0, None
        )
        try:
            decision = policy.decide(user_id, proposal)
            pol = policy.policy_for(user_id, decision.policy_id) if type(decision.policy_id) is str else None
        except Exception:  # noqa: BLE001
            return PushResult("no_policy")
        undo = pol.get("undo_window_s") if isinstance(pol, Mapping) else None
        checked = allowed_l3_decision(decision, now_ms, undo if type(undo) is int else 0)
        if checked is None or not isinstance(pol, Mapping) or checked[2] != 0:
            return PushResult("no_policy")  # a push is never held in an undo window, never carries a modifier
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
        evidence: dict[str, Any] = {"reserved_by": None, "authorised_by": copy.deepcopy(applied)}
        evidence |= {"policy": copy.deepcopy(dict(pol)), "team_lead": None, "world_owner": self._world_owner}
        evidence |= {"instruction": None, "earlier_applied": []}
        if not autopilot_gate.opens(entry, evidence):
            return PushResult("refused")
        self._emit(copy.deepcopy(applied))  # the event first: no effect without its record (HR-7)
        got = self._outbox.enqueue(entry, evidence)
        return PushResult("queued", outbox_id=got["id"]) if got is not None else PushResult("refused")
