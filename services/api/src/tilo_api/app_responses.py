from __future__ import annotations

import csv
import hashlib
import io
import re
import time
import unicodedata
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, StrictStr, ValidationError
from starlette.concurrency import run_in_threadpool
from tilo_memory.artifacts import ArtifactStore, Scope
from tilo_people.stores import PeopleStores

from tilo_api import deps
from tilo_api.app_response_store import get_app_store

MAX_PUBLIC_BODY = 16 * 1024
MAX_SIGNED_BODY = 32 * 1024
router = APIRouter()
Principal = Annotated[deps.Principal, Depends(deps.get_current_principal)]
State = Annotated[deps.Store, Depends(deps.get_store)]
Artifacts = Annotated[ArtifactStore, Depends(deps.get_artifact_store)]
People = Annotated[PeopleStores, Depends(deps.get_people_stores)]
Clock = Annotated[Any, Depends(deps.get_clock)]


class Capture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fields: dict[StrictStr, Any]
    website: StrictStr = ""


class Publish(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: StrictStr | None = None


Apps = Annotated[Any, Depends(get_app_store)]


def _slug(value: str, fallback: str) -> str:
    made = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:64]
    safe_fallback = re.sub(r"[^a-z0-9]+", "-", fallback.lower()).strip("-")[:64]
    return made or safe_fallback or "app-" + hashlib.sha256(fallback.encode()).hexdigest()[:12]


def _owned(
    artifact_id: str, principal: deps.Principal, store: deps.Store, artifacts: ArtifactStore, access: str = "editor"
) -> tuple[dict[str, Any], Scope, dict[str, Any]]:
    for world_id, world in store.worlds.items():
        owner = principal.user_id == world.owner
        member = owner or principal.world_id == world_id
        editor = owner or (principal.world_id == world_id and principal.role in {"team_lead", "approver"})
        if not {"owner": owner, "editor": editor, "viewer": member}[access]:
            continue
        refs = [
            e.get("data", {}).get("artifact", {})
            for e in store.events.get(world_id, [])
            if e.get("data", {}).get("artifact", {}).get("artifact_id") == artifact_id
        ]
        if not refs:
            continue
        ref = max(refs, key=lambda value: value.get("version", 0))
        scope = Scope(deps.ORG_ID, world_id, world.owner)
        head = artifacts.head(scope, ref)
        if head is not None and head.record["media_type"] == "text/html":
            return ref, scope, {"world_id": world_id, "owner": world.owner}
    raise HTTPException(404, "not_found")


async def _body(request: Request, cap: int) -> Capture:
    if request.headers.get("content-type", "").split(";")[0].lower() != "application/json":
        raise HTTPException(415, "Send application/json.")
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > cap:
            raise HTTPException(413, "body_too_large")
    try:
        return Capture.model_validate_json(raw)
    except ValidationError:
        raise HTTPException(422, "invalid_response") from None


def _clean(value: Any) -> Any:
    if isinstance(value, str):
        return "".join(c for c in value if unicodedata.category(c) not in {"Cc", "Cf"}).strip()[:5000]
    if isinstance(value, bool | int | float) or value is None:
        return value
    if isinstance(value, list):
        return [_clean(item) for item in value[:100]]
    raise HTTPException(422, "invalid_response")


def _row(body: Capture, clock: Any) -> dict[str, Any]:
    fields = {}
    for key, value in list(body.fields.items())[:100]:
        cleaned = _clean(key)[:100]
        if cleaned:
            fields[cleaned] = _clean(value)
    return {
        "id": "resp_" + uuid.uuid4().hex,
        "submitted_by": None,
        "at": clock(),
        "epoch": time.time(),
        "fields": fields,
    }


@router.post("/v1/artifacts/{artifact_id}/publish")
def publish(
    artifact_id: str,
    body: Publish,
    principal: Principal,
    store: State,
    artifacts: Artifacts,
    people: People,
    apps: Apps,
) -> dict[str, Any]:
    ref, _, where = _owned(artifact_id, principal, store, artifacts, "owner")
    person = people.persons.get(deps.ORG_ID, where["owner"])
    generated = getattr(store.runs.get(where["world_id"]), "titles", {}).get(artifact_id, "Published app")
    title = _clean(body.title or generated)[:120]
    handle = _slug((person.record if person else {}).get("display_name", "user"), where["owner"])
    record = apps.publish(
        {
            **where,
            **ref,
            "title": title,
            "handle": handle,
            "slug": _slug(title, artifact_id),
            "published": True,
            "response_count": 0,
        }
    )
    return {"app": record | {"path": f"/u/{record['handle']}/{record['slug']}"}}


@router.delete("/v1/artifacts/{artifact_id}/publish")
def unpublish(artifact_id: str, principal: Principal, store: State, artifacts: Artifacts, apps: Apps) -> dict[str, Any]:
    _owned(artifact_id, principal, store, artifacts, "owner")
    record = apps.unpublish(artifact_id)
    if record is None:
        raise HTTPException(404, "not_found")
    return {"app": record | {"path": f"/u/{record['handle']}/{record['slug']}"}}


@router.get("/public/apps/{handle}/{slug}")
def public_app(handle: str, slug: str, apps: Apps, artifacts: Artifacts) -> dict[str, str]:
    record = apps.public(handle, slug)
    if record is None:
        raise HTTPException(404, "not_found")
    html = artifacts.read(Scope(deps.ORG_ID, record["world_id"], record["owner"]), record).decode("utf-8")
    return {"title": record["title"], "html": html}


async def _capture(
    artifact_id: str, request: Request, apps: Any, clock: Any, cap: int, submitted_by: str | None
) -> dict[str, Any]:
    body = await _body(request, cap)
    if body.website:
        return {"response_id": "accepted", "count": len(apps.responses(artifact_id))}
    row = _row(body, clock) | {"artifact_id": artifact_id, "submitted_by": submitted_by}
    identity = (
        f"user:{submitted_by}"
        if submitted_by is not None
        else f"ip:{request.client.host if request.client else 'unknown'}"
    )
    rate_key = hashlib.sha256(identity.encode()).hexdigest()[:24]
    count = await run_in_threadpool(apps.add, artifact_id, row, rate_key)
    return {"response_id": row["id"], "count": count}


@router.post("/public/apps/{handle}/{slug}/responses", status_code=201)
async def public_response(handle: str, slug: str, request: Request, apps: Apps, clock: Clock) -> dict[str, Any]:
    record = apps.public(handle, slug)
    if record is None:
        raise HTTPException(404, "not_found")
    return await _capture(record["artifact_id"], request, apps, clock, MAX_PUBLIC_BODY, None)


@router.post("/v1/artifacts/{artifact_id}/responses", status_code=201)
async def signed_response(
    artifact_id: str,
    request: Request,
    principal: Principal,
    store: State,
    artifacts: Artifacts,
    apps: Apps,
    clock: Clock,
) -> dict[str, Any]:
    _owned(artifact_id, principal, store, artifacts, "viewer")
    return await _capture(artifact_id, request, apps, clock, MAX_SIGNED_BODY, principal.user_id)


@router.get("/v1/artifacts/{artifact_id}/responses")
def list_responses(
    artifact_id: str, principal: Principal, store: State, artifacts: Artifacts, apps: Apps
) -> dict[str, Any]:
    _owned(artifact_id, principal, store, artifacts, "owner")
    rows = apps.responses(artifact_id)
    return {"responses": [{k: v for k, v in row.items() if k != "epoch"} for row in rows], "count": len(rows)}


def _csv_safe(value: Any) -> str:
    text = str(value if value is not None else "")
    return "'" + text if text.startswith(("=", "+", "-", "@", "\t", "\r")) else text


@router.get("/v1/artifacts/{artifact_id}/responses.csv")
def response_csv(artifact_id: str, principal: Principal, store: State, artifacts: Artifacts, apps: Apps) -> Response:
    _owned(artifact_id, principal, store, artifacts, "owner")
    rows = apps.responses(artifact_id)
    fields = list(dict.fromkeys(key for row in rows for key in row.get("fields", {})))
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["id", "submitted_by", "at", *(_csv_safe(key) for key in fields)])
    for row in rows:
        values = [_csv_safe(row.get("fields", {}).get(key)) for key in fields]
        writer.writerow([row.get("id"), row.get("submitted_by"), row.get("at"), *values])
    headers = {"Content-Disposition": f'attachment; filename="{artifact_id}-responses.csv"'}
    return PlainTextResponse(output.getvalue(), media_type="text/csv", headers=headers)


@router.delete("/v1/artifacts/{artifact_id}/responses/{response_id}", status_code=204)
def delete_response(
    artifact_id: str, response_id: str, principal: Principal, store: State, artifacts: Artifacts, apps: Apps
) -> None:
    _owned(artifact_id, principal, store, artifacts, "owner")
    if not apps.delete(artifact_id, response_id):
        raise HTTPException(404, "not_found")
