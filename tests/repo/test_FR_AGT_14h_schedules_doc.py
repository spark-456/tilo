"""FR-AGT-14h (issue #502; BQ-AGT14-8 e): the scheduled-run notes leave services/api/CLAUDE.md for docs/schedules.md.

The long FR-AGT-14 entry of services/api/CLAUDE.md (14b, 14d, 14e, 14f, 14g) moves to docs/schedules.md, which also
gets 14h; services/api/CLAUDE.md links to it and stays within the 40-line cap (PRD 20.4, ticket P0-01).

stdlib only, like the rest of tests/repo.
"""

from __future__ import annotations

import pathlib
import re

DOC = "docs/schedules.md"
API_CLAUDE_MD = "services/api/CLAUDE.md"
STEPS = ("14b", "14d", "14e", "14f", "14g", "14h")  # the steps of FR-AGT-14 with notes (14c is Terraform only)
# Details that belong to the schedule notes: they live in docs/schedules.md, and no longer in services/api/CLAUDE.md.
MOVED = ("BQ-AGT14-4", "BQ-AGT14-5", "BQ-AGT14-6", "BQ-AGT14-7", "tasks_unavailable", "tasks_credential")
NOTED = (*MOVED, "BQ-AGT14-8", "tasks_quota", "tasks_server", "TILO_RUNS_QUEUE", "TILO_TASKS_CALLER")


def test_FR_AGT_14h_docs_schedules_md_names_every_schedule_step(repo_root: pathlib.Path) -> None:
    doc = repo_root / DOC
    assert doc.is_file(), f"{DOC} must exist"
    text = doc.read_text(encoding="utf-8")
    missing = [step for step in STEPS if not re.search(rf"(?<![0-9A-Za-z]){step}(?![0-9A-Za-z])", text)]
    assert not missing, f"{DOC} does not name {missing}"
    absent = [word for word in NOTED if word not in text]
    assert not absent, f"{DOC} is missing {absent}"


def test_FR_AGT_14h_api_claude_md_links_docs_schedules_md_and_stays_within_40_lines(repo_root: pathlib.Path) -> None:
    text = (repo_root / API_CLAUDE_MD).read_text(encoding="utf-8")
    assert DOC in text, f"{API_CLAUDE_MD} must link {DOC}"
    lines = len(text.splitlines())
    assert lines <= 40, f"{API_CLAUDE_MD} has {lines} lines; the cap is 40"
    left = [word for word in MOVED if word in text]
    assert not left, f"{API_CLAUDE_MD} still carries schedule notes that moved to {DOC}: {left}"
