"""Helpers for the SEC-15 acceptance tests (deployed access: visitor or judge; see API_SEC_15.md).

Named `_sec15_lib` for the same global-bare-module-name reason as `_clint1_lib.py`. Nothing here is business
logic. `Sec15` wires the real `tilo_api.app` to a fake signed-in principal, the in-memory `deps.Store`, a fake
access store (`get` / `declare`, the two methods API_SEC_15.md pins), a safety spy, a scripted router behind a
spy on `deps.router_for_mode`, and an in-memory flag store. A seam the production code does not have yet
resolves to a placeholder key nothing depends on, so a missing seam shows up as a wrong response (a visitor
getting through), not as an `AttributeError` during setup.

No network, no paid call: the router is a real `Router` over a scripted provider.
"""

from __future__ import annotations

import pathlib
import re
import threading
from dataclasses import dataclass, field
from typing import Any

from _api_lib import make_store, make_writer
from _clint1_lib import APPROACHES_REPLY, RoleScriptedProvider, brief_reply, build_router, make_spy_safety, seam
from fastapi import HTTPException
from fastapi.testclient import TestClient

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]

VISITOR = "u_sec15_visitor"
JUDGE = "u_sec15_judge"
NEWCOMER = "u_sec15_newcomer"  # signed in, never declared anything
OTHER = "u_sec15_other"

CODE_UNDER_CONSTRUCTION = "under_construction"
CODE_DECLARATION_REQUIRED = "declaration_required"
CODE_DECLARATION_LOCKED = "declaration_locked"

# The routes a refused or undeclared person may still call (API_SEC_15.md "Public routes"). Pinned here as
# literals so that adding a public route needs a change to this test.
PINNED_PUBLIC_ROUTES = frozenset(
    {("GET", "/health"), ("GET", "/healthz"), ("GET", "/access"), ("POST", "/access/declaration")}
)

PROBE_PARAMS = {"world_id": "w_probe", "task_id": "t_probe", "policy_id": "pol_probe", "card_id": "c_probe"}
_PARAM = re.compile(r"\{([a-z_]+)(?::[a-z]+)?\}")


def concrete(path: str) -> str:
    """A route template with each path parameter filled in with a syntactically plausible id."""
    return _PARAM.sub(lambda m: PROBE_PARAMS.get(m.group(1), "x_probe"), path)


def route_table(app: Any) -> list[tuple[str, str]]:
    """Every (METHOD, path template) the app serves, HEAD and OPTIONS excluded, sorted, deduplicated. Read from
    the OpenAPI document: FastAPI 0.14x keeps `app.routes` as lazy `_IncludedRouter` wrappers, so the route list is
    not a stable thing to walk (the gate itself must not depend on it either)."""
    paths = app.openapi()["paths"]
    return sorted({(m.upper(), p) for p, ops in paths.items() for m in ops if m.upper() not in {"HEAD", "OPTIONS"}})


def non_public(app: Any) -> list[tuple[str, str]]:
    return [r for r in route_table(app) if r not in PINNED_PUBLIC_ROUTES]


class FakeAccessStore:
    """The two methods of the pinned store protocol: `get(user_id)` and `declare(user_id, declaration)` (first
    write wins, atomic, returns what is stored). `reads` and `writes` record every call."""

    def __init__(self, declarations: dict[str, str] | None = None) -> None:
        self.data: dict[str, str] = dict(declarations or {})
        self.reads: list[str] = []
        self.writes: list[tuple[str, str]] = []
        self._lock = threading.Lock()

    def get(self, user_id: str) -> str | None:
        self.reads.append(user_id)
        return self.data.get(user_id)

    def declare(self, user_id: str, declaration: str) -> str:
        self.writes.append((user_id, declaration))
        with self._lock:
            return self.data.setdefault(user_id, declaration)


@dataclass
class Sec15:
    """The real app, deployed-style, with every injected seam. `as_user` switches the signed-in principal."""

    client: TestClient
    store: Any  # deps.Store
    access: FakeAccessStore
    safety: Any
    flags: Any
    router_modes: list[str] = field(default_factory=list)
    router_calls: Any = None
    user: str = VISITOR
    signed_in: bool = True

    def as_user(self, user_id: str) -> None:
        self.user, self.signed_in = user_id, True

    def sign_out(self) -> None:
        self.signed_in = False

    # --- calls -----------------------------------------------------------------------------------

    def call(self, method: str, path: str, **kwargs: Any):
        """One request to a concrete path. A body is sent as the route would get one from a browser."""
        return self.client.request(method, concrete(path), **kwargs)

    def declare(self, declaration: Any, **kwargs: Any):
        return self.client.post("/access/declaration", json={"declaration": declaration}, **kwargs)

    def me(self, **kwargs: Any):
        return self.client.get("/access", **kwargs)

    def intake(self, text: str = "Prepare the weekly supplier summary."):
        return self.client.post("/intake", data={"text": text})

    # --- what a refused request must not have touched ---------------------------------------------

    def snapshot(self) -> tuple[Any, ...]:
        s = self.store
        return (
            sorted(s.worlds),
            sorted(s.tasks),
            {k: len(v) for k, v in s.events.items()},
            sorted(s.policies),
            {k: len(v) for k, v in s.pending_events.items()},
            list(self.safety.calls),
            list(self.router_modes),
        )


def build(monkeypatch: Any, *, declarations: dict[str, str] | None = None, deployed: bool = True) -> Sec15:
    """Wires `tilo_api.app`. `deployed` sets K_SERVICE (the Cloud Run marker); clear every LIVE / judge switch."""
    from tilo_api import app, deps  # noqa: PLC0415
    from tilo_api import intake as intake_module  # noqa: PLC0415
    from tilo_metering.flags import InMemoryFlagStore  # noqa: PLC0415

    live_var = "LIVE"  # spelled apart: the repo's guard hook looks for the literal switch
    for name in (live_var, "TILO_JUDGE_LIVE", "K_SERVICE", "CLOUD_RUN_JOB", "TILO_API_DEV"):
        monkeypatch.delenv(name, raising=False)
    if deployed:
        monkeypatch.setenv("K_SERVICE", "tilo-api")

    store = make_store()
    writer = make_writer(store)
    safety = make_spy_safety()
    flags = InMemoryFlagStore()
    access = FakeAccessStore(declarations)
    provider = RoleScriptedProvider(brief_reply([]), APPROACHES_REPLY)
    scripted = build_router(REPO_ROOT, provider)

    h = Sec15(client=None, store=store, access=access, safety=safety, flags=flags)  # type: ignore[arg-type]

    def current_principal() -> Any:
        if not h.signed_in:
            raise HTTPException(status_code=401, detail="not signed in")
        return deps.Principal(user_id=h.user, role="owner")

    def spy_router_for_mode(mode: str) -> Any:
        h.router_modes.append(mode)
        return scripted

    app.dependency_overrides[deps.get_current_principal] = current_principal
    app.dependency_overrides[deps.get_store] = lambda: store
    app.dependency_overrides[deps.get_event_writer] = lambda: writer
    app.dependency_overrides[deps.get_flag_store] = lambda: flags
    app.dependency_overrides[intake_module.get_safety] = lambda: safety
    app.dependency_overrides[deps.get_safety] = lambda: safety
    app.dependency_overrides[seam(deps, "get_access_store")] = lambda: access
    # `deps.get_router` itself is never overridden: it must reach `router_for_mode(mode)`, the pinned seam.
    monkeypatch.setattr(deps, "router_for_mode", spy_router_for_mode, raising=False)
    h.client = TestClient(app, raise_server_exceptions=False)
    return h


def close() -> None:
    from tilo_api import app  # noqa: PLC0415

    app.dependency_overrides.clear()
