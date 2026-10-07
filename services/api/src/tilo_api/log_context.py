"""NFR-26: bind the ids a request's log lines carry (`tilo_logging`). Pure ASGI, so the binding is in force for the
whole request, the access gate's own log lines included.

`world_id` is the `/worlds/{world_id}` path segment, bound only if it has the contract's shape (a path is the
caller's input); `run_id` is the world's stored `run_id` (`deps.Store`, never invented), absent for an unknown world;
the trace is the `X-Cloud-Trace-Context` header's trace id. Nothing else of the request reaches a log line."""

from __future__ import annotations

import re

from starlette.types import ASGIApp, Receive, Scope, Send
from tilo_logging.context import bound, trace_from_header

_WORLD_PATH = re.compile(r"^/worlds/(w_[0-9A-Za-z_]{1,48})(?:/|$)")  # common.schema.json#/$defs/world_id


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
        world_id = match.group(1) if match else None
        header = next((v for k, v in scope["headers"] if k == b"x-cloud-trace-context"), b"")
        with bound(
            world_id=world_id,
            run_id=_run_id(scope, world_id) if world_id else None,
            trace=trace_from_header(header.decode("latin-1")),
        ):
            await self.app(scope, receive, send)
