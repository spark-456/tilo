"""STARTER-1: the default sample project must ship in the tilo-api image, or a new account would be empty again.

Static only (no docker daemon). The two recorded files are package data inside `tilo_api` (read with
importlib.resources), byte-identical to the contracts originals; the Dockerfile copies `services` whole and the
root `.dockerignore` must not drop them. Runtime stays fail-closed (sample absent + one log line) if they are missing.
"""

from __future__ import annotations

import fnmatch
import pathlib
import tomllib

DATA = pathlib.Path("services/api/src/tilo_api/sample_data")
PAIRS = {
    "village-basic.jsonl": pathlib.Path("contracts/fixtures/streams/village-basic.jsonl"),
    "village_basic.json": pathlib.Path("contracts/fixtures/layout/valid/village_basic.json"),
}


def _ignored(rel: str, patterns: list[str]) -> bool:
    """A small .dockerignore matcher: `**` and `*` as fnmatch globs on the path or any of its parent directories,
    `!` lines re-include. Enough for the patterns this repo uses."""
    parts = rel.split("/")
    prefixes = ["/".join(parts[: i + 1]) for i in range(len(parts))]
    ignored = False
    for pattern in patterns:
        negate = pattern.startswith("!")
        glob = pattern.lstrip("!").replace("**/", "*").rstrip("/")
        if any(fnmatch.fnmatch(p, glob) or fnmatch.fnmatch(p, "*/" + glob) for p in prefixes):
            ignored = not negate
    return ignored


def test_STARTER_1_packaged_sample_files_are_byte_identical_to_the_contracts_originals(repo_root):
    for name, original in PAIRS.items():
        packaged = repo_root / DATA / name
        assert packaged.is_file(), f"STARTER-1: {DATA / name} must exist (package data of tilo_api)"
        assert packaged.read_bytes() == (repo_root / original).read_bytes(), (
            f"STARTER-1: {name} drifted from {original}"
        )


def test_STARTER_1_api_image_copies_the_package_and_the_ignore_file_keeps_the_sample(repo_root):
    dockerfile = (repo_root / "services/api/Dockerfile").read_text(encoding="utf-8")
    assert "COPY services ./services" in dockerfile, "STARTER-1: the image must copy services/ (tilo_api and its data)"
    patterns = [
        line.strip()
        for line in (repo_root / ".dockerignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    for name in PAIRS:
        rel = f"{DATA.as_posix()}/{name}"
        assert not _ignored(rel, patterns), f"STARTER-1: .dockerignore drops {rel} from the api image"


def test_STARTER_1_wheel_build_includes_the_whole_tilo_api_package(repo_root):
    config = tomllib.loads((repo_root / "services/api/pyproject.toml").read_text(encoding="utf-8"))
    wheel = config["tool"]["hatch"]["build"]["targets"]["wheel"]
    assert wheel["packages"] == ["src/tilo_api"], "STARTER-1: the wheel must carry sample_data inside tilo_api"
    assert "exclude" not in wheel and "include" not in wheel
