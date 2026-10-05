"""P0-07a: every workspace package a service's code imports is in that service's declared dependency closure.

Each image runs `uv sync --package tilo-<svc>`, which installs only the dependencies the service declares (and
theirs). The local dev venv syncs the whole workspace, so a missing declaration passes every local test and only
fails when the container starts (tilo-render imported tilo_contracts without declaring it, 6 Oct). Static only.
"""

from __future__ import annotations

import ast
import pathlib
import re
import tomllib

import pytest

SERVICES = ["api", "harness", "channels", "connectors", "browser", "render"]
REQ_NAME = re.compile(r"^\s*([A-Za-z0-9_.-]+)")


def _workspace(repo_root: pathlib.Path) -> dict[str, list[str]]:
    """Workspace package name -> the workspace package names it declares as dependencies."""
    root = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))
    members = root["tool"]["uv"]["workspace"]["members"]
    projects = {}
    for member in members:
        data = tomllib.loads((repo_root / member / "pyproject.toml").read_text(encoding="utf-8"))
        projects[data["project"]["name"]] = data["project"].get("dependencies", [])
    names = set(projects)
    return {
        name: [m.group(1) for dep in deps if (m := REQ_NAME.match(dep)) and m.group(1) in names]
        for name, deps in projects.items()
    }


def _closure(graph: dict[str, list[str]], start: str) -> set[str]:
    seen: set[str] = set()
    todo = [start]
    while todo:
        name = todo.pop()
        if name not in seen:
            seen.add(name)
            todo.extend(graph[name])
    return seen


def _tilo_imports(src: pathlib.Path) -> dict[str, str]:
    """Top-level tilo_* module -> first file that imports it (lazy imports count: they run in the image too)."""
    found: dict[str, str] = {}
    for path in sorted(src.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                mods = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                mods = [node.module]
            else:
                continue
            for mod in mods:
                top = mod.split(".")[0]
                if top.startswith("tilo_"):
                    found.setdefault(top, path.as_posix())
    return found


@pytest.mark.parametrize("svc", SERVICES)
def test_P0_07a_service_imports_are_declared_dependencies(repo_root: pathlib.Path, svc: str) -> None:
    graph = _workspace(repo_root)
    closure = {name.replace("-", "_") for name in _closure(graph, f"tilo-{svc}")}
    imports = _tilo_imports(repo_root / "services" / svc / "src")
    missing = {mod: where for mod, where in imports.items() if mod not in closure}
    assert not missing, (
        f"P0-07a: tilo-{svc} imports workspace packages its image will not install "
        f"(add them to services/{svc}/pyproject.toml dependencies and [tool.uv.sources]): {missing}"
    )
