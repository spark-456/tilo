"""X-RESULT-1: owner-only downloads of recorded, delivered run output (AR-01/03).

RESULT-LIVE: a run may deliver several items. `GET /worlds/{id}/result` serves the main one: the item the delivering
agent made itself (a `deliver` unit's own document, or the item a send step sent), else the largest; the earliest
delivery breaks a tie. `?artifact=<id>` serves any other item the world delivered. Every item passes the same checks.
"""

import logging
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from tilo_memory.artifacts import ArtifactStore, Scope, StoredVersion
from tilo_providers.diagnostics import log_caught

from tilo_api import deps

router = APIRouter()
logger = logging.getLogger("tilo_api.results")

_RECORDS = {"artifact.created", "artifact.versioned", "artifact.rolled_back"}  # the events that record a version
_MAX_BYTES = 20 * 1024 * 1024


def result_store(request: Request, mode: Annotated[deps.Mode, Depends(deps.get_mode)]) -> Callable[[], ArtifactStore]:
    """Open storage only after ownership and recorded delivery have been checked. The app's own store seam applies
    (the dev run wires its in-memory store there), so a local run's output opens like a deployed one's."""

    def open_store() -> ArtifactStore:
        seam = request.app.dependency_overrides.get(deps.get_artifact_store)
        return seam() if seam is not None else deps.get_artifact_store(request, mode)

    return open_store


def _ref(event: dict[str, Any]) -> tuple[str, int] | None:
    artifact = event.get("data", {}).get("artifact")
    if not isinstance(artifact, dict):
        return None
    ident, version = artifact.get("artifact_id"), artifact.get("version")
    return (ident, version) if isinstance(ident, str) and type(version) is int else None


def _servable(version: StoredVersion, run_id: str | None) -> bool:
    return (
        version.record["run_id"] == run_id
        and version.record["origin"]["kind"] in {"unit", "render"}
        and version.record["screening"] == "clean"
        and version.record["size_bytes"] <= _MAX_BYTES
    )


@router.get("/worlds/{world_id}/result")
def get_result(
    world_id: str,
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    store: Annotated[deps.Store, Depends(deps.get_store)],
    artifacts: Annotated[Callable[[], ArtifactStore], Depends(result_store)],
    artifact: Annotated[str | None, Query(max_length=64)] = None,
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
    if not any(e.get("type") == "world.completed" for e in stream):
        logger.warning("result of %s: not completed yet", world_id)
        raise HTTPException(status_code=404, detail="Tilo could not find that.")
    makers: dict[tuple[str, int], Any] = {}  # each recorded version and the agent that recorded it
    for event in stream:
        if event.get("type") in _RECORDS and (ref := _ref(event)) is not None:
            makers.setdefault(ref, event.get("actor"))
    delivered: dict[tuple[str, int], bool] = {}  # recorded delivered refs, in delivery order -> made by its deliverer
    for event in stream:
        if event.get("type") == "artifact.delivered" and (ref := _ref(event)) is not None and ref in makers:
            delivered.setdefault(ref, makers[ref] == event.get("actor"))
    if artifact is not None:
        delivered = {ref: own for ref, own in delivered.items() if ref[0] == artifact}
    if not delivered:
        logger.warning("result of %s: no recorded, created and delivered item", world_id)
        raise HTTPException(status_code=404, detail="Tilo could not find that.")
    scope = Scope(deps.ORG_ID, world_id, world.owner)
    try:
        artifact_store = artifacts()  # a store that cannot open is "unavailable", never a bare 500
        heads = [(ref, own, artifact_store.head(scope, {"artifact_id": ref[0], "version": ref[1]})) for ref, own
                 in delivered.items()]  # fmt: skip
        found = [(not own, -v.record["size_bytes"], index, v) for index, (_, own, v) in enumerate(heads)
                 if v is not None and _servable(v, world.run_id)]  # fmt: skip
        if not found:
            raise ValueError("unavailable output")
        version = min(found, key=lambda f: f[:3])[3]
        content = artifact_store.read(scope, version.ref)  # AR-01: hash and size checked by the GCS-backed store.
    except Exception as caught_error:
        log_caught(caught_error, __name__, locals())
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
