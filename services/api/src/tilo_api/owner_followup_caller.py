"""Explicit owner follow-up caller, using the adopted minutes dependency design.

No route or automatic attendance trigger. Durable draft/autopilot dependencies refuse until
their production wiring is reviewed; this piece does not activate the minutes chain.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException
from tilo_channels.autopilot import Autopilot, Preview
from tilo_channels.drafting import DraftStore

from tilo_api import deps
from tilo_api.meeting_followup import draft_owner_followup
from tilo_api.owner_minutes_caller import OwnerMinutesCaller, get_owner_minutes_caller
from tilo_api.people_writes import Refusal, Writer

AutopilotFactory = Callable[[str, str, str, Callable[[dict], None]], Autopilot]


def get_owner_followup_drafts() -> DraftStore:
    """Durable set-if-absent store required; never silently replace it with memory."""
    raise HTTPException(503, "not_configured", headers={"Cache-Control": "no-store"})


def get_owner_followup_autopilot_factory() -> AutopilotFactory:
    """Scoped production card/outbox factory required; never an unscoped bench."""
    raise HTTPException(503, "not_configured", headers={"Cache-Control": "no-store"})


@dataclass(frozen=True)
class OwnerFollowupCaller:
    owner: OwnerMinutesCaller
    drafts: DraftStore
    autopilot_factory: AutopilotFactory

    def draft(self, meeting_id: str, recipients: Sequence[str] | None = None) -> Preview | None | list[Preview]:
        """Explicit person-id picks draft minutes mail; no picks draft confirmed-item nudges."""
        if re.fullmatch(r"mt_[0-9A-Za-z_]{1,48}", meeting_id) is None:
            raise Refusal(404, "not_found")
        c = self.owner
        writer = Writer(c.stores, deps.ORG_ID, c.principal.user_id, c.clock(), c.redact)
        return draft_owner_followup(
            c.request,
            writer,
            c.store,
            c.artifacts,
            meeting_id,
            principal=c.principal,
            switches=c.switches,
            budget=c.budget,
            events=c.events,
            drafts=self.drafts,
            autopilot_factory=self.autopilot_factory,
            recipients=recipients,
        )


def get_owner_followup_caller(
    owner: Annotated[OwnerMinutesCaller, Depends(get_owner_minutes_caller)],
    drafts: Annotated[DraftStore, Depends(get_owner_followup_drafts)],
    autopilot_factory: Annotated[AutopilotFactory, Depends(get_owner_followup_autopilot_factory)],
) -> OwnerFollowupCaller:
    """Reuse verified principal, stores, clock, mode guards and server-only budget from slice 1."""
    return OwnerFollowupCaller(owner, drafts, autopilot_factory)
