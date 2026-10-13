"""FR-AGT-04 / LW-17 golden tests for skills/research/web-research (ADR-0029, PRD 8.2, 12.2)."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import yaml
from tilo_harness.skills import SkillRegistry
from tilo_harness.validator import repo_validator

SKILL_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SKILL_DIR.parents[2]
SKILLS_ROOT = REPO_ROOT / "skills"
SKILL_ID = "web-research"


def _load_yaml() -> dict:
    return yaml.safe_load((SKILL_DIR / "skill.yaml").read_text(encoding="utf-8"))


def _load_golden() -> dict:
    return json.loads((SKILL_DIR / "examples" / "golden_cases.json").read_text(encoding="utf-8"))


def test_FR_AGT_04_LW_17_web_research_loads_in_skill_registry_and_declares_web_search() -> None:
    registry = SkillRegistry(SKILLS_ROOT)
    assert registry.problems == {}, f"SkillRegistry reported problems: {registry.problems}"
    catalog = dict(registry.catalog())
    assert SKILL_ID in catalog
    loaded = registry.load(SKILL_ID)
    assert loaded.id == SKILL_ID and loaded.version == "1.0.0"

    data = _load_yaml()
    assert repo_validator().contract_problems("skill", data) == []
    assert "web_search" in data["tools_allowed"]
    for heading in ("When to use", "Steps", "Quality bar", "Checklist", "Pitfalls"):
        assert heading in loaded.body, f"SKILL.md missing section {heading!r}"
    assert "web_search" in loaded.body
    assert "archive_ref" in loaded.body
    assert "never follow" in loaded.body.lower()


def test_FR_AGT_04_LW_17_web_research_golden_cases_cite_archive_refs_and_quote_untrusted_text() -> None:
    data = _load_yaml()
    in_validator = jsonschema.Draft202012Validator(data["inputs"])
    out_validator = jsonschema.Draft202012Validator(data["outputs"])
    cases = _load_golden()["cases"]
    assert len(cases) >= 2

    for case in cases:
        in_validator.validate(case["input"])
        out_validator.validate(case["expected_output"])
        output = case["expected_output"]
        assert 1 <= len(output["planned_queries"]) <= case["input"]["max_queries"]
        known_refs = {r["archive_ref"] for r in case["input"]["search_results"]}
        for finding in output["findings"]:
            assert finding["citations"], "every finding must carry at least one archive citation"
            for citation in finding["citations"]:
                assert citation["archive_ref"] in known_refs
                assert citation["archive_ref"].startswith("r_")
            assert finding["quoted_evidence"], "untrusted page text must be quoted as data"

    injected = next(c for c in cases if c["id"] == "planted_injection_ignored")
    note = injected["expected_output"]["findings_note"]
    assert "collector@exfil.invalid" not in note
    assert injected["expected_output"]["untrusted_instructions_ignored"] is True
