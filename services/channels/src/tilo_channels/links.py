"""Signed, single-use email action links (FR-CHN-07, PRD 10.3, 11.6, 16.2, 16.4 SEC-08).

Token: `<kid>.<b64url(json claims)>.<b64url(HMAC-SHA256 over "<kid>.<claims>")>`. The claims carry the
nonce, card, user, action, option and expiry. Single use is one atomic `NonceStore.consume`, called last,
so a refusal never burns a link (D4). A link alone never answers a gate or consent card (PRD 10.3:
questions only; gates need sign-in): `answer` is issued and redeemed only for needs_you cards that list
email; opening a gate, consent or meeting card yields `requires_sign_in` when no person is signed in.

Nothing here logs, and a refusal carries only a stable reason code, never a token, nonce or key.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
import secrets
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

TTL = timedelta(hours=24)  # D1
_RETENTION_SLACK = timedelta(minutes=5)  # nonce kept a little past expiry (clock skew between instances)
_MIN_KEY_BYTES = 32
_KID = re.compile(r"[A-Za-z0-9_-]{1,32}\Z")
_B64 = re.compile(r"[A-Za-z0-9_-]+\Z")
_ACTIONS = ("open", "answer")
_MAC_DOMAIN = b"tilo-link-v1|"  # domain separation: these keys sign nothing else
_MAX_EXPIRY = 2**32  # epoch seconds, year 2106; anything larger is not one of our claims
_MAX_BODY = 1024  # decoded claims are ~200 bytes; a bigger body is not one of ours and is not parsed


class LinkRefused(Exception):
    """A link was refused. `reason` is one of the stable codes in the FR-CHN-07 tests."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class _BadIdentifier(LinkRefused, ValueError):
    """issue() was given a card or user id that is not a non-blank str. A ValueError (caller bug) that
    also stays a LinkRefused, so callers catching the stable refusal codes keep working."""


class KeyRing:
    """Signing keys by id. New links use the active key; every key in the ring verifies until retired."""

    def __init__(self, keys: Mapping[str, bytes], active: str) -> None:
        self._lock = threading.Lock()
        self._keys: dict[str, bytes] = {}
        for kid, key in keys.items():
            self._put(kid, key)
        if active not in self._keys:
            raise ValueError("active key id is not in the ring")
        self._active = active

    def _put(self, kid: str, key: bytes) -> None:
        if not _KID.match(kid):
            raise ValueError("key id must be 1-32 characters of A-Z a-z 0-9 _ -")
        if len(key) < _MIN_KEY_BYTES:
            raise ValueError(f"signing keys must be at least {_MIN_KEY_BYTES} bytes")
        self._keys[kid] = bytes(key)

    @property
    def active_kid(self) -> str:
        with self._lock:
            return self._active

    def add(self, kid: str, key: bytes, *, activate: bool = False) -> None:
        with self._lock:
            if kid in self._keys:
                raise ValueError("key id already in the ring")
            self._put(kid, key)
            if activate:
                self._active = kid

    def retire(self, kid: str) -> None:
        with self._lock:
            if kid == self._active:
                raise ValueError("the active key cannot be retired")
            if kid not in self._keys:
                raise ValueError("unknown key id")
            del self._keys[kid]

    def signing(self) -> tuple[str, bytes]:
        with self._lock:
            return self._active, self._keys[self._active]

    def get(self, kid: str) -> bytes | None:
        with self._lock:
            return self._keys.get(kid)


@dataclass(frozen=True)
class CardState:
    card: Mapping[str, Any]  # a contracts/card.schema.json card
    answered: bool  # answered on any channel, or closed by its timeout


class NonceStore(Protocol):
    def consume(self, nonce: str, expires_at: datetime) -> bool:
        """Atomic set-if-absent: True only the first time this nonce is consumed."""
        ...


@dataclass(frozen=True)
class IssuedLink:
    token: str = field(repr=False)  # a live 24 h bearer link: never in a repr, log or traceback
    url: str = field(repr=False)
    nonce: str = field(repr=False)
    key_id: str
    card_id: str
    user_id: str
    action: str
    option: str | None
    issued_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class Redemption:
    card_id: str
    user_id: str
    action: str
    option: str | None
    nonce: str = field(repr=False)
    authn: str  # "session" if the viewer was the bound user, else "link"
    requires_sign_in: bool  # the caller sends the person through sign-in before anything else


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64d(text: str) -> bytes:
    """Strict: URL-safe alphabet only, canonical spelling only (one string per byte sequence)."""
    if not _B64.match(text):
        raise LinkRefused("malformed")
    try:
        raw = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (binascii.Error, ValueError):
        raise LinkRefused("malformed") from None
    if _b64e(raw) != text:
        raise LinkRefused("malformed")
    return raw


def _mac(key: bytes, signed: str) -> bytes:
    return hmac.new(key, _MAC_DOMAIN + signed.encode("ascii"), hashlib.sha256).digest()


def _options(card: Mapping[str, Any]) -> set[str]:
    """Option ids, or none at all unless options is a list of objects that all carry a str id."""
    options = card.get("options")
    if not isinstance(options, list) or not all(
        isinstance(o, Mapping) and isinstance(o.get("id"), str) for o in options
    ):
        return set()
    return {o["id"] for o in options}


def _question_card(card: Mapping[str, Any]) -> bool:
    """Fail-closed allowlist: only a plain question card is answerable by email, however a crafted card
    is shaped (a gate or consent object, another rung, answer_channels not a list)."""
    channels = card.get("answer_channels")
    return (
        card.get("kind") == "needs_you"
        and card.get("rung") in ("needs_you", "blocked")
        and card.get("gate") is None
        and card.get("consent") is None
        and isinstance(channels, list)
        and "email" in channels
    )


class LinkService:
    def __init__(
        self,
        *,
        keys: KeyRing,
        nonces: NonceStore,
        clock: Callable[[], datetime],
        cards: Callable[[str], CardState | None],
        base_url: str,
    ) -> None:
        self._keys = keys  # read live on every call; never snapshotted
        self._nonces = nonces
        self._clock = clock
        self._cards = cards
        self._base_url = base_url.rstrip("/")

    def issue(self, *, card_id: str, user_id: str, action: str, option: str | None = None) -> IssuedLink:
        if action not in _ACTIONS:
            raise LinkRefused("unknown_action")
        if not isinstance(card_id, str) or not card_id.strip():
            raise _BadIdentifier("unknown_card")
        if not isinstance(user_id, str) or not user_id.strip():
            raise _BadIdentifier("wrong_user")
        state = self._cards(card_id)
        if state is None:
            raise LinkRefused("unknown_card")
        if action == "answer":
            if not _question_card(state.card):  # D2: gates and consent never get an answer link
                raise LinkRefused("not_allowed")
            if option is None or option not in _options(state.card):
                raise LinkRefused("unknown_option")
            if state.answered:
                raise LinkRefused("card_answered")
        elif option is not None:
            raise LinkRefused("unknown_option")
        issued_at = self._now().replace(microsecond=0)
        expires_at = issued_at + TTL
        nonce = secrets.token_urlsafe(16)
        claims = {"n": nonce, "c": card_id, "u": user_id, "a": action, "o": option, "e": int(expires_at.timestamp())}
        kid, key = self._keys.signing()
        body = _b64e(json.dumps(claims, separators=(",", ":")).encode("utf-8"))
        signed = f"{kid}.{body}"
        token = f"{signed}.{_b64e(_mac(key, signed))}"
        return IssuedLink(
            token=token,
            url=f"{self._base_url}/l/{token}",
            nonce=nonce,
            key_id=kid,
            card_id=card_id,
            user_id=user_id,
            action=action,
            option=option,
            issued_at=issued_at,
            expires_at=expires_at,
        )

    def _now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:  # a naive clock would tie expiry to the host zone
            raise LinkRefused("bad_clock")
        return now

    def _verify(self, token: str) -> dict[str, Any]:
        """Signature first; the claims are parsed only after the MAC matches."""
        parts = token.split(".") if isinstance(token, str) else []
        if len(parts) != 3:
            raise LinkRefused("malformed")
        kid, body, sig = parts
        provided = _b64d(sig)
        if len(provided) != hashlib.sha256().digest_size or not _KID.match(kid) or not _B64.match(body):
            raise LinkRefused("malformed")
        key = self._keys.get(kid)
        if key is None:  # D5: unknown and retired look the same
            raise LinkRefused("unknown_key")
        if not hmac.compare_digest(_mac(key, f"{kid}.{body}"), provided):
            raise LinkRefused("bad_signature")
        raw = _b64d(body)
        if len(raw) > _MAX_BODY:
            raise LinkRefused("malformed")
        try:
            claims = json.loads(raw)
            if not isinstance(claims, dict) or not all(isinstance(claims.get(k), str) for k in "ncu"):
                raise ValueError
            if claims.get("a") not in _ACTIONS or "o" not in claims or type(claims.get("e")) is not int:
                raise ValueError
            if (claims["o"] is None) != (claims["a"] == "open") or not (
                claims["o"] is None or isinstance(claims["o"], str)
            ):
                raise ValueError
            if not 0 < claims["e"] < _MAX_EXPIRY:
                raise ValueError
        except (ValueError, RecursionError):
            raise LinkRefused("malformed") from None
        return claims

    def peek(self, token: str) -> tuple[str, str, str | None, str]:
        """(card id, action, option, user) of a well-signed, unexpired token, for a confirm page. Consumes nothing
        and checks nothing else: a GET (a scanner, a prefetch) never spends a link; `redeem` is the one that does."""
        claims = self._verify(token)
        if self._now() >= datetime.fromtimestamp(claims["e"], tz=UTC):
            raise LinkRefused("expired")
        return claims["c"], claims["a"], claims["o"], claims["u"]

    def redeem(
        self, token: str, *, card_id: str, action: str, viewer: str | None = None, option: str | None = None
    ) -> Redemption:
        claims = self._verify(token)
        now = self._now()
        expires_at = datetime.fromtimestamp(claims["e"], tz=UTC)
        if now >= expires_at:
            raise LinkRefused("expired")
        if card_id != claims["c"]:
            raise LinkRefused("wrong_card")
        if action != claims["a"]:
            raise LinkRefused("wrong_action")
        if option is not None and option != claims["o"]:
            raise LinkRefused("wrong_option")
        if viewer is not None and viewer != claims["u"]:  # a forwarded link used by someone else
            raise LinkRefused("wrong_user")
        state = self._cards(card_id)
        if state is None:
            raise LinkRefused("unknown_card")
        if claims["a"] == "answer":  # D2, D6: re-checked against the card as it is now
            if not _question_card(state.card):
                raise LinkRefused("not_allowed")
            if claims["o"] not in _options(state.card):
                raise LinkRefused("unknown_option")
            if state.answered:
                raise LinkRefused("card_answered")
        if not self._nonces.consume(claims["n"], expires_at + _RETENTION_SLACK):  # last: D4
            raise LinkRefused("used")
        return Redemption(
            card_id=claims["c"],
            user_id=claims["u"],
            action=claims["a"],
            option=claims["o"],
            nonce=claims["n"],
            authn="session" if viewer is not None else "link",
            requires_sign_in=viewer is None and not _question_card(state.card),  # D3, allowlist
        )
