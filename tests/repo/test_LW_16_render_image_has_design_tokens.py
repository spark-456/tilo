"""LW-16 (LW-11 piece): `render_pdf` reads `design/tokens.json` through `find_repo_root`, so every service image that
installs `tilo-render` (directly or through `tilo-harness`) must copy that one file in, and `.dockerignore` must let it
through. Static only: no docker daemon, no network."""

from __future__ import annotations

import pathlib
import re
import tomllib

COPY_LINE = "COPY design/tokens.json ./design/tokens.json"


def _workspace_deps(root: pathlib.Path) -> dict[str, set[str]]:
    deps: dict[str, set[str]] = {}
    for path in [*root.glob("services/*/pyproject.toml"), *root.glob("packages/*/pyproject.toml")]:
        project = tomllib.loads(path.read_text(encoding="utf-8"))["project"]
        deps[project["name"]] = {re.split(r"[<>=!~ \[;]", d, maxsplit=1)[0] for d in project.get("dependencies", [])}
    return deps


def _needs_render(root: pathlib.Path) -> list[str]:
    deps = _workspace_deps(root)

    def reaches(name: str, seen: frozenset[str] = frozenset()) -> bool:
        if name == "tilo-render":
            return True
        return any(reaches(dep, seen | {name}) for dep in deps.get(name, ()) if dep in deps and dep not in seen)

    return sorted(name for name in deps if name.startswith("tilo-") and name != "tilo-render" and reaches(name))


def test_LW_16_every_image_that_installs_tilo_render_copies_design_tokens(repo_root: pathlib.Path) -> None:
    packages = ["tilo-render", *_needs_render(repo_root)]
    images = [
        repo_root / "services" / name.removeprefix("tilo-") / "Dockerfile"
        for name in packages
        if (repo_root / "services" / name.removeprefix("tilo-") / "Dockerfile").is_file()
    ]
    assert {p.parent.name for p in images} >= {"render", "harness"}, "the render and harness images are the known two"
    for dockerfile in images:
        lines = [line.strip() for line in dockerfile.read_text(encoding="utf-8").splitlines()]
        assert COPY_LINE in lines, f"{dockerfile.parent.name}: render_pdf needs design/tokens.json in the image"
        assert lines.index(COPY_LINE) < next(i for i, line in enumerate(lines) if line.startswith("RUN uv sync")), (
            f"{dockerfile.parent.name}: copy the tokens file in the builder stage, before the install"
        )


def test_LW_16_dockerignore_lets_design_tokens_through_and_nothing_else_of_design(repo_root: pathlib.Path) -> None:
    lines = [line.strip() for line in (repo_root / ".dockerignore").read_text(encoding="utf-8").splitlines()]
    assert "design" in lines and "!design/tokens.json" in lines
    assert lines.index("!design/tokens.json") > lines.index("design"), "the exception must come after the exclusion"
    assert not any(line.startswith("!design/") and line != "!design/tokens.json" for line in lines)


def test_LW_16_cloudbuild_uploads_the_render_tokens_and_no_other_design_file(repo_root: pathlib.Path) -> None:
    from test_P0_07f_cloudbuild import _ignore_rules, _uploaded

    rules = _ignore_rules((repo_root / ".gcloudignore").read_text(encoding="utf-8").splitlines())
    assert _uploaded(rules, "design/tokens.json"), "Cloud Build must upload the render image COPY source"
    for excluded in ("design/source/x.js", "design/private.json", "design/sub/tokens.json", "design/.env"):
        assert not _uploaded(rules, excluded), f"{excluded}: only the root design tokens are needed"
