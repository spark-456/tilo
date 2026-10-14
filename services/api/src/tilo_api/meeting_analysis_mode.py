"""Internal owner-request minutes integration. No route, background job, confirmation or send."""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Callable
from datetime import datetime
from typing import Any, cast

from fastapi import Request
from tilo_memory.artifacts import ArtifactStore
from tilo_metering.flags import FlagStore
from tilo_providers.interfaces import SafetyProvider
from tilo_providers.router import Router

from tilo_api import deps, spend, team_access, team_store
from tilo_api.assistant.metering import SpendLedger
from tilo_api.meeting_allowance import allowance_router
from tilo_api.meeting_minutes import analyze_and_publish_minutes
from tilo_api.people_meetings import _mine
from tilo_api.people_quotes import GONE
from tilo_api.people_writes import Refusal, Writer


class _Calls:
    """Re-read team limits/switches and hold each live call. Unknown usage conservatively settles the unit reserve.

    Router retains credit budgeting. This is SEC-16's existing conservative per-unit accounting, not a price quote
    or actual provider-cost measurement. Failures after invocation stay charged; no content or errors are logged.
    """

    def __init__(self, request: Request, w: Writer, switches: FlagStore, mode: deps.Mode, run_id: str) -> None:
        self.request, self.w, self.switches, self.mode, self.run_id = request, w, switches, mode, run_id

    def invoke(self, call: Callable[[], Any]) -> Any:
        if self.mode != "live":
            return call()
        caps = deps.caps_for(self.request)
        switches = self.switches
        if not (isinstance(switches, spend.Switches) and switches.ledger is not None and caps is not None):
            raise deps.ReplayOnly
        try:
            team = team_store.team_reader(self.request.app.dependency_overrides)()
            cap = team_access.user_cap_minor(team, self.w.actor, caps.uid_lifetime_minor)
        except Exception:
            cap = 0
        if cap <= 0:
            raise spend.SpendCapReached
        guard = spend.SpendGuard(
            switches.ledger,
            switches.flags,
            dataclasses.replace(caps, uid_lifetime_minor=min(cap, caps.uid_lifetime_minor)),
        )
        try:
            remaining = min(cap, caps.uid_lifetime_minor) - switches.ledger.spent_minor(self.w.actor)
        except Exception:
            raise deps.ReplayOnly from None
        if remaining < caps.unit_reserve_minor:
            raise spend.SpendCapReached
        plan = guard.begin_unit(
            "live",
            uid=self.w.actor,
            run_id=self.run_id,
            org_id=self.w.org,
            estimate_minor=caps.unit_reserve_minor,
            at=datetime.fromisoformat(self.w.now.replace("Z", "+00:00")),
        )
        if plan.reservation is None:
            raise spend.SpendCapReached if plan.reason == "uid_lifetime" else deps.ReplayOnly
        try:
            return call()
        finally:
            guard.settle_unit(plan, caps.unit_reserve_minor)


class _Router:
    def __init__(self, router: Router, calls: _Calls) -> None:
        self.router, self.calls = router, calls

    def generate(self, role: str, request: Any, *, budget: float) -> Any:
        return self.calls.invoke(lambda: self.router.generate(role, request, budget=budget))


class _Safety:
    def __init__(self, safety: SafetyProvider, calls: _Calls) -> None:
        self.safety, self.calls = safety, calls

    def check(self, text: str) -> dict[str, Any]:
        return cast(dict[str, Any], self.calls.invoke(lambda: self.safety.check(text)))


def analyze_owner_minutes(
    request: Request,
    w: Writer,
    store: deps.Store,
    artifacts: ArtifactStore,
    meeting_id: str,
    *,
    principal: deps.Principal,
    switches: FlagStore,
    budget: float,
    events: deps.EventWriter,
    allowance: SpendLedger,
    allowance_cap: float,
    clock: Callable[[], str] | None = None,
) -> dict[str, Any]:
    """Server-only caller supplies writer/principal/switches and bounded credit budget, never a request body.

    Start is the stored scheduled start (capture has no persisted actual-start field); unscheduled imports refuse.
    Mode follows the verified request, demo always replays, and provider factories receive that explicit mode.
    Existing immutable-pin/retention/version publication guards still apply. Nothing launches this automatically.
    """
    meeting, version, _ = _mine(w, meeting_id, "read_full", GONE)
    world_id = meeting.get("world_id")
    world = store.load_world(world_id, settle=False) if world_id else None
    if (
        w.actor != principal.user_id
        or getattr(request.state, "uid", None) != w.actor
        or w.org != deps.ORG_ID
        or world is None
        or world.owner != w.actor
        or (principal.world_id is not None and principal.world_id != world_id)
    ):
        raise Refusal(404, "not_found")
    if meeting["status"] != "ended" or meeting["minutes"] is not None:
        raise Refusal(409, "not_publishable")
    until = meeting["delete_transcript_after"]
    if meeting["transcript"] is None or until is None or w.now >= until:
        raise Refusal(409, "transcript_unavailable")
    try:
        start = meeting["scheduled"]["start"]
        when = datetime.fromisoformat(start.replace("Z", "+00:00"))
        if when.tzinfo is None or when > datetime.fromisoformat(w.now.replace("Z", "+00:00")):
            raise ValueError
        if type(budget) not in (int, float) or not math.isfinite(budget) or budget <= 0:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise Refusal(409, "analysis_inputs_unavailable") from None
    mode = deps.get_work_mode(request, switches)
    if principal.demo_session or getattr(request.state, "demo_session", False) is True:
        mode = "replay"
    router, safety = deps.router_for_mode(mode), deps.get_safety(mode)
    # Factories must not silently adopt a changed meeting or schedule as this operation's source.
    if _mine(w, meeting_id, "read_full", GONE)[1] != version:
        raise Refusal(409, "version_conflict")
    calls = _Calls(request, w, switches, mode, world.run_id)
    with allowance_router(
        _Router(router, calls),
        ledger=allowance,
        user=w.actor,
        clock=clock or (lambda: w.now),
        cap=allowance_cap,
        budget=budget,
    ) as metered:
        return analyze_and_publish_minutes(
            w,
            store,
            artifacts,
            meeting_id,
            router=cast(Router, metered),
            meeting_at=start,
            budget=budget,
            safety=cast(SafetyProvider, _Safety(safety, calls)),
            events=events,
        )
