"""ADR-0001: "LF line endings everywhere via .gitattributes"."""
from __future__ import annotations

import pathlib


def test_PRD_20_3_gitattributes_forces_lf(repo_root: pathlib.Path) -> None:
    gitattributes = repo_root / ".gitattributes"
    assert gitattributes.is_file(), ".gitattributes must exist at the repo root"

    text = gitattributes.read_text(encoding="utf-8")
    lines = [ln.split("#", 1)[0].strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln]

    forces_lf = any(
        ln.startswith("*") and "text" in ln and "eol=lf" in ln
        for ln in lines
    )
    assert forces_lf, ".gitattributes must force LF line endings for text files (e.g. `* text=auto eol=lf`)"
