"""Shared, non-test support for the FR-HIL-10 harness acceptance tests (PRD 8.3, 10.2, 10.3, 10.6).

FR-HIL-10: "A routed question appears in <= 2 s; answering resumes the agent in <= 2 s." The API and
console half is pinned in `services/api/tests/API_FR_HIL_10.md` (branch tests/FR-INT-11-12-HIL-10).
This is the harness half: an agent that raised a question parks until `question.answered`, then
resumes. Choices the PRD does not fix are BQ-207..BQ-209 in docs/open-questions.md.

THE INTERFACE THESE TESTS PIN (a builder implements exactly this in `tilo_harness/question_wait.py`
and the `run_plan` change below):

    @dataclass(frozen=True) Answer: card_id: str, option: str, answered_by: str
        answered_by is the contract's answer_source: person | team_lead | default. option is the chosen option id;
        for a timeout it is the card's `safe_default`.

    QuestionWait(writer, *, clock)
        writer   the world's one WorldWriter (or a wrapper with the same emit/append): every event goes through it.
        clock    object with `now() -> datetime` (UTC, aware) and `async sleep(seconds: float) -> None`. Production
                 wraps asyncio and the wall clock; tests inject a fake that only moves when told to, so no real
                 timer can hide a delay. The deadline is waited with `clock.sleep`, never a poll.

    await QuestionWait.wait_for(card, *, lead, director, district) -> Answer
        card       a contracts/card.schema.json `needs_you` card; its deadline is created_at + timeout.
        Registers the card, then waits for the first of (a) its question.answered part or (b) its deadline.
        At the deadline, if still unanswered, the wait itself writes question.answered with answered_by "default",
        severity "nudge" (EV-08), actor `director`, target `lead`, `district` and vis [district], and resolves with
        the card's safe default. Registered synchronously before its first suspension, so a part delivered right
        after `asyncio.create_task(wait_for(...))` has had one loop turn is never lost.

    QuestionWait.write(part: dict) -> None          (the CardStore's `EventWriter` protocol, `tilo_api.cards`)
        `part` is what `CardStore` hands the harness-owned writer for a question:
            {"type": "question.answered", "data": {"answered_by": ...}, "authz": None, "world_id", "card_id",
             "district", "owner_only", "vis": [district], "event_id": <ULID>, "severity"?: "nudge", "option"?: str}
        `option` is the chosen option id and is new (BQ-207: the event's data has no option, the part must carry it).
        Thread-safe: the API calls it from its own threads. It commits the event under `event_id` through the
        writer BEFORE it returns (so "answered" means recorded), then resumes the agent that waits on that card on
        the event loop. A card nobody waits on still gets its event (BQ-209), and resumes nobody. An identical
        resend of a committed part writes nothing and resumes nothing twice.

    run_plan(..., must_ask=None, question_wait=None)   (`must_ask` is the FR-AGT-05 keyword, BQ-201)
        With both, a unit that must ask raises its question (agent.help_requested, agent.escalated,
        question.routed, one card), then WAITS FOR ITS ANSWER instead of parking and returning: it holds no
        `max_specialists` slot while it waits (BQ-209), the other units go on, and `run_plan` returns only when it
        has resumed and finished. On resume the unit's work runs once and `UnitContext.answer` is the `Answer`
        (None for a unit that never asked). Units that depend on it start only after it finished.
        With `must_ask` but no `question_wait`, BQ-201's park-and-return is unchanged.
"""

from __future__ import annotations

import asyncio
import copy
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from agt_support import build_layout, contract_errors
from conftest import CONTRACTS_DIR, sequential_ulid

WORLD = "w_hil_10"
LEAD = "A_lead"
DIRECTOR = "A_dir"
OWNER = "u_owner"
DISTRICT = "D1"
CARD_CREATED = datetime(2026, 9, 29, 9, 30, 0, tzinfo=UTC)  # contracts/fixtures/card/valid/needs_you_blocked.json
RESUME_BUDGET_S = 2.0  # PRD 10.6 FR-HIL-10
SLOW_WRITER_S = 0.5  # as API_FR_HIL_10.md: a slow event writer must still fit the 2 s budget


def layout() -> dict[str, Any]:
    return build_layout(
        world_id=WORLD,
        director_id=DIRECTOR,
        district_specs=[
            {"id": DISTRICT, "lead": LEAD, "specialists": ["A_s0", "A_s1", "A_s2"], "unit_ids": ["U1", "U2", "U3"]}
        ],
    )


def make_card(index: int = 1, *, timeout: int = 3600, safe_default: str = "per_kwh") -> dict[str, Any]:
    """A valid `needs_you` card (card.schema.json) cloned from the contract fixture, with its own id."""
    path = CONTRACTS_DIR / "fixtures/card/valid/needs_you_blocked.json"
    card = copy.deepcopy(json.loads(Path(path).read_text(encoding="utf-8")))
    card.update(id=sequential_ulid(9000 + index), world_id=WORLD, run_id="r_test_1", timeout=timeout)
    card["safe_default"] = safe_default
    assert contract_errors("card", card) == []
    return card


def answered_part(
    card: dict[str, Any],
    *,
    by: str = "person",
    option: str | None = "per_pack",
    index: int = 1,
    severity: str | None = None,
) -> dict[str, Any]:
    """What `tilo_api.cards.CardStore` hands the harness writer for an answered (or timed-out) question."""
    part: dict[str, Any] = {
        "type": "question.answered",
        "data": {"answered_by": by},
        "authz": None,
        "world_id": card["world_id"],
        "card_id": card["id"],
        "district": DISTRICT,
        "owner_only": False,
        "vis": [DISTRICT],
        "event_id": sequential_ulid(7000 + index),
    }
    if option is not None:
        part["option"] = option
    if severity is not None:
        part["severity"] = severity
    return part


class FakeAsyncClock:
    """`now()` and `async sleep()` that only move when `advance()` is called (never a real timer)."""

    def __init__(self, start: datetime = CARD_CREATED) -> None:
        self._now = start
        self._sleepers: list[tuple[datetime, asyncio.Future[None]]] = []

    def now(self) -> datetime:
        return self._now

    async def sleep(self, seconds: float) -> None:
        future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._sleepers.append((self._now + timedelta(seconds=seconds), future))
        await future

    def pending_sleepers(self) -> int:
        return sum(1 for _, future in self._sleepers if not future.done())

    def advance(self, seconds: float) -> None:
        """Call on the event loop's thread."""
        self._now += timedelta(seconds=seconds)
        for wake, future in list(self._sleepers):
            if wake <= self._now and not future.done():
                future.set_result(None)


class SlowWriter:
    """Wraps the real WorldWriter and makes every emit/append take `delay_s` of real time (starts at 0)."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.delay_s = 0.0

    def emit(self, **kwargs: Any) -> Any:
        time.sleep(self.delay_s)
        return self._inner.emit(**kwargs)

    def append(self, event: dict[str, Any]) -> Any:
        time.sleep(self.delay_s)
        return self._inner.append(event)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


async def until(predicate: Callable[[], bool], *, patience_s: float = 10.0) -> None:
    """Lets the loop run (real, tiny sleeps) until `predicate()`: patience only, never what is asserted."""
    deadline = time.perf_counter() + patience_s
    while not predicate():
        if time.perf_counter() > deadline:
            raise AssertionError("until: the condition never became true")
        await asyncio.sleep(0.001)


async def settle() -> None:
    """Enough loop turns (and a hair of real time) for already-possible work to have happened."""
    for _ in range(20):
        await asyncio.sleep(0)
    await asyncio.sleep(0.01)


def events_of(store: Any, type_: str) -> list[dict[str, Any]]:
    return [e for e in store.read_events("org_demo", WORLD) if e["type"] == type_]


# ---------------------------------------------------------------------------
# The FR-AGT-05 must-ask protocol (BQ-201) as a test double, so these tests need nothing unmerged.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FakeAsk:
    reason: str = "ambiguous_brief"
    question: str = "Compare per kWh or per pack?"


class AskingMustAsk:
    """Duck-types `tilo_harness.must_ask.MustAsk` for the executor: `assess` asks for the listed unit ids;
    `raise_question` writes the three chain events and returns the needs_you card (BQ-201)."""

    def __init__(self, ask_unit_ids: set[str], *, timeout: int = 3600, safe_default: str = "per_kwh") -> None:
        self.ask_unit_ids = ask_unit_ids
        self.timeout, self.safe_default = timeout, safe_default
        self.cards: dict[str, dict[str, Any]] = {}  # unit id -> card

    async def assess(self, unit: dict[str, Any], *, failures: int = 0) -> FakeAsk | None:
        return FakeAsk() if unit["id"] in self.ask_unit_ids else None

    def raise_question(
        self,
        ask: FakeAsk,
        *,
        writer: Any,
        unit: dict[str, Any],
        specialist: str,
        lead: str,
        director: str,
        district: str | None = None,
        cause: str | None = None,
    ) -> dict[str, Any]:
        card = make_card(len(self.cards) + 1, timeout=self.timeout, safe_default=self.safe_default)
        at: dict[str, Any] = {"district": district, "level": "L1"}
        asked = writer.emit(
            type="agent.help_requested", actor=specialist, target=lead, summary="The agent asked its Lead.",
            data={"unit": unit["id"]}, cause=cause, **at,
        )  # fmt: skip
        escalated = writer.emit(
            type="agent.escalated", actor=lead, target=director, summary="The Lead asked the Director.",
            data={"reason": ask.reason}, cause=asked["id"], **at,
        )  # fmt: skip
        writer.emit(
            type="question.routed", actor=lead, target=OWNER, summary="The Lead asked you a question.",
            data={"card_id": card["id"], "domain": None}, cause=escalated["id"], **at,
        )  # fmt: skip
        self.cards[unit["id"]] = card
        return card


class AnswerRunner:
    """A `UnitRunner` that records when each unit's work started and the `answer` its context carried."""

    def __init__(self) -> None:
        self.started: dict[str, float] = {}
        self.answers: dict[str, Any] = {}
        self.runs: list[str] = []

    async def run(self, unit: dict[str, Any], context: Any) -> Any:
        from tilo_harness.executor import UnitOutcome

        self.started[unit["id"]] = time.perf_counter()
        self.runs.append(unit["id"])
        self.answers[unit["id"]] = getattr(context, "answer", None)
        await asyncio.sleep(0)
        return UnitOutcome(success=True, summary=f"Finished {unit['id']}.")
