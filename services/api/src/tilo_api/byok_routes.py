"""`GET`, `PUT`, `PATCH` and `DELETE /v1/org/model-key` (ADR-0041 decisions 2 and 3, BYOK-3a). SECURITY PATH: this is
credential handling, and it is INERT: with `config/byok.yaml` `enabled: false` (the shipped value) every route answers
503 `not_configured` before it looks at the principal, the body or any store.

Who: the org is `deps.ORG_ID` (never a body, path or query value, BK-08); the actor is the verified principal on a full
web session whose directory record (`org_role`, PE-17) is `owner`, never `Principal.role` (every signed-in person is
`owner` of their own worlds, BK-05). A member reads `{active, label}` only. Widening acts (set or rotate, a bundle, a
higher cap, fallback on, resume) are T3 (`config/autonomy.yaml` `org_model_key_change`): they need a sign-in at most 10
minutes old (401 `reauth_required`), `confirm: true` and the `consent_version` the person saw (422 `confirm_required`),
and are limited to 5 an hour per org. Narrowing (pause, a lower cap, fallback off, removal) is immediate and never
limited: a revocation is never harder than a grant.

No key is ever in an answer, a log record, an audit entry or the reference (BK-02, BK-04): the only place this process
sees one is the `put` body in transit, handed to the vault and dropped. Validation errors answer a fixed code and never
the input (FastAPI's default 422 echoes it). The vault is a seam with no deployed implementation yet (503
`not_configured`). A failed reference write after the vault created a version removes that version (no half state).
"""

from __future__ import annotations

import logging
import os
import re
import threading
import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, ValidationError
from tilo_people.stores import PeopleStores
from tilo_policy import load_risk_table
from tilo_providers.byok import ByokConfig, OrgBundle, load_byok_config

from tilo_api import deps
from tilo_api.byok_store import SLOT, KeyReference, ModelKeyVault, OrgKeyStore, VaultRefused
from tilo_api.people import _PeopleRoute
from tilo_api.people_writes import Refusal, Writer, _capped_body

logger = logging.getLogger("tilo_api.byok")
ROUTE = "/v1/org/model-key"
ACTION = "org_model_key_change"  # config/autonomy.yaml, pinned T3
FRESH_S = 600  # BK-06: a sign-in older than 10 minutes cannot widen
_KEY = re.compile(r"[A-Za-z0-9_\-.~+/=]{8,512}")  # a bearer token's characters: JSON, spaces and quotes never match
_PROJECT = re.compile(r"[a-z][a-z0-9-]{4,28}[a-z0-9]")
# SEC-REVIEW-29 B1. A `google_vertex_iam` bundle is the org's own Vertex project reached by Tilo's service identity,
# so a project the owner types could be Tilo's own (Tilo-billed spend that SEC-16 never sees). Nothing proves a
# project is the org's yet (BQ-BYOK-2 is open; the grant check is BYOK-4/6), so the route refuses the bundle. Only
# that ticket flips it.
VERTEX_GRANT_CHECKED = False
router = APIRouter(route_class=_PeopleRoute)


# --- seams: the flag, the vault, the store --------------------------------------------------------------------------


def get_byok_config() -> ByokConfig:
    """`config/byok.yaml`, read on every call. Anything unreadable is the off config: fail closed, nothing is keyed."""
    try:
        return load_byok_config(providers=deps.providers_config())
    except Exception as exc:  # noqa: BLE001
        logger.warning("byok config unusable, so BYOK is off: %s", type(exc).__name__)
        return ByokConfig()


def get_model_key_vault() -> ModelKeyVault:
    """No deployed vault yet (BYOK-4: connectors' routes and the Secret Manager adapter, a contract change first)."""
    raise HTTPException(status_code=503, detail="not_configured")


_STORE: OrgKeyStore | None = None
_STORE_LOCK = threading.Lock()


def get_org_key_store() -> OrgKeyStore:
    """Dev and tests: one in-memory store. Deployed it is refused (the Firestore store is a later ticket)."""
    global _STORE
    if "K_SERVICE" in os.environ or "CLOUD_RUN_JOB" in os.environ:
        raise HTTPException(status_code=503, detail="not_configured")
    with _STORE_LOCK:
        if _STORE is None:
            _STORE = OrgKeyStore()
        return _STORE


# --- who may act ----------------------------------------------------------------------------------------------------


class Actor:
    def __init__(self, user: str, org: str, owner: bool, now: str, auth_time: float | None) -> None:
        self.user, self.org, self.owner, self.now, self.auth_time = user, org, owner, now, auth_time

    @property
    def epoch(self) -> float:
        return datetime.fromisoformat(self.now.replace("Z", "+00:00")).timestamp()


def gated(config: Annotated[ByokConfig, Depends(get_byok_config)]) -> ByokConfig:
    if not config.enabled:
        raise HTTPException(status_code=503, detail="not_configured")
    return config


def actor(
    _: Annotated[ByokConfig, Depends(gated)],
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    stores: Annotated[PeopleStores, Depends(deps.get_people_stores)],
    clock: Annotated[Any, Depends(deps.get_clock)],
) -> Actor:
    """A full web session with a directory record in this org. Demo, email and signed-link sessions have none."""
    if principal.demo_session or not principal.full_session:
        raise Refusal(403, "owner_only")
    now = clock()
    try:
        record = Writer(stores, deps.ORG_ID, principal.user_id, now).directory().record(principal.user_id)
    except Exception:  # noqa: BLE001 - the directory cannot be read: nothing is decided
        raise HTTPException(status_code=503, detail="unavailable") from None
    if record is None:
        raise Refusal(403, "forbidden")
    return Actor(
        principal.user_id, deps.ORG_ID, record.get("org_role") == "owner", now, getattr(principal, "auth_time", None)
    )


def owner(who: Annotated[Actor, Depends(actor)]) -> Actor:
    if not who.owner:
        raise Refusal(403, "owner_only")
    return who


def fresh_owner(who: Annotated[Actor, Depends(owner)]) -> Actor:
    """BK-06 for a widening act: the verified `auth_time` is at most 10 minutes old."""
    if who.auth_time is None or who.epoch - who.auth_time > FRESH_S or who.auth_time > who.epoch + 60:
        raise Refusal(401, "reauth_required", code="reauth_required")
    return who


# --- bodies: closed, strict, and a validation error never echoes its input -----------------------------------------


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)


class PutIn(_Closed):
    confirm: StrictBool
    consent_version: StrictInt
    bundle_id: Annotated[str, Field(min_length=1, max_length=64)]
    day_cap_credits: Annotated[StrictInt, Field(ge=1, le=1_000_000_000)]
    fallback_to_tilo: StrictBool = False
    key: str | None = Field(default=None, max_length=4096, repr=False)
    project_id: str | None = Field(default=None, max_length=64)


class PatchIn(_Closed):
    paused: StrictBool | None = None
    day_cap_credits: Annotated[StrictInt, Field(ge=1, le=1_000_000_000)] | None = None
    fallback_to_tilo: StrictBool | None = None
    confirm: StrictBool | None = None
    consent_version: StrictInt | None = None


def body_of[Model: BaseModel](model: type[Model]) -> Any:
    """JSON only (415); a refusal is a fixed code: `confirm_required` when the confirm or the consent version is wrong,
    `key_refused` when the key or project is, else `invalid_body`. The input is never echoed (BK-02)."""

    async def parse(request: Request) -> Model:
        if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
            raise Refusal(415, "Send application/json.")
        raw = await _capped_body(request)
        try:
            return model.model_validate_json(raw)
        except ValidationError as exc:
            where = {str(e["loc"][0]) for e in exc.errors() if e["loc"]}
            code = (
                "confirm_required"
                if where & {"confirm", "consent_version"}
                else "key_refused"
                if where & {"key", "project_id"}
                else "invalid_body"
            )
            raise Refusal(422, code, code=code) from None  # `from None`: no context holds the input

    return parse


# --- the routes -----------------------------------------------------------------------------------------------------


def _public(ref: KeyReference | None, config: ByokConfig, *, owner_view: bool) -> dict[str, Any]:
    bundle = config.bundles.get(ref.bundle_id) if ref else None
    base: dict[str, Any] = {"active": bool(ref and ref.active()), "label": bundle.label if bundle and ref else None}
    if not owner_view:
        return base  # every member may see where their work goes, and nothing more (BK-20)
    if ref is None:
        return {**base, "state": "none", "consent_version": config.consent_version}
    keep = ("bundle_id", "auth_mode", "project_id", "secret_version", "set_at", "rotated_at", "day_cap_credits")
    keep += ("fallback_to_tilo", "last_error", "last_used_at", "consent_version")
    return {**base, "state": ref.status, **{k: v for k, v in ref.to_dict().items() if k in keep}}


@router.get(ROUTE)
def read_key(
    who: Annotated[Actor, Depends(actor)],
    config: Annotated[ByokConfig, Depends(gated)],
    store: Annotated[OrgKeyStore, Depends(get_org_key_store)],
) -> dict[str, Any]:
    return _public(store.get(who.org), config, owner_view=who.owner)


def _audit(store: OrgKeyStore, who: Actor, action: str, ref: KeyReference | None, *, widening: bool, cfg: int) -> None:
    entry = {
        "id": uuid.uuid4().hex, "at": who.now, "actor": who.user, "action": action,
        "bundle": ref.bundle_id if ref else None, "version": ref.secret_version if ref else None, "outcome": "ok",
        "authz": {
            "actor": who.user, "org_role": "owner", "basis": "owner_confirm" if widening else "owner_narrowing",
            "tier": "T3" if widening else None, "consent_version": cfg if widening else None,
        },
    }  # fmt: skip
    try:
        store.audit(who.org, entry)
    except Exception as exc:  # noqa: BLE001 - the act is done; the id is enough to find the gap
        logger.warning("byok audit entry %s not written (%s)", entry["id"], type(exc).__name__)


def _widening(store: OrgKeyStore, who: Actor, config: ByokConfig, confirm: bool | None, version: int | None) -> None:
    """The person act of a T3 widening: pinned tier, confirm, consent version, then the hourly limit."""
    if load_risk_table().tier_of(ACTION, []) != "T3":  # the pin in config/autonomy.yaml: fail closed if it moved
        raise HTTPException(status_code=503, detail="not_configured")
    if confirm is not True or version != config.consent_version:
        raise Refusal(422, "confirm_required", code="confirm_required")
    wait = store.note_act(who.org, who.epoch)
    if wait is not None:
        raise Refusal(429, "rate_limited", headers={"Retry-After": str(wait)}, code="rate_limited")


def _mode(bundle: OrgBundle, body: PutIn) -> str:
    """BQ-BYOK-2: an API key is a secret; Vertex IAM takes a project and never a key."""
    if bundle.kind == "google_vertex_iam":
        if not VERTEX_GRANT_CHECKED:  # SEC-REVIEW-29 B1: refused before any act is counted or any vault is asked
            raise Refusal(422, "key_refused", code="key_refused")
        if body.key is not None or body.project_id is None or not _PROJECT.fullmatch(body.project_id):
            raise Refusal(422, "key_refused", code="key_refused")
        return "vertex_iam"
    if body.project_id is not None or body.key is None or not _KEY.fullmatch(body.key):
        raise Refusal(422, "key_refused", code="key_refused")  # a service-account JSON never matches the charset
    return "api_key"


@router.put(ROUTE)
def put_key(
    who: Annotated[Actor, Depends(fresh_owner)],
    config: Annotated[ByokConfig, Depends(gated)],
    body: Annotated[PutIn, Depends(body_of(PutIn))],
    store: Annotated[OrgKeyStore, Depends(get_org_key_store)],
    vault: Annotated[ModelKeyVault, Depends(get_model_key_vault)],
) -> dict[str, Any]:
    """Set or rotate: validate, create the version, write the reference, compensate if that write fails (BK-03)."""
    bundle = config.bundles.get(body.bundle_id)
    if bundle is None or body.day_cap_credits > config.day_cap_credits_max:
        raise Refusal(422, "invalid_body", code="invalid_body")
    mode = _mode(bundle, body)
    _widening(store, who, config, body.confirm, body.consent_version)
    held = store.get(who.org)
    try:
        put = vault.put(who.org, SLOT, mode=mode, key=body.key, project_id=body.project_id)
    except VaultRefused as refused:
        if refused.code == "key_refused":
            raise Refusal(422, "key_refused", code="key_refused") from None
        raise HTTPException(status_code=503, detail="unavailable") from None
    except Exception:  # noqa: BLE001 - connectors or the vault is down; nothing was kept
        raise HTTPException(status_code=503, detail="unavailable") from None
    record = KeyReference(
        bundle_id=bundle.id, auth_mode="vertex_iam" if mode == "vertex_iam" else "api_key", project_id=body.project_id,
        status="active" if put.validated else "unverified", secret_version=put.secret_version, set_by=who.user,
        set_at=held.set_at if held else who.now, rotated_at=who.now if held else None,
        day_cap_credits=body.day_cap_credits, fallback_to_tilo=body.fallback_to_tilo,
        consent_version=body.consent_version, rev=(held.rev + 1) if held else 1,
    )  # fmt: skip
    try:
        stored = store.cas(who.org, record, expected_rev=held.rev if held else 0)
    except Exception:  # noqa: BLE001
        stored = False
    if not stored:
        try:  # the compensating act: this version never becomes usable and the old key stays as it was
            vault.remove(who.org, SLOT, put.secret_version)
        except Exception as exc:  # noqa: BLE001
            logger.warning("byok compensating remove failed (%s)", type(exc).__name__)
        raise HTTPException(status_code=503, detail="unavailable")
    _audit(store, who, "rotate" if held else "set", record, widening=True, cfg=body.consent_version)
    return {"state": record.status, "secret_version": record.secret_version, "validated": put.validated}


@router.patch(ROUTE)
def change_settings(
    who: Annotated[Actor, Depends(owner)],
    config: Annotated[ByokConfig, Depends(gated)],
    body: Annotated[PatchIn, Depends(body_of(PatchIn))],
    store: Annotated[OrgKeyStore, Depends(get_org_key_store)],
) -> dict[str, Any]:
    """Narrowing is immediate; the same body that raises something is a person act (confirm and a fresh sign-in)."""
    held = store.get(who.org)
    if held is None or body.model_dump(exclude={"confirm", "consent_version"}, exclude_none=True) == {}:
        raise Refusal(422, "invalid_body", code="invalid_body")
    changes: dict[str, Any] = {}
    widening = False
    if body.paused is not None and body.paused != (held.status == "paused"):
        if (
            body.paused and held.status != "active"
        ):  # B2: only a verified key is paused, so a resume restores a verified one
            raise Refusal(422, "invalid_body", code="invalid_body")
        changes["status"] = "paused" if body.paused else "active"
        widening |= not body.paused
    if body.day_cap_credits is not None:
        if body.day_cap_credits > config.day_cap_credits_max:
            raise Refusal(422, "invalid_body", code="invalid_body")
        changes["day_cap_credits"] = body.day_cap_credits
        widening |= body.day_cap_credits > held.day_cap_credits
    if body.fallback_to_tilo is not None:
        changes["fallback_to_tilo"] = body.fallback_to_tilo
        widening |= body.fallback_to_tilo and not held.fallback_to_tilo
    if widening:
        fresh_owner(who)
        _widening(store, who, config, body.confirm, body.consent_version)
    updated = held.bumped(**changes, consent_version=body.consent_version if widening else held.consent_version)
    try:
        stored = store.cas(who.org, updated, expected_rev=held.rev)
    except Exception:  # noqa: BLE001
        stored = False
    if not stored:
        raise HTTPException(status_code=503, detail="unavailable")
    _audit(store, who, "change", updated, widening=widening, cfg=updated.consent_version)
    return _public(updated, config, owner_view=True)


@router.delete(ROUTE)
def remove_key(
    who: Annotated[Actor, Depends(owner)],
    store: Annotated[OrgKeyStore, Depends(get_org_key_store)],
    vault: Annotated[ModelKeyVault, Depends(get_model_key_vault)],
) -> dict[str, Any]:
    """Destroy every version, then the reference: the org returns to Tilo's own key (BK-17 step 2). Idempotent."""
    held = store.get(who.org)
    try:
        vault.remove(who.org, SLOT, None)
    except Exception:  # noqa: BLE001 - nothing is claimed removed that is not
        raise HTTPException(status_code=503, detail="unavailable") from None
    try:
        store.delete(who.org)
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=503, detail="unavailable") from None
    _audit(store, who, "remove", held, widening=False, cfg=0)
    return {"removed": True}
