"""tilo_channels.autopilot: Email Autopilot preview with Send / Edit / Cancel (L1) and send with a 60 s undo window
(L2) (FR-CHN-11; PRD 10.4, 11.2, 11.4 Preview and Undo; OB-01 to OB-05; BQ-152 to BQ-158).

The tier is deterministic: `send_email` is T2 unless a modifier applies (`money_or_legal` from `t3_content_signal` on
the raw body, which it cleans itself; `safety_flag`; `new_recipients` for an address that is neither a contact nor
known from the thread, BQ-154), and any modifier makes it T3. Only a ready T2 draft of the person's own
instruction, under an L2 answer from the injected policy port, is scheduled at once with the undo window; everything
else waits for its owner's Send. A redraft after Edit is a new proposal and always waits for a person. Side effects
go only through the injected outbox port, keyed so a replay never adds an entry. Cards hold mail text; no event, log
line or key does.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from collections.abc import Callable, Iterable
from dataclasses import dataclass, fields
from datetime import UTC, datetime
from typing import Any, Protocol

from tilo_channels.autopilot_t3 import clean_text, t3_content_signal
from tilo_channels.drafting import (
    MAX_INSTRUCTION,
    MAX_MESSAGES,
    Drafter,
    DraftResult,
    DraftStore,
    ThreadReader,
    _address,
    _addresses,
    _base,
)

__all__ = ["Autopilot", "DraftContext", "Outcome", "Preview", "clean_text", "t3_content_signal"]

OPTIONS = ("send", "edit", "cancel")
UNDO_WINDOW_S = 60  # PRD 10.4 L2 default
PREVIEW_CHARS = 600  # PRD 11.4 Preview
ACTION_TYPE = "send_email"
FINDING_CAP = 300  # characters of one finding's text shown on a card (issue #243)

_LOG = logging.getLogger(__name__)
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
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


class Outbox(Protocol):  # the names of tilo_connectors.outbox.Outbox, which tilo-channels never imports (BQ-158)
    def enqueue(self, entry: dict, evidence: dict) -> dict: ...
    def cancel(self, outbox_id: str) -> dict: ...


class CardStore(DraftStore, Protocol):
    def put(self, user_id: str, key: str, value: dict) -> None: ...


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


def _timestamp(ms: int) -> str:
    return datetime.fromtimestamp(ms // 1000, UTC).strftime("%Y-%m-%dT%H:%M:%S") + f".{ms % 1000:03d}Z"


def _ulid(ms: int) -> str:
    value = (ms << 80) | secrets.randbits(80)
    return "".join(_CROCKFORD[(value >> shift) & 31] for shift in range(125, -1, -5))


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
        emit: Callable[[dict], None] = lambda part: None,
        world_id: str,
        run_id: str,
        connector: str = "gmail",
    ) -> None:
        self._drafter, self._reader, self._contacts = drafter, reader, contacts
        self._policy, self._outbox, self._cards, self._clock = policy, outbox, cards, clock
        self._emit = emit  # FR-CHN-11 emits no event: the outbox emits data.transfer when an entry is sent
        self._world_id, self._run_id, self._connector = world_id, run_id, connector

    def preview(self, user_id: str, context: DraftContext, result: DraftResult) -> Preview:
        """The card for a draft of the person's own instruction; at L2 a ready T2 draft is scheduled at once."""
        return self._card(user_id, context, result, instructed=True)

    def send(self, user_id: str, card_id: str) -> Outcome:
        doc = self._cards.get(user_id, card_id)
        if doc is None or doc["state"] != "open" or "send" not in doc["options"]:
            return Outcome("refused", None)
        if doc["level"] == "L2":
            return Outcome("scheduled", doc["outbox_id"])
        if not self._decide(user_id, card_id, "send"):
            return Outcome("refused", None)
        entry = self._enqueue(doc, {"by": "person", "ref": user_id}, 0)
        self._cards.put(user_id, card_id, doc | {"outbox_id": entry["id"]})
        _LOG.info("autopilot card %s: queued by its owner, %s", card_id, doc["tier"])
        return Outcome("queued", entry["id"])

    def cancel(self, user_id: str, card_id: str) -> Outcome:
        doc = self._cards.get(user_id, card_id)
        if doc is None or doc["state"] == "superseded":
            return Outcome("refused", None)
        if doc["state"] == "open" and not self._close(user_id, doc, "close"):
            return Outcome("too_late", doc["outbox_id"])
        if doc["state"] == "open":
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
        if len(instruction) > MAX_INSTRUCTION or "#" in instruction_id:
            raise ValueError("edit too long or bad instruction id")
        if doc["state"] == "open" and self._close(user_id, doc, f"edit:{instruction_id}"):
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

    # -- internals ----------------------------------------------------------------------------------------------

    def _card(self, user_id: str, context: DraftContext, result: DraftResult, *, instructed: bool) -> Preview:
        if result.instruction_id != context.instruction_id:
            raise ValueError("the draft is not of this instruction")
        card_id = _card_id(user_id, context.instruction_id)
        existing = self._cards.get(user_id, card_id)
        if existing is not None:
            return _preview(existing)
        draft = result.draft
        sendable = result.status == "ready" and draft is not None and not draft.bcc and not draft.attachments
        body = clean_text(draft.body) if draft is not None else ""
        doc: dict[str, Any] = {
            "card_id": card_id,
            "user_id": user_id,
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
        }
        if sendable and draft is not None:
            modifiers = ["money_or_legal"] if t3_content_signal(draft.body) else []  # hidden characters too
            modifiers += ["safety_flag"] if draft.safety_flag or result.flagged else []
            known = self._known(user_id, context)
            modifiers += ["new_recipients"] if any(a.lower() not in known for a in draft.to + draft.cc) else []
            doc |= {"tier": "T3" if modifiers else "T2", "modifiers": modifiers}
            if instructed and not modifiers:
                level, policy_id = self._policy.level(user_id, ACTION_TYPE)
                if level == "L2" and policy_id:  # only L2 rides the undo window; anything else waits (fail closed)
                    entry = self._enqueue(doc, {"by": "policy", "ref": policy_id}, UNDO_WINDOW_S)
                    doc |= {"level": "L2", "undo_window_s": UNDO_WINDOW_S}
                    doc |= {"outbox_id": entry["id"], "scheduled_at": entry["scheduled_at"]}
        if not self._cards.create(user_id, card_id, doc):  # another call or instance stored it first
            doc = self._cards.get(user_id, card_id) or doc
        _LOG.info("autopilot card %s: %s %s %s", card_id, doc["status"], doc["tier"], doc["level"])
        return _preview(doc)

    def _known(self, user_id: str, context: DraftContext) -> set[str]:
        """BQ-154: contacts, every From in the thread, and To / Cc of the user's own messages: From the mailbox and
        carrying Gmail's SENT label (a From header alone is sender-controlled). A thread that cannot be read adds
        nothing (fail closed: more recipients are new)."""
        known = {a.lower() for a in self._contacts(user_id)}
        own = _base(_address(context.mailbox) or context.mailbox.lower())
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

    def _decide(self, user_id: str, card_id: str, decision: str) -> bool:
        """An L1 card's one decision (send, close, or one edit), claimed atomically; True when it is `decision`."""
        key = f"{card_id}#decision"
        if self._cards.create(user_id, key, {"by": decision}):
            return True
        return (self._cards.get(user_id, key) or {}).get("by") == decision

    def _close(self, user_id: str, doc: dict[str, Any], decision: str) -> bool:
        """Stops the card's send: cancels a scheduled L2 entry, or claims an L1 card before its owner's Send."""
        if doc["level"] != "L2":
            return self._decide(user_id, doc["card_id"], decision)
        try:
            self._outbox.cancel(doc["outbox_id"])
        except Exception:  # the outbox raises once the entry is no longer scheduled
            return False
        return True

    def _enqueue(self, doc: dict[str, Any], authority: dict[str, str], window: int) -> dict:
        ms = round(self._clock() * 1000)
        created = _timestamp(ms)
        entry = {
            "id": _ulid(ms),
            "idempotency_key": f"autopilot:{doc['card_id']}",
            "world_id": self._world_id,
            "run_id": self._run_id,
            "action_type": ACTION_TYPE,
            "connector": self._connector,
            "recipients": list(dict.fromkeys(doc["to"] + doc["cc"])),
            "attachments": [],
            "item": doc["item"],
            "destination": doc["thread_id"],
            "modifiers": doc["modifiers"],
            "risk_tier": doc["tier"],
            "authz": authority | {"at": created},
            "undo_window_s": window,
            "scheduled_at": _timestamp(ms + window * 1000),
            "state": "scheduled" if window else "queued",
            "created_at": created,
        }
        evidence = {"instruction_id": doc["instruction_id"], "level": "L2" if window else "L1"}
        return self._outbox.enqueue(entry, evidence)
