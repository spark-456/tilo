"""X-RESULT-1: owner-only downloads of recorded, delivered run output (AR-01/03)."""

import logging
from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from tilo_memory.artifacts import ArtifactStore, Scope

from tilo_api import deps

router = APIRouter()
logger = logging.getLogger("tilo_api.results")


def result_store(request: Request, mode: Annotated[deps.Mode, Depends(deps.get_mode)]) -> Callable[[], ArtifactStore]:
    """Open storage only after ownership and recorded delivery have been checked. The app's own store seam applies
    (the dev run wires its in-memory store there), so a local run's output opens like a deployed one's."""

    def open_store() -> ArtifactStore:
        seam = request.app.dependency_overrides.get(deps.get_artifact_store)
        return seam() if seam is not None else deps.get_artifact_store(request, mode)

    return open_store


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
        logger.warning("result of %s: no such world for this person", world_id)
        raise HTTPException(status_code=404, detail="Tilo could not find that.")
    stream = store.events.get(world_id, [])
    delivered = [e for e in stream if e.get("type") == "artifact.delivered"]
    if not delivered or not any(e.get("type") == "world.completed" for e in stream):
        logger.warning("result of %s: nothing delivered and completed yet", world_id)
        raise HTTPException(status_code=404, detail="Tilo could not find that.")
    ref = delivered[-1].get("data", {}).get("artifact")
    if not any(
        e.get("type") in {"artifact.created", "artifact.versioned", "artifact.rollback"}
        and e.get("data", {}).get("artifact") == ref
        for e in stream
    ):
        logger.warning("result of %s: the delivered item was never recorded as created", world_id)
        raise HTTPException(status_code=404, detail="Tilo could not find that.")
    scope = Scope(deps.ORG_ID, world_id, world.owner)
    try:
        artifact_store = artifacts()  # a store that cannot open is "unavailable", never a bare 500
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
        logger.warning("the output of %s is not available to download", world_id, exc_info=True)
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
