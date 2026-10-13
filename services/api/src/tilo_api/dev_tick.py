"""Dev-only schedule tick (DEV-HARNESS-1d): `POST /dev/schedules/tick` fires the due routines end to end with no Google
ID token. `tilo_api.dev.install` registers it and nothing else does, so a deployed or live process has no such route,
and dev mode's loopback-Host check covers it. It runs the code `POST /internal/schedules/tick` runs after its token
check (`schedules._fan_out`, then `schedules._run_task` for each task it hands over), with an in-process Tasks client in
place of Cloud Tasks; the real route, its OIDC verifier and the L3 `grant_budget` policy a scheduled run needs are
untouched. The optional `as_of` instant stands in for "now", because a weekly slot is days away. No paid call."""

from __future__ import annotations

import base64
import json
import logging
import os
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import AwareDatetime, BaseModel, ConfigDict, field_validator
from starlette.requests import Request
from starlette.responses import Response
from tilo_harness.schedule_store import InMemoryScheduleStore

from tilo_api import schedules
from tilo_api.dev import refuse_if_unsafe

logger = logging.getLogger("tilo_api.dev_tick")
router = APIRouter()
_AUDIENCE, _CALLER = "http://localhost:8080", "dev-tick"  # placeholders for the task a Cloud Tasks queue would sign
_QUEUE = "projects/demo-tilo/locations/local/queues/dev"


class _InProcessTasks:
    """The `TasksClient` of the dev tick: keeps the tasks the fan-out hands over, to deliver them in this request."""

    def __init__(self) -> None:
        self.tasks: list[Mapping[str, Any]] = []

    def enqueue(self, task: Mapping[str, Any]) -> None:
        self.tasks.append(task)


class TickIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    as_of: AwareDatetime | None = None

    @field_validator("as_of", mode="before")
    @classmethod
    def _text_only(cls, value: Any) -> Any:
        if value is not None and not isinstance(value, str):
            raise ValueError("as_of is an ISO 8601 instant with a time zone")  # not an epoch number
        return value


def _plain(result: Any) -> Any:
    return (
        {"status": result.status_code, "detail": json.loads(bytes(result.body))}
        if isinstance(result, Response)
        else result
    )


def _json_only(request: Request) -> None:
    """A browser page on another site can send `text/plain` with no preflight; only JSON needs one (415 otherwise)."""
    if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
        raise HTTPException(status_code=415, detail="Send application/json.")


def _refuse_real_store() -> None:
    """The dev tick claims slots and moves `next_due`, so it may only ever touch a schedule store in this process
    (or an emulator project named `demo-...`): a real Firestore project named in the environment is refused, whatever
    store the app is wired with."""
    env = os.environ
    if env.get("TILO_SCHEDULES_STORE") == "firestore" and not env.get("TILO_FIRESTORE_PROJECT", "").startswith("demo-"):
        raise HTTPException(status_code=503, detail="dev_tick_needs_memory_store")


@router.post("/dev/schedules/tick", dependencies=[Depends(_json_only)])
def dev_tick(
    request: Request,
    schedule_store: Annotated[Any, Depends(schedules.get_schedule_store_factory)],
    seams_factory: Annotated[Any, Depends(schedules.get_seams_factory)],
    flags: schedules.Flags,
    store_factory: Annotated[Callable[[], Any], Depends(schedules.get_store_factory)],
    clock: schedules.Clock,
    body: TickIn = TickIn(),
) -> Any:
    refuse_if_unsafe()
    _refuse_real_store()
    repo = schedule_store()
    if not isinstance(repo, InMemoryScheduleStore):  # nothing else is claimed from, even if the wiring changes
        raise HTTPException(status_code=503, detail="dev_tick_needs_memory_store")
    as_of = body.as_of.astimezone(UTC) if body.as_of else None
    now: Callable[[], datetime] = clock if as_of is None else (lambda at=as_of: at)  # type: ignore[misc]
    tasks = _InProcessTasks()
    fanned = schedules._fan_out(
        lambda: repo, lambda: tasks, now, flags, audience=_AUDIENCE, caller=_CALLER, queue=_QUEUE
    )
    if isinstance(fanned, JSONResponse):
        return fanned
    # the app rides in the scope: `_run_task` reads `request.app.dependency_overrides` for the stores it wires
    delivery = Request({"type": "http", "headers": [(b"content-type", b"application/json")], "app": request.app})
    ran: list[Any] = []
    for task in tasks.tasks:  # one task failing never loses the slots after it
        try:
            raw = base64.b64decode(task["httpRequest"]["body"])
            ran.append(
                _plain(schedules._run_task(delivery, raw, lambda: repo, seams_factory, now, flags, store_factory))
            )
        except Exception as exc:
            logger.warning("dev tick task failed (%s)", type(exc).__name__)
            ran.append({"ran": 0, "error": "task_failed"})
    return {"fired": fanned["fired"], "tasks": ran, "as_of": as_of.isoformat() if as_of else None}
