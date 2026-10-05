"""Gmail push watch with polling fallback (FR-CHN-08; API in tests/API_FR_CHN_08.md, BQ-121 to BQ-129).

`MailWatcher` keeps one cursor (a Gmail history id) per watched user in the `WatchStore`. A push, a poll
and a resync all read history from that cursor, never from the pushed id, so a lost, late or duplicated
push loses nothing. Each message id is claimed in the `DedupeStore` before `triage` runs: at most once,
across restarts and instances. A failed triage keeps its claim (at-most-once,
BQ-127); the rest of the batch still runs. The watcher handles ids only, never message content.

`GmailPushEndpoint` authenticates Pub/Sub's OIDC token (verifier, then aud, iss, service account,
email_verified) before it parses anything. Logs carry exception types only: never a token, an address,
a body or exception text.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from .dedupe import DedupeStore

log = logging.getLogger("tilo_channels.gmail_watch")

WATCH_TTL_S = 7 * 86400  # Gmail's users.watch lifetime
RENEW_BEFORE_S = 86400.0  # re-watch inside the last day (Google recommends a daily re-watch)
POLL_INTERVAL_S = 30.0  # the sweeper (Cloud Tasks) calls poll_due() and renew_due() at this cadence
RESYNC_MAX_MESSAGES = 50  # = config/connectors.yaml gmail limits.batch_size
DEDUPE_TTL_S = 365 * 86400.0  # a resync re-lists recent mail; a year keeps it from being triaged again
_ISSUERS = frozenset({"https://accounts.google.com", "accounts.google.com"})
_MAX_HISTORY_ID = 2**64 - 1


class Mailbox(Protocol):  # production: an RPC client to tilo-connectors, never GmailAdapter in-process (SEC-02)
    def watch(self, user_id: str, *, topic_name: str, label_ids: Sequence[str]) -> dict[str, Any]: ...
    def stop_watch(self, user_id: str) -> None: ...
    def list_history(self, user_id: str, start_history_id: str, *, page_token: str | None = None) -> dict[str, Any]: ...
    def recent_inbox(self, user_id: str, *, max_results: int) -> dict[str, Any]: ...


class WatchStore(Protocol):  # Firestore in production; JSON-able dicts
    def get(self, user_id: str) -> dict[str, Any] | None: ...
    def put(self, user_id: str, value: dict[str, Any]) -> None: ...
    def delete(self, user_id: str) -> None: ...
    def user_ids(self) -> list[str]: ...


def _ignore(_part: dict[str, Any]) -> None:
    """No event is required from FR-CHN-08 (BQ-128)."""


class MailWatcher:
    def __init__(
        self,
        *,
        mailbox: Mailbox,
        store: WatchStore,
        dedupe: DedupeStore,
        triage: Callable[[str, str], object],
        clock: Callable[[], float],
        topic_name: str,
        emit: Callable[[dict[str, Any]], None] = _ignore,
    ) -> None:
        self._mailbox, self._store, self._dedupe, self._triage = mailbox, store, dedupe, triage
        self._clock, self._topic, self._emit = clock, topic_name, emit
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def _lock(self, user_id: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(user_id, threading.Lock())

    def start(self, user_id: str) -> None:
        """Watch the INBOX. Only mail after this point is new (BQ-121); a repeated start keeps the cursor."""
        with self._lock(user_id):
            info = self._mailbox.watch(user_id, topic_name=self._topic, label_ids=["INBOX"])
            state = self._store.get(user_id) or {"cursor": str(info["history_id"]), "read_at": self._clock()}
            self._store.put(user_id, {**state, "expires_at": float(info["expiration"])})

    def stop(self, user_id: str) -> None:
        """Forget the user first, so a failing users.stop never leaves them polled or renewed."""
        with self._lock(user_id):
            self._store.delete(user_id)
        self._mailbox.stop_watch(user_id)

    def on_push(self, user_id: str, history_id: str) -> None:
        """Read history from the stored cursor. A push at or behind the cursor announces nothing new.
        A mailbox error propagates, so the endpoint answers 5xx and Pub/Sub redelivers."""
        pushed = _decimal(history_id)
        with self._lock(user_id):
            state = self._store.get(user_id)
            if state is None or (pushed is not None and pushed <= int(state["cursor"])):
                return
            self._sync(user_id, state)

    def poll_due(self) -> None:
        """Poll every user whose history was last read at least half an interval ago (a push or poll that
        recently read it makes a poll redundant). One user's failure never stops the sweep."""
        for user_id in self._store.user_ids():
            try:
                with self._lock(user_id):
                    state = self._store.get(user_id)
                    if state is not None and self._clock() - float(state["read_at"]) >= POLL_INTERVAL_S / 2:
                        self._sync(user_id, state)
            except Exception as exc:  # noqa: BLE001 - logged by type; the next sweep retries
                log.warning("gmail poll failed: %s", type(exc).__name__)

    def renew_due(self) -> None:
        """Re-watch users inside the renewal window. Only the expiry changes, never the cursor, so mail
        that arrived just before the renewal is still read. A failure is retried on the next sweep."""
        for user_id in self._store.user_ids():
            try:
                with self._lock(user_id):
                    state = self._store.get(user_id)
                    if state is None or float(state["expires_at"]) - self._clock() > RENEW_BEFORE_S:
                        continue
                    info = self._mailbox.watch(user_id, topic_name=self._topic, label_ids=["INBOX"])
                    self._save(user_id, expires_at=float(info["expiration"]))
            except Exception as exc:  # noqa: BLE001 - logged by type; the next sweep retries
                log.warning("gmail watch renewal failed: %s", type(exc).__name__)

    def _sync(self, user_id: str, state: Mapping[str, Any]) -> None:
        """Every history page from the cursor, then triage in mailbox order, then move the cursor forward.
        A 404 (the cursor is older than Gmail's history) runs one bounded resync instead."""
        read_at, cursor, token = self._clock(), str(state["cursor"]), None
        ids: list[str] = []
        try:
            while True:
                page = self._mailbox.list_history(user_id, cursor, page_token=token)
                ids += page["message_ids"]
                newest, token = str(page["history_id"]), page.get("next_page_token")
                if not token:
                    break
        except Exception as exc:
            if getattr(exc, "status", None) != 404:
                raise
            recent = self._mailbox.recent_inbox(user_id, max_results=RESYNC_MAX_MESSAGES)
            ids, newest = list(reversed(recent["message_ids"])), str(recent["history_id"])
        for message_id in dict.fromkeys(ids):
            if not self._dedupe.claim(f"gmail:{user_id}:{message_id}", DEDUPE_TTL_S):
                continue
            try:
                self._triage(user_id, message_id)
            except Exception as exc:  # noqa: BLE001 - at-most-once: the claim is kept (BQ-127)
                log.warning("gmail triage failed: %s", type(exc).__name__)
        self._save(user_id, cursor=newest, read_at=read_at)

    def _save(self, user_id: str, **changes: Any) -> None:
        """Merge into the stored state; a stopped user stays stopped and the cursor never moves back."""
        state = self._store.get(user_id)
        if state is None:
            return
        if "cursor" in changes and int(changes["cursor"]) < int(state["cursor"]):
            changes["cursor"] = state["cursor"]
        self._store.put(user_id, {**state, **changes})


def _decimal(value: Any) -> int | None:
    """A history id (int, or ASCII decimal string) in 0..2^64-1, else None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        if not (0 < len(value) <= 20 and value.isascii() and value.isdigit()):
            return None
        value = int(value)
    return value if isinstance(value, int) and 0 <= value <= _MAX_HISTORY_ID else None


@dataclass(frozen=True)
class PushResponse:
    status: int
    body: str  # short and generic: never a token, claim, address, payload or exception text


class OidcVerifier(Protocol):  # google-auth id_token verification in production
    def verify(self, token: str, audience: str) -> Mapping[str, Any]: ...


class GmailPushEndpoint:
    """Pub/Sub push for Gmail: 401/403 unauthenticated, 400 malformed, 200 for an unwatched address,
    500 when the watcher fails (Pub/Sub redelivers). Nothing runs after a failed check."""

    def __init__(
        self,
        *,
        verifier: OidcVerifier,
        audience: str,
        service_account: str,
        accounts: Callable[[str], str | None],
        on_notification: Callable[[str, str], object],
        emit: Callable[[dict[str, Any]], None] = _ignore,
    ) -> None:
        self._verifier, self._audience, self._service_account = verifier, audience, service_account
        self._accounts, self._on_notification, self._emit = accounts, on_notification, emit

    def receive(self, headers: Mapping[str, str], raw_body: bytes) -> PushResponse:
        auth = next((str(v) for k, v in headers.items() if str(k).lower() == "authorization"), "")
        scheme, _, token = auth.partition(" ")
        token = token.strip()
        if scheme.lower() != "bearer" or not token:
            return PushResponse(401, "unauthenticated")
        try:
            claims = self._verifier.verify(token, self._audience)
        except Exception as exc:  # noqa: BLE001 - the verifier's text may describe the token
            log.info("gmail push refused: %s", type(exc).__name__)
            return PushResponse(401, "unauthenticated")
        if not (
            isinstance(claims, Mapping)
            and claims.get("aud") == self._audience
            and isinstance(claims.get("iss"), str)
            and claims["iss"] in _ISSUERS
            and claims.get("email") == self._service_account
            and claims.get("email_verified") is True
        ):
            log.info("gmail push refused: claims")
            return PushResponse(403, "forbidden")
        notification = _notification(raw_body)
        if notification is None:
            return PushResponse(400, "malformed")
        try:
            user_id = self._accounts(notification[0])
            if user_id is None:
                return PushResponse(200, "ignored")
            self._on_notification(user_id, str(notification[1]))
        except Exception as exc:  # noqa: BLE001 - logged by type; Pub/Sub redelivers
            log.warning("gmail push failed: %s", type(exc).__name__)
            return PushResponse(500, "retry")
        return PushResponse(200, "ok")


def _notification(raw_body: bytes) -> tuple[str, int] | None:
    """(emailAddress, historyId) from a Pub/Sub push body whose message.data is base64 JSON, else None."""
    try:
        message = json.loads(raw_body)["message"]
        data = json.loads(base64.b64decode(message["data"], validate=True))
        address, history_id = data["emailAddress"], _decimal(data["historyId"])
    except (ValueError, TypeError, KeyError, IndexError, RecursionError, binascii.Error):
        return None
    if not isinstance(address, str) or not address or history_id is None:
        return None
    return address, history_id
