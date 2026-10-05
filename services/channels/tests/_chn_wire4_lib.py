"""Test doubles for CHN-WIRE-4 (FR-CHN-11, issue #307 plan ticket 4 "policy port for L2", issue #256 gate 3): the
autopilot asks `AutonomyPolicy.decide(user_id, proposal)` (a `tilo_policy.Proposal`, answered by a
`tilo_policy.Decision`) instead of the `level()` hint. The API they drive is pinned in API_CHN_WIRE_4.md.

Nothing here is production logic. `DecideStub` is a FAKE engine: it answers whatever a test scripts, stamped from the
fake clock. `EnginePolicy` is a thin pass-through to the REAL `tilo_policy.decide` (with the real risk table and a
contract-valid L2 policy record) for the tests that show the real engine still gates every L2 send while
`coverage.L2_ACTION_RECORDED` is False (BQ-57, ADR-0013 Proposed). The outbox is `FakeOutbox` (OB-02 and the outbox
schema are checked; `check_entry` is not), or the real `tilo_connectors.Outbox` with the REAL `check_entry` where a
test pins that the L2 policy entry is still refused (ticket 5 builds that evidence). No network, no real mail.
"""

from __future__ import annotations

import copy
import json
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import tilo_policy
from _chn10_lib import USER, Thread
from _chn11_lib import (
    BENIGN,
    DAVID,
    MAILBOX,
    POLICY_ID,
    RUN,
    SARAH,
    WORLD,
    EventLog,
    FakeContacts,
    FakeOutbox,
    MemoryDraftStore,
    autopilot_module,
    context,
    make_rig,
    ready,
    scripted_thread,
)
from _chn13_lib import iso
from _chn_0305_lib import CONTRACTS, data_errors

DISTRICT = "D3"
OMIT = object()
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def fresh_ulid() -> str:
    """A contract-valid ULID (policy.applied's `instruction_id` must be one)."""
    return secrets.choice("01234567") + "".join(secrets.choice(_CROCKFORD) for _ in range(25))


def attempt(fn: Callable[[], Any]) -> Any | None:
    """The result of `fn()`, or None when it raised (a down outbox, a refusal): the tests assert on state afterwards."""
    try:
        return fn()
    except Exception:
        return None


def decision(clock: Any, **over: Any) -> Any:
    """A `tilo_policy.Decision` the way the engine's `run_after_undo` looks, stamped now; `over` replaces fields."""
    policy_id = over.get("policy_id", POLICY_ID)
    now = iso(clock())
    window = over.get("undo_window_s", 60)
    fields: dict[str, Any] = {
        "outcome": "run_after_undo",
        "tier": "T2",
        "modifiers": (),
        "level": "L2",
        "policy_id": policy_id,
        "authz": {"by": "policy", "ref": policy_id, "at": now},
        "undo_window_s": window,
        "scheduled_at": iso(clock() + (window if isinstance(window, int) and not isinstance(window, bool) else 60)),
        "reason": "l2_run_after_undo",
    }
    return tilo_policy.Decision(**(fields | over))


def gate_decision(reason: str = "no_covering_policy", level: str = "L1", policy_id: str | None = None) -> Any:
    return tilo_policy.Decision("gate", "T2", (), level, policy_id, None, None, None, reason)


class DecideStub:
    """The fake engine behind the new port: `decide(user_id, proposal)`. `respond` is what a test replaces to script an
    answer (a Decision, anything else, or a raise); by default it answers `run_after_undo` stamped now."""

    def __init__(self, clock: Any) -> None:
        self.clock = clock
        self.calls: list[tuple[str, Any]] = []
        self.respond: Callable[[str, Any], Any] = lambda user_id, proposal: decision(clock)

    def decide(self, user_id: str, proposal: Any) -> Any:
        self.calls.append((user_id, copy.deepcopy(proposal)))
        return self.respond(user_id, proposal)

    def proposals(self) -> list[Any]:
        return [p for _, p in self.calls]


class DecideAndLevelStub(DecideStub):
    """A policy object with BOTH methods: the new port wins; the old hint must never be asked."""

    def __init__(self, clock: Any) -> None:
        super().__init__(clock)
        self.level_calls: list[tuple[str, str]] = []

    def level(self, user_id: str, action_type: str) -> tuple[str, str | None]:
        self.level_calls.append((user_id, action_type))
        return ("L2", POLICY_ID)


class Revocable(DecideStub):
    """Runs after undo until `revoked` (a revocation or "Stop all autopilot"), then gates (`no_covering_policy`)."""

    def __init__(self, clock: Any) -> None:
        super().__init__(clock)
        self.revoked = False
        self.respond = lambda user_id, proposal: gate_decision() if self.revoked else decision(clock)


def l2_policy_record(clock: Any, *, owner: str = USER, district: str = DISTRICT) -> dict:
    """A contract-valid L2 policy of `owner` covering gmail to anyone in `district`, created an hour ago."""
    path = CONTRACTS / "fixtures" / "outbox" / "crossref" / "valid" / "policy_reply_instructed_on_the_web.json"
    record = json.loads(path.read_text(encoding="utf-8"))["policy"]
    created = iso(clock() - 3600)
    return record | {
        "id": POLICY_ID,
        "owner": owner,
        "scope": {"connectors": ["gmail"], "recipients": [], "domains": [], "districts": [district]},
        "expiry": iso(clock() + 365 * 86400),
        "created_by": {"by": owner, "at": created},
        "changed_by": None,
        "history": [{"by": owner, "at": created, "change": "Created at L2", "level": "L2"}],
    }


class EnginePolicy:
    """The REAL `tilo_policy.decide` behind the port (real risk table), over one L2 policy that covers the card."""

    def __init__(self, clock: Any, *, district: str = DISTRICT, owner: str = USER) -> None:
        self.clock, self.owner = clock, owner
        self.policies = [l2_policy_record(clock, owner=owner, district=district)]
        self.calls: list[tuple[str, Any]] = []
        self.decisions: list[Any] = []

    def decide(self, user_id: str, proposal: Any) -> Any:
        self.calls.append((user_id, proposal))
        result = tilo_policy.decide(
            proposal,
            table=tilo_policy.load_risk_table(),
            policies=copy.deepcopy(self.policies),
            world_owner=self.owner,
            applied=[],
            now=iso(self.clock()),
        )
        self.decisions.append(result)
        return result


class GateOutbox(FakeOutbox):
    """`FakeOutbox` that can be down: `enqueue` (and so `revoke`) raise while `down`."""

    def __init__(self, clock: Any) -> None:
        super().__init__(clock)
        self.down = False

    def enqueue(self, entry: dict, evidence: dict) -> dict:
        if self.down:
            raise ConnectionError("the outbox is down")
        return super().enqueue(entry, evidence)


@dataclass
class W4:
    """A production-mode Autopilot (no `fake_evidence`, trusted `world_owner`) over `GateOutbox`, with a scripted
    policy. `new_ap()` is another instance over the same stores (a restart or a second Cloud Run instance)."""

    rig: Any
    outbox: GateOutbox
    cards: MemoryDraftStore
    events: EventLog
    contacts: FakeContacts
    policy: Any
    district: Any = DISTRICT  # OMIT: the Autopilot is built without the keyword
    ap: Any = None

    def new_ap(self, **over: Any) -> Any:
        kw: dict[str, Any] = {
            "drafter": self.rig.svc,
            "reader": self.rig.reader,
            "contacts": self.contacts,
            "policy": self.policy,
            "outbox": self.outbox,
            "cards": self.cards,
            "clock": self.rig.clock,
            "emit": self.events,
            "world_id": WORLD,
            "run_id": RUN,
            "world_owner": USER,
            "district": self.district,
        }
        kw = {k: v for k, v in (kw | over).items() if v is not OMIT}  # OMIT: leave the keyword out
        return autopilot_module().Autopilot(**kw)

    @property
    def clock(self) -> Any:
        return self.rig.clock

    def thread(self, *later_bodies: str) -> Thread:
        """A thread whose scripted model answers BENIGN, then `later_bodies` (for Edit's redrafts)."""
        return scripted_thread(self, BENIGN, *later_bodies)  # type: ignore[arg-type]

    def drafted(self, thread: Thread, instruction_id: str | None = None) -> tuple[Any, Any]:
        """Through the real FR-CHN-10 Drafter, with a ULID instruction id (so a policy.applied can name it)."""
        ctx = context(thread, instruction_id=instruction_id or fresh_ulid())
        result = self.rig.svc.draft(
            USER,
            instruction_id=ctx.instruction_id,
            thread_id=thread.thread_id,
            instruction=ctx.instruction,
            mailbox=MAILBOX,
        )
        assert result.status == "ready", "CHN-WIRE-4 test setup: the benign draft must pass the FR-CHN-10 checker"
        return ctx, result

    def pair(
        self,
        thread: Thread,
        body: str = BENIGN,
        *,
        to: tuple[str, ...] = (DAVID,),
        cc: tuple[str, ...] = (),
        instruction_id: str | None = None,
        instruction: str | None = None,
    ) -> tuple[Any, Any]:
        iid = instruction_id or fresh_ulid()
        kw = {"instruction": instruction} if instruction else {}
        ctx = context(thread, instruction_id=iid, **kw)
        return ctx, ready(thread, body, to=to, cc=cc, instruction_id=iid)

    def entries(self) -> list[dict]:
        return self.outbox.all()

    def of_type(self, event_type: str) -> list[dict]:
        return [p for p in self.events.parts if p.get("type") == event_type]


def make_w4(
    policy: Callable[[Any], Any] | None = None, contacts: tuple[str, ...] = (DAVID, SARAH), district: Any = DISTRICT
) -> W4:
    """`policy` is a factory taking the rig's fake clock (default `DecideStub`)."""
    rig = make_rig()
    w4 = W4(
        rig=rig,
        outbox=GateOutbox(rig.clock),
        cards=MemoryDraftStore(),
        events=EventLog(),
        contacts=FakeContacts(contacts),
        policy=(policy or DecideStub)(rig.clock),
        district=district,
    )
    w4.ap = w4.new_ap()
    return w4


def card_id_of(ctx: Any) -> str:
    return autopilot_module()._card_id(USER, ctx.instruction_id)


def policy_part_errors(part: dict) -> list[str]:
    """Schema errors of a `policy.applied` part: its data, and its authz being a policy stamp (ref == policy_id)."""
    errors = data_errors("policy.applied", part.get("data"))
    authz = part.get("authz") or {}
    if part.get("type") != "policy.applied" or authz.get("by") != "policy":
        errors.append("not a policy.applied part stamped by a policy")
    elif authz.get("ref") != (part.get("data") or {}).get("policy_id"):
        errors.append("authz.ref is not the policy id")
    return errors


def assert_no_send_ever(w4: W4, *, minutes: int = 10) -> None:
    """No entry now, none later, and nothing sent however long the clock runs."""
    w4.clock.advance(minutes * 60)
    w4.outbox.down = False
    w4.outbox.dispatch_due()
    assert w4.entries() == [], "no outbox entry may exist"
    assert w4.outbox.sent == [], "nothing may be sent"
