"""Dev-only schedule tick (DEV-HARNESS-1d): `POST /dev/schedules/tick` fires the due routines end to end with no Google
ID token. `tilo_api.dev.install` registers it and nothing else does, so a deployed or live process has no such route,
and dev mode's loopback-Host check covers it. It runs the code `POST /internal/schedules/tick` runs after its token
check (`schedules._fan_out`, then `schedules._run_task` for each task it hands over), with an in-process Tasks client in
place of Cloud Tasks; the real route, its OIDC verifier and the L3 `grant_budget` policy a scheduled run needs are
untouched. The optional `as_of` instant stands in for "now", because a weekly slot is days away. No paid call."""

from __future__ import annotations

import base64
import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import AwareDatetime, BaseModel, ConfigDict, field_validator
from starlette.requests import Request
from starlette.responses import Response

from tilo_api import schedules
from tilo_api.dev import refuse_if_unsafe

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


@router.post("/dev/schedules/tick")
def dev_tick(
    schedule_store: Annotated[Any, Depends(schedules.get_schedule_store_factory)],
    seams_factory: Annotated[Any, Depends(schedules.get_seams_factory)],
    flags: schedules.Flags,
    store: schedules.StoreDep,
    clock: schedules.Clock,
    body: TickIn = TickIn(),
) -> Any:
    refuse_if_unsafe()
    as_of = body.as_of.astimezone(UTC) if body.as_of else None
    now: Callable[[], datetime] = clock if as_of is None else (lambda at=as_of: at)  # type: ignore[misc]
    tasks = _InProcessTasks()
    fanned = schedules._fan_out(
        schedule_store, lambda: tasks, now, flags, audience=_AUDIENCE, caller=_CALLER, queue=_QUEUE
    )
    if isinstance(fanned, JSONResponse):
        return fanned
    delivery = Request({"type": "http", "headers": [(b"content-type", b"application/json")]})
    raws = (base64.b64decode(t["httpRequest"]["body"]) for t in tasks.tasks)
    ran = [_plain(schedules._run_task(delivery, raw, schedule_store, seams_factory, now, flags, store)) for raw in raws]
    return {"fired": fanned["fired"], "tasks": ran, "as_of": as_of.isoformat() if as_of else None}
