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

_DEADLINE = "deadline"  # who claimed a card's resolution when nobody answered


class AlreadyAnswered(Exception):
    """The card was already resolved by another answer, or by its deadline."""


@dataclass(frozen=True)
class Answer:
    card_id: str
    option: str  # the chosen option id; at the deadline the card's safe_default
    answered_by: str  # person | team_lead | default


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


def _resolve(waiter: _Waiter, outcome: Answer | Exception) -> None:
    def settle() -> None:
        if not waiter.future.done():
            if isinstance(outcome, Exception):
                waiter.future.set_exception(outcome)
            else:
                waiter.future.set_result(outcome)

    try:
        waiter.future.get_loop().call_soon_threadsafe(settle)
    except RuntimeError:  # the loop is closed: the run ended and nobody waits any more
        pass


class QuestionWait:
    def __init__(self, writer: Any, *, clock: Clock | None = None) -> None:
        self._writer, self._clock = writer, clock or SystemClock()
        self._lock = threading.Lock()
        self._waiting: dict[str, _Waiter] = {}
        self._claimed: dict[str, str] = {}  # card id -> event id of the resolution that won
        self._early: dict[str, tuple[str | None, str]] = {}  # resolved before anyone waited: (option, answered_by)

    async def wait_for(self, card: dict[str, Any], *, lead: str, director: str, district: str | None) -> Answer:
        card_id = card["id"]
        waiter = _Waiter(card, lead, director, district, asyncio.get_running_loop().create_future())
        with self._lock:  # registered before the first suspension: a part that arrives next is never lost
            early = self._early.pop(card_id, None)
            if early is None:
                self._waiting[card_id] = waiter
        if early is not None:
            return Answer(card_id, early[0] or card["safe_default"], early[1])
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
        director, lead = (waiter.director, waiter.lead) if waiter else ("system", part["district"] or part["world_id"])
        try:
            self._writer.emit(
                type="question.answered", actor=director if by == "default" else "system", target=lead,
                summary=f"The question was answered ({by}).", data={"answered_by": by}, district=part["district"],
                severity=part.get("severity"), vis=part["vis"], event_id=event_id,
            )  # fmt: skip
        except BaseException:
            with self._lock:
                del self._claimed[card_id]  # nothing committed: the same answer may be sent again
            raise
        with self._lock:
            waiter = self._waiting.get(card_id)
            if waiter is None:
                self._early[card_id] = (part.get("option"), by)
        if waiter is not None:
            _resolve(waiter, Answer(card_id, part.get("option") or waiter.card["safe_default"], by))

    async def _at_deadline(self, waiter: _Waiter) -> None:
        card = waiter.card
        deadline = datetime.fromisoformat(card["created_at"]) + timedelta(seconds=card["timeout"])
        while (left := (deadline - self._clock.now()).total_seconds()) > 0:
            await self._clock.sleep(left)
        with self._lock:
            if card["id"] in self._claimed:
                return  # an answer is being written and resumes the unit
            self._claimed[card["id"]] = _DEADLINE
        try:
            self._writer.emit(
                type="question.answered", actor=waiter.director, target=waiter.lead, data={"answered_by": "default"},
                summary="Nobody answered in time, so the Director applied the safe default.", severity="nudge",
                district=waiter.district, vis=[waiter.district] if waiter.district else "all",
            )  # fmt: skip
        except Exception as error:
            with self._lock:
                del self._claimed[card["id"]]
            _resolve(waiter, error)
            return
        _resolve(waiter, Answer(card["id"], card["safe_default"], "default"))
