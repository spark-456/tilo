"""Local dev wiring for tilo-api (CL-INT-4, ADR-0003): one fixed dev owner, the in-memory `Store`, a stamping
event writer and CORS for the Vite dev origin, so `just dev-api` can serve the flow to the web client. Selected by
`TILO_API_DEV=1`; it refuses to start when deployed (`K_SERVICE` or `CLOUD_RUN_JOB` set, the rule the fake
safety provider uses) or in live mode (`LIVE=1`), and every dev dependency re-checks that on each call. It makes
no network or paid call, and it is a stand-in for sign-in and Firestore, never a second implementation of them.
`main` (`just dev-api`) also selects `config/models.dev.yaml`, whose Director is a deterministic fake (CL-INT-5);
`dev_run` adds a fake unit runner, recipient and mock adapters, so a run reaches a gate and a fake send (5c)."""

from __future__ import annotations

import os
import re
import threading
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send
from tilo_harness.validator import repo_validator
from tilo_people.stores import PeopleStores

from tilo_api import deps, dev_run, events

ENV_FLAG = "TILO_API_DEV"  # "1" turns dev mode on; nothing else does
ENV_ORIGINS = "TILO_API_DEV_ORIGINS"  # comma-separated allowed browser origins
DEFAULT_ORIGIN = "http://localhost:5173"  # the Vite dev server
DEV_OWNER = "u_dev_owner"  # the one dev principal (common.schema.json user_id)
PORT = 8080
ENV_MODELS = "TILO_MODELS_FILE"  # `main` points it at the dev models file unless the user already chose one
DEV_MODELS = Path(__file__).resolve().parents[4] / "config" / "models.dev.yaml"  # a fake Director, CL-INT-5

_ORIGIN_RE = re.compile(r"^https?://[A-Za-z0-9.-]+(:[0-9]{1,5})?$")
_HOST_RE = re.compile(rf"^(localhost|127\.0\.0\.1|\[::1\]):{PORT}$", re.IGNORECASE)  # the dev server's own address
_NULL_TRACE = dict.fromkeys(("model_role", "profile", "tokens_in", "tokens_out", "tool", "latency_ms", "archive_ref"))


class DevModeRefused(RuntimeError):
    """Dev mode was asked for where it must never run, or was configured unsafely."""


def dev_enabled(env: Mapping[str, str] | None = None) -> bool:
    return (os.environ if env is None else env).get(ENV_FLAG) == "1"


def refuse_if_unsafe(env: Mapping[str, str] | None = None) -> None:
    """Presence, not truthiness: Cloud Run can set a variable to an empty string."""
    env = os.environ if env is None else env
    if "K_SERVICE" in env or "CLOUD_RUN_JOB" in env:
        raise DevModeRefused(f"{ENV_FLAG}=1 is refused when deployed (K_SERVICE or CLOUD_RUN_JOB is set)")
    if env.get("LIVE") == "1":
        raise DevModeRefused(f"{ENV_FLAG}=1 is refused in live mode (LIVE=1); dev mode never makes a paid call")


class _LocalHostOnly:
    """Refuses any request whose Host is not the dev server's own loopback address and port, so a page that
    rebinds its DNS name to 127.0.0.1 cannot reach the dev server as its fixed owner. (Starlette's own
    TrustedHostMiddleware drops the port and mangles `[::1]`, so it cannot express this.)"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket"):
            host = next((v.decode("latin-1") for k, v in scope["headers"] if k == b"host"), "")
            if not _HOST_RE.match(host):
                if scope["type"] == "http":
                    await PlainTextResponse("Invalid host header", status_code=400)(scope, receive, send)
                else:
                    await send({"type": "websocket.close", "code": 1008})
                return
        await self.app(scope, receive, send)


def cors_origins(env: Mapping[str, str] | None = None) -> list[str]:
    """Explicit origins only: a wildcard, a path or a `null` origin is refused."""
    raw = (os.environ if env is None else env).get(ENV_ORIGINS) or DEFAULT_ORIGIN
    origins = [o.strip().rstrip("/") for o in raw.split(",") if o.strip()]
    bad = [o for o in origins if not _ORIGIN_RE.match(o)]
    if bad or not origins:
        raise DevModeRefused(f"{ENV_ORIGINS} must list explicit http(s) origins, not {bad or raw!r}")
    return origins


class DevEventWriter:
    """Stands in for the harness's single writer (PRD 15.3) over the in-memory store: stamps `v`, `seq` (strictly
    increasing after whatever the API itself wrote), `ts`, `world_id`, `run_id` and the null trace; validates the
    result against the contract before it is stored; idempotent by event `id`. It never defaults `vis`: an event
    without one is refused, so nothing built against dev mode can widen who sees it."""

    def __init__(self, store: deps.Store) -> None:
        self._store, self._lock = store, threading.Lock()

    def append(self, world_id: str, event: dict) -> dict:
        refuse_if_unsafe()
        world = self._store.worlds.get(world_id)
        if world is None:
            raise deps.EventRejected(f"unknown world {world_id!r}")
        if event.get("vis") is None:
            raise deps.EventRejected("an event must say who may see it (`vis`); dev mode does not default it")
        with self._lock:
            committed = self._store.events.setdefault(world_id, [])
            existing = next((e for e in committed if e.get("id") == event.get("id")), None)
            seq = existing["seq"] if existing else max((e["seq"] for e in committed), default=0) + 1
            ts = existing["ts"] if existing else event.get("ts") or events.now()
            stamped = {
                "v": "1.0", "seq": seq, "ts": ts, "world_id": world_id, "run_id": world.run_id,
                "level": None, "district": None, "item": None, "severity": "info", "credits": 0, "cause": None,
                "authz": None, "data": {}, "trace": dict(_NULL_TRACE), **event,
            }  # fmt: skip
            stamped.update(v="1.0", seq=seq, ts=ts, world_id=world_id, run_id=world.run_id)
            if existing is not None:
                if stamped == existing:
                    return existing
                raise deps.EventRejected(f"id {event.get('id')!r} already committed for {world_id!r} differently")
            if problems := repo_validator().problems(stamped):
                raise deps.EventRejected("; ".join(problems[:3]))
            committed.append(stamped)
            return stamped


class DevDeskWorlds:
    """One Desk world per person over the in-memory `Store`: `w_desk_<user id without "u_">`, owned by that person with
    no districts, made on first use (idempotent). A user id that cannot make a valid world id raises."""

    def __init__(self, store: deps.Store) -> None:
        self._store, self._lock = store, threading.Lock()

    def desk_world(self, org_id: str, user_id: str) -> str:
        refuse_if_unsafe()
        suffix = user_id[2:] if user_id.startswith("u_") else ""
        if re.fullmatch(r"[0-9A-Za-z_]{1,43}", suffix) is None:
            raise ValueError("no Desk world for this user id")
        world_id = f"w_desk_{suffix}"
        with self._lock:
            self._store.worlds.setdefault(world_id, deps.WorldRecord(owner=user_id, districts={}))
        return world_id


class _NoSources:
    """Dev plate sources and source owners: nothing to join and no owner to name (a stand-in, never a second store)."""

    def cards(self, user_id: str) -> tuple[()]:
        refuse_if_unsafe()
        return ()

    runs = mail = cards

    def owner_of(self, kind: str, ref: str) -> None:
        refuse_if_unsafe()


def _dev_people() -> dict[Callable[..., Any], Callable[[], Any]]:
    """One in-memory `PeopleStores` per install, holding the dev owner as an org owner of `deps.ORG_ID` (PPL-11a)."""
    stores, none = PeopleStores.in_memory(), _NoSources()
    stamp = {"by": DEV_OWNER, "at": "2026-09-29T09:30:00.000Z"}
    stores.persons.create(
        {
            "id": DEV_OWNER, "org_id": deps.ORG_ID, "display_name": "Dev Owner", "aliases": [],
            "email": "dev-owner@example.com", "time_zone": "Asia/Kolkata", "preferred_channel": "web",
            "org_role": "owner", "memberships": [], "created_by": stamp,
        }
    )  # fmt: skip

    def get_stores() -> PeopleStores:
        refuse_if_unsafe()
        return stores

    def get_none() -> _NoSources:
        refuse_if_unsafe()
        return none

    return {deps.get_people_stores: get_stores, deps.get_plate_sources: get_none, deps.get_source_owners: get_none}


def install(app: FastAPI, env: Mapping[str, str] | None = None) -> None:
    """Wires `app` for local dev; raises DevModeRefused before changing anything if that is unsafe."""
    refuse_if_unsafe(env)
    origins = cors_origins(env)
    store = deps.Store()
    store.policies["pol_dev_send"] = dev_run.dev_send_policy(DEV_OWNER)  # the dev run goes straight to its gate card
    writer = DevEventWriter(store)

    def principal(request: Request) -> deps.Principal:
        refuse_if_unsafe()
        # The one owner is a member of whichever of its own worlds the path names; an unknown world is
        # the same 404 as ever, because the route looks the world up in the store.
        return deps.Principal(user_id=DEV_OWNER, role="owner", world_id=request.path_params.get("world_id"))

    def get_store() -> deps.Store:
        refuse_if_unsafe()
        return store

    app.dependency_overrides[deps.get_current_principal] = principal
    app.dependency_overrides[deps.get_store] = get_store

    def get_writer() -> DevEventWriter:
        refuse_if_unsafe()
        return writer

    app.dependency_overrides[deps.get_event_writer] = get_writer
    desks = DevDeskWorlds(store)

    def get_desks() -> DevDeskWorlds:
        refuse_if_unsafe()
        return desks

    app.dependency_overrides[deps.get_desk_worlds] = get_desks  # the Desk worlds of the work-item events (PE-12)
    app.dependency_overrides.update(dev_run.overrides())  # fake unit runner, recipient and send (CL-INT-5c)
    app.dependency_overrides.update(_dev_people())  # in-memory people stores, the dev owner an org owner
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Idempotency-Key"],
        expose_headers=["Retry-After"],
    )  # no credentials: the dev principal reads no cookie or header
    app.add_middleware(_LocalHostOnly)  # added last, so it runs first


def install_if_enabled(app: FastAPI, env: Mapping[str, str] | None = None) -> bool:
    if not dev_enabled(env):
        return False
    install(app, env)
    return True


def main() -> None:
    """`just dev-api`: the reloader's child imports `tilo_api` afresh, so it sees the flag set here."""
    import uvicorn

    os.environ[ENV_FLAG] = "1"
    os.environ.setdefault(ENV_MODELS, str(DEV_MODELS))
    refuse_if_unsafe()
    cors_origins()
    uvicorn.run("tilo_api:app", host="127.0.0.1", port=PORT, reload=True)
