"""A unit that asked a person waits for the answer (FR-HIL-10; PRD 10.2, 10.3, 10.6; BQ-207 to BQ-209).

`QuestionWait.wait_for(card, ...)` parks the asking unit until the first of two resolutions of its card: a
`question.answered` part (a person's or a Team Lead's, handed in through `write`, the API CardStore's
`EventWriter`) or the card's deadline (created_at + timeout), when the Director applies the card's safe default and
posts it as a Nudge (EV-08). The first resolution wins and writes exactly one `question.answered`; a later part
raises `AlreadyAnswered` and changes nothing, an identical resend of the winning part writes nothing. An answer for a
card nobody waits on is still recorded (BQ-209). The deadline is waited with the injected clock, never polled, and an
answer resumes the unit as soon as its event is committed. An answer never authorises a side effect.
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from tilo_harness.writer import new_ulid

_DEADLINE = "deadline"  # who claimed a card's resolution when nobody answered


class AlreadyAnswered(Exception):
    """The card was already resolved by another answer, or by its deadline."""


class AlreadyCommitted(Exception):
    """Raised by an event writer when this resolution's event id is already committed under other content: an
    earlier answer won, though its caller saw a failure. `args[0]` is the committed event, when the writer has it."""


@dataclass(frozen=True)
class Answer:
    card_id: str
    option: str | None  # the chosen option id; at the deadline the card's safe_default
    answered_by: str  # person | team_lead | default
    text: str | None = None


class Clock(Protocol):
    def now(self) -> datetime: ...  # aware, UTC

    async def sleep(self, seconds: float) -> None: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


@dataclass
class _Waiter:
    card: dict[str, Any]
    lead: str
    director: str
    district: str | None
    future: asyncio.Future[Answer]
    released: asyncio.Event  # set when an answer's claim on the card is given back (its write failed)


def _resolve(waiter: _Waiter, outcome: Answer | Exception) -> None:
    def settle() -> None:
        if not waiter.future.done():
            if isinstance(outcome, Exception):
                waiter.future.set_exception(outcome)
            else:
                waiter.future.set_result(outcome)

    _on_loop(waiter, settle)


def _on_loop(waiter: _Waiter, call: Any) -> None:
    try:
        waiter.future.get_loop().call_soon_threadsafe(call)
    except RuntimeError:  # the loop is closed: the run ended and nobody waits any more
        pass


class QuestionWait:
    def __init__(self, writer: Any, *, clock: Clock | None = None) -> None:
        self._writer, self._clock = writer, clock or SystemClock()
        self._lock = threading.Lock()
        self._waiting: dict[str, _Waiter] = {}
        self._claimed: dict[str, str] = {}  # card id -> event id of the resolution that won
        self._early: dict[str, tuple[str | None, str, str | None]] = {}  # early option, answerer, typed text
        # Answers whose write raised: each may still have committed (commit-then-raise). card id -> by -> (event id,
        # options tried). An event id carries no option, so a committed event is matched to its attempt only when one
        # option was tried under it: the unit resumes with what was chosen, else with the card's safe default.
        self._tried: dict[str, dict[str, tuple[str, set[str | None]]]] = {}

    async def wait_for(self, card: dict[str, Any], *, lead: str, director: str, district: str | None) -> Answer:
        card_id = card["id"]
        if district is None:
            raise ValueError("a question with no district has no safe visibility")  # never vis "all"
        waiter = _Waiter(card, lead, director, district, asyncio.get_running_loop().create_future(), asyncio.Event())
        with self._lock:  # registered before the first suspension: a part that arrives next is never lost
            early = self._early.pop(card_id, None)
            if early is None:
                self._waiting[card_id] = waiter
        if early is not None:
            option = early[0] if early[2] is not None else early[0] or card["safe_default"]
            return Answer(card_id, option, early[1], early[2])
        deadline = asyncio.ensure_future(self._at_deadline(waiter))
        try:
            return await waiter.future
        finally:
            deadline.cancel()
            with self._lock:
                self._waiting.pop(card_id, None)

    def write(self, part: dict[str, Any]) -> None:
        """The CardStore's part for a question: committed under its own event id, then the unit resumes. Thread-safe."""
        card_id, event_id, by = part["card_id"], part["event_id"], part["data"]["answered_by"]
        with self._lock:
            waiter = self._waiting.get(card_id)
            if waiter is not None and part.get("option") not in {None, *(o["id"] for o in waiter.card["options"])}:
                raise ValueError("the answer names an option the card does not have")
            if card_id in self._claimed:
                if self._claimed[card_id] == event_id:
                    return  # a resend of the resolution already written
                raise AlreadyAnswered(card_id)
            self._claimed[card_id] = event_id
            earlier = self._tried.get(card_id, {}).get(by)
            differs = earlier is not None and bool(earlier[1] - {part.get("option")})
        if differs:  # an earlier attempt under this id chose another option: did it commit? (the id has no option)
            found = self._committed(event_id)
            if found is not None:  # it did: that answer resolved the question; this one is refused and writes nothing
                self._settle_committed(card_id, AlreadyCommitted(found), by)
                raise AlreadyAnswered(card_id)
            with self._lock:
                self._tried.get(card_id, {}).pop(by, None)  # none of those attempts committed
        director, lead = (waiter.director, waiter.lead) if waiter else ("system", part["district"] or part["world_id"])
        try:
            self._writer.emit(
                type="question.answered", actor=director if by == "default" else "system", target=lead,
                summary=f"The question was answered ({by}).", data=part["data"], district=part["district"],
                severity=part.get("severity"), vis=part["vis"], event_id=event_id,
            )  # fmt: skip
        except AlreadyCommitted as exc:  # an earlier answer of this card committed though its caller saw a failure
            self._settle_committed(card_id, exc, by)
            raise AlreadyAnswered(card_id) from None
        except BaseException:
            with self._lock:
                del self._claimed[card_id]  # the same answer may be sent again; it may still have committed
                self._tried.setdefault(card_id, {}).setdefault(by, (event_id, set()))[1].add(part.get("option"))
                waiter = self._waiting.get(card_id)
            if waiter is not None:  # the deadline may have seen this claim and stood down: let it look again
                _on_loop(waiter, waiter.released.set)
            raise
        with self._lock:
            self._tried.pop(card_id, None)
            waiter = self._waiting.get(card_id)
            if waiter is None:
                self._early[card_id] = (part.get("option"), by, part["data"].get("text"))
        if waiter is not None:
            text = part["data"].get("text")
            option = part.get("option") if text is not None else part.get("option") or waiter.card["safe_default"]
            _resolve(waiter, Answer(card_id, option, by, text))

    def _settle_committed(self, card_id: str, exc: AlreadyCommitted, fallback_by: str) -> None:
        """The card's one event is already committed: the unit resumes with the answer that wrote it, never a second."""
        committed = exc.args[0] if exc.args and isinstance(exc.args[0], dict) else {}
        text = (committed.get("data") or {}).get("text")
        by = (committed.get("data") or {}).get("answered_by") or fallback_by
        with self._lock:
            tried = self._tried.pop(card_id, {})
            attempt = tried.get(by)
            options = attempt[1] if attempt else set()
            option = next(iter(options)) if len(options) == 1 else None  # unknown or several: the safe default
            waiter = self._waiting.get(card_id)
            if waiter is None:
                self._early[card_id] = (option, by, text)
        if waiter is not None:
            chosen = option if text is not None else option or waiter.card["safe_default"]
            _resolve(waiter, Answer(card_id, chosen, by, text))

    def _committed(self, event_id: str) -> dict[str, Any] | None:
        lookup = getattr(self._writer, "committed", None)  # the writer's own record of a committed event id
        return lookup(event_id) if lookup else None

    async def _at_deadline(self, waiter: _Waiter) -> None:
        card = waiter.card
        deadline = datetime.fromisoformat(card["created_at"]) + timedelta(seconds=card["timeout"])
        while (left := (deadline - self._clock.now()).total_seconds()) > 0:
            await self._clock.sleep(left)
        while True:
            with self._lock:
                if card["id"] not in self._claimed:
                    self._claimed[card["id"]] = _DEADLINE
                    tried = self._tried.get(card["id"], {})
                    again = next((event_id for event_id, _ in tried.values()), None)
                    break
            # An answer is being written. A success resumes the unit (and ends this wait); a failure gives it back.
            await waiter.released.wait()
            waiter.released.clear()
        # After a write that raised, the default reuses its event id: if that answer did commit, the writer says so.
        # Else it has an id of its own, so a default that committed and then raised is found and counts as written.
        default_id = again or new_ulid(self._clock.now())
        try:
            self._writer.emit(
                type="question.answered", actor=waiter.director, target=waiter.lead, data={"answered_by": "default"},
                summary="Nobody answered in time, so the Director applied the safe default.", severity="nudge",
                district=waiter.district, vis=[waiter.district], event_id=default_id,
            )  # fmt: skip
        except AlreadyCommitted as exc:
            self._settle_committed(card["id"], exc, "default")
            return
        except Exception as error:
            found = self._committed(default_id)
            if not found or (found.get("data") or {}).get("answered_by") != "default":
                with self._lock:
                    del self._claimed[card["id"]]
                _resolve(waiter, error)
                return
        with self._lock:
            self._tried.pop(card["id"], None)
        _resolve(waiter, Answer(card["id"], card["safe_default"], "default"))
