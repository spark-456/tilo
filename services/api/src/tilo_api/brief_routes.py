"""`/v1/me/brief` and `/v1/me/brief-settings`, and the Scheduler's brief sweep (ADR-0049, MO-01 to MO-04, MO-10).

Whose: the owner and the org are the verified Principal and `deps.ORG_ID`; no route takes a user id, a date or an org,
and nobody reads another person's brief or setting. `GET /v1/me/brief` serves today's latest version (404 `not_ready`
before the first); `POST /v1/me/brief` (body `{}`) makes one now, three a day (429 `brief_limit`, nothing read). A
setting sends nothing and grants nothing (MO-02). The sweep runs on the tick's every-minute Scheduler call, only with
`TILO_MORNING_BRIEF=1`, claims (org, user, local date) before it makes anything and makes at most ten per tick (MO-03).
Whatever fails for one person is logged by type and never changes the tick's answer.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Annotated, Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Request
from tilo_memory.artifacts import ArtifactStore
from tilo_people.stores import PeopleStores
from tilo_policy.schemas import conforms
from tilo_providers.interfaces import GenerateRequest

from tilo_api import deps, events, morning_brief_model, plate_mailer
from tilo_api.assistant.config import AssistantConfig
from tilo_api.assistant.metering import SpendLedger
from tilo_api.brief_store import BriefStore, MemoryBriefStore, brief_store_of
from tilo_api.meeting_allowance import allowance_router
from tilo_api.meeting_analysis_mode import _Calls, _Router, _Safety
from tilo_api.morning_brief import ON_DEMAND_MAX, SCHEMA, Ctx, local_date
from tilo_api.morning_brief_doc import make_brief, purge_old, read_latest
from tilo_api.people import _PeopleRoute
from tilo_api.people_limits import write_limit
from tilo_api.people_plate import build_plate
from tilo_api.people_writes import Empty, Refusal, _Closed, json_body
from tilo_api.quick_rules import load_quick_rules
from tilo_api.user_settings import _zone_known, settings_store_of

logger = logging.getLogger("tilo_api.brief_routes")
ENV_BRIEF = "TILO_MORNING_BRIEF"
SETTINGS = "/v1/me/brief-settings"
BRIEF = "/v1/me/brief"
MAX_PER_TICK = 10  # MO-03
MAX_PEOPLE = 500
WINDOW = timedelta(hours=3)  # MO-03: a brief is made from the person's time until this long after it
DEFAULT_TIME = "07:30"
_DEMO_STORE = MemoryBriefStore()  # a demo session keeps its setting in the process, never durably (MO-01)

router = APIRouter(route_class=_PeopleRoute)
Principal = Annotated[deps.Principal, Depends(deps.get_current_principal)]
Clock = Annotated[Callable[[], str], Depends(deps.get_clock)]


class SettingsIn(_Closed):
    enabled: bool
    time: str
    time_zone: str
    email_copy: bool


def get_brief_mailer(request: Request) -> Any:
    """The owner-only digest sender (`DeskPlateMailer.deliver_text`, `rule_ready`), or None while a seam it needs is
    missing: nothing is mailed and `email_rule_ready` is false."""
    try:
        return plate_mailer.production_mailer(request.app.dependency_overrides)
    except Exception as exc:  # noqa: BLE001 - HTTPException or NotConfigured: either way, nothing is sent
        logger.info("brief mailer not configured (%s)", type(exc).__name__)
        return None


def _mailer(request: Request) -> Any:
    """The mailer seam as the app is wired (a test's override takes no argument)."""
    seam = request.app.dependency_overrides.get(get_brief_mailer, get_brief_mailer)
    return seam(request) if seam is get_brief_mailer else seam()


def _briefs(principal: deps.Principal, stores: PeopleStores) -> BriefStore:
    return _DEMO_STORE if principal.demo_session else brief_store_of(stores)


def _zone_of(stores: PeopleStores, user: str) -> str:
    try:
        saved = settings_store_of(stores).read(deps.ORG_ID, user)
    except Exception:  # noqa: BLE001 - an unreadable setting is the default zone
        saved = None
    zone = saved["profile"]["time_zone"] if saved is not None else "UTC"
    return zone if _zone_known(zone) else "UTC"


def settings_of(briefs: BriefStore, stores: PeopleStores, user: str, ready: bool) -> dict[str, Any]:
    """MO-02: the stored setting, or the defaults with `updated_at` null; `email_rule_ready` is computed per answer."""
    held = briefs.settings(deps.ORG_ID, user)
    base = held or {
        "enabled": False, "time": DEFAULT_TIME, "time_zone": _zone_of(stores, user), "email_copy": False,
        "updated_at": None,
    }  # fmt: skip
    keys = ("enabled", "time", "time_zone", "email_copy", "updated_at")
    return {"owner_id": user, "org_id": deps.ORG_ID, **{k: base[k] for k in keys}, "email_rule_ready": ready}


def _ready(mailer: Any, user: str, now: str) -> bool:
    try:
        return bool(mailer is not None and mailer.rule_ready(user, now))
    except Exception:  # noqa: BLE001
        return False


@router.get(SETTINGS)
def get_settings(
    request: Request,
    principal: Principal,
    stores: Annotated[PeopleStores, Depends(deps.get_people_stores)],
    clock: Clock,
) -> dict[str, Any]:
    try:
        briefs = _briefs(principal, stores)
        return settings_of(briefs, stores, principal.user_id, _ready(_mailer(request), principal.user_id, clock()))
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=503, detail="unavailable") from None


@router.put(SETTINGS, dependencies=[Depends(write_limit)])
def put_settings(
    body: Annotated[SettingsIn, Depends(json_body(SettingsIn))],
    request: Request,
    principal: Principal,
    stores: Annotated[PeopleStores, Depends(deps.get_people_stores)],
    clock: Clock,
) -> dict[str, Any]:
    """The whole setting; the server owns the owner, the org, `updated_at` and `email_rule_ready` (MO-02)."""
    update = body.model_dump()
    if not conforms(f"{SCHEMA}#/$defs/settings_update", update):
        raise Refusal(422, "invalid_settings", code="invalid_settings", fields=["time"])
    if not _zone_known(update["time_zone"]):
        raise Refusal(422, "invalid_settings", code="invalid_settings", fields=["time_zone"])
    now = clock()
    briefs = _briefs(principal, stores)
    try:
        briefs.save_settings(
            deps.ORG_ID, principal.user_id, {**update, "owner_id": principal.user_id, "updated_at": now}
        )
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=503, detail="unavailable") from None
    return settings_of(briefs, stores, principal.user_id, _ready(_mailer(request), principal.user_id, now))


@router.get(BRIEF)
def get_brief(
    principal: Principal,
    stores: Annotated[PeopleStores, Depends(deps.get_people_stores)],
    artifacts: Annotated[ArtifactStore, Depends(deps.get_artifact_store)],
    desks: Annotated[deps.DeskWorlds, Depends(deps.get_desk_worlds)],
    clock: Clock,
) -> dict[str, Any]:
    """Today's latest version in the person's zone, or 404 `not_ready` (MO-01); it never makes one."""
    user = principal.user_id
    zone = (_briefs(principal, stores).settings(deps.ORG_ID, user) or {}).get("time_zone") or _zone_of(stores, user)
    found = read_latest(artifacts, desks, deps.ORG_ID, user, local_date(clock(), zone))
    if found is None:
        raise Refusal(404, "not_ready")
    return found


def _mode(request: Request, user: str | None, switches: Any, *, demo: bool) -> str | None:
    """The provider mode for this person's call: the request's own for a route, the person's declared mode for the
    sweep. None when a switch or the person's cap says no new work (the model is then skipped)."""
    try:
        if user is None:
            return str(deps.get_work_mode(request, switches))
        ov = request.app.dependency_overrides
        declaration = ov.get(deps.get_access_store, deps.get_access_store)().get(user)
        mode, capped = deps.spend_mode(request, user, declaration, switches, demo=demo)
        return None if capped else str(mode)
    except Exception:  # noqa: BLE001 - replay-only, capped or unreadable: no model call
        return None


def _model(
    request: Request, user: str, now: str, mode: str | None, switches: Any, run_id: str
) -> tuple[Callable[[str], bool] | None, Callable[[str, str], str] | None]:
    """(screen, ask): the SafetyProvider check and the one metered `assistant` call. The same accounting as the
    meeting brief: SEC-16 units through `_Calls` and the person's per-user allowance through `allowance_router`."""
    ov = request.app.dependency_overrides
    resolved: deps.Mode = "live" if mode == "live" else "replay"
    calls = _Calls(request, SimpleNamespace(actor=user, org=deps.ORG_ID, now=now), switches, resolved, run_id)  # type: ignore[arg-type]
    try:
        live = resolved == "live"
        provider = (
            deps.build_safety_provider(deps.providers_config(), fixtures_dir=deps.FIXTURES_DIR, force_replay=False)
            if live
            else deps.get_safety(resolved)
        )
        checker = _Safety(provider, calls)
    except Exception as exc:  # noqa: BLE001
        logger.warning("brief safety unavailable (%s)", type(exc).__name__)
        return None, None

    def screen(text: str) -> bool:
        verdict = checker.check(text)
        if not isinstance(verdict, dict) or type(verdict.get("flagged")) is not bool:
            raise RuntimeError("unreadable verdict")
        return bool(verdict["flagged"])

    if mode is None:
        return screen, None
    config: AssistantConfig = ov.get(deps.get_assistant_config, deps.get_assistant_config)()
    ledger: SpendLedger = ov.get(deps.get_spend_ledger, deps.get_spend_ledger)()
    day = datetime.fromisoformat(now.replace("Z", "+00:00")).date().isoformat()

    def ask(system: str, prompt: str) -> str:
        room = float(config.user_day_credits) - ledger.spent(user, day)
        budget = min(room, load_quick_rules().budget)  # one assistant call of a Quick ask's size
        if budget <= 0:
            raise Refusal(429, "allowance_capped")
        request_ = GenerateRequest(
            system=system, prompt=prompt, json_mode=True, response_schema=morning_brief_model._REPLY_SCHEMA
        )
        with allowance_router(
            _Router(deps.router_for_mode(resolved), calls),  # type: ignore[arg-type]
            ledger=ledger, user=user, clock=lambda: now, cap=float(config.user_day_credits), budget=budget,
        ) as metered:  # fmt: skip
            result = metered.generate("assistant", request_, budget=budget)
        if getattr(result, "outcome", "ok") != "ok" or result.response is None:
            raise RuntimeError("no reply")
        return str(result.response.text or "")

    return screen, ask


def _context(
    request: Request, user: str, *, demo: bool, now: str, zone: str, trigger: str, mode: str | None, email_copy: bool,
    seams: dict[str, Any],
) -> Ctx:  # fmt: skip
    """The brief's context from the seams the caller resolved (`stores`, `artifacts`, `events`, `desks`, `redact`,
    `sources`, `owners`, `briefs`, `switches`) and the app's own meeting-host client and mailer."""
    ov = request.app.dependency_overrides
    desks = seams["desks"]
    run_id = "r_" + desks.desk_world(deps.ORG_ID, user)[2:50]
    screen, ask = _model(request, user, now, mode, seams["switches"], run_id) if not demo else (None, None)
    return Ctx(
        org=deps.ORG_ID, user=user, demo=demo, now=now, zone=zone, trigger=trigger, artifacts=seams["artifacts"],
        events=seams["events"], desks=desks, redact=seams["redact"],
        plate=lambda: build_plate(seams["stores"], seams["sources"], seams["owners"], deps.ORG_ID, user, now),
        rpc=ov.get(deps.get_meeting_host_client, deps.get_meeting_host_client), briefs=seams["briefs"],
        screen=screen, ask=ask, mailer=None if demo else _mailer(request), email_copy=email_copy,
    )  # fmt: skip


@router.post(BRIEF)
def make_now(
    _: Annotated[Empty, Depends(json_body(Empty))],
    request: Request,
    principal: Principal,
    stores: Annotated[PeopleStores, Depends(deps.get_people_stores)],
    artifacts: Annotated[ArtifactStore, Depends(deps.get_artifact_store)],
    events_: Annotated[deps.EventWriter, Depends(deps.get_event_writer)],
    desks: Annotated[deps.DeskWorlds, Depends(deps.get_desk_worlds)],
    redact: Annotated[Callable[[str], str], Depends(deps.get_redactor)],
    sources: Annotated[deps.PlateSources, Depends(deps.get_plate_sources)],
    owners: Annotated[deps.SourceOwners, Depends(deps.get_source_owners)],
    switches: Annotated[Any, Depends(deps.get_switches)],
    clock: Clock,
) -> dict[str, Any]:
    """MO-04: a version now, whatever `enabled` says, three a day per local date. The count comes before any read."""
    user = principal.user_id
    if getattr(request.state, "uid", None) not in (None, user):
        raise Refusal(404, "not_found")
    briefs = _briefs(principal, stores)
    now = clock()
    zone = (briefs.settings(deps.ORG_ID, user) or {}).get("time_zone") or _zone_of(stores, user)
    day = local_date(now, zone)
    if not briefs.take_on_demand(deps.ORG_ID, user, day, ON_DEMAND_MAX):
        raise Refusal(429, "brief_limit")
    seams = dict(stores=stores, artifacts=artifacts, events=events_, desks=desks, redact=redact, sources=sources,
                 owners=owners, briefs=briefs, switches=switches)  # fmt: skip
    mode = None if principal.demo_session else _mode(request, None, switches, demo=False)
    ctx = _context(request, user, demo=principal.demo_session, now=now, zone=zone, trigger="on_demand", mode=mode,
                   email_copy=False, seams=seams)  # fmt: skip
    return make_brief(ctx, day)


# -- the Scheduler's sweep (MO-03) -----------------------------------------------------------------------------------


def due_date(now: str, zone: str, clock_time: str) -> str | None:
    """The local date this person's brief is due for at `now`: from their time until three hours after it, which may
    run past midnight into the next local day. None outside the window."""
    local = datetime.fromisoformat(now.replace("Z", "+00:00")).astimezone(ZoneInfo(zone))
    hour, minute = (int(part) for part in clock_time.split(":"))
    for back in (0, 1):  # the window that started today, or yesterday and runs past midnight
        start = (local - timedelta(days=back)).replace(hour=hour, minute=minute, second=0, microsecond=0)
        if start <= local < start + WINDOW:
            return start.date().isoformat()
    return None


def sweep(request: Request, now: str) -> int:
    """One pass: every person with the setting on whose window is open and whose (org, user, date) nobody has claimed
    gets a brief, at most `MAX_PER_TICK`. Off unless `TILO_MORNING_BRIEF=1`; returns how many were made."""
    if os.environ.get(ENV_BRIEF) != "1":
        return 0
    ov = request.app.dependency_overrides

    def seam(fn: Callable[..., Any]) -> Any:
        return ov.get(fn, fn)()

    try:
        stores = seam(deps.get_people_stores)
        briefs = brief_store_of(stores)
        candidates = sorted(briefs.enabled(deps.ORG_ID, MAX_PEOPLE), key=lambda d: d["owner_id"])
        flags = seam(deps.get_flag_store)
        found = ov.get(deps.get_switches)
        seams = dict(
            stores=stores, artifacts=seam(deps.get_artifact_store), events=seam(deps.get_event_writer),
            desks=seam(deps.get_desk_worlds), redact=seam(deps.get_redactor), sources=seam(deps.get_plate_sources),
            owners=seam(deps.get_source_owners), briefs=briefs,
            switches=found() if found is not None else deps.get_switches(request, flags),
        )  # fmt: skip
    except Exception as exc:  # noqa: BLE001
        logger.info("morning brief sweep not run (%s)", type(exc).__name__)
        return 0
    made = 0
    for setting in candidates:
        if made >= MAX_PER_TICK:
            break
        user = setting["owner_id"]
        try:
            day = due_date(now, setting["time_zone"], setting["time"])
            if day is None or not briefs.claim(deps.ORG_ID, user, day, "schedule"):
                continue
            made += 1  # a claim is spent whether or not the brief succeeds: one try per person per day
            mode = _mode(request, user, seams["switches"], demo=False)
            ctx = _context(request, user, demo=False, now=now, zone=setting["time_zone"], trigger="schedule",
                           mode=mode, email_copy=setting["email_copy"], seams=seams)  # fmt: skip
            make_brief(ctx, day)
            if briefs.claim(deps.ORG_ID, user, local_date(now, setting["time_zone"]), "purge"):
                purge_old(seams["artifacts"], seams["desks"], deps.ORG_ID, user, day)
        except Exception as exc:  # noqa: BLE001 - the type only; never a title, subject or address
            logger.warning("a morning brief failed for one person (%s)", type(exc).__name__)
    return made


__all__ = ["router", "sweep", "events", "ZoneInfoNotFoundError"]
