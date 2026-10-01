"""FR-AGT-03 (PRD 8.2, 8.6): "Skill registry: load, validate, pin versions, list in Trace ...
A run's Trace lists every skill and version used." This file covers the registry's static
surface: `catalog()` (planner-visible: id + one-line description only, PRD 8.2 Selection),
`load(skill_id)` (the executing agent's full body + integrity hash), and that an invalid skill
folder is reported, never loaded.
"""

from __future__ import annotations

import hashlib

import pytest
from agt_support import INVALID_SKILLS_FIXTURES_DIR, SKILLS_FIXTURES_DIR, make_skill_registry


def test_FR_AGT_03_catalog_lists_only_id_and_description(tmp_path) -> None:
    from agt_support import copy_skills_fixture_tree

    registry = make_skill_registry(copy_skills_fixture_tree(tmp_path / "skills"))
    catalog = list(registry.catalog())

    ids = {entry[0] for entry in catalog}
    assert ids == {"web_research", "exec_summary"}, f"catalog must list every valid skill's id, got {ids}"
    for entry in catalog:
        assert len(entry) == 2, f"catalog() must expose only (id, description) -- PRD 8.2 Selection, got {entry!r}"
        skill_id, description = entry
        assert isinstance(description, str) and description, f"{skill_id}: description must be a non-empty string"
    descriptions = {entry[0]: entry[1] for entry in catalog}
    assert descriptions["web_research"] == "Web research with citations for a specialist unit."


def test_FR_AGT_03_load_returns_body_version_and_sha256(tmp_path) -> None:
    from agt_support import copy_skills_fixture_tree

    root = copy_skills_fixture_tree(tmp_path / "skills")
    registry = make_skill_registry(root)

    loaded = registry.load("web_research")
    assert loaded.id == "web_research"
    assert loaded.version == "1.0.0"
    assert "When to use" in loaded.body, "load() must return SKILL.md's own text as the body"

    skill_yaml = (root / "research/web_research/skill.yaml").read_bytes()
    skill_md = (root / "research/web_research/SKILL.md").read_bytes()
    expected_sha256 = hashlib.sha256(skill_yaml + skill_md).hexdigest()
    assert loaded.sha256 == expected_sha256, "sha256 must cover skill.yaml plus SKILL.md exactly"


def test_FR_AGT_03_load_of_unknown_skill_id_raises(tmp_path) -> None:
    from agt_support import copy_skills_fixture_tree

    registry = make_skill_registry(copy_skills_fixture_tree(tmp_path / "skills"))
    with pytest.raises(Exception):  # noqa: B017, PT011 -- the registry's own exception type
        registry.load("does_not_exist")


def test_FR_AGT_03_invalid_skill_folder_id_mismatch_is_reported_not_loaded(tmp_path) -> None:
    """skills_invalid/wrong_folder/bad_id_folder/skill.yaml is schema-valid but its own `id`
    ("mismatched_id") does not match its folder name ("bad_id_folder"); skill.schema.json's own
    description requires the folder to be skills/<domain>/<skill-id>/."""
    registry = make_skill_registry(INVALID_SKILLS_FIXTURES_DIR)

    catalog_ids = {entry[0] for entry in registry.catalog()}
    assert "mismatched_id" not in catalog_ids and "bad_id_folder" not in catalog_ids

    with pytest.raises(Exception):  # noqa: B017, PT011
        registry.load("mismatched_id")


def test_FR_AGT_03_invalid_skill_folder_schema_violation_is_reported_not_loaded(tmp_path) -> None:
    """skills_invalid/schema_violation/broken_skill/skill.yaml is missing required fields
    (reviewer, outputs)."""
    registry = make_skill_registry(INVALID_SKILLS_FIXTURES_DIR)

    catalog_ids = {entry[0] for entry in registry.catalog()}
    assert "broken_skill" not in catalog_ids

    with pytest.raises(Exception):  # noqa: B017, PT011
        registry.load("broken_skill")


def test_FR_AGT_03_an_invalid_sibling_folder_never_hides_a_valid_one(tmp_path) -> None:
    """A registry rooted over both a valid domain and invalid ones must still serve the valid
    skill -- one bad folder must be reported, not abort loading the rest."""
    import shutil

    root = tmp_path / "mixed"
    shutil.copytree(SKILLS_FIXTURES_DIR, root, dirs_exist_ok=True)
    shutil.copytree(INVALID_SKILLS_FIXTURES_DIR / "schema_violation", root / "schema_violation", dirs_exist_ok=True)

    registry = make_skill_registry(root)
    ids = {entry[0] for entry in registry.catalog()}
    assert ids == {"web_research", "exec_summary"}, f"the valid skills must still be served, got {ids}"
