"""Support for the FR-HIL-10 claim-race tests (issue #338 item 2; PRD 10.2, 10.3, 10.6; `hil_wait_support.py`).

NEW CONTRACT these tests pin: `tilo_harness.question_wait.AlreadyCommitted` is an `Exception`. A writer's `emit(...)`
raises it when the event id it was given is already committed under OTHER content (an earlier answer won although its
caller saw a failure); `exc.args[0]` may be the committed event dict. `QuestionWait` reads it as "the card is resolved
by the committed event", never as an ordinary failure.

`ScriptedWriter` is the writer double the tests control. Each `emit` follows the next scripted mode, then `commit`:

    commit              the event is committed and returned
    raise               nothing is committed; an ordinary error is raised (the caller saw a failure)
    commit+raise        committed, then raises (commit-then-raise: the caller saw a failure, the event exists)
    block+raise         waits for `release()` (in the calling thread), then raises, nothing committed
    block+commit        waits for `release()`, then commits

An `emit` carrying an `event_id` that is already committed returns that event when the content is the same (a resend,
FR-HIL-07) and raises `AlreadyCommitted(committed_event)` when it differs (type, actor, target or data). An `emit` with
no `event_id` gets a fresh one. Not a test module.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections import deque
from typing import Any

from hil_wait_support import CARD_CREATED, DIRECTOR, DISTRICT, LEAD, FakeAsyncClock, make_card, settle, until

OPTION_OF = {"person": "per_pack", "team_lead": "per_kwh"}  # who answered -> the option the tests give for them
SAFE_DEFAULT = "per_kwh"  # make_card()'s safe_default


class InjectedFailure(Exception):
    """An ordinary error from the writer (the store is down, a timeout): nothing is known to be committed."""


class ScriptedWriter:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.calls: list[dict[str, Any]] = []
        self.entered = threading.Event()  # set when an emit reaches a `block` step
        self._release = threading.Event()
        self._modes: deque[str] = deque()
        self._lock = threading.Lock()

    def plan(self, *modes: str) -> None:
        self._modes.extend(modes)

    def release(self) -> None:
        self._release.set()

    def commit_directly(self, *, event_id: str, by: str) -> dict[str, Any]:
        """An event somebody else (another process, an earlier attempt) already committed under `event_id`."""
        return self._commit(
            {
                "type": "question.answered",
                "actor": "system",
                "target": LEAD,
                "data": {"answered_by": by},
                "event_id": event_id,
            }  # fmt: skip
        )

    def _commit(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            event_id = kwargs.get("event_id")
            same = ("type", "actor", "target", "data")
            if event_id is not None:
                for event in self.events:
                    if event["id"] == event_id:
                        if all(event[k] == kwargs.get(k) for k in same):
                            return event
                        from tilo_harness.question_wait import AlreadyCommitted  # noqa: PLC0415  (new name; lazy)

                        raise AlreadyCommitted(dict(event))
            event = {k: kwargs.get(k) for k in same + ("summary", "district", "severity", "vis")}
            event["id"] = event_id or f"01JB5VQ0000000000000{900000 + len(self.events):06d}"
            event["seq"] = len(self.events) + 1
            self.events.append(event)
            return event

    def emit(self, **kwargs: Any) -> dict[str, Any]:
        with self._lock:
            self.calls.append(dict(kwargs))
            steps = (self._modes.popleft() if self._modes else "commit").split("+")
        committed: dict[str, Any] | None = None
        for step in steps:
            if step == "block":
                self.entered.set()
                if not self._release.wait(timeout=10):
                    raise InjectedFailure("the blocked emit was never released")
            elif step == "commit":
                committed = self._commit(kwargs)
            elif step == "raise":
                raise InjectedFailure("the writer failed (scripted)")
        assert committed is not None, "a mode that never raises must commit"
        return committed

    def answered(self) -> list[dict[str, Any]]:
        return [e for e in self.events if e["type"] == "question.answered"]


def world(timeout: int = 3600):
    """(QuestionWait, writer, fake clock, card). The clock only moves when told to."""
    from tilo_harness.question_wait import QuestionWait  # noqa: PLC0415

    writer, clock = ScriptedWriter(), FakeAsyncClock()
    return QuestionWait(writer, clock=clock), writer, clock, make_card(timeout=timeout)


async def park(wait: Any, clock: FakeAsyncClock, card: dict[str, Any]) -> asyncio.Future:
    task = asyncio.ensure_future(wait.wait_for(card, lead=LEAD, director=DIRECTOR, district=DISTRICT))
    await until(lambda: clock.pending_sleepers() >= 1 or task.done())
    return task


def attempt(fn: Any, *args: Any) -> Exception | None:
    """Calls `fn(*args)` (a thread-safe `QuestionWait.write`) and returns the exception it raised, else None."""
    try:
        fn(*args)
    except Exception as error:  # noqa: BLE001
        return error
    return None


async def finished(task: asyncio.Future, *, within_s: float = 3.0) -> bool:
    """True if `task` completes within `within_s` of real time (patience only; the fake clock does not move)."""
    deadline = time.perf_counter() + within_s
    while not task.done():
        if time.perf_counter() > deadline:
            return False
        await asyncio.sleep(0.001)
    return True


__all__ = [
    "CARD_CREATED",
    "OPTION_OF",
    "SAFE_DEFAULT",
    "InjectedFailure",
    "ScriptedWriter",
    "attempt",
    "finished",
    "park",
    "settle",
    "world",
]
