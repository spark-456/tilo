"""Every web HTTP call must match a registered FastAPI path and method, offline."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from fastapi.routing import APIRoute
from tilo_api import app

# Only another service may be exempted, with its service name. Currently all web
# calls use tilo-api (connector calls are proxied by it); no exemptions are needed.
OTHER_SERVICES: dict[tuple[str, str], str] = {}


def matches(web_path: str, api_path: str) -> bool:
    """Parameter names differ between TS expressions and FastAPI declarations."""
    pattern = re.sub(r"\{[^}]+\}", "{param}", api_path)
    return re.sub(r"\{[^}]+\}", "{param}", web_path) == pattern


def test_ROUTE_AUDIT_1_every_web_call_is_registered(repo_root: Path) -> None:
    result = subprocess.run(
        ["node", str(repo_root / "tests/repo/web_routes.cjs")],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
        timeout=90,
    )
    collected = json.loads(result.stdout)
    assert not collected["errors"], "Unresolved web HTTP calls:\n" + "\n".join(collected["errors"])
    routes = []
    for route in app.routes:
        if isinstance(route, APIRoute):
            routes.append(route)
        elif hasattr(route, "effective_route_contexts"):
            # FastAPI's lazy included routers expose fully prefixed contexts.
            routes.extend(route.effective_route_contexts())
    assert routes, "No registered FastAPI routes were collected"
    assert collected["routes"], "The web route collector must not silently collect nothing"
    assert all(OTHER_SERVICES.values()), "Every external route must name its service"
    missing = [
        f"{call['file']}:{call['line']}: {call['method']} {call['path']}"
        for call in collected["routes"]
        if (call["method"], call["path"]) not in OTHER_SERVICES
        and not any(
            call["method"] in (route.methods or set()) and matches(call["path"], route.path) for route in routes
        )
    ]
    assert not missing, "Web calls absent from tilo-api:\n" + "\n".join(sorted(set(missing)))


def test_ROUTE_AUDIT_1_matching_keeps_literal_segments_and_methods() -> None:
    assert matches("/worlds/{param}/cards/{param}/fields", "/worlds/{world_id}/cards/{card_id}/fields")
    assert not matches("/worlds/{param}/missing", "/worlds/{world_id}/layout")
    assert not matches("/v1/{param}", "/v1/people")


def test_ROUTE_AUDIT_1_collector_catches_new_calls_and_preserves_pairs(repo_root: Path, tmp_path: Path) -> None:
    probe = tmp_path / "probe.ts"
    probe.write_text(
        """
        const BASE = "/new-route";
        const pathOf = (id: string, leaf: string) => `${BASE}/${encodeURIComponent(id)}/${leaf}`;
        http.getJson(pathOf(id, "read") + "?limit=10");
        http.postJson(pathOf(id, "write"), {});
        http.sendJson(on ? "PUT" : "DELETE", pathOf(id, "share"));
        function requestOf(op: string) {
          switch (op) {
            case "remove": return {method: "DELETE", path: "/remove"};
            default: return {method: "POST", path: "/create"};
          }
        }
        const {method, path} = requestOf(op);
        http.sendJson(method, path);
        function list(kind: "meetings" | "pinboards") { http.getJson(`/v1/${kind}`); }
        class Client {
          update(id: string) {
            const init = {method: "PATCH"};
            this.request(`/schedules/${id}`, init);
          }
        }
        http.getJson(unresolvableUrl);
        """,
        encoding="utf-8",
    )
    result = subprocess.run(
        ["node", str(repo_root / "tests/repo/web_routes.cjs"), str(probe)],
        check=True,
        capture_output=True,
        text=True,
        timeout=90,
    )
    collected = json.loads(result.stdout)
    assert {(r["method"], r["path"].split("?")[0]) for r in collected["routes"]} == {
        ("GET", "/new-route/{param}/read"),
        ("POST", "/new-route/{param}/write"),
        ("PUT", "/new-route/{param}/share"),
        ("DELETE", "/new-route/{param}/share"),
        ("DELETE", "/remove"),
        ("POST", "/create"),
        ("GET", "/v1/meetings"),
        ("GET", "/v1/pinboards"),
        ("PATCH", "/schedules/{param}"),
    }
    assert len(collected["errors"]) == 1
    assert "unresolvableUrl" in collected["errors"][0]
