"""Test doubles for FR-CHN-11 (Email Autopilot preview with Send / Edit / Cancel and the L2 undo window). The API
they drive is pinned in API_FR_CHN_11.md.

Nothing here is production logic. `FakeOutbox` stands in for `tilo_connectors.outbox.Outbox` (same method names):
it checks every entry against contracts/outbox.schema.json (so OB-04, T3 needs a person, is enforced) and OB-02
(scheduled_at = created_at + undo_window_s), dedupes on (world_id, idempotency_key) like OB-03, cancels only a
`scheduled` entry and sends an entry only once it is due by the fake clock. "Sending" only records the entry: no
connector, no network, no real mail. Addresses are fictional `.example` domains.
"""

from __future__ import annotations

import copy
import functools
import importlib
import json
import secrets
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from _channels_lib import FakeClock
from _chn10_lib import USER, MemoryDraftStore, Msg, Rig, Thread, answer, drafting_module, make_rig, message_id_header
from _chn_contracts_lib import CONTRACTS, _registry
from jsonschema import Draft202012Validator

MAILBOX = "sarah.ops@harborview.example"  # CHN-GATE-E: the bench mailbox names its owner (see the note below)
DAVID = "david.miller@harriercharters.example"
SARAH = "sarah.chen@harborview.example"
WORLD = "w_autopilot"
RUN = "r_autopilot"
POLICY_ID = "pol_autopilot_l2"
INSTRUCTION = "Tell David Friday 2pm works."
BENIGN = "Hi David,\n\nFriday 2pm works for us. See you then.\n\nBest,\nSarah"
BENIGN_V2 = "Hi David,\n\nFriday 2pm works for us. Thanks again.\n\nBest,\nSarah"

__all__ = ["USER", "Rig", "Thread", "answer", "make_rig"]

# CHN-GATE-E (ADR-0025, "Migration" and the 8 Oct amendment): the L2 gate no longer guesses names from their position in
# the body; a name rides L2 only when a BASE address local part of the draft's own To / Cc or of the mailbox vouches for
# it (no display name does, no plus tag). The benches' bodies greet "David" (the draft's recipient: david.miller@) and
# sign "Sarah", so the bench mailbox is `sarah.ops@...` (`named_rig`); `scripted_thread(names=...)` adds recipients
# whose local parts are the names a test needs (`Thread.vouch`, the extra To of `ready()`), known from the user's SENT
# mail. `_chn_gate_e_lib.make_bench` goes back to the plain `ops@` mailbox with no such help.
OWN_NAME = f"Sarah Chen <{MAILBOX}>"
# The names a bench thread vouches for: DAVID's address local part and the bench mailbox's.
VOUCHED = frozenset({"david", "miller", "sarah", "chen", "ops"})
# Further names some positive controls use (`scripted_thread(names=...)`).
EXTRA_NAMES = ("Anna Maria", "Jones", "Pat", "Alex")
EXTRA_WORDS = frozenset({"anna", "maria", "jones", "pat", "alex"})


def name_words(*names: str) -> frozenset[str]:
    """The lower-case words of display names: the `names` a gate call is given for them."""
    return frozenset(w.lower() for n in names for w in n.split())


@dataclass
class Mail(Msg):
    """A message with Gmail's `labelIds` (only "SENT" makes it the user's own, BQ-223)."""

    labels: list[str] = field(default_factory=list)

    def as_message(self) -> dict[str, Any]:
        message = super().as_message()
        return message | {"labelIds": list(self.labels)} if self.labels else message


def named_rig() -> Rig:
    """`make_rig()` in the bench mailbox `sarah.ops@...` (see above); every thread still starts with the owner's own
    SENT note to the mailbox itself (it adds no recipient a test could trip over)."""
    note = Mail("m-own-note", OWN_NAME, "Note", "A note for later.", to=[MAILBOX], labels=["SENT"])
    rig = make_rig(own_mail=(note,))
    rig.mailbox = MAILBOX
    return rig


def autopilot_module() -> Any:
    """Imported at call time so a missing module fails the test, not collection."""
    return importlib.import_module("tilo_channels.autopilot")


def fake_evidence_kwargs() -> dict[str, Any]:
    """CHN-WIRE-1 (API_CHN_WIRE_1.md, BQ-228): the FR-CHN-11/13 benches drive `Autopilot.send()` with no approval and
    over a fake outbox (or a `check_entry` accept-all). Once `Autopilot` has the explicit `fake_evidence` mode, they
    opt into it through this helper; production never does. Until the parameter exists this returns {}, so those
    benches stay green before and after the ticket lands. Drop the `inspect` guard once CHN-WIRE-1 is merged."""
    import inspect

    cls = autopilot_module().Autopilot
    return {"fake_evidence": True} if "fake_evidence" in inspect.signature(cls).parameters else {}


def needs_autopilot(test: Callable[..., Any]) -> Callable[..., Any]:
    """A missing `tilo_channels.autopilot` fails once, before Hypothesis generates or shrinks anything."""

    @functools.wraps(test)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        autopilot_module()
        return test(*args, **kwargs)

    return wrapper


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def at(clock: FakeClock) -> datetime:
    return datetime.fromtimestamp(clock(), UTC)


@functools.cache
def _outbox_validator() -> Draft202012Validator:
    schema = json.loads((CONTRACTS / "outbox.schema.json").read_text(encoding="utf-8"))
    return Draft202012Validator(schema, registry=_registry())


class OutboxRefused(Exception):
    pass


_PROBE: dict = {}  # what `FakeOutbox.revoke` passes through `enqueue`: stores nothing, counts nothing


class FakeOutbox:
    """`enqueue(entry, evidence)`, `cancel(outbox_id)`, `dispatch_due()`, as `tilo_connectors.outbox.Outbox`, plus
    CHN-GATE-A's read port (`get`, `get_by_idempotency_key`) and `revoke`."""

    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.entries: dict[str, dict] = {}
        self._keys: dict[tuple[str, str], str] = {}
        self.revoked: set[tuple[str, str]] = set()
        self.sent: list[tuple[str, datetime]] = []
        self.enqueue_calls = 0
        self._lock = threading.Lock()

    def enqueue(self, entry: dict, evidence: dict) -> dict:
        if entry is _PROBE:
            return {}
        with self._lock:
            if (entry.get("world_id"), entry.get("idempotency_key")) in self.revoked:
                raise OutboxRefused("the key was revoked: the outbox refuses to create it")
            self.enqueue_calls += 1
            errors = [e.message for e in _outbox_validator().iter_errors(entry)]
            if errors:
                raise OutboxRefused(f"outbox.schema.json: {errors[0]}")
            if not isinstance(evidence, dict):
                raise OutboxRefused("evidence must be a dict")
            window = entry["undo_window_s"]
            if entry["state"] != ("queued" if window == 0 else "scheduled"):
                raise OutboxRefused("OB-02: a new entry is 'queued' with no window, else 'scheduled'")
            created = parse_ts(entry["created_at"])
            if parse_ts(entry["scheduled_at"]) - created != timedelta(seconds=window):
                raise OutboxRefused("OB-02: scheduled_at must be created_at + undo_window_s")
            if abs((created - at(self.clock)).total_seconds()) > 1:
                raise OutboxRefused("created_at must come from the injected clock")
            key = (entry["world_id"], entry["idempotency_key"])
            if key in self._keys:
                return copy.deepcopy(self.entries[self._keys[key]])
            if entry["id"] in self.entries:
                raise OutboxRefused("id already stored under another idempotency_key")
            self.entries[entry["id"]] = copy.deepcopy(entry)
            self._keys[key] = entry["id"]
            return copy.deepcopy(entry)

    def cancel(self, outbox_id: str) -> dict:
        with self._lock:
            entry = self.entries.get(outbox_id)
            if entry is None or entry["state"] != "scheduled":
                raise OutboxRefused("not 'scheduled'")
            entry["state"] = "cancelled"
            return copy.deepcopy(entry)

    def get(self, outbox_id: str) -> dict | None:
        with self._lock:
            return copy.deepcopy(self.entries.get(outbox_id))

    def get_by_idempotency_key(self, world_id: str, idempotency_key: str) -> dict | None:
        with self._lock:
            outbox_id = self._keys.get((world_id, idempotency_key))
        return self.get(outbox_id) if outbox_id is not None else None

    def revoke(self, world_id: str, idempotency_key: str) -> dict | None:
        """Writes the key like an enqueue and cancels like a cancel, so it goes through this instance's `enqueue` (with
        a probe that stores nothing) and `cancel`: an FR-CHN-11 bench that faults either one faults a revocation too."""
        self.enqueue(_PROBE, {})
        key = (world_id, idempotency_key)
        with self._lock:
            outbox_id = self._keys.get(key)
            if outbox_id is None:
                self.revoked.add(key)
                return None
            scheduled = self.entries[outbox_id]["state"] == "scheduled"
        if scheduled:
            try:
                return self.cancel(outbox_id)
            except OutboxRefused:  # no longer scheduled, or the bench refuses: answer what is stored
                pass
        return self.get(outbox_id)

    def dispatch_due(self) -> list[dict]:
        with self._lock:
            now, out = at(self.clock), []
            for entry in self.entries.values():
                due = entry["state"] == "queued" or (
                    entry["state"] == "scheduled" and parse_ts(entry["scheduled_at"]) <= now
                )
                if due:
                    entry["state"] = "sent"
                    self.sent.append((entry["id"], now))
                    out.append(copy.deepcopy(entry))
            return out

    def state(self, outbox_id: str) -> str:
        return self.entries[outbox_id]["state"]

    def all(self) -> list[dict]:
        return [copy.deepcopy(e) for e in self.entries.values()]

    def sent_entries(self) -> list[dict]:
        return [copy.deepcopy(self.entries[i]) for i, _ in self.sent]


class FakePolicy:
    """The autonomy-policy port: `level(user_id, action_type) -> (level, policy_id)`. With level "L2" it is
    deliberately permissive for every send; the autopilot must still never auto-send T3."""

    def __init__(self, level: str = "L1") -> None:
        self._level = level
        self.calls: list[tuple[str, str]] = []

    def level(self, user_id: str, action_type: str) -> tuple[str, str | None]:
        self.calls.append((user_id, action_type))
        return (self._level, None if self._level == "L1" else POLICY_ID)


class FakeContacts:
    def __init__(self, known: Iterable[str] = ()) -> None:
        self.known = {a.lower() for a in known}

    def __call__(self, user_id: str) -> list[str]:
        return sorted(self.known)


class EventLog:
    def __init__(self) -> None:
        self.parts: list[dict[str, Any]] = []

    def __call__(self, part: dict[str, Any]) -> None:
        self.parts.append(copy.deepcopy(part))


@dataclass
class Bench:
    rig: Rig
    outbox: FakeOutbox
    policy: FakePolicy
    contacts: FakeContacts
    cards: MemoryDraftStore
    events: EventLog
    ap: Any = None

    def new_autopilot(self) -> Any:
        """Another instance over the same stores and outbox (a restart, or a second Cloud Run instance)."""
        return autopilot_module().Autopilot(
            drafter=self.rig.svc,
            reader=self.rig.reader,
            contacts=self.contacts,
            policy=self.policy,
            outbox=self.outbox,
            cards=self.cards,
            clock=self.rig.clock,
            emit=self.events,
            world_id=WORLD,
            run_id=RUN,
            **fake_evidence_kwargs(),
        )


def make_bench(level: str = "L2", contacts: Iterable[str] = ()) -> Bench:
    rig = named_rig()
    bench = Bench(rig, FakeOutbox(rig.clock), FakePolicy(level), FakeContacts(contacts), MemoryDraftStore(), EventLog())
    bench.ap = bench.new_autopilot()
    return bench


def context(
    thread: Thread, *, instruction: str = INSTRUCTION, instruction_id: str | None = None, mode: str = "reply"
) -> Any:
    return autopilot_module().DraftContext(
        instruction_id=instruction_id or "ins-" + secrets.token_hex(6),
        thread_id=thread.thread_id,
        instruction=instruction,
        mailbox=thread.mailbox,
        mode=mode,
    )


def reply_target(thread: Thread) -> str:
    """The Message-ID header a real Drafter puts in `in_reply_to` / `references`: that of the thread's last inbound
    message (the inbound-aware L2 check, FR-CHN-11, looks that message up). A thread with no inbound message keeps a
    placeholder."""
    try:
        return message_id_header(thread.last_inbound(thread.mailbox).message_id)
    except IndexError:
        return "<m@mail.example>"


def ready(
    thread: Thread,
    body: str,
    *,
    to: tuple[str, ...] | None = None,
    cc: tuple[str, ...] = (),
    safety_flag: bool = False,
    flagged: bool = False,
    instruction_id: str | None = None,
    mode: str = "reply",
) -> Any:
    """A FR-CHN-10 `ready` DraftResult built directly: what the checker passed, with no findings."""
    mod = drafting_module()
    to = (DAVID, *thread.vouch) if to is None else to
    iid = instruction_id or "ins-" + secrets.token_hex(6)
    target = reply_target(thread)
    draft = mod.Draft(
        artifact_id="art_" + secrets.token_hex(6),
        version=1,
        thread_id=thread.thread_id,
        mode=mode,
        to=to,
        cc=cc,
        bcc=(),
        subject="Re: Engine tuneup scheduling",
        in_reply_to=target,
        references=target,
        body=body,
        attachments=(),
        safety_flag=safety_flag,
    )
    return mod.DraftResult(instruction_id=iid, status="ready", draft=draft, findings=(), questions=(), flagged=flagged)


def pair(
    thread: Thread, body: str, *, instruction: str = INSTRUCTION, mode: str = "reply", **ready_kw: Any
) -> tuple[Any, Any]:
    """(DraftContext, ready DraftResult) for the same instruction id and format (BQ-171: a mismatch is T3)."""
    ctx = context(thread, instruction=instruction, mode=mode)
    return ctx, ready(thread, body, instruction_id=ctx.instruction_id, mode=mode, **ready_kw)


def drafted(bench: Bench, thread: Thread, instruction: str = INSTRUCTION) -> tuple[Any, Any]:
    """Drafts through the real FR-CHN-10 Drafter; returns (DraftContext, DraftResult)."""
    ctx = context(thread, instruction=instruction)
    result = bench.rig.svc.draft(
        USER,
        instruction_id=ctx.instruction_id,
        thread_id=thread.thread_id,
        instruction=instruction,
        mailbox=thread.mailbox,
    )
    assert result.status == "ready", "FR-CHN-11 test setup: the benign draft must pass the FR-CHN-10 checker"
    return ctx, result


def scripted_thread(bench: Bench, *bodies: str, names: Iterable[str] = ()) -> Thread:
    """A bench thread. `names` become extra recipients of a `ready()` draft whose address local parts are those names
    (`anna.maria@...`), known from the user's own SENT mail, so a body may greet or sign them (CHN-GATE-E: only an
    address local part of the draft's own recipients or the mailbox vouches for a name)."""
    addresses = tuple(f"{'.'.join(n.lower().split())}@harriercharters.example" for n in names)
    note = Mail(
        "m-names", f"Sarah Chen <{bench.rig.mailbox}>", "Note", "A note.", to=[DAVID, *addresses], labels=["SENT"]
    )
    thread, _ = bench.rig.thread(earlier=(note,) if addresses else (), answers=tuple(answer(b) for b in bodies))
    thread.vouch = addresses
    return thread
