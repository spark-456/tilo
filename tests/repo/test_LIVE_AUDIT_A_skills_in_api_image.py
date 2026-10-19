"""LIVE-PATH-AUDIT-A finding 3: the tilo-api image must carry `skills/`.

`tilo_api.deps.get_skill_registry` and `skill_proposals` read `<repo root>/skills` (the editable installs put the repo
root at /app). Until this copy existed, the deployed registry was empty: the Director's catalog had no skills and the
Skills page listed none. Static only (no docker daemon), like test_STARTER_1_sample_ships_in_api_image.
"""

from __future__ import annotations

import fnmatch
import pathlib


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


def test_LIVE_AUDIT_A_api_image_copies_skills(repo_root: pathlib.Path) -> None:
    dockerfile = (repo_root / "services/api/Dockerfile").read_text(encoding="utf-8")
    builder = dockerfile.split("AS runtime")[0]
    assert "COPY skills ./skills" in builder, "the api image must copy skills/ (deps.get_skill_registry reads it)"


def test_LIVE_AUDIT_A_dockerignore_keeps_every_skill_manifest(repo_root: pathlib.Path) -> None:
    patterns = [
        line.strip()
        for line in (repo_root / ".dockerignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    manifests = sorted((repo_root / "skills").glob("*/*/skill.yaml"))
    assert manifests, "the repository ships at least one skill"
    for manifest in manifests:
        rel = manifest.relative_to(repo_root).as_posix()
        assert not _ignored(rel, patterns), f"LIVE-AUDIT-A: .dockerignore drops {rel} from the api image"
