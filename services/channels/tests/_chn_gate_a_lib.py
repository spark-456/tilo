"""Test doubles for CHN-GATE-A (issue #256 gates on FR-CHN-11): the outbox read port and revocation, and the stop
sweeper. The API they drive is pinned in API_CHN_GATE_A.md.

Nothing here is production logic.

- `GateOutbox` is `_chn11_lib.FakeOutbox` (schema, OB-02 and OB-03 checks, fake-clock dispatch) plus the pinned read
  port (`get`, `get_by_idempotency_key`) and `revoke`. It counts every port call and can be put "down" (raise before
  doing anything) or "lost" (do it, then raise) per method. `dispatch_due` is never faulted. Sending only records.
- `MemoryStopQueue` is the pinned `StopQueue` port.
- `Rig` drives one L2 card through fresh `Autopilot` instances (other instances, or a restart) with one-shot faults:
  an outbox call down or its answer lost, the instance dying (`Died`, a BaseException, so nothing catches it as an
  outbox error) before or after its n-th outbox / card-store / stop-queue call, or another owner's action landing while
  an enqueue is in flight. It records what a stop did: `violations` lists every `enqueue` called by a Cancel, Edit or
  sweep and every entry stored by an enqueue that started after a recorded stop.

Fake clock only; no network, no real mail. Addresses are fictional `.example` domains (`_chn11_lib`).
"""

from __future__ import annotations

import collections
import copy
import functools
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import pytest
from _chn11_lib import (
    BENIGN,
    RUN,
    USER,
    WORLD,
    Bench,
    EventLog,
    FakeContacts,
    FakeOutbox,
    FakePolicy,
    MemoryDraftStore,
    OutboxRefused,
    autopilot_module,
    fake_evidence_kwargs,
    named_rig,
    pair,
    scripted_thread,
)

__all__ = ["BENIGN", "USER", "WORLD", "OutboxRefused", "autopilot_module"]

STOPPERS = ("cancel", "edit", "sweep")
PORT = ("enqueue", "cancel", "revoke", "get", "get_by_idempotency_key")


class OutboxDown(Exception):
    """The outbox is unavailable, or its answer was lost."""


class Died(BaseException):
    """The instance dies here (SIGKILL, OOM): not an Exception, so no outbox error handler swallows it."""


def card_id_of(ctx: Any) -> str:
    return autopilot_module()._card_id(USER, ctx.instruction_id)


def key_of(card_id: str) -> str:
    return f"autopilot:{card_id}"


def needs_sweeper(test: Callable[..., Any]) -> Callable[..., Any]:
    """A missing `Autopilot.sweep` fails once, before Hypothesis generates or shrinks anything."""

    @functools.wraps(test)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        autopilot = autopilot_module().Autopilot
        for name in ("sweep", "stop_state"):
            if not hasattr(autopilot, name):
                pytest.fail(f"CHN-GATE-A: Autopilot.{name} is missing (API_CHN_GATE_A.md)")
        return test(*args, **kwargs)

    return wrapper


class GateOutbox(FakeOutbox):
    """FakeOutbox + the pinned read port and revocation. `down` / `lost`: method names to fault."""

    def __init__(self, clock: Any) -> None:
        super().__init__(clock)
        self._lock = threading.RLock()  # FakeOutbox's methods re-enter it from here
        self.revoked: set[tuple[str, str]] = set()
        self.down: set[str] = set()
        self.lost: set[str] = set()
        self.port_calls: collections.Counter[str] = collections.Counter()

    def _enter(self, name: str) -> None:
        with self._lock:
            self.port_calls[name] += 1
        if name in self.down:
            raise OutboxDown(f"outbox unavailable ({name})")

    def _leave(self, name: str, value: Any) -> Any:
        if name in self.lost:
            raise OutboxDown(f"{name} applied, answer lost")
        return value

    def enqueue(self, entry: dict, evidence: dict) -> dict:
        self._enter("enqueue")
        with self._lock:
            if (entry.get("world_id"), entry.get("idempotency_key")) in self.revoked:
                raise OutboxRefused("the key was revoked: the outbox refuses to create it")
            stored = super().enqueue(entry, evidence)
        return self._leave("enqueue", stored)

    def cancel(self, outbox_id: str) -> dict:
        self._enter("cancel")
        done = super().cancel(outbox_id)
        return self._leave("cancel", done)

    def get(self, outbox_id: str) -> dict | None:
        self._enter("get")
        with self._lock:
            found = copy.deepcopy(self.entries.get(outbox_id))
        return self._leave("get", found)

    def get_by_idempotency_key(self, world_id: str, idempotency_key: str) -> dict | None:
        self._enter("get_by_idempotency_key")
        with self._lock:
            outbox_id = self._keys.get((world_id, idempotency_key))
            found = copy.deepcopy(self.entries[outbox_id]) if outbox_id is not None else None
        return self._leave("get_by_idempotency_key", found)

    def revoke(self, world_id: str, idempotency_key: str) -> dict | None:
        self._enter("revoke")
        with self._lock:
            outbox_id = self._keys.get((world_id, idempotency_key))
            if outbox_id is None:
                self.revoked.add((world_id, idempotency_key))
                found = None
            else:
                entry = self.entries[outbox_id]
                if entry["state"] == "scheduled":
                    entry["state"] = "cancelled"
                found = copy.deepcopy(entry)
        return self._leave("revoke", found)

    def heal(self) -> None:
        self.down.clear()
        self.lost.clear()

    def policy_entries(self) -> list[dict]:
        return [e for e in self.all() if e["authz"]["by"] == "policy"]


class MemoryStopQueue:
    """The pinned `StopQueue`: thread-safe, insertion-ordered, idempotent add and remove."""

    def __init__(self) -> None:
        self._items: dict[tuple[str, str], None] = {}
        self._lock = threading.Lock()

    def add(self, user_id: str, card_id: str) -> None:
        with self._lock:
            self._items.setdefault((user_id, card_id), None)

    def pending(self) -> list[tuple[str, str]]:
        with self._lock:
            return list(self._items)

    def remove(self, user_id: str, card_id: str) -> None:
        with self._lock:
            self._items.pop((user_id, card_id), None)


@dataclass
class Gate:
    bench: Bench
    outbox: GateOutbox
    stops: MemoryStopQueue = field(default_factory=MemoryStopQueue)

    @property
    def clock(self) -> Any:
        return self.bench.rig.clock

    def autopilot(self, *, sweeper: bool = True) -> Any:
        """A new instance over the shared stores (another Cloud Run instance, or a restart). `sweeper=False` builds it
        exactly as FR-CHN-11 does, without the pinned `stops` argument."""
        extra = {"stops": self.stops} if sweeper else {}
        return autopilot_module().Autopilot(
            drafter=self.bench.rig.svc,
            reader=self.bench.rig.reader,
            contacts=self.bench.contacts,
            policy=self.bench.policy,
            outbox=self.outbox,
            cards=self.bench.cards,
            clock=self.bench.rig.clock,
            emit=self.bench.events,
            world_id=WORLD,
            run_id=RUN,
            **extra,
            **fake_evidence_kwargs(),
        )

    def new_card(self) -> tuple[Any, Any, str]:
        """(DraftContext, ready benign DraftResult, card id) of a new L2-eligible instruction on its own thread."""
        ctx, result = pair(scripted_thread(self.bench), BENIGN)
        return ctx, result, card_id_of(ctx)

    def entry_of(self, card_id: str) -> dict | None:
        with self.outbox._lock:
            outbox_id = self.outbox._keys.get((WORLD, key_of(card_id)))
            return copy.deepcopy(self.outbox.entries[outbox_id]) if outbox_id else None

    def run_out(self) -> list[dict]:
        """Heals the outbox, moves an hour on, dispatches; returns every sent policy entry."""
        self.outbox.heal()
        self.clock.advance(3600)
        self.outbox.dispatch_due()
        return [e for e in self.outbox.policy_entries() if e["state"] == "sent"]


def make_gate(level: str = "L2") -> Gate:
    rig = named_rig()  # CHN-GATE-E: the owner's own SENT message names "Sarah"
    outbox = GateOutbox(rig.clock)
    bench = Bench(rig, outbox, FakePolicy(level), FakeContacts(), MemoryDraftStore(), EventLog())  # type: ignore[arg-type]
    return Gate(bench, outbox)


class Rig:
    """One L2 card under faults; every action runs on a fresh Autopilot instance.

    One-shot `faults` are consumed by the first matching call, in order:
      ("enqueue", "down" | "lost" | "crash"); ("enqueue", "before" | "after", op, "ok" | "crash") runs another owner's
      `op` while the enqueue is in flight (then the enqueuing instance dies if "crash");
      (call, "down" | "lost") for call in cancel, revoke, get, get_by_idempotency_key;
      ("create" | "put", "crash_before" | "crash_after") around the next card-store write.
    `crash_at = (op, n, "before" | "after")`: the instance running `op` dies before / after its n-th outbox, card-store
    or stop-queue call. `died_on` names that call.
    """

    def __init__(self, *, sweeper: bool = True, step_s: float = 25) -> None:
        self.gate = make_gate("L2")
        self.sweeper, self.step_s = sweeper, step_s
        self.ctx, self.result, self.card_id = self.gate.new_card()
        self.faults: list[tuple] = []
        self.crash_at: tuple[str, int, str] | None = None
        self.died_on: str | None = None
        self.answers: list[str] = []
        self.sweeps: list[dict] = []
        self.violations: list[str] = []
        self.confirmed = False  # a Cancel answered "cancelled", or an Edit of the L2 card returned a redraft
        self.recorded = False  # confirmed, "too_late", or CancelPending raised anywhere: a stop is recorded
        self.stack: list[str] = []
        self._counted = 0
        self._edits = 0
        self._wrap()

    # -- wiring -------------------------------------------------------------------------------------------------

    def _wrap(self) -> None:
        outbox, cards, stops = self.gate.outbox, self.gate.bench.cards, self.gate.stops
        for name in PORT:
            setattr(outbox, name, self._port(name, getattr(outbox, name)))
        for name in ("create", "put"):
            setattr(cards, name, self._write(name, getattr(cards, name)))
        for name in ("add", "remove"):
            setattr(stops, name, self._write(f"stops.{name}", getattr(stops, name)))

    def _tick(self, call: str, when: str) -> None:
        if self.crash_at is None or not self.stack:
            return
        op, n, where = self.crash_at
        if self.stack[-1] != op or where != when:
            return
        self._counted += 1
        if self._counted == n:
            self.crash_at, self.died_on = None, call
            raise Died(f"{op} died {when} its call {n} ({call})")

    def _take(self, kind: str) -> tuple | None:
        for i, fault in enumerate(self.faults):
            if fault[0] == kind:
                return self.faults.pop(i)
        return None

    def _port(self, name: str, real: Callable[..., Any]) -> Callable[..., Any]:
        if name == "enqueue":
            return self._enqueue(real)

        def call(*args: Any) -> Any:
            self._tick(name, "before")
            fault = self._take(name)
            if fault and fault[1] == "down":
                raise OutboxDown(f"{name} unavailable")
            done = real(*args)
            if fault and fault[1] == "lost":
                raise OutboxDown(f"{name} applied, answer lost")
            self._tick(name, "after")
            return done

        return call

    def _enqueue(self, real: Callable[..., Any]) -> Callable[..., Any]:
        def enqueue(entry: dict, evidence: dict) -> dict:
            self._tick("enqueue", "before")
            top = self.stack[-1] if self.stack else None
            if top in STOPPERS:
                self.violations.append(f"{top} called Outbox.enqueue; a stop only reads or revokes")
            after_stop = self.recorded
            fault = self._take("enqueue")
            if fault == ("enqueue", "down"):
                raise OutboxDown("enqueue unavailable")
            if fault and fault[1] == "before":
                self.act(fault[2])
            before = len(self.gate.outbox.entries)
            try:
                stored = real(entry, evidence)
            finally:
                if after_stop and len(self.gate.outbox.entries) > before:
                    self.violations.append("an enqueue that started after a recorded stop stored an entry")
            if fault and fault[1] == "after":
                self.act(fault[2])
            if fault == ("enqueue", "lost"):
                raise OutboxDown("stored, answer lost")
            if fault and (fault == ("enqueue", "crash") or fault[-1] == "crash"):
                raise Died("the enqueuing instance died after the outbox stored the entry")
            self._tick("enqueue", "after")
            return stored

        return enqueue

    def _write(self, name: str, real: Callable[..., Any]) -> Callable[..., Any]:
        kind = name.split(".")[-1] if not name.startswith("stops.") else name

        def write(*args: Any) -> Any:
            self._tick(name, "before")
            fault = self._take(kind)
            if fault and fault[1] == "crash_before":
                raise Died(f"died before {name}")
            done = real(*args)
            if fault:
                raise Died(f"died after {name}")
            self._tick(name, "after")
            return done

        return write

    # -- actions ------------------------------------------------------------------------------------------------

    def act(self, op: str) -> None:
        """One owner action (or a sweep, an advance, a dispatch); failures are what a caller would see."""
        ap = self.gate.autopilot(sweeper=self.sweeper)
        pending = autopilot_module().CancelPending
        self.stack.append(op)
        try:
            if op == "replay":
                ap.preview(USER, self.ctx, self.result)
            elif op == "send":
                ap.send(USER, self.card_id)
            elif op == "cancel":
                status = ap.cancel(USER, self.card_id).status
                self.answers.append(status)
                self.recorded |= status in ("cancelled", "too_late")
                self.confirmed |= status == "cancelled"
            elif op == "edit":
                self._edits += 1
                new = ap.edit(USER, self.card_id, "add a thank you", instruction_id=f"ins-gate-{self._edits}")
                self.answers.append("edited" if new is not None else "none")
                self.recorded |= new is not None
                self.confirmed |= new is not None
            elif op == "sweep":
                self.sweeps.append(ap.sweep())
            elif op == "advance":
                self.gate.clock.advance(self.step_s)
            elif op == "dispatch":
                self.gate.outbox.dispatch_due()
        except pending:
            self.answers.append("CancelPending")
            self.recorded = True
        except Died as exc:
            self.answers.append("Died")
            if op == "sweep":
                self.sweeps.append({"died": str(exc)})
        except (OutboxDown, OutboxRefused) as exc:
            self.answers.append(type(exc).__name__)
            if op == "sweep":
                self.violations.append(f"sweep raised {type(exc).__name__}; a card's failure is never raised")
        finally:
            self.stack.pop()

    def start(self, faults: list[tuple] | None = None) -> None:
        """The first preview (the card is recorded at L2), under `faults`; then a clean slate."""
        self.faults = list(faults or [])
        self.act("replay")
        self.faults.clear()
        self.answers.clear()

    def stop_state(self) -> str | None:
        return self.gate.autopilot().stop_state(USER, self.card_id)

    def check(self) -> list[dict]:
        """Clears faults, moves an hour on, dispatches, and checks the FR-CHN-11 safety rules; returns sent entries."""
        self.faults.clear()
        self.crash_at = None
        sent = self.gate.run_out()
        assert self.violations == [], self.violations
        assert len(self.gate.outbox.policy_entries()) <= 1, "one card, one entry"
        if self.confirmed:
            assert sent == [], f"sent after a confirmed stop: {self.answers}"
        if "too_late" in self.answers:
            assert sent, "too_late although nothing was sent"
        return sent
