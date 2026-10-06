"""Draft reply on a plate mail item (FR-PA-07; ADR-0021, PE-10, BQ-279 to BQ-284).

A thin wrapper: it checks the mail is on the person's own plate, then runs the FR-CHN-10 `Drafter` and the FR-CHN-11
`Autopilot.preview` unchanged. It has no send path of its own (SEC-03): no connector, outbox, policy or provider is
imported, nothing is written or emitted here. The drafter emits `artifact.created`, the autopilot emits
`approval.requested`; Send, Edit and Cancel stay the card's (`Autopilot.send` with the owner's approval, CHN-WIRE-1).

A tap carries no instruction text, so the card is always L1 (BQ-222: nothing a person wrote never rides L2): nothing
is queued until the person's own Send. The reply must answer the plate mail itself: a later message in the thread
(from a stranger, or one the safety screen flags) never becomes the card (BQ-284). Never logs mail text, addresses or
exception messages.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from hashlib import sha256

from .autopilot import Autopilot, DraftContext, Preview
from .drafting import Drafter, message_id_of
from .triage import MailReader, TriageStore
from .triage import _result as triage_result  # the one place the "flag beats label beats model" rule lives

MODE = "reply"  # to the sender, no Cc (BQ-283); reply-all, forward and new mail stay with typed instructions


def _instruction_id(request_id: str, mail_id: str) -> str:
    """The FR-CHN-10 key (and so the card id) of one tap: the same tap on the same mail is the same draft; a new tap
    is a new draft (BQ-282). The pair is JSON-encoded, so no choice of ids makes two pairs hash alike. No "#", which
    the drafter keeps for its own markers."""
    return "plate-" + sha256(json.dumps([request_id, mail_id]).encode()).hexdigest()[:32]


def _not_found(exc: Exception) -> bool:
    """A read that found nothing: the reader's own LookupError, or Gmail's 404 (an adapter error with `status`)."""
    return isinstance(exc, LookupError) or getattr(exc, "status", None) == 404


class PlateReply:
    def __init__(
        self,
        *,
        triage: TriageStore,
        mail: MailReader,
        drafter: Drafter,
        autopilot: Autopilot,
        mailbox: Callable[[str], str | None],
    ) -> None:
        self._triage, self._mail, self._mailbox = triage, mail, mailbox
        self._drafter, self._autopilot = drafter, autopilot

    def draft_reply(self, user_id: str, mail_id: str, *, request_id: str) -> Preview | None:
        """The FR-CHN-11 card for a reply to `mail_id`, or None (nothing drafted, stored, emitted or queued) when the
        mail is not on this person's plate. `request_id` is the tap's id and the idempotency key: replays, restarts
        and parallel instances give one card."""
        if not request_id or "#" in request_id:
            raise ValueError("a tap needs its own request id")
        if not self._autopilot.owns(user_id):  # before anything is read or drafted, as `preview` checks it first
            return None
        mailbox = self._mailbox(user_id)
        if not mailbox or not self._on_plate(user_id, mail_id):
            return None
        mail = self._read(self._mail.get_message, user_id, mail_id)
        thread_id = mail.get("thread_id") if mail else None
        own_id = message_id_of(mail) if mail else ""
        if not isinstance(thread_id, str) or not thread_id or not own_id:  # nothing proves the draft answers this mail
            return None
        if self._read(self._drafter.reply_target, user_id, thread_id, mailbox) != own_id:
            return None  # a later message in the thread would be the one answered
        instruction_id = _instruction_id(request_id, mail_id)
        result = self._drafter.draft(
            user_id, instruction_id=instruction_id, thread_id=thread_id, instruction="", mailbox=mailbox, mode=MODE
        )
        if result.draft is not None and result.draft.in_reply_to != own_id:  # the thread moved between the two reads
            return None
        context = DraftContext(instruction_id, thread_id, "", mailbox, MODE)
        return self._autopilot.preview(user_id, context, result)

    def _on_plate(self, user_id: str, mail_id: str) -> bool:
        """A result stored for exactly this person and message whose effective category is needs_reply (her label
        beats the model; a safety flag beats a label)."""
        doc = self._triage.get(user_id, mail_id)
        if not isinstance(doc, dict) or "flagged" not in doc or "category" not in doc:
            return False
        result = triage_result(mail_id, doc)
        return not result.flagged and result.category == "needs_reply"

    @staticmethod
    def _read(read: Callable, *args: str):
        """A read that found nothing (triaged earlier, no longer readable) is None; any other failure propagates."""
        try:
            return read(*args)
        except Exception as exc:
            if _not_found(exc):
                return None
            raise
