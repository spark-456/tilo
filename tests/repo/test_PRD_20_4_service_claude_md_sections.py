"""PRD 20.4 Claude Code working agreement + 17.6 Maintainability.

"Every service has its own CLAUDE.md: purpose, commands, contracts it reads
and writes, config it uses, requirement IDs it owns, and local rules."
Kept under 40 lines per the ticket's size budget.
"""
from __future__ import annotations

import pathlib
import re

import pytest

# Services/packages that get a CLAUDE.md in ticket P0-01 (apps/web gets only
# a CLAUDE.md; its app code is ticket P0-08).
CLAUDE_MD_OWNERS = [
    "packages/providers",
    "packages/contracts-py",
    "packages/contracts-ts",
    "apps/web",
    "services/api",
    "services/harness",
    "services/channels",
    "services/connectors",
    "services/browser",
    "services/render",
    "services/sandbox-web",
]

# Each required section may appear as a heading using any of these words
# (case-insensitive), since exact heading wording is not fixed by the PRD.
REQUIRED_SECTIONS = {
    "purpose": ["purpose"],
    "commands": ["command"],
    "contracts": ["contract"],
    "config": ["config"],
    "requirement IDs": ["requirement"],
    "local rules": ["rule"],
}

HEADING_RE = re.compile(r"^#{1,6}\s*(.+)$", re.MULTILINE)


@pytest.mark.parametrize("service_dir", CLAUDE_MD_OWNERS)
def test_PRD_20_4_service_has_claude_md(repo_root: pathlib.Path, service_dir: str) -> None:
    claude_md = repo_root / service_dir / "CLAUDE.md"
    assert claude_md.is_file(), f"PRD 20.4: {service_dir}/CLAUDE.md must exist"


@pytest.mark.parametrize("service_dir", CLAUDE_MD_OWNERS)
def test_PRD_20_4_service_claude_md_has_required_sections(repo_root: pathlib.Path, service_dir: str) -> None:
    claude_md = repo_root / service_dir / "CLAUDE.md"
    assert claude_md.is_file(), f"PRD 20.4: {service_dir}/CLAUDE.md must exist"

    text = claude_md.read_text(encoding="utf-8")
    headings = " ".join(h.lower() for h in HEADING_RE.findall(text))

    missing = [
        label
        for label, keywords in REQUIRED_SECTIONS.items()
        if not any(kw in headings for kw in keywords)
    ]
    assert not missing, f"{service_dir}/CLAUDE.md is missing sections: {missing}"


@pytest.mark.parametrize("service_dir", CLAUDE_MD_OWNERS)
def test_PRD_17_6_service_claude_md_under_40_lines(repo_root: pathlib.Path, service_dir: str) -> None:
    claude_md = repo_root / service_dir / "CLAUDE.md"
    assert claude_md.is_file(), f"PRD 20.4: {service_dir}/CLAUDE.md must exist"

    line_count = len(claude_md.read_text(encoding="utf-8").splitlines())
    assert line_count <= 40, f"{service_dir}/CLAUDE.md has {line_count} lines; ticket P0-01 caps each at 40"


def test_PRD_20_4_root_claude_md_commands_section_filled(repo_root: pathlib.Path) -> None:
    root_claude_md = repo_root / "CLAUDE.md"
    assert root_claude_md.is_file()
    text = root_claude_md.read_text(encoding="utf-8")
    match = re.search(r"^## Commands\s*$(.*?)(^## |\Z)", text, re.MULTILINE | re.DOTALL)
    assert match, "root CLAUDE.md must have a ## Commands section"
    body = match.group(1).strip()
    assert "Filled in by the scaffold ticket" not in body, "ticket P0-01 must fill in the root CLAUDE.md Commands section"
    for cmd in ["just dev", "just check", "just check-fast", "just test", "just eval", "just deploy"]:
        assert cmd in body, f"root CLAUDE.md Commands section must document `{cmd}`"
