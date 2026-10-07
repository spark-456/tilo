"""NFR-26: bind the ids a request's log lines carry (`tilo_logging`). Two pure-ASGI middlewares.

`LogContext` is outermost, in front of the SEC-15 access gate, so it does no I/O at all: it binds `world_id` (the
`/worlds/{world_id}` path segment, only if it has the contract's shape, since a path is the caller's input) and the
trace id of the `X-Cloud-Trace-Context` header. The trace id comes from a header the caller can set: it is a
correlation hint for finding log lines, never an audit key.

`LogRunId` sits inside the gate, so it only runs for a request the gate admitted (API_SEC_15.md: no world lookup
before the gate). It binds `run_id`, the stored world's (`deps.Store`, never invented; absent for an unknown world),
looked up off the event loop. A store that fails costs the run id, never the request."""

from __future__ import annotations

import re

from starlette.concurrency import run_in_threadpool
from starlette.types import ASGIApp, Receive, Scope, Send
from tilo_logging.context import bound, current, trace_from_header

_WORLD_PATH = re.compile(r"^/worlds/(w_[0-9A-Za-z_]{1,48})(?:/|\Z)")  # common.schema.json#/$defs/world_id


def _run_id(scope: Scope, world_id: str) -> str | None:
    from tilo_api import deps  # noqa: PLC0415  (this module is imported by the package __init__)

    try:
        store = scope["app"].dependency_overrides.get(deps.get_store, deps.get_store)()
        return store.worlds[world_id].run_id if world_id in store.worlds else None
    except Exception:  # no store wired (503 not_configured) or a broken one: log without a run id
        return None


class LogContext:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        match = _WORLD_PATH.match(scope["path"])
        header = next((v for k, v in scope["headers"] if k == b"x-cloud-trace-context"), b"")
        with bound(world_id=match.group(1) if match else None, trace=trace_from_header(header.decode("latin-1"))):
            await self.app(scope, receive, send)


class LogRunId:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        world_id = current().get("world_id") if scope["type"] == "http" else None
        if world_id is None:
            await self.app(scope, receive, send)
            return
        with bound(run_id=await run_in_threadpool(_run_id, scope, world_id)):
            await self.app(scope, receive, send)
