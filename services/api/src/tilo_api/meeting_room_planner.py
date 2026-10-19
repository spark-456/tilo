"""The meeting room's change planner (MROOM-H2b; ADR-0028 decisions 6, 8 and 10; MR-09, MR-10, MR-11).

`confirm_change` calls `plan_change` once the `meeting.change_requested` is stored, handing over refs only. The planner
reads the confirmed wording back from the redacted archive, re-fences and re-screens it as the model will see it, loads
the world's current plan, asks the Director role (through the Router, replay unless the request's mode is live) for
revision units and writes `plan.revised` through the world's one writer. A finished run is reopened as a
`revision_run`: a new `run_id` no earlier event of the world uses, `plan.revised` its first event. Then
`budget.requested` goes to the world owner. This module never writes `budget.granted` or `world.started` and starts no
unit: the owner's in-person grant and the start are MROOM-H2c (BQ-MROOM-H2b-1). Any failure writes no `plan.revised` and
one `alert.raised` (`needs_you`) to the convener; the words and the error text are in no event."""

from __future__ import annotations

import copy
import logging
import math
import threading
import uuid
from datetime import UTC, datetime
from typing import Any

import tilo_policy
from tilo_harness.untrusted import neutralise
from tilo_metering import LedgerEntry
from tilo_metering.prices import Usage
from tilo_planning.brief import DIRECTOR_ROLE
from tilo_planning.compiler import PlanCompileError, PlanInputs
from tilo_planning.revision import compile_revision
from tilo_providers.router import RouterError

from tilo_api import deps, events
from tilo_api import meeting_room as mr

logger = logging.getLogger("tilo_api.meeting_room_planner")
_PLANNING: dict[str, threading.Lock] = {}  # world id -> the one revision being planned; this process only
_SAYS = {  # fixed texts: the wording and the error never reach an event
    "declined": "The change was not planned: the safety screen declined the wording.",
    "unavailable": "The change was not planned: it could not be screened or planned just now.",
    "no_plan": "The change was not planned: the world's current plan is not available.",
    "refused": "The change was not planned: the Director found no valid revision of the plan.",
    "budget": "The change was planned, but the owner's budget request could not be recorded.",
}


class _Refused(Exception):
    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.key = key


class _Metered:
    """The Router as the planner sees it: every attempt that reached a model is kept, also after an error."""

    def __init__(self, router: Any) -> None:
        self._router: Any = router
        self.attempts: list[Any] = []

    def generate(self, *args: Any, **kwargs: Any) -> Any:
        try:
            result = self._router.generate(*args, **kwargs)
        except RouterError as exc:
            self.attempts += list(getattr(exc, "attempts", None) or [])
            raise
        self.attempts += list(getattr(result, "attempts", None) or [])
        return result


def plan_change(call: mr.PlanCall) -> str:
    """`started` (plan.revised written), `failed` (an alert was written) or `pending` (the world paused; waits)."""
    ctx, meter = call.ctx, _Metered(None)
    pid = call.event["data"]["proposal_id"]
    with mr._lock_of(_PLANNING, ctx.world_id):  # noqa: SLF001
        try:
            if any(e["type"] == "plan.revised" and e["data"].get("proposal_id") == pid for e in ctx.stream()):
                return "started"  # planned already: a change is planned once
            return _plan(call, meter)
        except _Refused as why:
            return _failed(call, why.key)
        except Exception as exc:
            logger.warning("revision for world %s not planned (%s)", ctx.world_id, type(exc).__name__)
            return _failed(call, "unavailable")
        finally:
            _charge(call, meter)


def _failed(call: mr.PlanCall, key: str) -> str:
    ctx, event = call.ctx, call.event
    if ctx.world.paused:
        return "pending"  # a paused world gets nothing more (FR-WLD-07); the request stays recorded
    pid = event["data"]["proposal_id"]
    data = {"alert_id": events.stable_part_id(pid, "alert_id"), "card_id": None}
    part = _part(call, "alert.raised", _SAYS[key], data,
                 target=call.room.convener, severity="needs_you", id_=events.stable_part_id(pid, "alert"))  # fmt: skip
    try:
        ctx.writer.append(ctx.world_id, part)
    except Exception as exc:
        logger.warning("alert for world %s not written (%s)", ctx.world_id, type(exc).__name__)
    return "failed"


def _director(ctx: mr.Ctx) -> str:
    agents = ((ctx.world.layout or {}).get("semantic") or {}).get("agents") or []
    return next((a["id"] for a in agents if a.get("rank") == "director"), "system")


def _part(call: mr.PlanCall, type_: str, summary: str, data: dict, **more: Any) -> dict:
    ctx, room = call.ctx, call.room
    part = {
        "id": more.pop("id_", None) or events.new_part_id(), "type": type_, "actor": _director(ctx),
        "target": more.pop("target", ctx.world_id), "level": None, "district": None, "item": None,
        "severity": more.pop("severity", "info"), "credits": more.pop("credits", 0), "summary": summary[:140],
        "cause": more.pop("cause", call.event["id"]), "vis": more.pop("vis", room.vis), "authz": None, "data": data,
    }  # fmt: skip
    return {**part, **more}


def _wording(call: mr.PlanCall) -> str:
    """The confirmed words, read back from the redacted archive by `message_ref` (MR-12: never from an event)."""
    room, ref = call.room, call.event["data"]["message_ref"]
    archive = mr._seam(call.ctx.request, deps.get_run_archive)(org_id=deps.ORG_ID, run_id=room.run_id)  # noqa: SLF001
    for record in archive.records():
        if f"{room.run_id}/{record['seq']}" == ref and isinstance(record["payload"].get("text"), str):
            return record["payload"]["text"]
    raise _Refused("unavailable")


def _screened(call: mr.PlanCall) -> str:
    """The wording as the model will get it (neutralised), screened as stored and as neutralised (PRD 16.3)."""
    text = _wording(call)
    clean = neutralise(text, limit=2000)
    try:
        flagged = mr._flagged(call.safety, text) or (clean != text and mr._flagged(call.safety, clean))  # noqa: SLF001
    except Exception:  # an outage is never "not flagged"
        raise _Refused("unavailable") from None
    if flagged:
        raise _Refused("declined")
    return clean


def _current(ctx: mr.Ctx) -> tuple[Any, dict]:
    """The world's compiled plan (the run's own, or the one the last revision produced). Without it, or when an earlier
    revision cannot be found, nothing is planned: a new unit id could collide."""
    run = ctx.store.runs.get(ctx.world_id)
    revised, plan = getattr(run, "revised_plan", None), getattr(run, "plan", None)
    earlier = any(e["type"] == "plan.revised" for e in ctx.stream())
    chosen = revised if isinstance(revised, dict) else None if earlier else plan
    if not isinstance(chosen, dict) or not chosen.get("units"):
        raise _Refused("no_plan")
    return run, copy.deepcopy(chosen)


def _inputs(call: mr.PlanCall, run: Any, plan: dict) -> PlanInputs:
    ctx = call.ctx
    skills, connectors = (
        mr._seam(ctx.request, deps.get_skill_registry),
        mr._seam(ctx.request, deps.get_connector_registry),
    )  # noqa: SLF001
    ctx.store.load_owner(ctx.world.owner)
    return PlanInputs(
        approaches=copy.deepcopy(getattr(run, "approaches", None) or plan.get("approaches") or []),
        owner=ctx.world.owner, skills=dict(skills.catalog()),
        connectors={c: connectors.get(c) for c in connectors.ids()}, risk_table=tilo_policy.load_risk_table(),
        policies=dict(ctx.store.policies),
    )  # fmt: skip


def _router(call: mr.PlanCall) -> Any:
    seam = call.ctx.request.app.dependency_overrides.get(deps.get_router)
    return seam() if seam is not None else deps.router_for_mode(call.how.mode)  # type: ignore[arg-type]  # replay unless live (PL-01, EFF-01)


def _finished(stream: list[dict], request_id: str) -> bool:
    """MR-09: finished when the latest started/completed/failed event before the request is not a start."""
    state = None
    for e in stream:
        if e["id"] == request_id:
            break
        if e["type"] in ("world.started", "world.completed", "world.failed"):
            state = e["type"]
    return state in ("world.completed", "world.failed")


def _new_run_id(stream: list[dict]) -> str:
    used = {e["run_id"] for e in stream}
    while (run_id := "r_rev_" + uuid.uuid4().hex[:16]) in used:
        pass
    return run_id


def _plan(call: mr.PlanCall, meter: _Metered) -> str:
    ctx, event = call.ctx, call.event
    if ctx.world.paused:
        return "pending"
    wording = _screened(call)
    run, plan = _current(ctx)
    stream = ctx.stream()
    asked = {
        e["data"]["proposal_id"]: list(e["data"]["units"]) for e in stream if e["type"] == "meeting.change_requested"
    }
    meter._router = _router(call)  # noqa: SLF001
    change = {"proposal_id": event["data"]["proposal_id"], "units": event["data"]["units"],
              "artifacts": event["data"]["artifacts"]}  # fmt: skip
    try:
        result = compile_revision(plan, change, wording, meter, _inputs(call, run, plan), changes=asked)  # type: ignore[arg-type]
    except PlanCompileError:
        raise _Refused("refused") from None
    # No cost history for a unit type (empty seed): the most a grant may be (BQ-MROOM-H2b-2)
    credits = result.credits or {"min": 0.0, "max": float(deps.budget_cap_ceiling())}
    if ctx.world.paused:  # paused while the Director worked: nothing is written, the request waits
        return "pending"
    same = not _finished(stream, event["id"])
    _write_revision(call, meter, result, credits, run, same, stream)
    return "started"


def _write_revision(
    call: mr.PlanCall, meter: _Metered, result: Any, credits: dict, run: Any, same: bool, stream: list
) -> None:
    ctx, event = call.ctx, call.event
    pid, units = event["data"]["proposal_id"], result.revision_units
    record, old = ctx.world, ctx.world.run_id
    data = {"proposal_id": pid, "run": "same_run" if same else "revision_run", "units": units, "credits": credits}
    summary = f"The Director planned {len(units)} revision unit{'s' * (len(units) != 1)} for the change."
    part = _part(
        call, "plan.revised", summary, data, credits=_credits(meter.attempts), id_=events.stable_part_id(pid, "plan")
    )
    if meter.attempts:
        last = meter.attempts[-1]
        part["trace"] = {
            "model_role": DIRECTOR_ROLE, "profile": last.profile_id, "tokens_in": last.tokens_in,
            "tokens_out": last.tokens_out, "tool": None, "latency_ms": None, "archive_ref": None,
        }  # fmt: skip
    if not same:  # decision 8: plan.revised is the first event of a new run of the same world
        record.run_id = _new_run_id(stream)
        ctx.store.commit(worlds={ctx.world_id: record}, evict=False)
    try:
        written = ctx.writer.append(ctx.world_id, part)
    except Exception:
        if not same:
            record.run_id = old
            ctx.store.commit(worlds={ctx.world_id: record}, evict=False)
        raise
    if run is not None:
        run.revised_plan = result.plan  # the next change plans on top of this one
    _request_budget(call, written, result, credits, same, stream)


def _request_budget(call: mr.PlanCall, revised: dict, result: Any, cr: dict, same: bool, stream: list[dict]) -> None:
    """MR-10 (b) for everything (BQ-MROOM-H2b-1): the owner is asked, and nothing starts until their in-person grant."""
    ctx, pid = call.ctx, call.event["data"]["proposal_id"]
    mine = [e for e in stream if same and e["run_id"] == revised["run_id"]]
    spent = math.fsum(float(e.get("credits") or 0) for e in mine)
    cap = next((float(e["data"]["budget_cap"]) for e in reversed(mine) if e["type"] == "world.started"), 0.0)
    added = [u for u in result.plan["units"] if u["id"] in {x["id"] for x in result.revision_units}]
    data = {
        "requested": float(cr["max"]), "spent": spent, "cap": cap,
        "remaining_units": [{"unit_id": u["id"], "title": u["title"]} for u in added],
        "estimate": {"min": spent + float(cr["min"]), "max": spent + float(cr["max"])},
    }  # fmt: skip
    summary = f"The Director asks the owner for {data['requested']:g} credits for a change from the Meeting Hall."
    part = _part(call, "budget.requested", summary, data, severity="needs_you", vis=[], cause=revised["id"],
                 id_=events.stable_part_id(pid, "budget"))  # fmt: skip
    try:
        ctx.writer.append(ctx.world_id, part)
    except Exception as exc:
        logger.warning("budget request for world %s not written (%s)", ctx.world_id, type(exc).__name__)
        raise _Refused("budget") from None


def _credits(attempts: list) -> float:
    """Credits the attempts that reached a model cost: their tokens at the profile's price (unknown: none)."""
    try:
        providers, total = deps.providers_config(), 0.0
        for a in attempts:
            if a.tokens_in is not None and a.tokens_out is not None:
                q = providers.price(a.profile_id)
                total += providers.credits((a.tokens_in * q.input + a.tokens_out * q.output) / 1e6)
        return total
    except Exception:
        return 0.0


def _charge(call: mr.PlanCall, meter: _Metered) -> None:
    """Settles the confirmer's hold (a model was reached) or releases it; one ledger row with the credits."""
    mr.release(call.held, called=bool(meter.attempts))
    credits, ctx = _credits(meter.attempts), call.ctx
    writer = deps.ledger_writer_for(ctx.request)
    if writer is None or credits <= 0:
        return
    last = meter.attempts[-1]
    usage = Usage(last.profile_id, max(last.tokens_in or 0, 0), max(last.tokens_out or 0, 0))
    entry = LedgerEntry(
        "commit", mr.plan_run(call.room.room_id), ctx.principal.user_id, deps.ORG_ID, datetime.now(UTC),
        step="revision_plan", credits=float(credits), usage=usage,
    )  # fmt: skip
    try:
        writer.append(entry)
    except Exception as exc:
        logger.warning("revision ledger write failed: %s", type(exc).__name__)
