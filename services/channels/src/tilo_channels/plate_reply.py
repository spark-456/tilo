"""Draft reply on a plate mail item (FR-PA-07; ADR-0021, PE-10, BQ-279 to BQ-284).

A thin wrapper: it checks the mail is on the person's own plate, then runs the FR-CHN-10 `Drafter` and the FR-CHN-11
`Autopilot.preview` unchanged. It has no send path of its own (SEC-03): no connector, outbox, policy or provider is
imported, nothing is written or emitted here. The drafter emits `artifact.created`, the autopilot emits
`approval.requested`; Send, Edit and Cancel stay the card's (`Autopilot.send` with the owner's approval, CHN-WIRE-1).

A tap carries no instruction text, so the card is always L1 (BQ-222: nothing a person wrote never rides L2): nothing
is queued until the person's own Send. Never logs mail text, addresses or exception messages.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable

from .autopilot import Autopilot, DraftContext, Preview
from .drafting import Drafter
from .triage import MailReader, TriageStore
from .triage import _result as triage_result  # the one place the "flag beats label beats model" rule lives

MODE = "reply"  # to the sender, no Cc (BQ-283); reply-all, forward and new mail stay with typed instructions


def _instruction_id(request_id: str, mail_id: str) -> str:
    """The FR-CHN-10 key (and so the card id) of one tap: the same tap on the same mail is the same draft; a new tap
    is a new draft (BQ-282). No "#", which the drafter keeps for its own markers."""
    return "plate-" + hashlib.sha256(f"{request_id}\n{mail_id}".encode()).hexdigest()[:32]


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
        """The FR-CHN-11 card for a reply to `mail_id`, or None (nothing read beyond the mail, drafted, stored,
        emitted or queued) when the mail is not on this person's plate. `request_id` is the tap's id and the
        idempotency key: replays, restarts and parallel instances give one card."""
        if not request_id or "#" in request_id:
            raise ValueError("a tap needs its own request id")
        if not self._on_plate(user_id, mail_id):
            return None
        mailbox = self._mailbox(user_id)
        thread_id = self._thread_of(user_id, mail_id)
        if not mailbox or not thread_id:
            return None
        instruction_id = _instruction_id(request_id, mail_id)
        result = self._drafter.draft(
            user_id, instruction_id=instruction_id, thread_id=thread_id, instruction="", mailbox=mailbox, mode=MODE
        )
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

    def _thread_of(self, user_id: str, mail_id: str) -> str | None:
        try:
            thread_id = self._mail.get_message(user_id, mail_id).get("thread_id")
        except LookupError:  # triaged earlier, no longer readable
            return None
        return thread_id if isinstance(thread_id, str) else None
