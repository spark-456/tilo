"""Owner-only reads of masked frames recorded by a browser run."""

from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from tilo_memory.artifacts import ArtifactStore, Scope

from tilo_api import deps
from tilo_api.results import result_store

router = APIRouter()
_MISSING = HTTPException(status_code=404, detail="Tilo could not find that.")
# DEMO-BROWSER: Model Armor answers FAILURE for an image, so a frame is `clean` or, with no verdict, `unscreened`. The
# owner sees their own recorded, masked frame either way; it never leaves Tilo (AR-11; leaving is T3 when not clean,
# AR-07). A `flagged` frame is never served.
_SHOWN = frozenset({"clean", "unscreened"})


@router.get("/worlds/{world_id}/browser/frames/{artifact_id}")
def get_browser_frame(
    world_id: str,
    artifact_id: str,
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    store: Annotated[deps.Store, Depends(deps.get_store)],
    artifacts: Annotated[Callable[[], ArtifactStore], Depends(result_store)],
) -> Response:
    world = store.worlds.get(world_id)
    if (
        world is None
        or principal.role != "owner"
        or principal.user_id != world.owner
        or principal.channel not in ("web", "mobile_web")
        or principal.world_id not in (None, world_id)
    ):
        raise _MISSING
    refs = (
        event.get("data", {}).get("frame")
        for event in store.events.get(world_id, [])
        if event.get("type") in ("browser.started", "browser.acted")
    )
    if not any(
        isinstance(ref, dict) and ref.get("artifact_id") == artifact_id and ref.get("version") == 1 for ref in refs
    ):
        raise _MISSING
    scope = Scope(deps.ORG_ID, world_id, world.owner)
    ref = {"artifact_id": artifact_id, "version": 1}
    try:
        keeper = artifacts()
        saved = keeper.head(scope, ref)
        if saved is None:
            raise ValueError("frame missing")
        record = saved.record
        if (
            record["run_id"] != world.run_id
            or record["origin"]["kind"] != "browser"
            or record["media_type"] != "image/png"
            or record["screening"] not in _SHOWN
            or record["size_bytes"] > 4_000_000
        ):
            raise ValueError("frame record mismatch")
        content = keeper.read(scope, ref)
    except Exception:
        raise _MISSING from None
    return Response(
        content,
        media_type="image/png",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.post("/worlds/{world_id}/browser/{session}/stop")
def stop_browser(
    world_id: str,
    session: str,
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    store: Annotated[deps.Store, Depends(deps.get_store)],
) -> dict[str, bool]:
    world = store.worlds.get(world_id)
    if (
        world is None
        or principal.role != "owner"
        or principal.user_id != world.owner
        or principal.channel not in ("web", "mobile_web")
        or principal.world_id not in (None, world_id)
    ):
        raise _MISSING
    events = store.events.get(world_id, [])
    started = any(e.get("type") == "browser.started" and e.get("data", {}).get("session") == session for e in events)
    stopped = any(e.get("type") == "browser.stopped" and e.get("data", {}).get("session") == session for e in events)
    if not started or stopped:
        raise _MISSING
    store.browser_controls[session] = "stop"
    return {"requested": True}
