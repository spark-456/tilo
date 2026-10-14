"""Internal explicit owner-request caller; no route registration or automatic trigger.

Future HTTP wiring must use the existing access/App Check middleware and this dependency,
with a separately reviewed server budget. The default budget seam refuses all work.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request
from tilo_memory.artifacts import ArtifactStore
from tilo_metering.flags import FlagStore
from tilo_people.stores import PeopleStores

from tilo_api import deps
from tilo_api.assistant.config import AssistantConfig
from tilo_api.assistant.metering import SpendLedger
from tilo_api.meeting_analysis_mode import analyze_owner_minutes
from tilo_api.meeting_minutes import MinutesWriter
from tilo_api.people_writes import Refusal


def get_owner_minutes_budget() -> float:
    """Server-owned activation/budget authority, unwired until owner adoption; never a body/env switch."""
    raise HTTPException(503, "not_configured", headers={"Cache-Control": "no-store"})


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
    allowance: SpendLedger | None = None
    allowance_cap: float = 0

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
