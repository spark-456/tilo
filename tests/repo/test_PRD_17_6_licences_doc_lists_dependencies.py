"""CLAUDE.md hard rule: "Record every dependency's licence in docs/licences.md."

docs/licences.md must list every direct dependency declared in any
pyproject.toml (project.dependencies + dependency-groups/optional-dependencies)
or package.json (dependencies + devDependencies) in the repo.
"""

from __future__ import annotations

import json
import pathlib
import re
import subprocess
import tomllib

import yaml  # noqa: F401  (pyyaml is an allowed test dependency; imported to confirm availability)


def _iter_project_files(repo_root: pathlib.Path, filename: str):
    # Only tracked manifests count: untracked worktrees under .claude/worktrees hold other tickets' work.
    tracked = subprocess.run(
        ["git", "ls-files", "--", f"*{filename}"], cwd=repo_root, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    for rel in tracked:
        if pathlib.PurePosixPath(rel).name == filename:
            yield repo_root / rel


def _python_dependency_names(pyproject_path: pathlib.Path) -> set[str]:
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    project = data.get("project", {})
    names: set[str] = set()

    def _add_all(specs):
        for spec in specs:
            match = re.match(r"^[A-Za-z0-9_.\-]+", spec)
            if match:
                names.add(match.group(0).lower())

    _add_all(project.get("dependencies", []))
    for group_deps in project.get("optional-dependencies", {}).values():
        _add_all(group_deps)
    dep_groups = data.get("dependency-groups", {})
    for group_deps in dep_groups.values():
        _add_all([d for d in group_deps if isinstance(d, str)])
    return names


def _js_dependency_names(package_json_path: pathlib.Path) -> set[str]:
    data = json.loads(package_json_path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for key in ("dependencies", "devDependencies"):
        names.update(data.get(key, {}).keys())
    return {n.lower() for n in names}


def test_PRD_17_6_licences_doc_exists(repo_root: pathlib.Path) -> None:
    licences_doc = repo_root / "docs" / "licences.md"
    assert licences_doc.is_file(), "docs/licences.md must exist"


def test_PRD_17_6_licences_doc_lists_every_direct_dependency(repo_root: pathlib.Path) -> None:
    licences_doc = repo_root / "docs" / "licences.md"
    assert licences_doc.is_file(), "docs/licences.md must exist"
    doc_text = licences_doc.read_text(encoding="utf-8").lower()

    all_deps: set[str] = set()
    for pyproject in _iter_project_files(repo_root, "pyproject.toml"):
        all_deps |= _python_dependency_names(pyproject)
    for package_json in _iter_project_files(repo_root, "package.json"):
        all_deps |= _js_dependency_names(package_json)

    assert all_deps, (
        "no pyproject.toml/package.json with dependencies found yet -- "
        "ticket P0-01 must add the uv and pnpm workspaces before this can pass"
    )

    missing = sorted(dep for dep in all_deps if dep not in doc_text)
    assert not missing, f"docs/licences.md is missing these direct dependencies: {missing}"


def test_PRD_17_6_licences_doc_lists_tooling(repo_root: pathlib.Path) -> None:
    licences_doc = repo_root / "docs" / "licences.md"
    assert licences_doc.is_file(), "docs/licences.md must exist"
    doc_text = licences_doc.read_text(encoding="utf-8").lower()

    for tool in ["uv", "just", "pnpm", "biome", "terraform"]:
        assert tool in doc_text, f"docs/licences.md must list the {tool} tool and its licence"
