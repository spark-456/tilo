"""Owner-only, recorded and independently tested quiz AppSpecs (AS-02..04)."""

from __future__ import annotations

import json
from typing import Annotated, Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from tilo_harness.quiz import validate_sources, validate_spec
from tilo_memory.artifacts import ArtifactStore, Scope
from tilo_providers.media import MAX_PART_BYTES, MediaPart

from tilo_api import deps, events

router = APIRouter()


def source_loader(artifacts: ArtifactStore, scope: Scope, stream: list[dict[str, Any]]):
    recorded = {
        (e.get("data", {}).get("artifact", {}).get("artifact_id"), e.get("data", {}).get("artifact", {}).get("version"))
        for e in stream
        if e.get("type") in {"artifact.created", "artifact.versioned", "artifact.rollback"}
    }

    cached: dict[tuple[str, int], MediaPart] = {}

    def load(ref):
        key = (ref["artifact_id"], ref["version"])
        if key in cached:
            return cached[key]
        if (ref["artifact_id"], ref["version"]) not in recorded:
            return None
        version = artifacts.head(scope, ref)
        if version is None or version.record["origin"]["kind"] not in {"fetch", "upload"}:
            return None
        if version.record["screening"] != "clean" or version.record["size_bytes"] > MAX_PART_BYTES:
            return None
        cached[key] = MediaPart(mime_type=version.record["media_type"], data=artifacts.read(scope, ref))
        return cached[key]

    return load


@router.get("/worlds/{world_id}/apps/{artifact_id}")
def get_quiz(
    world_id: str,
    artifact_id: str,
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    store: Annotated[deps.Store, Depends(deps.get_store)],
    artifacts: Annotated[ArtifactStore, Depends(deps.get_artifact_store)],
    writer: Annotated[deps.EventWriter, Depends(deps.get_event_writer)],
) -> JSONResponse:
    world = store.worlds.get(world_id)
    if (
        world is None
        or principal.role != "owner"
        or principal.user_id != world.owner
        or principal.channel not in {"web", "mobile_web"}
        or (principal.world_id not in {None, world_id})
    ):
        raise HTTPException(status_code=404, detail="Tilo could not find that.")
    stream = store.events.get(world_id, [])
    specs = [
        e
        for e in stream
        if e.get("type") == "app.spec" and e.get("data", {}).get("spec", {}).get("artifact_id") == artifact_id
    ]
    if not specs:
        raise HTTPException(status_code=404, detail="Tilo could not find that.")
    made = specs[-1]
    ref = made["data"]["spec"]
    scope = Scope(deps.ORG_ID, world_id, world.owner)
    try:
        if not any(
            e.get("data", {}).get("artifact") == ref
            and e.get("type") in {"artifact.created", "artifact.versioned", "artifact.rollback"}
            for e in stream
        ):
            raise ValueError("unrecorded spec")
        version = artifacts.head(scope, ref)
        if version is None or version.record["origin"]["kind"] != "unit":
            raise ValueError("not a unit spec")
        producer = version.record["origin"]["agent"]
        verifier_ids = {
            a["id"] for a in (world.layout or {}).get("semantic", {}).get("agents", []) if a.get("rank") == "verifier"
        }
        tests = [
            e
            for e in stream
            if e.get("type") == "app.tested"
            and e.get("data", {}).get("spec") == ref
            and e.get("seq", 0) > made.get("seq", 0)
        ]
        if (
            not tests
            or tests[-1]["data"].get("passed") is not True
            or tests[-1].get("actor") == producer
            or tests[-1].get("actor") not in verifier_ids
        ):
            raise ValueError("not independently tested")
        if version.record["media_type"] != "application/json":
            raise ValueError("not JSON")
        spec = validate_spec(json.loads(artifacts.read(scope, ref)))
        validate_sources(spec, source_loader(artifacts, scope, stream))
        publishers = {}
        for question in spec["questions"]:
            source = question["source"]["artifact"]
            for text in artifacts.source_texts(scope, source).values():
                try:
                    payload = json.loads(text)
                    url = payload.get("source", {}).get("ref", "")
                    parsed = urlsplit(url)
                    if parsed.scheme in {"https", "http"} and parsed.hostname and not parsed.username:
                        publishers[source["artifact_id"]] = parsed.hostname
                except (ValueError, AttributeError, TypeError):
                    continue
    except Exception:
        raise HTTPException(status_code=404, detail="Tilo could not find that.") from None
    part = {
        "id": events.stable_part_id(world_id, artifact_id, str(ref["version"]), "app.deployed"),
        "type": "app.deployed",
        "actor": principal.user_id,
        "target": artifact_id,
        "summary": "The owner opened the quiz.",
        "vis": "all",
        "cause": tests[-1]["id"],
        "data": {"spec": ref},
    }
    try:
        writer.append(world_id, part)
    except Exception as exc:
        raise deps.event_failure(world_id, exc) from None
    return JSONResponse(
        {"spec": spec, "publishers": publishers, "artifact": ref}, headers={"Cache-Control": "no-store"}
    )
