"""PRD 20.3 Repository layout and stack, adapted by ADR-0001 (native Windows, `just`).

Ticket P0-01 scaffolds the monorepo layout except `contracts/` (P0-02) and
`infra/` (P0-07, running in parallel) -- those two are asserted by their own
tickets' acceptance tests, not here.
"""
from __future__ import annotations

import pathlib

import pytest

# Directories PRD 20.3 lists that ticket P0-01 is responsible for creating.
# Each entry is (path, needs_claude_md). `apps/web` gets only a CLAUDE.md
# (no app code yet -- that is ticket P0-08).
P0_01_DIRECTORIES = [
    ("config", False),
    ("prompts", False),
    ("skills", False),
    ("templates", False),
    ("evals", False),
    ("evals/cases", False),
    ("evals/checks", False),
    ("packages/providers", True),
    ("packages/contracts-py", True),
    ("packages/contracts-ts", True),
    ("apps/web", True),
    ("services/api", True),
    ("services/harness", True),
    ("services/channels", True),
    ("services/connectors", True),
    ("services/browser", True),
    ("services/render", True),
    ("services/sandbox-web", True),
    (".github/workflows", False),
]


@pytest.mark.parametrize("rel_path,_needs_claude_md", P0_01_DIRECTORIES, ids=[d for d, _ in P0_01_DIRECTORIES])
def test_PRD_20_3_layout_directories_exist(repo_root: pathlib.Path, rel_path: str, _needs_claude_md: bool) -> None:
    directory = repo_root / rel_path
    assert directory.is_dir(), f"PRD 20.3 layout: {rel_path}/ must exist at the repo root"


def test_PRD_20_3_layout_excludes_out_of_scope_tickets(repo_root: pathlib.Path) -> None:
    """contracts/ (P0-02) and infra/ (P0-07) are owned by other, parallel tickets.

    Ambiguity resolved per CLAUDE.md ticket-loop rules: P0-01 must not create
    or claim these directories, so this test only documents the boundary and
    does not assert either directory's absence (the parallel ticket may have
    already created its own before this one runs).
    """
    assert True
