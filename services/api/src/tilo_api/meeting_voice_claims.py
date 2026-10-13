"""ADR-0042 decision 2 (BQ-M2-4, BQ-M2-5; MV-02, MV-08, MV-14, MV-16): the attend claim.

`meeting_bot.attend_meeting` is the only code that makes one, from the verified principal (uid and org), after the
`joining` claim commits and before the bot is called; it closes it in its `finally`. The meter routes
(`meeting_voice_meter`) find it by meeting id and the attend's random nonce, which the bot echoes. A bot body never
carries a uid or an org, so there is nothing to forge. In-process on purpose (one API instance, ADR-0026): a restart or
a second instance finds no claim and the bot speaks its local voice, never unmetered.

Inert until the user answers BQ-M2-5: `TILO_VOICE_METER` must be exactly "1" (read per request), else
`get_attend_claims()` is None, no claim is made and the bot is called exactly as before."""

from __future__ import annotations

import hmac
import logging
import os
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from tilo_api import spend

logger = logging.getLogger("tilo_api.meeting_voice")
ENV_ENABLED = "TILO_VOICE_METER"
CLAIM_TTL_S = 3500.0  # the attend request's own read timeout (`MeetingBotRpc.attend`): no claim outlives its attend
_ABSENT = "-" * 32  # compared when there is no claim, so absent, wrong and expired cost the same one comparison


def enabled() -> bool:
    return os.environ.get(ENV_ENABLED) == "1"


@dataclass
class Hold:
    """One spoken reply's hold. `state` leaves "open" once, for good: a closed key is never reopened (MV-05)."""

    plan: spend.UnitPlan
    guard: spend.SpendGuard
    unit: int
    reserved_at: float
    state: str = "open"  # open | settled | released

    def settle_whole(self) -> None:
        """A reply nobody closed may have reached the model, so the count can only be too high, never too low."""
        self.guard.settle_unit(self.plan, self.unit)
        self.state = "settled"


@dataclass
class Claim:
    uid: str
    org_id: str
    run_id: str
    nonce: str
    expires_at: float
    holds: dict[str, Hold] = field(default_factory=dict)
    reserves: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)

    def open_hold(self) -> Hold | None:
        return next((h for h in self.holds.values() if h.state == "open"), None)

    def settle_stale(self, now: float, ttl_s: float) -> None:
        """MV-17(a): a hold open longer than `ttl_s` (3 x voice.live.timeout_s) is settled at the whole unit, so a bot
        that died mid-reply does not hold the meeting's Live voice until the claim ends. Callers hold `lock`."""
        for hold in self.holds.values():
            if hold.state == "open" and now - hold.reserved_at > ttl_s:
                hold.settle_whole()


class AttendClaims:
    def __init__(self, *, clock: Callable[[], float] = time.monotonic, ttl_s: float = CLAIM_TTL_S) -> None:
        self._clock, self._ttl, self._claims, self._lock = clock, ttl_s, dict[str, Claim](), threading.Lock()

    def now(self) -> float:
        return self._clock()

    def open(self, meeting_id: str, *, uid: str, org_id: str) -> str:
        """The nonce of this attend. The meeting's `joining` claim already allows only one attend at a time."""
        nonce = secrets.token_urlsafe(24)
        claim = Claim(uid, org_id, meeting_id, nonce, self._clock() + self._ttl)
        with self._lock:
            self._claims[meeting_id] = claim
        return nonce

    def find(self, meeting_id: str, nonce: str) -> Claim | None:
        """The claim, or None: absent, a wrong nonce, another attend's and an expired claim are one answer and one
        comparison (MV-14, MV-16)."""
        with self._lock:
            claim = self._claims.get(meeting_id)
        same = hmac.compare_digest(nonce, claim.nonce if claim is not None else _ABSENT)
        return claim if same and claim is not None and self._clock() < claim.expires_at else None

    def end(self, meeting_id: str, nonce: str) -> None:
        """Closes this attend's claim (a later attend's is left alone) and settles its open holds at the whole unit
        (MV-08). Never raises: it runs in the attend's `finally`."""
        with self._lock:
            claim = self._claims.get(meeting_id)
            if claim is None or claim.nonce != nonce:
                return
            del self._claims[meeting_id]
        with claim.lock:
            for hold in claim.holds.values():
                if hold.state == "open":
                    try:
                        hold.settle_whole()
                    except Exception as exc:  # the unit stays held, which can only count too high
                        logger.warning("meeting voice hold not settled (%s)", type(exc).__name__)


_CLAIMS = AttendClaims()


def get_attend_claims() -> AttendClaims | None:
    """The process's registry, or None while the meter is off (the default)."""
    return _CLAIMS if enabled() else None
