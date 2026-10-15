"""Internal explicit owner-request caller; no route registration or automatic trigger.

HTTP wiring uses the existing access/App Check middleware and this dependency,
with the existing per-user allowance as its server-owned maximum budget.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request
from tilo_memory.artifacts import ArtifactStore
from tilo_metering.flags import FlagStore
from tilo_people.stores import PeopleStores

from tilo_api import deps
from tilo_api.assistant.config import AssistantConfig
from tilo_api.assistant.metering import SpendLedger
from tilo_api.meeting_analysis_mode import analyze_owner_minutes
from tilo_api.meeting_brief import brief_for_owner
from tilo_api.meeting_minutes import MinutesWriter
from tilo_api.people_writes import Refusal, Writer


def get_owner_minutes_budget(
    config: Annotated[AssistantConfig, Depends(deps.get_assistant_config)],
) -> float:
    """Existing intake allowance caps the operation; no independent budget, price or body switch."""
    cap = config.user_day_credits
    if type(cap) not in (int, float) or not math.isfinite(cap) or cap <= 0:
        raise Refusal(429, "allowance_capped", headers={"Cache-Control": "no-store"})
    return float(cap)


@dataclass(frozen=True)
class OwnerMinutesCaller:
    request: Request
    principal: deps.Principal
    stores: PeopleStores
    store: deps.Store
    artifacts: ArtifactStore
    clock: Callable[[], str]
    redact: Callable[[str], str]
    switches: FlagStore
    events: deps.EventWriter
    budget: float
    allowance: SpendLedger
    allowance_cap: float

    def analyze(self, meeting_id: str) -> dict[str, Any]:
        """Invoke only for an explicit owner instruction; reads/attendance/confirm never call this."""
        if re.fullmatch(r"mt_[0-9A-Za-z_]{1,48}", meeting_id) is None:
            raise Refusal(404, "not_found")
        writer = MinutesWriter(
            self.stores, deps.ORG_ID, self.principal.user_id, self.clock(), self.redact, clock=self.clock
        )
        return analyze_owner_minutes(
            self.request,
            writer,
            self.store,
            self.artifacts,
            meeting_id,
            principal=self.principal,
            switches=self.switches,
            budget=self.budget,
            events=self.events,
            allowance=self.allowance,
            allowance_cap=self.allowance_cap,
            clock=self.clock,
        )

    def brief(self, meeting_id: str, worlds: deps.MeetingWorlds) -> dict[str, Any]:
        """The owner's explicit "make my brief now" (ADR-0047 MB-03): same budget, allowance and modes as minutes."""
        if re.fullmatch(r"mt_[0-9A-Za-z_]{1,48}", meeting_id) is None:
            raise Refusal(404, "not_found")
        writer = Writer(self.stores, deps.ORG_ID, self.principal.user_id, self.clock(), self.redact)
        return brief_for_owner(
            self.request,
            writer,
            self.store,
            self.artifacts,
            worlds,
            meeting_id,
            principal=self.principal,
            switches=self.switches,
            budget=self.budget,
            events=self.events,
            allowance=self.allowance,
            allowance_cap=self.allowance_cap,
            clock=self.clock,
        )


def get_owner_minutes_caller(
    request: Request,
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    budget: Annotated[float, Depends(get_owner_minutes_budget)],
    stores: Annotated[PeopleStores, Depends(deps.get_people_stores)],
    store: Annotated[deps.Store, Depends(deps.get_store)],
    artifacts: Annotated[ArtifactStore, Depends(deps.get_artifact_store)],
    clock: Annotated[Callable[[], str], Depends(deps.get_clock)],
    redact: Annotated[Callable[[str], str], Depends(deps.get_redactor)],
    switches: Annotated[FlagStore, Depends(deps.get_switches)],
    events: Annotated[deps.EventWriter, Depends(deps.get_event_writer)],
    allowance: Annotated[SpendLedger, Depends(deps.get_spend_ledger)],
    config: Annotated[AssistantConfig, Depends(deps.get_assistant_config)],
) -> OwnerMinutesCaller:
    """Resolve through existing request-scoped seams; no body, payload, caller identity or model mode accepted."""
    if type(budget) not in (int, float) or not math.isfinite(budget) or budget <= 0:
        raise HTTPException(503, "not_configured", headers={"Cache-Control": "no-store"})
    uid = getattr(request.state, "uid", None)
    if uid is not None and uid != principal.user_id:
        raise Refusal(404, "not_found")
    try:
        stamp = datetime.fromisoformat(clock().replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            raise ValueError
        cap = config.user_day_credits
        spent = allowance.spent(principal.user_id, stamp.astimezone(UTC).date().isoformat())
        if (
            type(cap) not in (int, float)
            or not math.isfinite(cap)
            or cap <= 0
            or type(spent) not in (int, float)
            or not math.isfinite(spent)
            or spent < 0
            or spent >= cap
        ):
            raise ValueError
        # A read bounds the operation, never grants authority: the later atomic reservation
        # still checks competing holds and commits before any provider invocation.
        budget = min(budget, cap - spent)
    except Exception:
        raise Refusal(429, "allowance_capped", headers={"Cache-Control": "no-store"}) from None
    # Where SEC-15's deployed gate is absent, the verified sign-in dependency supplies the same identity.
    request.state.uid = principal.user_id
    return OwnerMinutesCaller(
        request,
        principal,
        stores,
        store,
        artifacts,
        clock,
        redact,
        switches,
        events,
        budget,
        allowance,
        config.user_day_credits,
    )
