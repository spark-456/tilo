"""Test doubles and payload builders for services/channels acceptance tests (FR-CHN-02, FR-CHN-06).

Kept out of conftest.py under a package-unique module name: every test directory in the repo has
its own conftest.py, so `from conftest import ...` resolves to whichever one was imported first
when the whole suite runs together. No production code lives here: every class below is a test
double for an injected dependency (clock, dedupe store, number bindings, control plane, sender) or
a builder of a Meta WhatsApp Cloud API webhook body. `tilo_channels` itself does not exist yet;
importing it is what makes the tests fail for the right reason (see API.md in this directory).

No secret-shaped literal appears here: the fake app secret is assembled at runtime.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
from dataclasses import dataclass, field
from typing import Any

# A fixed, plausible instant (2026-10-02T09:00:00Z) so timestamps in payloads are realistic.
T0 = 1_790_931_600

# Bound users. Numbers are WhatsApp wa_ids (digits, no plus), as Meta sends them in `from`.
USER_A = "u_riya"
USER_B = "u_sam"
NUMBER_A = "6591110001"
NUMBER_B = "6592220002"
NUMBER_UNBOUND = "6593330003"


def make_app_secret() -> bytes:
    """A fresh fake Meta app secret, assembled at runtime (never a literal in the repo)."""
    return ("fake-app-" + secrets.token_hex(16)).encode("ascii")


class FakeClock:
    """Injected clock: `clock()` returns unix seconds as a float; tests move it with advance()."""

    def __init__(self, start: float = float(T0)) -> None:
        self._now = float(start)
        self._lock = threading.Lock()

    def __call__(self) -> float:
        with self._lock:
            return self._now

    def advance(self, seconds: float) -> None:
        with self._lock:
            self._now += seconds


class MemoryDedupeStore:
    """Thread-safe in-memory DedupeStore: `claim(key, ttl_s)` is an atomic set-if-absent that
    returns True for the first claimant and False for every later one until the ttl lapses (by
    the injected clock). Records every call so tests can assert what the webhook touched."""

    def __init__(self, clock: FakeClock) -> None:
        self._clock = clock
        self._expires: dict[str, float] = {}
        self._lock = threading.Lock()
        self.claims: list[tuple[str, float]] = []

    def claim(self, key: str, ttl_s: float) -> bool:
        with self._lock:
            self.claims.append((key, ttl_s))
            now = self._clock()
            expires = self._expires.get(key)
            if expires is not None and expires > now:
                return False
            self._expires[key] = now + ttl_s
            return True


class FakeBindings:
    """Number -> user lookup for bound numbers only (FR-CHN-03 owns binding; this is its read side)."""

    def __init__(self, bound: dict[str, str] | None = None) -> None:
        self._bound = dict(bound if bound is not None else {NUMBER_A: USER_A, NUMBER_B: USER_B})

    def user_for(self, number: str) -> str | None:
        return self._bound.get(number)


class FakeControls:
    """The control plane the keyword handler drives (the tilo-api client in production: channels
    never writes business state itself). Every call is recorded with the injected clock's time;
    each call also advances the clock by `latency_s` to simulate a round trip. `fail` makes the
    named method raise to model an unreachable control plane."""

    def __init__(self, clock: FakeClock, *, latency_s: float = 0.5, policies_per_user: int = 3) -> None:
        self._clock = clock
        self._latency_s = latency_s
        self._policies_per_user = policies_per_user
        self.calls: list[tuple[str, str, float]] = []  # (method, user_id, at)
        self.channels: list[str] = []
        self.fail: set[str] = set()

    def _record(self, method: str, user_id: str, channel: str | None) -> None:
        if method in self.fail:
            raise RuntimeError(f"{method} unavailable")
        self._clock.advance(self._latency_s)
        self.calls.append((method, user_id, self._clock()))
        if channel is not None:
            self.channels.append(channel)

    def stop_all_autopilot(self, user_id: str, *, channel: str) -> int:
        self._record("stop_all_autopilot", user_id, channel)
        return self._policies_per_user

    def pause_all(self, user_id: str, *, channel: str) -> None:
        self._record("pause_all", user_id, channel)

    def unsubscribe_whatsapp(self, user_id: str) -> None:
        self._record("unsubscribe_whatsapp", user_id, None)

    def methods(self) -> list[str]:
        return [c[0] for c in self.calls]


class FakeSender:
    """Records WhatsApp sends: `send_text(to, body)`. Never touches the network."""

    def __init__(self, clock: FakeClock) -> None:
        self._clock = clock
        self.sent: list[tuple[str, str, float]] = []  # (to, body, at)

    def send_text(self, to: str, body: str) -> None:
        self.sent.append((to, body, self._clock()))

    def bodies_to(self, number: str) -> list[str]:
        return [b for (to, b, _) in self.sent if to == number]


# ---------------------------------------------------------------------------
# Meta WhatsApp Cloud API webhook body and signature.


def text_message(message_id: str, sender: str, ts: int, body: str) -> dict[str, Any]:
    return {"from": sender, "id": message_id, "timestamp": str(ts), "type": "text", "text": {"body": body}}


def image_message(message_id: str, sender: str, ts: int) -> dict[str, Any]:
    return {
        "from": sender,
        "id": message_id,
        "timestamp": str(ts),
        "type": "image",
        "image": {"id": "media-1", "mime_type": "image/jpeg"},
    }


def delivery_body(messages: list[dict[str, Any]]) -> bytes:
    """The raw bytes of one webhook POST carrying `messages` (shape of Meta's `messages` webhook)."""
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "waba-1",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"display_phone_number": "6590000000", "phone_number_id": "pn-1"},
                            "contacts": [{"profile": {"name": "x"}, "wa_id": m["from"]} for m in messages],
                            "messages": messages,
                        },
                    }
                ],
            }
        ],
    }
    return json.dumps(payload).encode("utf-8")


def status_only_body() -> bytes:
    """A delivery receipt: a `statuses` array and no `messages` (Meta sends these constantly)."""
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "waba-1",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"display_phone_number": "6590000000", "phone_number_id": "pn-1"},
                            "statuses": [{"id": "wamid.out1", "status": "delivered", "recipient_id": NUMBER_A}],
                        },
                    }
                ],
            }
        ],
    }
    return json.dumps(payload).encode("utf-8")


def sign(app_secret: bytes, raw_body: bytes) -> str:
    """Meta's X-Hub-Signature-256 header value: `sha256=` + hex HMAC-SHA256 of the raw body."""
    return "sha256=" + hmac.new(app_secret, raw_body, hashlib.sha256).hexdigest()


def wamid(n: int) -> str:
    return f"wamid.TEST{n:08d}"


@dataclass
class Recorder:
    """A handler double that records each InboundMessage it is given, in call order."""

    messages: list[Any] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def __call__(self, message: Any) -> None:
        with self._lock:
            self.messages.append(message)

    def ids(self) -> list[str]:
        return [m.message_id for m in self.messages]
