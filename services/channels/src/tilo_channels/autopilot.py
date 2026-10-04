"""tilo_channels.autopilot: Email Autopilot preview with Send / Edit / Cancel (L1) and send with a 60 s undo window
(L2) (FR-CHN-11; PRD 10.4, 11.2, 11.4 Preview and Undo; OB-01 to OB-05; BQ-152 to BQ-158).

The tier is deterministic: `send_email` is T2 unless a modifier applies (`money_or_legal` from `t3_content_signal` on
the raw body, which it cleans itself; `safety_flag`; `new_recipients` for an address that is neither a contact nor
known from the thread, BQ-154, or any forward, new email, format mismatch or Bcc, FR-CHN-12; `attachments`), and
any modifier makes it T3. Only a ready T2 draft of the person's own
instruction, under an L2 answer from the injected policy port, is scheduled at once with the undo window; everything
else waits for its owner's Send. A redraft after Edit is a new proposal and always waits for a person. Side effects
go only through the injected outbox port, keyed so a replay never adds an entry. Cards hold mail text; no event, log
line or key does.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass, fields
from typing import Any, Protocol

from tilo_channels.autopilot_send import index_artifact
from tilo_channels.autopilot_state import (
    ACTION_TYPE,
    CancelPending,
    CardStore,
    Ledger,
    Outbox,
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
__all__ += ["CardStore", "StopQueue", "t3_content_signal"]

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
        emit: Callable[[dict], None] = lambda part: None,  # unused: no event here; the outbox emits data.transfer
        world_id: str,
        run_id: str,
        connector: str = "gmail",
        stops: StopQueue | None = None,  # None only for benches that never sweep; production passes one (BQ-187)
    ) -> None:
        self._drafter, self._reader, self._contacts = drafter, reader, contacts
        self._policy, self._cards, self._clock, self._stops = policy, cards, clock, stops
        self._world_id = world_id
        self._ledger = Ledger(
            cards=cards, outbox=outbox, clock=clock, world_id=world_id, run_id=run_id, connector=connector, stops=stops
        )

    def preview(self, user_id: str, context: DraftContext, result: DraftResult) -> Preview:
        """The card for a draft of the person's own instruction; at L2 a ready T2 draft is scheduled at once."""
        return self._card(user_id, context, result, instructed=True)

    def send(self, user_id: str, card_id: str) -> Outcome:
        doc = self._cards.get(user_id, card_id)
        if doc is None or doc["state"] != "open" or "send" not in doc["options"]:
            return Outcome("refused", None)
        index_artifact(self._cards, user_id, doc)  # a preview that died before indexing is completed here
        if doc["level"] == "L2":  # the entry's real state; a stopped card never enqueues again
            entry = self._ledger.schedule(user_id, doc)
            state = entry["state"] if entry else "cancelled"
            status = (
                "refused" if state in ("cancelled", "failed") else "scheduled" if state == "scheduled" else "queued"
            )
            return Outcome(status, doc["outbox_id"])
        if self._ledger.first(user_id, card_id, "decision", "send") != "send":
            return Outcome("refused", None)
        entry = self._ledger.enqueue(doc)
        self._cards.put(user_id, card_id, doc | {"outbox_id": entry["id"]})
        _LOG.info("autopilot card %s: queued by its owner, %s", card_id, doc["tier"])
        return Outcome("queued", entry["id"])

    def cancel(self, user_id: str, card_id: str) -> Outcome:
        doc = self._cards.get(user_id, card_id)
        if doc is None or doc["state"] == "superseded":
            return Outcome("refused", None)
        if doc["state"] == "open":
            if doc["level"] == "L2":  # cancels the entry whichever Cancel or Edit claimed the stop first
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
        doc = self._cards.get(user_id, card_id)
        if doc is None:
            return None
        instruction = f"{doc['instruction']}\nChange: {change}"
        if len(instruction) > MAX_INSTRUCTION or "#" in instruction_id or doc["mode"] not in REPLY_FORMATS:
            raise ValueError("edit too long, bad instruction id, or a format the drafter cannot redraft")
        mine = f"edit:{instruction_id}"
        if doc["state"] == "open" and doc["level"] == "L2":
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
        if result.instruction_id != context.instruction_id:
            raise ValueError("the draft is not of this instruction")
        card_id = _card_id(user_id, context.instruction_id)
        doc = self._cards.get(user_id, card_id)
        if doc is None:  # one atomic record fixes tier, level and entry id before any enqueue; first writer wins
            doc = self._decision(user_id, card_id, context, result, instructed)
            if not self._cards.create(user_id, card_id, doc):
                doc = self._cards.get(user_id, card_id)
                if doc is None:
                    raise LookupError("card store refused a create but holds no card")
        index_artifact(self._cards, user_id, doc)  # the text DraftArtifacts serves, before any enqueue (BQ-182)
        if doc["level"] == "L2" and doc["state"] == "open":  # the recorded decision, never worked out again
            entry = self._ledger.schedule(user_id, doc)  # the card's one entry, by its key; none once stopped
            doc = doc | {"scheduled_at": entry["scheduled_at"]} if entry else doc
        _LOG.info("autopilot card %s: %s %s %s", card_id, doc["status"], doc["tier"], doc["level"])
        return _preview(doc)

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
            if instructed and sendable and not modifiers:
                level, policy_id = self._policy.level(user_id, ACTION_TYPE)
                if level == "L2" and policy_id:  # only L2 rides the undo window; anything else waits (fail closed)
                    ms = round(self._clock() * 1000)
                    doc |= {"level": "L2", "undo_window_s": UNDO_WINDOW_S, "policy_id": policy_id}
                    doc |= {"outbox_id": ulid(ms), "scheduled_at": timestamp(ms + UNDO_WINDOW_S * 1000)}
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
        """BQ-154: contacts, every From in the thread, and To / Cc of the user's own messages: From the mailbox and
        carrying Gmail's SENT label (a From header alone is sender-controlled). A thread that cannot be read adds
        nothing (fail closed: more recipients are new)."""
        known = {a.lower() for a in self._contacts(user_id) if isinstance(a, str) and a.isascii()}
        mailbox = _address(context.mailbox)
        own = _base(mailbox) if mailbox else None  # a non-ASCII mailbox vouches for nothing
        try:
            listed = self._reader.get_thread(user_id, context.thread_id).get("messages")
        except Exception:  # any read failure only narrows what is known
            listed = []
        for message in [m for m in (listed if isinstance(listed, list) else []) if isinstance(m, dict)][-MAX_MESSAGES:]:
            sender = _addresses(message.get("from"))[:1]
            known.update(sender)
            labels = message.get("labelIds")
            if sender and _base(sender[0]) == own and isinstance(labels, list) and "SENT" in labels:
                known.update(_addresses(message.get("to")) + _addresses(message.get("cc")))
        return known
