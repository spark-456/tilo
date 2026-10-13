"""ADR-0042 (BQ-M2-4, BQ-M2-5; MV-01 to MV-16): the two routes the meeting bot meters its Gemini Live voice through.

`POST /internal/meeting-voice/reserve` and `.../close` are public routes of the access gate and of App Check and check
their own caller: a Google ID token for `TILO_VOICE_METER_AUDIENCE` from `TILO_VOICE_METER_CALLER`, variables of their
own (never the schedule tick's or the Tasks one). A body names the meeting, the attend's nonce and a key of its own per
reply and nothing else (closed schema, 2 KiB): the uid and org come from the attend claim (`meeting_voice_claims`),
the amount is `unit_reserve_minor`, and what a reply is booked at is priced here from config and never above that one
unit (K = 1, MV-15). Anything but 200 `live` is the local voice. Deterministic code; no event, no outbox, no model.

INERT until the user answers BQ-M2-5: `TILO_VOICE_METER` unset (or not "1") is a plain 404, nothing read."""

from __future__ import annotations

import dataclasses
import logging
import math
import os
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from tilo_contracts import MeetingVoiceMeterCloseRequest, MeetingVoiceMeterReserveRequest
from tilo_harness.schedule import tick_caller_ok
from tilo_providers.meeting import load_meeting_caps
from tilo_providers.voice import load_voice_config

from tilo_api import deps, meeting_voice_claims, schedules, spend
from tilo_api.meeting_voice_claims import AttendClaims, Claim, Hold
from tilo_api.spend_units import INR_MINOR_PER_USD
from tilo_api.spend_voice import LiveVoiceSpend

logger = logging.getLogger("tilo_api.meeting_voice")
router = APIRouter()
ENV_AUDIENCE, ENV_CALLER = "TILO_VOICE_METER_AUDIENCE", "TILO_VOICE_METER_CALLER"
RESERVE, CLOSE = "/internal/meeting-voice/reserve", "/internal/meeting-voice/close"
MAX_BODY = 2048
_AUDIENCE = re.compile(r"https://[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?(?::[0-9]{1,5})?")
_CONFIG = Path(__file__).resolve().parents[4] / "config"


@dataclass(frozen=True)
class MeterConfig:
    caps: spend.SpendCaps  # `unit_reserve_minor` is the hold and the most one reply books (K = 1)
    ceiling: int  # tokens: max(8 x voice.live.max_output_tokens, 4 x voice.max_chars); above it a count is not believed
    hold_ttl_s: float  # 3 x voice.live.timeout_s
    max_reserves: int  # `config/meeting.yaml` max_speech_calls, per claim
    cost_usd: Callable[[int, int], float] | None  # (prompt, response tokens) -> USD from the live profile's price row


class NotConfigured(Exception):
    """A setting, a config file or the ledger is missing or unusable: the routes answer 503."""


def load_meter_config(root: Path | None = None) -> MeterConfig:
    root = root or _CONFIG
    voice = load_voice_config(root / "voice.yaml", models_path=root / "models.yaml")
    if voice.live is None:
        raise NotConfigured("no voice.live section")
    profile, cost = voice.live.profile_id, None
    try:  # no price row (or an unset sheet) is a priced-at-the-whole-unit meter, not a refusal (MV-09)
        providers = deps.providers_config()
        cost = lambda i, o: providers.cost_usd(profile, i, o, at=date.today())  # noqa: E731
    except Exception as exc:
        logger.warning("meeting voice prices unavailable (%s)", type(exc).__name__)
    return MeterConfig(
        caps=spend.load_spend_caps(root / "spend_caps.yaml"),
        ceiling=max(8 * voice.live.max_output_tokens, 4 * voice.max_chars),
        hold_ttl_s=3 * float(voice.live.timeout_s),
        max_reserves=load_meeting_caps(root / "meeting.yaml").max_speech_calls,
        cost_usd=cost,
    )


def get_meter_config() -> MeterConfig:
    """Read on every call (a cap, a price or a ceiling is a config edit, never code)."""
    try:
        return load_meter_config()
    except Exception as exc:
        raise NotConfigured(type(exc).__name__) from exc


def _price_minor(cfg: MeterConfig, prompt: int, response: int) -> int | None:
    if cfg.cost_usd is None:
        return None
    try:
        return max(1, math.ceil(cfg.cost_usd(prompt, response) * INR_MINOR_PER_USD))
    except Exception:  # no row, expired price, nonsense: unpriced
        return None


def bounded_minor(cfg: MeterConfig, usage: Mapping[str, int], unit: int) -> int | None:
    """MV-09, MV-15: the bot's counts priced from config, at least 1 and at most the unit; None (the whole unit) for
    empty usage, a count above the ceiling (a total above twice it), an unpriced profile. Never above the hold."""
    prompt, response, total = (
        usage.get(k) for k in ("prompt_token_count", "response_token_count", "total_token_count")
    )
    if prompt is None and response is None:
        return None
    if any(c is not None and c > cfg.ceiling for c in (prompt, response)) or (total or 0) > 2 * cfg.ceiling:
        return None
    priced = _price_minor(cfg, prompt or 0, response or 0)
    return None if priced is None else min(priced, unit)


def _ceiling_fits(cfg: MeterConfig) -> bool:
    """A ceiling-sized reply priced above one unit would be under-booked in silence, so the routes refuse (503)."""
    priced = _price_minor(cfg, cfg.ceiling, cfg.ceiling)
    return priced is None or priced <= cfg.caps.unit_reserve_minor


# --- the routes ------------------------------------------------------------------------------------------------------


def _out(status: int, body: dict[str, str], route: str, why: str) -> JSONResponse:
    logger.info("meeting voice meter %s %s %s", route.rsplit("/", 1)[-1], status, why)  # route, status, reason only
    return JSONResponse(body, status_code=status, headers={"Cache-Control": "no-store"})


def _error(status: int, code: str, route: str) -> JSONResponse:
    return _out(status, {"error": code}, route, code)


def _pins() -> tuple[str, str] | None:
    """(audience, caller) when both are set and valid and the caller is not the tick's or the Tasks account."""
    audience, caller = os.environ.get(ENV_AUDIENCE) or "", os.environ.get(ENV_CALLER) or ""
    others = {os.environ.get(schedules.ENV_CALLER) or "", os.environ.get(schedules.ENV_TASKS_CALLER) or ""}
    if not _AUDIENCE.fullmatch(audience) or not caller or caller in others:
        return None
    return audience, caller


def _bearer(request: Request) -> str | None:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    token = token.strip()
    return token if scheme.lower() == "bearer" and token and not any(c.isspace() for c in token) else None


async def _read_body(request: Request) -> bytes | None:
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BODY:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


def _seam(request: Request, fn: Callable[[], Any]) -> Any:
    return request.app.dependency_overrides.get(fn, fn)()


async def _serve(request: Request, route: str) -> JSONResponse:
    if not meeting_voice_claims.enabled():  # the default: as if the route did not exist
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    if (pins := _pins()) is None:
        return _error(503, "not_configured", route)
    audience, caller = pins
    if (token := _bearer(request)) is None:
        return _error(401, "unauthenticated", route)
    try:
        claims = await run_in_threadpool(_seam(request, schedules.get_oidc_verifier).verify, token, audience)
    except Exception as exc:  # bad signature, expiry, audience or a verifier outage: the type only, never the text
        logger.warning("meeting voice meter token refused (%s)", type(exc).__name__)
        return _error(401, "unauthenticated", route)
    if not isinstance(claims, Mapping):
        return _error(401, "unauthenticated", route)
    if not tick_caller_ok(claims, audience=audience, caller=caller):
        return _error(403, "forbidden", route)
    raw = await _read_body(request)
    try:
        if raw is None:
            raise ValueError("too large")
        model = MeetingVoiceMeterReserveRequest if route == RESERVE else MeetingVoiceMeterCloseRequest
        body = model.model_validate_json(raw)
        if isinstance(body, MeetingVoiceMeterCloseRequest) and (body.outcome == "settled") != (body.usage is not None):
            raise ValueError("usage exactly when settled")
    except (ValidationError, ValueError):
        return _error(422, "invalid_request", route)
    return await run_in_threadpool(_decide, request, route, body)


@router.post(RESERVE)
async def reserve(request: Request) -> JSONResponse:
    return await _serve(request, RESERVE)


@router.post(CLOSE)
async def close(request: Request) -> JSONResponse:
    return await _serve(request, CLOSE)


def _decide(request: Request, route: str, body: Any) -> JSONResponse:
    try:
        cfg: MeterConfig = _seam(request, get_meter_config)
        if not _ceiling_fits(cfg):
            raise NotConfigured("a ceiling-sized reply is priced above the unit")
        claims: AttendClaims | None = _seam(request, meeting_voice_claims.get_attend_claims)
        claim = claims.find(body.meeting_id, body.claim) if claims is not None else None
        if claim is None:  # absent, wrong nonce, another attend's, expired: one answer (MV-14, MV-16)
            return _error(409, "not_attending", route)
        with claim.lock:
            if route == RESERVE:
                return _reserve(request, claims, claim, cfg, body.key)
            return _close(claim, cfg, body)
    except NotConfigured:
        return _error(503, "not_configured", route)


def _replay(reason: str) -> JSONResponse:
    return _out(200, {"decision": "replay", "reason": reason}, RESERVE, reason)


def _guard(request: Request, uid: str, cfg: MeterConfig) -> spend.SpendGuard | None:
    """The uid's guard as `deps.meter_for` builds it: the team's role and limits only ever lower the lifetime cap, and
    limits that cannot be read are no live voice. None: no Live voice. NotConfigured: no ledger is wired."""
    from tilo_api import team_access, team_store  # noqa: PLC0415  (team_store's dev seam imports `deps`)

    try:
        cap = team_access.user_cap_minor(
            team_store.team_reader(request.app.dependency_overrides)(), uid, cfg.caps.uid_lifetime_minor
        )
    except Exception as exc:
        logger.warning("team limits unreadable, so no live voice (%s)", type(exc).__name__)
        return None
    try:
        ledger, flags = _seam(request, deps.get_spend_cap_ledger), _seam(request, deps.get_flag_store)
    except Exception as exc:
        raise NotConfigured(type(exc).__name__) from exc
    if cap <= 0:
        return None
    caps = dataclasses.replace(cfg.caps, uid_lifetime_minor=min(cap, cfg.caps.uid_lifetime_minor))
    return spend.SpendGuard(ledger, flags, caps)


def _reserve(request: Request, claims: AttendClaims, claim: Claim, cfg: MeterConfig, key: str) -> JSONResponse:
    known = claim.holds.get(key)
    if known is not None:  # the same reply again: one hold; a closed key is never reopened (MV-05)
        if known.state == "open":
            return _out(200, {"decision": "live"}, RESERVE, "live")
        return _error(409, "key_used", RESERVE)
    if claim.open_hold() is not None:  # one spoken reply at a time (MV-06)
        return _replay("hold_open")
    if claim.reserves >= cfg.max_reserves:
        return _replay("meeting_limit")
    claim.reserves += 1
    guard = _guard(request, claim.uid, cfg)
    if guard is None:
        return _replay("unavailable")
    unit = cfg.caps.unit_reserve_minor
    if guard.headroom_minor(claim.uid) < unit:  # under one unit of room, also under a team-lowered cap
        return _replay("capped" if guard.uid_capped(claim.uid) or guard.headroom_minor(claim.uid) else "unavailable")
    meter = LiveVoiceSpend(guard, uid=claim.uid, run_id=claim.run_id, org_id=claim.org_id, unit_minor=unit)
    plan = meter.reserve()
    if plan is None:
        return _replay(meter.refusal or "unavailable")
    claim.holds[key] = Hold(plan, guard, unit, claims.now())
    return _out(200, {"decision": "live"}, RESERVE, "live")


def _close(claim: Claim, cfg: MeterConfig, body: MeetingVoiceMeterCloseRequest) -> JSONResponse:
    hold = claim.holds.get(body.key)
    if hold is None:  # a settle with no reserve, another claim's key, a replay that held nothing (MV-05)
        return _error(409, "no_hold", CLOSE)
    if hold.state != "open":  # the same close again answers as the first did; a different one has no hold
        if hold.state == body.outcome:
            return _out(200, {"outcome": hold.state}, CLOSE, hold.state)
        return _error(409, "no_hold", CLOSE)
    meter = LiveVoiceSpend(
        hold.guard, uid=claim.uid, run_id=claim.run_id, org_id=claim.org_id, unit_minor=hold.unit,
        price=lambda usage: bounded_minor(cfg, usage, hold.unit),
    )  # fmt: skip
    if body.outcome == "settled":
        meter.settle(hold.plan, body.usage.model_dump(exclude_none=True) if body.usage is not None else {})
    else:
        meter.release(hold.plan)
    hold.state = body.outcome
    return _out(200, {"outcome": hold.state}, CLOSE, hold.state)
