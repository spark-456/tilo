"""WhatsApp Cloud API webhook: signature verified, idempotent, ordered per sender (FR-CHN-02).

Order of work in `WhatsAppWebhook.receive`: verify the signature over the raw bytes (nothing else
runs on failure), parse Meta's `entry[].changes[].value.messages[]`, drop stale (or future-dated) messages without
claiming them, then per message, inside that sender's lock, claim its id in the injected
`DedupeStore` and call the handler. Message text, numbers in full and the app secret are never
logged.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

log = logging.getLogger("tilo_channels.whatsapp")

DEFAULT_MAX_AGE_S = 300.0
DEFAULT_MAX_FUTURE_SKEW_S = 60.0
MIN_APP_SECRET_BYTES = 32  # Meta app secrets are 32 characters
_SIG_PREFIX = "sha256="
_OBJECT = "whatsapp_business_account"
_FIELD = "messages"


class DedupeStore(Protocol):
    def claim(self, key: str, ttl_s: float) -> bool:
        """Atomic set-if-absent: True for the first claimant of `key`, False afterwards (until ttl)."""
        ...


@dataclass(frozen=True)
class InboundMessage:
    message_id: str
    sender: str
    timestamp: int
    kind: str
    text: str | None


@dataclass(frozen=True)
class MessageOutcome:
    message_id: str
    sender: str
    result: str  # "processed" | "duplicate" | "stale" | "failed"


@dataclass(frozen=True)
class WebhookResponse:
    status: int  # 200, 400 (signed but not JSON), 401 (signature)
    outcomes: tuple[MessageOutcome, ...]


def mask_number(number: str) -> str:
    """Last four digits only, for logs."""
    return "***" + number[-4:]


def message_ref(message_id: str) -> str:
    """Irreversible log reference for a wamid: a wamid encodes the sender's number, so it is never logged."""
    return hashlib.sha256(message_id.encode("utf-8", "replace")).hexdigest()[:12]


def verify_signature(app_secret: bytes, raw_body: bytes, header: str | None) -> bool:
    """True only for `sha256=` + lowercase-hex HMAC-SHA256(app_secret, raw_body). Never raises.

    An empty key is never valid: anyone can sign with it."""
    if not app_secret or not header or not header.isascii():
        return False
    expected = _SIG_PREFIX + hmac.new(app_secret, raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(header.encode("utf-8"), expected.encode("ascii"))


def _parse_messages(payload: Any, phone_number_id: str | None) -> list[InboundMessage]:
    """Messages in payload order. Oddly shaped levels and other products, fields or numbers are
    skipped; `statuses` are ignored."""
    found: list[InboundMessage] = []
    if not isinstance(payload, dict) or payload.get("object") != _OBJECT:
        return found
    for entry in _as_list(payload.get("entry")):
        for change in _as_list(entry.get("changes") if isinstance(entry, dict) else None):
            if not isinstance(change, dict) or change.get("field") != _FIELD:
                continue
            value = change.get("value")
            if not isinstance(value, dict):
                continue
            if phone_number_id is not None:
                metadata = value.get("metadata")
                if not isinstance(metadata, dict) or metadata.get("phone_number_id") != phone_number_id:
                    continue
            for raw in _as_list(value.get("messages")):
                message = _parse_message(raw)
                if message is not None:
                    found.append(message)
    return found


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _parse_message(raw: Any) -> InboundMessage | None:
    if not isinstance(raw, dict):
        return None
    message_id, sender, kind = raw.get("id"), raw.get("from"), raw.get("type")
    if not (isinstance(message_id, str) and isinstance(sender, str) and isinstance(kind, str)):
        return None
    try:
        timestamp = int(raw.get("timestamp"))  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None
    text = None
    if kind == "text":
        body = (raw.get("text") or {}).get("body") if isinstance(raw.get("text"), dict) else None
        text = body if isinstance(body, str) else None
    return InboundMessage(message_id=message_id, sender=sender, timestamp=timestamp, kind=kind, text=text)


class WhatsAppWebhook:
    def __init__(
        self,
        *,
        app_secret: bytes,
        now: Callable[[], float],
        store: DedupeStore,
        handler: Callable[[InboundMessage], object],
        max_age_s: float = DEFAULT_MAX_AGE_S,
        max_future_skew_s: float = DEFAULT_MAX_FUTURE_SKEW_S,
        phone_number_id: str | None = None,
    ) -> None:
        if len(app_secret) < MIN_APP_SECRET_BYTES:
            raise ValueError(f"app secret must be at least {MIN_APP_SECRET_BYTES} bytes")
        self._phone_number_id = phone_number_id
        self._max_future_skew_s = max_future_skew_s
        self._app_secret = app_secret
        self._now = now
        self._store = store
        self._handler = handler
        self._max_age_s = max_age_s
        self._locks_guard = threading.Lock()
        self._locks: dict[str, list[Any]] = {}  # sender -> [lock, users]

    def receive(self, raw_body: bytes, signature_header: str | None) -> WebhookResponse:
        if not verify_signature(self._app_secret, raw_body, signature_header):
            return WebhookResponse(401, ())
        try:
            payload = json.loads(raw_body)
        except ValueError:
            return WebhookResponse(400, ())
        if not isinstance(payload, dict):
            return WebhookResponse(400, ())

        messages = _parse_messages(payload, self._phone_number_id)
        results: dict[int, str] = {}
        fresh: list[tuple[int, int]] = []  # (timestamp, payload position)
        now = self._now()
        for position, message in enumerate(messages):
            age = now - message.timestamp
            if age > self._max_age_s or -age > self._max_future_skew_s:
                log.warning("whatsapp message dropped stale ref=%s age_s=%d", message_ref(message.message_id), age)
                results[position] = "stale"
            else:
                fresh.append((message.timestamp, position))
        for _, position in sorted(fresh):  # stable: equal timestamps keep payload order
            results[position] = self._process(messages[position])
        outcomes = tuple(MessageOutcome(m.message_id, m.sender, results[i]) for i, m in enumerate(messages))
        return WebhookResponse(200, outcomes)

    def _process(self, message: InboundMessage) -> str:
        with self._sender_lock(message.sender):
            # The claim lives at least as long as a replay can still look fresh.
            if not self._store.claim(f"whatsapp:msg:{message.message_id}", self._max_age_s * 2):
                return "duplicate"
            try:
                self._handler(message)
            except Exception as exc:  # at-most-once: the claim is kept, Meta still gets a 200
                log.error(
                    "whatsapp handler failed ref=%s sender=%s error=%s",
                    message_ref(message.message_id),
                    mask_number(message.sender),
                    type(exc).__name__,
                )
                return "failed"
            return "processed"

    def _sender_lock(self, sender: str) -> _SenderLock:
        return _SenderLock(self, sender)


class _SenderLock:
    """Per-sender mutex from a refcounted table, so idle senders leave no lock behind."""

    def __init__(self, hook: WhatsAppWebhook, sender: str) -> None:
        self._hook = hook
        self._sender = sender
        self._entry: list[Any] | None = None

    def __enter__(self) -> None:
        hook = self._hook
        with hook._locks_guard:
            entry = hook._locks.setdefault(self._sender, [threading.Lock(), 0])
            entry[1] += 1
        self._entry = entry
        entry[0].acquire()

    def __exit__(self, *_exc: object) -> None:
        entry = self._entry
        assert entry is not None
        entry[0].release()
        with self._hook._locks_guard:
            entry[1] -= 1
            if entry[1] == 0:
                del self._hook._locks[self._sender]
