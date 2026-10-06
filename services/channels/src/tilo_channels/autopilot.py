"""tilo_channels.autopilot: Email Autopilot preview with Send / Edit / Cancel (L1) and send with a 60 s undo window
(L2) (FR-CHN-11; PRD 10.4, 11.2, 11.4 Preview and Undo; OB-01 to OB-05; BQ-152 to BQ-158).

The tier is deterministic: `send_email` is T2 unless a modifier applies (`money_or_legal` from `t3_content_signal` on
the raw body, which it cleans itself; `safety_flag`; `new_recipients` for an address that is neither a contact nor
known from the thread, BQ-154, BQ-223, or any forward, new email, format mismatch or Bcc, FR-CHN-12; `attachments`),
and any modifier makes it T3. Only a ready T2 draft of the person's own non-empty instruction, answering a message
whose one replied-to message is clean (BQ-274: no money, legal or commitment signal in its body or Subject, a DMARC
pass, no shared Message-ID), under an L2 answer from the injected policy port, is scheduled at once with the undo
window; everything else waits for its owner's Send. A redraft after Edit is a new proposal and always waits for a
person. Side effects go only through the injected outbox port, keyed so a replay never adds an
entry. Cards hold mail text; no event, log line or key does.
"""

from __future__ import annotations

import copy
import hashlib
import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass, fields
from typing import Any, Protocol

import tilo_policy

from tilo_channels.autopilot_gate import evidence_for, opens, requested_part
from tilo_channels.autopilot_inbound import inbound_is_clean
from tilo_channels.autopilot_policy import DECISION_MAX_AGE_S, PolicyPort
from tilo_channels.autopilot_send import index_artifact
from tilo_channels.autopilot_state import (
    ACTION_TYPE,
    CancelPending,
    CardStore,
    Ledger,
    Outbox,
    StaleDecision,
    StopQueue,
    timestamp,
    ulid,
)
from tilo_channels.autopilot_t3 import clean_text, t3_content_signal
from tilo_channels.drafting import (
    MAX_INSTRUCTION,
    MAX_MESSAGES,
    Draft,
    Drafter,
    DraftResult,
    ThreadReader,
    _address,
    _addresses,
    _base,
)

__all__ = ["ACTION_TYPE", "Autopilot", "CancelPending", "DraftContext", "Outbox", "Outcome", "Preview", "clean_text"]
__all__ += ["CardStore", "StopQueue", "t3_content_signal", "DECISION_MAX_AGE_S"]

OPTIONS = ("send", "edit", "cancel")
REPLY_FORMATS = ("reply", "reply_all")  # stay in the thread; everything else adds a recipient (BQ-145, BQ-171)
FORMATS = REPLY_FORMATS + ("forward", "new")
UNDO_WINDOW_S = 60  # PRD 10.4 L2 default
SWEEP_INTERVAL_S = 10  # how often production runs Autopilot.sweep(): several tries inside the window (BQ-187)
PREVIEW_CHARS = 600  # PRD 11.4 Preview
FINDING_CAP = 300  # characters of one finding's text shown on a card (issue #243)

_LOG = logging.getLogger(__name__)
_TUPLES = ("options", "to", "cc", "findings", "questions", "modifiers")


@dataclass(frozen=True)
class DraftContext:
    instruction_id: str
    thread_id: str
    instruction: str
    mailbox: str
    mode: str = "reply"


class AutonomyPolicy(Protocol):
    def decide(self, user_id: str, proposal: tilo_policy.Proposal) -> tilo_policy.Decision: ...  # CHN-WIRE-4
    def level(self, user_id: str, action_type: str) -> tuple[str, str | None]: ...


@dataclass(frozen=True)
class Preview:
    card_id: str
    user_id: str
    instruction_id: str
    status: str
    options: tuple[str, ...]
    to: tuple[str, ...]
    cc: tuple[str, ...]
    subject: str
    excerpt: str
    body: str
    findings: tuple[str, ...]
    questions: tuple[str, ...]
    tier: str | None
    modifiers: tuple[str, ...]
    level: str
    undo_window_s: int
    outbox_id: str | None
    scheduled_at: str | None


@dataclass(frozen=True)
class Outcome:
    status: str  # send: queued | scheduled | refused; cancel: cancelled | too_late | refused
    outbox_id: str | None


def _card_id(user_id: str, instruction_id: str) -> str:
    return "apc_" + hashlib.sha256(f"{user_id}\n{instruction_id}".encode()).hexdigest()[:32]


def _preview(doc: dict[str, Any]) -> Preview:
    values: dict[str, Any] = {f.name: tuple(doc[f.name]) if f.name in _TUPLES else doc[f.name] for f in fields(Preview)}
    return Preview(**values)


class Autopilot:
    def __init__(
        self,
        *,
        drafter: Drafter,
        reader: ThreadReader,
        contacts: Callable[[str], Iterable[str]],
        policy: AutonomyPolicy,
        outbox: Outbox,
        cards: CardStore,
        clock: Callable[[], float],
        emit: Callable[[dict], None] = lambda part: None,  # the gate's approval.requested only
        world_id: str,
        run_id: str,
        connector: str = "gmail",
        stops: StopQueue | None = None,  # None only for benches that never sweep; production passes one (BQ-187)
        fake_evidence: bool = False,  # TESTS ONLY (BQ-228): the old unapproved Send; production never passes it
        world_owner: str | Callable[[], str | None] | None = None,  # the world's owner, from the world record (BQ-226)
        district: str = "D1",  # the district the policy is asked about (BQ-242)
    ) -> None:
        self._fake, self._owner = fake_evidence, world_owner
        self._drafter, self._reader, self._contacts, self._emit = drafter, reader, contacts, emit
        self._policy, self._cards, self._clock, self._stops = policy, cards, clock, stops
        self._world_id = world_id
        self._ledger = Ledger(
            cards=cards, outbox=outbox, clock=clock, world_id=world_id, run_id=run_id, connector=connector, stops=stops
        )
        self._port = PolicyPort(
            policy=policy,
            cards=cards,
            ledger=self._ledger,
            clock=clock,
            emit=emit,
            world_id=world_id,
            connector=connector,
            district=district,
        )

    def preview(self, user_id: str, context: DraftContext, result: DraftResult) -> Preview:
        """The card for a draft of the person's own instruction; at L2 a ready T2 draft is scheduled at once."""
        return self._card(user_id, context, result, instructed=True)

    def _world_owner(self) -> str | None:
        """The trusted owner of this Autopilot's world, never taken from a preview or send argument or a card; None
        when unknown or the lookup fails (production mode then refuses everything)."""
        try:
            owner = self._owner() if callable(self._owner) else self._owner
        except Exception:
            return None
        return owner if isinstance(owner, str) and owner else None

    def _owns(self, user_id: str) -> bool:
        return self._fake or (self._world_owner() is not None and user_id == self._world_owner())

    def owns(self, user_id: str) -> bool:
        """Whether `user_id` is this world's owner: the check `preview` makes first, for callers that must not draft
        for anyone else (FR-PA-07). No behaviour of the card path changes."""
        return self._owns(user_id)

    def _get(self, user_id: str, card_id: str) -> dict[str, Any] | None:
        """The stored card as it stands: an L2 card's newest decision, or L1 once its decision was dropped."""
        return self._port.view(user_id, self._cards.get(user_id, card_id))

    def approval_requested(self, user_id: str, card_id: str) -> dict | None:
        """The card's stored `approval.requested` part (a copy), or None: the same from any instance (CHN-WIRE-1)."""
        part = (self._get(user_id, card_id) or {}).get("approval_requested")
        return copy.deepcopy(part) if isinstance(part, dict) else None

    def policy_applied(self, user_id: str, card_id: str) -> dict | None:
        """The card's live `policy.applied` part (a copy), the same from any instance; None for an L1 card, a dropped
        one or one decided by the legacy `level()` hint (CHN-WIRE-4; BQ-243)."""
        part = (self._get(user_id, card_id) or {}).get("policy_applied")
        return copy.deepcopy(part) if isinstance(part, dict) else None

    def send(self, user_id: str, card_id: str, approval: dict | None = None) -> Outcome:
        """L1 and T3: only with the `approval.resolved` that `tilo-api` recorded for the owner's tap, whose authz the
        entry carries unchanged; its OB-01 / OB-05 check runs before the card's one decision is claimed, so a refusal
        (never raised) leaves the card open. L2 is scheduled by the policy path (unchanged)."""
        doc = self._get(user_id, card_id)
        if doc is None or doc["state"] != "open" or "send" not in doc["options"]:
            return Outcome("refused", None)
        if not self._owns(user_id) or doc.get("user_id") != user_id:  # only the world's owner's own card
            return Outcome("refused", None)
        index_artifact(self._cards, user_id, doc)  # a preview that died before indexing is completed here
        doc = self._port.resolve(user_id, doc)  # a stale L2 decision is made again; dropped, it is an L1 card below
        if doc["level"] == "L2":  # the entry's real state; a stopped card never enqueues again
            entry, doc = self._schedule(user_id, doc)
            if doc["level"] == "L2":
                state = entry["state"] if entry else "cancelled"
                status = (
                    "refused" if state in ("cancelled", "failed") else "scheduled" if state == "scheduled" else "queued"
                )
                return Outcome(status, doc["outbox_id"])
        built: dict[str, Any] = {}
        if not self._fake:  # the gate path: nothing is built from the model, the card or the caller beyond the approval
            evidence = evidence_for(doc, approval, self._world_owner())
            if evidence is None:
                return Outcome("refused", None)
            entry = self._ledger.entry_for(doc, evidence["authorised_by"]["authz"])  # copied, never re-stamped
            if not opens(entry, evidence):
                return Outcome("refused", None)
            built = {"entry": entry, "evidence": evidence}
        if self._ledger.first(user_id, card_id, "decision", "send") != "send":
            return Outcome("refused", None)
        entry = self._ledger.enqueue(doc, **built)
        if entry.get("state") in ("cancelled", "failed"):  # a repeated key returns the stored entry as it stands
            return Outcome("refused", entry["id"])
        self._cards.put(user_id, card_id, doc | {"outbox_id": entry["id"]})
        _LOG.info("autopilot card %s: queued by its owner, %s", card_id, doc["tier"])
        return Outcome("queued", entry["id"])

    def cancel(self, user_id: str, card_id: str) -> Outcome:
        doc = self._get(user_id, card_id)
        if doc is None or doc["state"] == "superseded":
            return Outcome("refused", None)
        if doc["state"] == "open":
            if doc["level"] == "L2" or doc.get(
                "dropped"
            ):  # cancels the entry (a dropped card too) whichever Cancel or Edit claimed the stop first
                status = self._ledger.stop(user_id, doc, "cancel")  # raises CancelPending: retry
            else:  # an L1 card is closed unless its owner's Send came first (a crashed Edit's claim closes it too)
                send_first = self._ledger.first(user_id, card_id, "decision", "close") == "send"
                status = "too_late" if send_first else "cancelled"
            if status == "too_late":
                return Outcome("too_late", doc["outbox_id"])
            self._cards.put(user_id, card_id, doc | {"state": "cancelled"})
            _LOG.info("autopilot card %s: cancelled", card_id)
        return Outcome("cancelled", doc["outbox_id"])

    def edit(self, user_id: str, card_id: str, change: str, *, instruction_id: str) -> Preview | None:
        """Cancels the pending send, then redrafts with the original instruction plus `change` (BQ-155). The new
        card always waits for a person (OB-01, OB-05). None when the card is closed or its send already went."""
        doc = self._get(user_id, card_id)
        if doc is None or not self._owns(user_id):
            return None
        instruction = f"{doc['instruction']}\nChange: {change}"
        if len(instruction) > MAX_INSTRUCTION or "#" in instruction_id or doc["mode"] not in REPLY_FORMATS:
            raise ValueError("edit too long, bad instruction id, or a format the drafter cannot redraft")
        mine = f"edit:{instruction_id}"
        if doc["state"] == "open" and (doc["level"] == "L2" or doc.get("dropped")):
            closed = self._ledger.stop(user_id, doc, mine) == "cancelled"
            closed = closed and self._ledger.first(user_id, card_id, "stop", mine) == mine
        else:
            closed = doc["state"] == "open" and self._ledger.first(user_id, card_id, "decision", mine) == mine
        if closed:
            doc |= {"state": "superseded", "superseded_by": instruction_id}
            self._cards.put(user_id, card_id, doc)
        if doc["state"] != "superseded" or doc.get("superseded_by") != instruction_id:
            return None  # cancelled, too late, or replaced by another edit; the same edit again resumes it
        context = DraftContext(instruction_id, doc["thread_id"], instruction, doc["mailbox"], doc["mode"])
        result = self._drafter.draft(
            user_id,
            instruction_id=instruction_id,
            thread_id=context.thread_id,
            instruction=instruction,
            mailbox=context.mailbox,
            mode=context.mode,
        )
        return self._card(user_id, context, result, instructed=False)

    def sweep(self) -> dict[tuple[str, str], str]:
        """Settles every queued stop of this world's cards (BQ-187): "cancelled", "too_late" or "pending" (stays
        queued for the next run). Another world's card is left queued for that world's sweeper. Never enqueues; one
        card's failure is never raised. Only an owner's Cancel or Edit queues a stop, so a tap that died between
        queueing and recording it is recorded here (fail safe: the send stops)."""
        done: dict[tuple[str, str], str] = {}
        for user_id, card_id in self._stops.pending() if self._stops is not None else []:
            try:
                doc = self._cards.get(user_id, card_id)
                if doc is None or not self._ledger.ours(doc):
                    continue
                self._ledger.first(user_id, card_id, "stop", "sweep")
                done[(user_id, card_id)] = self._ledger.settle(user_id, doc)
            except Exception as exc:  # CancelPending, or a store or outbox failure: the next sweep retries
                _LOG.warning("autopilot card %s: stop not confirmed (%s)", card_id, type(exc).__name__)
                done[(user_id, card_id)] = "pending"
        return done

    def stop_state(self, user_id: str, card_id: str) -> str | None:
        """None (no stop recorded), "pending" (shown as "Not confirmed, retry"), "cancelled" or "too_late" (BQ-188)."""
        if not self._ledger.holds(user_id, card_id, "stop"):
            return None
        return self._ledger.settled(user_id, card_id) or "pending"

    # -- internals ----------------------------------------------------------------------------------------------

    def _card(self, user_id: str, context: DraftContext, result: DraftResult, *, instructed: bool) -> Preview:
        if not self._owns(user_id):  # before anything is read or recorded: no card, no gate, no event
            raise PermissionError("only the world's owner has Autopilot cards in it")
        if result.instruction_id != context.instruction_id:
            raise ValueError("the draft is not of this instruction")
        if result.draft is not None and result.draft.thread_id != context.thread_id:
            raise ValueError("the draft is not of this thread")  # BQ-221: before anything is recorded
        card_id = _card_id(user_id, context.instruction_id)
        doc = self._cards.get(user_id, card_id)
        if doc is None:  # one atomic record fixes tier, level and entry id before any enqueue; first writer wins
            doc = self._decision(user_id, card_id, context, result, instructed)
            if self._cards.create(user_id, card_id, doc):
                if "approval_requested" in doc:  # once: only the instance whose create won emits the gate
                    self._emit(copy.deepcopy(doc["approval_requested"]))
                if "policy_applied" in doc:  # and the decision's event, before any entry (OB-01, HR-7)
                    self._emit(copy.deepcopy(doc["policy_applied"]))
            else:
                doc = self._cards.get(user_id, card_id)
                if doc is None:
                    raise LookupError("card store refused a create but holds no card")
        index_artifact(self._cards, user_id, doc)  # the text DraftArtifacts serves, before any enqueue (BQ-182)
        doc = self._port.resolve(user_id, doc)  # the stored decision, kept only while fresh and bound to this card
        if doc["level"] == "L2" and doc["state"] == "open":  # the recorded decision, never worked out again
            entry, doc = self._schedule(user_id, doc)  # the card's one entry, by its key; none once stopped
            doc = doc | {"scheduled_at": entry["scheduled_at"]} if entry else doc
        _LOG.info("autopilot card %s: %s %s %s", card_id, doc["status"], doc["tier"], doc["level"])
        return _preview(doc)

    def _schedule(self, user_id: str, doc: dict[str, Any]) -> tuple[dict | None, dict[str, Any]]:
        """`Ledger.schedule` for an L2 card, and the card as it then stands. An entry that would be created outside
        its decision's bound is refused and the card decided again; an entry that landed while the decision was
        dropped by another instance is stopped like a Cancel (CHN-WIRE-4: no entry the card's Cancel cannot stop)."""
        for _ in range(3):
            try:
                entry = self._ledger.schedule(user_id, doc)
            except StaleDecision:
                doc = self._port.resolve(user_id, doc)
                if doc["level"] != "L2":
                    return None, doc
                continue
            if entry is not None and self._port.dropped(user_id, doc):
                self._ledger.stop(user_id, doc, "dropped")  # raises CancelPending: retry
                return None, self._port.resolve(user_id, doc)
            return entry, doc
        raise RuntimeError("the card's policy decision did not settle: retry")

    def _decision(
        self, user_id: str, card_id: str, context: DraftContext, result: DraftResult, instructed: bool
    ) -> dict[str, Any]:
        draft = result.draft
        ready = result.status == "ready" and draft is not None
        # BQ-171 to BQ-173: an unknown format, a format mismatch, a Bcc or an attachment is never sent from this card
        # (the preview shows no format, Bcc or attachment), but it is still tiered so the card says why it waits
        sendable = ready and draft is not None and draft.mode == context.mode and draft.mode in FORMATS
        sendable = sendable and draft is not None and not draft.bcc and not draft.attachments
        sendable = sendable and draft is not None and bool(draft.to + draft.cc)  # no recipient: nothing to send
        body = clean_text(draft.body) if draft is not None else ""
        doc: dict[str, Any] = {
            "card_id": card_id,
            "user_id": user_id,
            "world_id": self._world_id,  # its entry's world: only this world enqueues or settles a stop of it
            "instruction_id": context.instruction_id,
            "status": result.status,
            "options": list(OPTIONS if sendable else OPTIONS[1:]),
            "to": list(draft.to) if draft else [],
            "cc": list(draft.cc) if draft else [],
            "subject": clean_text(draft.subject) if draft else "",
            "excerpt": body[:PREVIEW_CHARS],
            "body": body,
            "findings": [clean_text(f"{f.kind}: {f.text[:FINDING_CAP]}") for f in result.findings],
            "questions": [clean_text(q) for q in result.questions],
            "tier": None,
            "modifiers": [],
            "level": "L1",
            "undo_window_s": 0,
            "outbox_id": None,
            "scheduled_at": None,
            "state": "open",
            "thread_id": context.thread_id,
            "mailbox": context.mailbox,
            "mode": context.mode,
            "instruction": context.instruction,
            "item": {"artifact_id": draft.artifact_id, "version": draft.version} if draft else None,
            "in_reply_to": draft.in_reply_to if draft else "",  # the message the draft answers (BQ-185)
            "references": draft.references if draft else "",
        }
        if ready and draft is not None:
            modifiers = ["money_or_legal"] if t3_content_signal(draft.body) else []  # hidden characters too
            modifiers += ["safety_flag"] if self._flagged(user_id, context, result) else []
            modifiers += ["new_recipients"] if self._adds_recipient(user_id, context, draft) else []
            modifiers += ["attachments"] if draft.attachments else []
            doc |= {"tier": "T3" if modifiers else "T2", "modifiers": modifiers}
            reserved = sendable and not self._fake  # a gate at L1 or T3 reserves its entry's id (OB-01)
            blank = not clean_text(context.instruction).strip()  # BQ-222: nothing a person wrote never rides L2
            rides = instructed and sendable and not modifiers and not blank
            # BQ-274: a risky, unauthenticated or unknown replied-to message keeps a clean draft at L1 (no window)
            if rides and inbound_is_clean(self._reader, user_id, context.thread_id, draft.in_reply_to):
                ms = round(self._clock() * 1000)
                if self._port.decides():  # CHN-WIRE-4: the engine's decision; only a clean one rides L2 (fail closed)
                    doc["outbox_id"] = ulid(ms)
                    part = self._port.first(user_id, doc, ms)
                    if part is not None:
                        window, policy_id = part["data"]["undo_window_s"], part["data"]["policy_id"]
                        doc |= {"level": "L2", "undo_window_s": window, "policy_id": policy_id, "policy_applied": part}
                        doc["scheduled_at"] = timestamp(ms + window * 1000)
                        reserved = False
                    else:
                        doc["outbox_id"] = None
                else:
                    level, policy_id = self._policy.level(user_id, ACTION_TYPE)
                    if level == "L2" and policy_id:  # only L2 rides the undo window; anything else waits
                        doc |= {"level": "L2", "undo_window_s": UNDO_WINDOW_S, "policy_id": policy_id}
                        doc |= {"outbox_id": ulid(ms), "scheduled_at": timestamp(ms + UNDO_WINDOW_S * 1000)}
                        reserved = False
            if reserved:
                doc["outbox_id"] = ulid(round(self._clock() * 1000))
                doc["approval_requested"] = requested_part(doc, doc["outbox_id"])
        return doc

    def _flagged(self, user_id: str, context: DraftContext, result: DraftResult) -> bool:
        """BQ-183: the passed result's flags or those of the draft FR-CHN-10 stored for the instruction, if any."""
        stored = self._drafter.stored(user_id, context.instruction_id)
        results = [result] + ([stored] if stored is not None else [])
        return any(r.flagged or (r.draft is not None and r.draft.safety_flag) for r in results)

    def _adds_recipient(self, user_id: str, context: DraftContext, draft: Draft) -> bool:
        """FR-CHN-12: a forward, a new email, an unknown or mismatched format and any Bcc always add a recipient
        (BQ-171, BQ-173); otherwise any To / Cc address not known after lower-casing alone (BQ-174)."""
        if draft.mode != context.mode or draft.mode not in REPLY_FORMATS or draft.bcc:
            return True
        known = self._known(user_id, context)  # ASCII only: str.lower() folds U+212A KELVIN SIGN to "k"
        return any(not a.isascii() or a.lower() not in known for a in draft.to + draft.cc)

    def _known(self, user_id: str, context: DraftContext) -> set[str]:
        """BQ-154, BQ-223: contacts, the From of the message the reply answers (the last one not from the mailbox; an
        earlier From adds nothing), and To / Cc of the user's own messages: From the mailbox and carrying Gmail's
        SENT label (a From header alone is sender-controlled). A thread that cannot be read adds nothing (fail
        closed: more recipients are new)."""
        known = {a.lower() for a in self._contacts(user_id) if isinstance(a, str) and a.isascii()}
        answered: list[str] = []
        mailbox = _address(context.mailbox)
        own = _base(mailbox) if mailbox else None  # a non-ASCII mailbox vouches for nothing
        try:
            listed = self._reader.get_thread(user_id, context.thread_id).get("messages")
        except Exception:  # any read failure only narrows what is known
            listed = []
        for message in [m for m in (listed if isinstance(listed, list) else []) if isinstance(m, dict)][-MAX_MESSAGES:]:
            sender = _addresses(message.get("from"))[:1]
            labels = message.get("labelIds")
            if not sender or _base(sender[0]) != own:
                answered = sender  # the last one wins; a sender that cannot be read leaves nothing known
            elif isinstance(labels, list) and "SENT" in labels:
                known.update(_addresses(message.get("to")) + _addresses(message.get("cc")))
        return known | set(answered)
