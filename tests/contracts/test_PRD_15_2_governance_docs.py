"""PRD 15.2 Contract files (ticket P0-02 sections 1 and 5): the conventions
and cross-reference rules that a JSON Schema cannot express on its own.

- `docs/adr/0002-contract-conventions.md`: ids, $id, versioning, fixtures,
  codegen, and the authz shape resolved from BQ-01.
- `contracts/CLAUDE.md` and `contracts/README.md` (short).
- `contracts/plan.rules.md`: PlanGraph cross-reference rules the schema
  cannot express (every irreversible action maps to a gate; `depends_on`
  refers to existing units), with rule ids for the P1 validator.
- `contracts/layout.rules.md`: WorldLayout validation rules WE-01.. (PRD 9.2),
  with a note that the v1 rule list is unavailable (BQ-02).
"""

from __future__ import annotations


def _text(path):
    return path.read_text(encoding="utf-8")


def test_PRD_15_2_adr_0002_contract_conventions_exists(repo_root):
    path = repo_root / "docs" / "adr" / "0002-contract-conventions.md"
    assert path.is_file(), "PRD 15.2: docs/adr/0002-contract-conventions.md must exist (ticket P0-02 section 5)"
    text = _text(path).lower()
    for topic in ("$id", "x-version", "fixture", "authz", "bq-01"):
        assert topic in text, f"PRD 15.2: docs/adr/0002-contract-conventions.md must cover {topic!r}"


def test_PRD_15_2_contracts_claude_md_exists(repo_root):
    path = repo_root / "contracts" / "CLAUDE.md"
    assert path.is_file(), "PRD 15.2: contracts/CLAUDE.md must exist (ticket P0-02 section 5)"
    assert _text(path).strip(), "PRD 15.2: contracts/CLAUDE.md must not be empty"


def test_PRD_15_2_contracts_readme_exists(repo_root):
    path = repo_root / "contracts" / "README.md"
    assert path.is_file(), "PRD 15.2: contracts/README.md must exist (ticket P0-02 section 5)"
    assert _text(path).strip(), "PRD 15.2: contracts/README.md must not be empty"


def test_PRD_15_2_plan_rules_md_exists_with_gate_and_depends_on_rules(repo_root):
    path = repo_root / "contracts" / "plan.rules.md"
    assert path.is_file(), (
        "PRD 15.2: contracts/plan.rules.md must exist -- cross-reference rules plan.schema.json "
        "cannot express, with rule ids for the P1 validator (ticket P0-02 section 1)"
    )
    text = _text(path).lower()
    assert "gate" in text, "PRD 15.2: contracts/plan.rules.md must state the every-irreversible-action-has-a-gate rule"
    assert (
        "depends_on" in text
    ), "PRD 15.2: contracts/plan.rules.md must state the depends_on-refers-to-existing-units rule"


def test_PRD_15_2_layout_rules_md_exists_as_we_series_with_bq_02_note(repo_root):
    path = repo_root / "contracts" / "layout.rules.md"
    assert path.is_file(), (
        "PRD 9.2 / ticket P0-02 section 1: contracts/layout.rules.md must exist with WorldLayout "
        "validation rules WE-01.."
    )
    text = _text(path)
    assert "WE-01" in text, "PRD 9.2: contracts/layout.rules.md must number its rules starting at WE-01"
    assert "BQ-02" in text, (
        "PRD 9.2 / docs/open-questions.md BQ-02: contracts/layout.rules.md must note that the v1 "
        "rule list (WE-01..WE-16) is unavailable and that these rules are derived from the 9.2 "
        "summary sentence"
    )
