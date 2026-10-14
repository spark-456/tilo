"""LIVE-AUDIT-B: the built-in skills must ship in the tilo-api image.

`deps.get_skill_registry` and `skill_proposals` read `<repo root>/skills`, which is `/app/skills` in the image.
`SkillRegistry` globs `*/*/skill.yaml`, so a missing directory is an empty catalogue with no error: the meeting-room
planner finds no skill and a proposal has nothing to diff. Static only: no docker daemon, no network.
"""

from __future__ import annotations

import fnmatch
import pathlib

COPY_LINE = "COPY skills ./skills"


def _ignored(rel: str, patterns: list[str]) -> bool:
    parts = rel.split("/")
    prefixes = ["/".join(parts[: i + 1]) for i in range(len(parts))]
    ignored = False
    for pattern in patterns:
        negate = pattern.startswith("!")
        glob = pattern.lstrip("!").replace("**/", "*").rstrip("/")
        if any(fnmatch.fnmatch(p, glob) or fnmatch.fnmatch(p, "*/" + glob) for p in prefixes):
            ignored = not negate
    return ignored


def test_LIVE_AUDIT_B_api_image_copies_the_skills_directory(repo_root: pathlib.Path) -> None:
    dockerfile = (repo_root / "services/api/Dockerfile").read_text(encoding="utf-8")
    lines = [line.strip() for line in dockerfile.splitlines()]
    builder_end = next(i for i, line in enumerate(lines) if line.startswith("RUN uv sync"))
    assert COPY_LINE in lines[:builder_end], f"the api builder stage must contain {COPY_LINE!r} before `uv sync`"


def test_LIVE_AUDIT_B_dockerignore_keeps_the_skill_definitions(repo_root: pathlib.Path) -> None:
    patterns = [
        line.strip()
        for line in (repo_root / ".dockerignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    skills = sorted(repo_root.glob("skills/*/*/skill.yaml"))
    assert skills, "the repo ships built-in skills"
    for path in skills:
        for name in ("skill.yaml", "SKILL.md"):
            rel = (path.parent / name).relative_to(repo_root).as_posix()
            assert not _ignored(rel, patterns), f".dockerignore drops {rel} from the api image"
