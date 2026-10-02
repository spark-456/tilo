"""WhatsApp number binding with a one-time code (FR-CHN-03, PRD 11.1, 15.1 ChannelBinding, SEC-06).

The signed-in user enters a number on the web app; a 6-digit code goes to it over WhatsApp; confirming
the code binds the number for 30 days. Numbers are stored only encrypted (the injected cipher, Cloud KMS
in production) and looked up by a keyed hash; codes are stored only as a keyed hash. Store layout:

- `num:<hash>`    -> {user_id, verified_at}                       one number, at most one user
- `user:<id>`     -> {number_hash, number_ct, verified_at}        one user, at most one number
- `pending:<id>`  -> {pid, number_hash, number_ct, code_hash, sent_at}
- `try:<pid>:<i>` -> {expires_at}   attempt slot i of a code (atomic create); a replaced code keeps its slots
- `cap:<n|u>:<hash or id>:<window>:<bucket>:<i>` -> {expires_at}   code-send slot i (SEC-10 caps)
- `optin:<hash>`  -> {expires_at}   the last opt-in reply to an unbound number

`expires_at` is for the store's TTL purge (a Firestore TTL policy in production).

A binding counts only while both records agree and `now < verified_at + RECONFIRM_AFTER_S`. Defaults
the PRD leaves open are BQ-89. Numbers and codes are never logged.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from tilo_channels.whatsapp import mask_number

log = logging.getLogger("tilo_channels.binding")

CODE_TTL_S = 600
MAX_CODE_ATTEMPTS = 5
RECONFIRM_AFTER_S = 30 * 86400
MIN_HASH_KEY_BYTES = 32
# SEC-10 code-send caps, (window_s, sends) per number ("n") and per user ("u"). Off unless passed as
# `send_caps`: the HTTP route must pass SEND_CAPS (the FR-CHN-03 acceptance tests start uncapped).
SEND_CAPS: dict[str, tuple[tuple[int, int], ...]] = {"n": ((3600, 3), (86400, 10)), "u": ((3600, 5), (86400, 20))}
OPT_IN_EVERY_S = 600
_STRIP = str.maketrans("", "", " -.()")


def normalise_number(raw: str) -> str | None:
    """E.164 as typed -> WhatsApp wa_id digits; None unless 8 to 15 ASCII digits remain, the first is not 0
    (no country code starts with 0, so "00" or a national 0 is refused) and they are not all the same."""
    digits = raw.translate(_STRIP)
    if digits.startswith("+"):
        digits = digits[1:]
    if not (digits.isascii() and digits.isdigit() and 8 <= len(digits) <= 15):
        return None
    if digits[0] == "0" or len(set(digits)) == 1:
        return None
    return digits


class NumberCipher(Protocol):
    def encrypt(self, plaintext: str) -> str: ...
    def decrypt(self, ciphertext: str) -> str: ...


class BindingStore(Protocol):
    def get(self, key: str) -> dict[str, Any] | None: ...
    def put(self, key: str, value: dict[str, Any]) -> None: ...
    def create(self, key: str, value: dict[str, Any]) -> bool: ...
    def delete(self, key: str) -> None: ...


class Sender(Protocol):
    def send_text(self, to: str, body: str) -> object: ...


@dataclass(frozen=True)
class BindingResult:
    ok: bool
    reason: str | None


@dataclass(frozen=True)
class BindingStatus:
    state: str  # "none" | "pending" | "bound" | "expired"
    number_masked: str | None
    verified_at: float | None
    expires_at: float | None


_OK = BindingResult(True, None)


def _refused(reason: str) -> BindingResult:
    return BindingResult(False, reason)


class BindingService:
    def __init__(
        self,
        *,
        store: BindingStore,
        cipher: NumberCipher,
        sender: Sender,
        clock: Callable[[], float],
        hash_key: bytes,
        send_caps: Mapping[str, tuple[tuple[int, int], ...]] | None = None,
    ) -> None:
        if len(hash_key) < MIN_HASH_KEY_BYTES:
            raise ValueError(f"hash key must be at least {MIN_HASH_KEY_BYTES} bytes")
        self._store = store
        self._cipher = cipher
        self._sender = sender
        self._clock = clock
        self._key = hash_key
        self._caps = send_caps or {}

    # --- web app ---------------------------------------------------------------------------------

    def start(self, user_id: str, number: str) -> BindingResult:
        wa_id = normalise_number(number)
        if wa_id is None:
            return _refused("invalid_number")
        number_hash = self._mac("number", wa_id)
        owner = self._owner(number_hash)
        if owner is not None and owner != user_id:
            return _refused("number_taken")
        if not self._claim_send(user_id, number_hash):
            return _refused("rate_limited")  # the pending code, if any, and its attempts stay as they are
        code = f"{secrets.randbelow(1_000_000):06d}"
        pid = secrets.token_hex(8)
        pending = {
            "pid": pid,
            "number_hash": number_hash,
            "number_ct": self._cipher.encrypt(wa_id),
            "code_hash": self._mac("code", f"{pid}|{code}"),
            "sent_at": self._clock(),
        }
        try:  # stored before the send, so a store failure never strands a code nobody can confirm
            self._store.put(f"pending:{user_id}", pending)
        except Exception as exc:
            log.error("binding pending write failed user=%s error=%s", user_id, type(exc).__name__)
            return _refused("unavailable")
        try:
            self._sender.send_text(wa_id, f"Your Tilo code is {code}. It is valid for 10 minutes.")
        except Exception as exc:
            log.warning("binding code send failed user=%s error=%s", user_id, type(exc).__name__)
            self._drop_pending(user_id)
            return _refused("send_failed")
        return _OK

    def confirm(self, user_id: str, code: str) -> BindingResult:
        pending = self._store.get(f"pending:{user_id}")
        if pending is None:
            return _refused("no_pending")
        pid = pending["pid"]
        if self._store.get(f"try:{pid}:{MAX_CODE_ATTEMPTS - 1}") is not None:
            return _refused("too_many_attempts")
        now = self._clock()
        if now >= pending["sent_at"] + CODE_TTL_S:
            return _refused("expired")
        expiry = {"expires_at": pending["sent_at"] + CODE_TTL_S}
        slot = next((i for i in range(MAX_CODE_ATTEMPTS) if self._store.create(f"try:{pid}:{i}", expiry)), None)
        if slot is None:
            return _refused("too_many_attempts")
        if not hmac.compare_digest(self._mac("code", f"{pid}|{code}"), pending["code_hash"]):
            return _refused("too_many_attempts" if slot == MAX_CODE_ATTEMPTS - 1 else "wrong_code")
        number_hash = pending["number_hash"]
        record = {"user_id": user_id, "verified_at": now}
        owner = self._owner(number_hash)
        if owner == user_id:
            self._store.put(f"num:{number_hash}", record)
        elif owner is not None or not self._claim(number_hash, record) or not self._holds(number_hash, user_id):
            self._drop_pending(user_id)
            return _refused("number_taken")
        previous = self._store.get(f"user:{user_id}")
        self._store.put(
            f"user:{user_id}",
            {"number_hash": number_hash, "number_ct": pending["number_ct"], "verified_at": now},
        )
        self._drop_pending(user_id)
        if self._owner(number_hash) != user_id:  # lost a race after the write: keep what the user had
            if previous is None:
                self._store.delete(f"user:{user_id}")
            else:
                self._store.put(f"user:{user_id}", previous)
            return _refused("number_taken")
        if previous is not None and previous["number_hash"] != number_hash:
            self._release(previous["number_hash"], user_id)
        return _OK

    def allow_opt_in(self, number: str) -> bool:
        """At most one opt-in reply per number per OPT_IN_EVERY_S (InboundRouter `opt_in_allowed`)."""
        key = f"optin:{self._mac('number', normalise_number(number) or number)}"
        now = self._clock()
        record = {"expires_at": now + OPT_IN_EVERY_S}
        if self._store.create(key, record):
            return True
        seen = self._store.get(key)
        if seen is not None and now < float(seen["expires_at"]):
            return False
        self._store.put(key, record)
        return True

    def unbind(self, user_id: str) -> bool:
        user = self._store.get(f"user:{user_id}")
        removed = user is not None
        if user is not None:
            self._release(user["number_hash"], user_id)
            self._store.delete(f"user:{user_id}")
        if self._store.get(f"pending:{user_id}") is not None:
            self._drop_pending(user_id)
            removed = True
        return removed

    def status(self, user_id: str) -> BindingStatus:
        user = self._store.get(f"user:{user_id}")
        if user is not None and self._agrees(user_id, user):
            verified_at = float(user["verified_at"])
            state = "bound" if self._live(verified_at) else "expired"
            if state == "bound" or not self._pending_live(user_id):
                masked = mask_number(self._cipher.decrypt(user["number_ct"]))
                return BindingStatus(state, masked, verified_at, verified_at + RECONFIRM_AFTER_S)
        if self._pending_live(user_id):
            pending = self._store.get(f"pending:{user_id}") or {}
            return BindingStatus("pending", mask_number(self._cipher.decrypt(pending["number_ct"])), None, None)
        return BindingStatus("none", None, None, None)

    # --- lookups (keywords.Bindings, cards.CardBindings) -----------------------------------------------

    def user_for(self, number: str) -> str | None:
        wa_id = normalise_number(number)
        if wa_id is None:
            return None
        return self._owner(self._mac("number", wa_id))

    def number_for(self, user_id: str) -> str | None:
        user = self._store.get(f"user:{user_id}")
        if user is None or self._owner(user["number_hash"]) != user_id:
            return None
        return self._cipher.decrypt(user["number_ct"])

    # --- internals -------------------------------------------------------------------------------------

    def _mac(self, purpose: str, value: str) -> str:
        message = f"tilo-binding-v1|{purpose}|{value}".encode()
        return hmac.new(self._key, message, hashlib.sha256).hexdigest()

    def _live(self, verified_at: float) -> bool:
        return self._clock() < verified_at + RECONFIRM_AFTER_S

    def _owner(self, number_hash: str) -> str | None:
        """The user a number is validly bound to: both records agree and the 30 days have not passed."""
        record = self._store.get(f"num:{number_hash}")
        if record is None or not self._live(float(record["verified_at"])):
            return None
        user = self._store.get(f"user:{record['user_id']}")
        if user is None or user["number_hash"] != number_hash:
            return None
        return str(record["user_id"])

    def _agrees(self, user_id: str, user: dict[str, Any]) -> bool:
        return self._holds(user["number_hash"], user_id)

    def _holds(self, number_hash: str, user_id: str) -> bool:
        record = self._store.get(f"num:{number_hash}")
        return record is not None and record["user_id"] == user_id

    def _release(self, number_hash: str, user_id: str) -> None:
        if self._holds(number_hash, user_id):
            self._store.delete(f"num:{number_hash}")

    def _claim_send(self, user_id: str, number_hash: str) -> bool:
        """Claims one slot in each SEC-10 send window; refused (claiming nothing) when any window is full."""
        now = self._clock()
        windows = []
        for scope, ident in (("n", number_hash), ("u", user_id)):
            for window, limit in self._caps.get(scope, ()):
                bucket = int(now // window)
                windows.append((f"cap:{scope}:{ident}:{window}:{bucket}", limit, (bucket + 1) * window))
        if any(self._store.get(f"{prefix}:{limit - 1}") is not None for prefix, limit, _ in windows):
            return False
        for prefix, limit, expires_at in windows:
            slot = {"expires_at": float(expires_at)}
            if not any(self._store.create(f"{prefix}:{i}", slot) for i in range(limit)):
                return False  # a concurrent start took the last slot
        return True

    def _claim(self, number_hash: str, record: dict[str, Any]) -> bool:
        """Atomic create; a lapsed or orphaned record (no valid owner) is overwritten."""
        if self._store.create(f"num:{number_hash}", record):
            return True
        if self._owner(number_hash) is not None:
            return False
        self._store.put(f"num:{number_hash}", record)
        return True

    def _pending_live(self, user_id: str) -> bool:
        pending = self._store.get(f"pending:{user_id}")
        if pending is None or self._clock() >= pending["sent_at"] + CODE_TTL_S:
            return False
        return self._store.get(f"try:{pending['pid']}:{MAX_CODE_ATTEMPTS - 1}") is None

    def _drop_pending(self, user_id: str) -> None:
        pending = self._store.get(f"pending:{user_id}")
        if pending is None:
            return
        self._store.delete(f"pending:{user_id}")
        for i in range(MAX_CODE_ATTEMPTS):
            self._store.delete(f"try:{pending['pid']}:{i}")
