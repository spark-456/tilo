"""PRD 20.5 Submission package: "open-source licence"; CLAUDE.md hard rule:
fresh code only, every dependency's licence recorded. The ticket specifies
Apache-2.0.
"""

from __future__ import annotations

import pathlib


def test_PRD_20_5_license_file_exists(repo_root: pathlib.Path) -> None:
    license_file = repo_root / "LICENSE"
    assert license_file.is_file(), "LICENSE must exist at the repo root"


def test_PRD_20_5_license_is_apache_2_0(repo_root: pathlib.Path) -> None:
    license_file = repo_root / "LICENSE"
    assert license_file.is_file(), "LICENSE must exist at the repo root"

    text = license_file.read_text(encoding="utf-8")
    assert "Apache License" in text and "2.0" in text, "LICENSE must be the Apache License, Version 2.0"
    assert "The Tilo authors" in text, 'LICENSE copyright line must read "The Tilo authors"'
