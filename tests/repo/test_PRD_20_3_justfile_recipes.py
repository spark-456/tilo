"""PRD 20.3 "one `make` entry point", adapted by ADR-0001 to `just`.

ADR-0001 maps every PRD `make <x>` recipe to `just <x>`, plus `check-fast`
(used by .claude/hooks/stop_check.py), `skills-test` (FR-AGT-04) and
`deploy env=dev`.
"""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess

REQUIRED_RECIPES = [
    "setup",
    "dev",
    "check",
    "check-fast",
    "test",
    "fmt",
    "lint",
    "typecheck",
    "eval",
    "skills-test",
    "deploy",
]


def _recipe_names_via_just(justfile: pathlib.Path) -> set[str] | None:
    just_bin = shutil.which("just")
    if just_bin is None:
        return None
    result = subprocess.run(
        [just_bin, "--summary", "--justfile", str(justfile)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(f"`just --summary` failed: {result.stderr}")
    return set(result.stdout.split())


def _recipe_names_via_text(justfile: pathlib.Path) -> set[str]:
    text = justfile.read_text(encoding="utf-8")
    # A recipe header is a line starting at column 0 with an identifier,
    # optional parameters, then `:` (not `:=`, which is a variable assignment).
    pattern = re.compile(r"^([a-zA-Z_][a-zA-Z0-9_-]*)(\s+[a-zA-Z_][a-zA-Z0-9_=\"' -]*)?\s*:(?!=)", re.MULTILINE)
    return {m.group(1) for m in pattern.finditer(text)}


def test_PRD_20_3_justfile_exists_at_root(repo_root: pathlib.Path) -> None:
    assert (repo_root / "justfile").is_file(), "ADR-0001: root justfile must exist (replaces PRD 20.3's Makefile)"


def test_PRD_20_3_justfile_declares_windows_shell(repo_root: pathlib.Path) -> None:
    justfile = repo_root / "justfile"
    assert justfile.is_file(), "justfile must exist before its shell setting can be checked"
    text = justfile.read_text(encoding="utf-8")
    assert "windows-shell" in text and "pwsh" in text, (
        'ADR-0001: justfile must set `set windows-shell := ["pwsh", ...]` so recipes run on native Windows'
    )


def test_PRD_20_3_justfile_recipes_exist(repo_root: pathlib.Path) -> None:
    justfile = repo_root / "justfile"
    assert justfile.is_file(), "justfile must exist before its recipes can be checked"

    names = _recipe_names_via_just(justfile)
    if names is None:
        names = _recipe_names_via_text(justfile)

    missing = [r for r in REQUIRED_RECIPES if r not in names]
    assert not missing, f"justfile is missing required recipes: {missing} (found: {sorted(names)})"
