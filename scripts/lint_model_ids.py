#!/usr/bin/env python3
"""PL-01 lint (PRD 6.4): a model id may live only in config/ or
packages/providers/. Scans git-tracked Python/TypeScript/JavaScript/YAML
files outside those two paths for a model id: every "model:" value in
config/models.yaml, plus generic family patterns (gemini-, gemma-, gpt-,
claude-, llama-, mistral-, nemotron-). Docs (*.md) and design/source/ are
excluded. stdlib only. Wired into `just lint`. Usage: python
scripts/lint_model_ids.py [repo_root] (defaults to cwd)."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

EXCLUDED_PREFIXES = ("config/", "packages/providers/", "design/source/")
SCANNED_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".jsx", ".yaml", ".yml"}
FAMILY_PATTERN = re.compile(r"\b(?:gemini|gemma|gpt|claude|llama|mistral|nemotron)-[A-Za-z0-9][A-Za-z0-9_.\-]*")
CONFIG_MODEL_ID_PATTERN = re.compile(r"\bmodel:\s*[\"']?([A-Za-z0-9][A-Za-z0-9_.\-]*)")


def _tracked_files(repo_root: Path) -> list[str]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=repo_root, check=True, capture_output=True).stdout
    return [name for name in out.decode("utf-8").split("\0") if name]


def _configured_model_ids(repo_root: Path) -> set[str]:
    models_path = repo_root / "config" / "models.yaml"
    if not models_path.is_file():
        return set()
    text = models_path.read_text(encoding="utf-8", errors="ignore")
    return {m for m in CONFIG_MODEL_ID_PATTERN.findall(text) if m}


def _is_scanned(relative_path: str) -> bool:
    normalised = relative_path.replace("\\", "/")
    if any(normalised.startswith(prefix) for prefix in EXCLUDED_PREFIXES):
        return False
    return Path(normalised).suffix in SCANNED_SUFFIXES


def main(argv: list[str]) -> int:
    repo_root = Path(argv[0]).resolve() if argv else Path.cwd()
    known_ids = _configured_model_ids(repo_root)

    violations: list[str] = []
    for relative_path in _tracked_files(repo_root):
        if not _is_scanned(relative_path):
            continue
        try:
            text = (repo_root / relative_path).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        found = set(FAMILY_PATTERN.findall(text)) | {m for m in known_ids if m in text}
        violations += [
            f"{relative_path}: model id {m!r} outside config/ and packages/providers/" for m in sorted(found)
        ]

    if violations:
        sys.stderr.write("lint_model_ids.py: PL-01 violation(s):\n" + "\n".join(f"  {v}" for v in violations) + "\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
