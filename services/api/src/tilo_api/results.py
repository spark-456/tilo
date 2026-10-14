"""X-RESULT-1: owner-only downloads of recorded, delivered run output (AR-01/03)."""

from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from tilo_memory.artifacts import ArtifactStore, Scope

from tilo_api import deps

router = APIRouter()


def result_store(request: Request, mode: Annotated[deps.Mode, Depends(deps.get_mode)]) -> Callable[[], ArtifactStore]:
    """Open storage only after ownership and recorded delivery have been checked."""
    return lambda: deps.get_artifact_store(request, mode)


@router.get("/worlds/{world_id}/result")
def get_result(
    world_id: str,
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    store: Annotated[deps.Store, Depends(deps.get_store)],
    artifacts: Annotated[Callable[[], ArtifactStore], Depends(result_store)],
) -> Response:
    world = store.worlds.get(world_id)
    if (
        world is None
        or principal.role != "owner"
        or principal.user_id != world.owner
        or principal.channel not in {"web", "mobile_web"}
        or principal.world_id not in {None, world_id}
    ):
        raise HTTPException(status_code=404, detail="Tilo could not find that.")
    stream = store.events.get(world_id, [])
    delivered = [e for e in stream if e.get("type") == "artifact.delivered"]
    if not delivered or not any(e.get("type") == "world.completed" for e in stream):
        raise HTTPException(status_code=404, detail="Tilo could not find that.")
    ref = delivered[-1].get("data", {}).get("artifact")
    if not any(
        e.get("type") in {"artifact.created", "artifact.versioned", "artifact.rollback"}
        and e.get("data", {}).get("artifact") == ref
        for e in stream
    ):
        raise HTTPException(status_code=404, detail="Tilo could not find that.")
    scope = Scope(deps.ORG_ID, world_id, world.owner)
    artifact_store = artifacts()
    try:
        version = artifact_store.head(scope, ref)
        if (
            version is None
            or version.record["run_id"] != world.run_id
            or version.record["origin"]["kind"] not in {"unit", "render"}
            or version.record["screening"] != "clean"
            or version.record["size_bytes"] > 20 * 1024 * 1024
        ):
            raise ValueError("unavailable output")
        content = artifact_store.read(scope, ref)  # AR-01: hash and size checked by the GCS-backed store.
    except Exception:
        raise HTTPException(status_code=404, detail="Tilo could not find that.") from None
    media = version.record["media_type"]
    if media not in {"application/pdf", "application/json", "text/plain", "text/markdown"}:
        media = "application/octet-stream"
    return Response(
        content,
        media_type=media,
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": 'attachment; filename="tilo-result"',
        },
    )
