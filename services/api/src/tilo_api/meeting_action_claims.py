"""ADR-0042 amendment 1 (owner decision 21 Oct, BQ-MTG-ACTIONS-1): the attend's ACTION claim.

`meeting_bot.attend_meeting` opens one, from the verified principal (the meeting owner), after the meeting's `joining`
compare-and-set and before the bot is called, and closes it in its `finally`; the bot echoes the nonce on
`POST /internal/meeting-actions/run`. A bot body never carries a uid or an org, so there is nothing to forge. Separate
from the voice meter's claim (its own switch and registry): one never turns the other on. In-process on purpose, like
the meter's (one API instance, ADR-0026): a restart finds no claim and the bot's actions are refused, never misrouted.

Inert until the owner sets `TILO_MEETING_ACTIONS=1` (read per request); then `get_action_claims()` is the registry."""

from __future__ import annotations

import hmac
import os
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

ENV_ENABLED = "TILO_MEETING_ACTIONS"
CLAIM_TTL_S = 3500.0  # the attend request's own read timeout: no claim outlives its attend
MAX_ACTIONS = 5  # writes per call, whoever asks (owner decision 21 Oct)
_ABSENT = "-" * 32  # compared when there is no claim, so absent, wrong and expired cost the same one comparison


def enabled() -> bool:
    return os.environ.get(ENV_ENABLED) == "1"


@dataclass
class ActionClaim:
    uid: str  # the meeting owner who sent Tilo: the actor one-on-one, and the viewer for name matching
    org_id: str
    meeting_id: str
    nonce: str
    expires_at: float
    done: int = 0  # writes made under this claim
    replies: dict[str, tuple[int, dict[str, Any]]] = field(default_factory=dict)  # key -> the answer it got
    # the context read per scope (one-on-one?): (monotonic time it was built, the answer), reused for CONTEXT_TTL_S
    contexts: dict[bool, tuple[float, dict[str, Any]]] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)


class ActionClaims:
    def __init__(self, *, clock: Callable[[], float] = time.monotonic, ttl_s: float = CLAIM_TTL_S) -> None:
        self._clock, self._ttl, self._claims, self._lock = clock, ttl_s, dict[str, ActionClaim](), threading.Lock()

    def open(self, meeting_id: str, *, uid: str, org_id: str) -> str:
        nonce = secrets.token_urlsafe(24)
        claim = ActionClaim(uid, org_id, meeting_id, nonce, self._clock() + self._ttl)
        with self._lock:
            self._claims[meeting_id] = claim
        return nonce

    def find(self, meeting_id: str, nonce: str) -> ActionClaim | None:
        """The claim, or None: absent, a wrong nonce, another attend's and an expired claim are one answer and one
        comparison."""
        with self._lock:
            claim = self._claims.get(meeting_id)
        same = hmac.compare_digest(nonce, claim.nonce if claim is not None else _ABSENT)
        return claim if same and claim is not None and self._clock() < claim.expires_at else None

    def end(self, meeting_id: str, nonce: str) -> None:
        """Closes this attend's claim (a later attend's is left alone). Never raises: it runs in a `finally`."""
        with self._lock:
            claim = self._claims.get(meeting_id)
            if claim is not None and claim.nonce == nonce:
                del self._claims[meeting_id]


_CLAIMS = ActionClaims()


def get_action_claims() -> ActionClaims | None:
    """The process's registry, or None while meeting actions are off (the default)."""
    return _CLAIMS if enabled() else None
