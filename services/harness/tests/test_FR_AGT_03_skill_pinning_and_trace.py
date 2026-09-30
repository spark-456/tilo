"""FR-AGT-03 execution-level behaviour (PRD 8.2 Pinning, ticket brief item 5):

- `registry.pin(skill_ids) -> Pins` snapshots id -> (version, sha256) at run start.
- `run_plan` refuses to start when a unit names a skill that is not in the registry (PG-11, fail
  closed) -- before any event is written.
- The run's Trace (its written events) lists a `skill.loaded` event with the *pinned* version for
  every (unit, skill) pair used, even when the file on disk changes mid-run.
- Loading a pinned skill whose files no longer match the pinned sha256 fails that unit closed
  rather than silently using the changed content.
"""

from __future__ import annotations

import hashlib

from agt_support import (
    RecordingRunner,
    build_layout,
    build_plan,
    build_unit,
    copy_skills_fixture_tree,
    load_config_sync,
    make_skill_registry,
    run_plan_sync,
    write_agents_config,
)
from conftest import make_memory_writer


def _config(tmp_path):
    return load_config_sync(write_agents_config(tmp_path / "agents.yaml"))


def test_FR_AGT_03_pin_snapshots_version_and_sha256(tmp_path) -> None:
    root = copy_skills_fixture_tree(tmp_path / "skills")
    registry = make_skill_registry(root)

    pins = registry.pin(["web_research"])

    assert pins["web_research"][0] == "1.0.0"
    skill_yaml = (root / "research/web_research/skill.yaml").read_bytes()
    skill_md = (root / "research/web_research/SKILL.md").read_bytes()
    assert pins["web_research"][1] == hashlib.sha256(skill_yaml + skill_md).hexdigest()


def test_FR_AGT_03_unknown_skill_pg11_refused_before_any_event(tmp_path) -> None:
    layout = build_layout(district_specs=[{"id": "D1", "lead": "A_lead", "specialists": ["A_s0"], "unit_ids": ["U1"]}])
    plan = build_plan([build_unit("U1", skills=["does_not_exist"])])
    config = _config(tmp_path)
    skills = make_skill_registry(copy_skills_fixture_tree(tmp_path / "skills"))
    writer, store = make_memory_writer(layout, world_id="w_pg11")

    raised = False
    try:
        run_plan_sync(plan, layout, writer=writer, config=config, skills=skills, runner=RecordingRunner())
    except Exception:  # noqa: BLE001 -- the executor's own exception type; only "refused" matters
        raised = True
    assert raised, "PG-11: a unit naming an unregistered skill must be refused"
    assert store.read_events("org_demo", "w_pg11") == [], "PG-11: a refused plan must write nothing at all"


def test_FR_AGT_03_trace_lists_skill_loaded_with_pinned_version_per_unit_skill_pair(tmp_path) -> None:
    layout = build_layout(
        district_specs=[{"id": "D1", "lead": "A_lead", "specialists": ["A_s0", "A_s1"], "unit_ids": ["U1", "U2"]}]
    )
    plan = build_plan(
        [
            build_unit("U1", skills=["web_research"]),
            build_unit("U2", skills=["web_research", "exec_summary"]),
        ]
    )
    config = _config(tmp_path)
    skills = make_skill_registry(copy_skills_fixture_tree(tmp_path / "skills"))
    writer, store = make_memory_writer(layout, world_id="w_trace_skills")

    run_plan_sync(plan, layout, writer=writer, config=config, skills=skills, runner=RecordingRunner())

    loaded = [e for e in store.read_events("org_demo", "w_trace_skills") if e["type"] == "skill.loaded"]
    by_actor_skill = {(e["actor"], e["data"]["skill"]): e["data"]["version"] for e in loaded}

    # (unit, skill) pairs: U1 is worked by A_s0 (web_research); U2 by A_s1 (web_research, exec_summary).
    assert ("A_s0", "web_research") in by_actor_skill
    assert ("A_s1", "web_research") in by_actor_skill
    assert ("A_s1", "exec_summary") in by_actor_skill
    assert by_actor_skill[("A_s0", "web_research")] == "1.0.0"
    assert by_actor_skill[("A_s1", "exec_summary")] == "2.1.0"


def test_FR_AGT_03_mid_run_file_change_does_not_change_the_pinned_version_or_body(tmp_path) -> None:
    """Pinning happens at run start; a skill.yaml/SKILL.md edit made *after* pinning must never
    change what a still-running unit uses. Resolved ambiguity (see
    test_FR_AGT_03_pinned_sha_mismatch_fails_closed_registry_level): since `SkillRegistry` holds
    no cache, "does not change what the run uses" cannot mean an in-memory copy survives a disk
    edit untouched -- it means the pins snapshot itself is immutable data (asserted directly
    here) and a disk edit is never silently substituted in (asserted as the sha-mismatch case in
    the other test); together they are the same "load from the pins, not from disk" guarantee.
    `registry.load(skill_id)` (unpinned, PRD 8.2's ordinary planner/author-facing accessor) is a
    different accessor that legitimately *does* reflect the current disk state -- it is not what
    a running unit is supposed to use, so it is deliberately not exercised by this test."""
    root = copy_skills_fixture_tree(tmp_path / "skills")
    registry = make_skill_registry(root)
    pins = registry.pin(["web_research"])
    pinned_version, pinned_sha256 = pins["web_research"]

    # Mutate the skill's files on disk after pinning, simulating an edit mid-run.
    skill_yaml_path = root / "research/web_research/skill.yaml"
    skill_yaml_path.write_text(skill_yaml_path.read_text(encoding="utf-8").replace("1.0.0", "9.9.9"), encoding="utf-8")

    assert pins["web_research"] == (pinned_version, pinned_sha256), "the Pins snapshot itself must never change"
    assert pinned_version == "1.0.0"


def test_FR_AGT_03_pinned_sha_mismatch_fails_closed_registry_level(tmp_path) -> None:
    """Ticket brief: "loading a pinned skill whose files no longer match the pinned sha256 fails
    that unit closed rather than using unpinned content." Resolved ambiguity: the brief names no
    method for "loading from the pins" beyond `pin()` and `load(skill_id)`; this test assumes
    `SkillRegistry.load_pinned(skill_id, pins)` -- re-reads the skill from disk, recomputes its
    sha256 and raises instead of returning a `LoadedSkill` when it no longer matches the pinned
    sha256 (the mechanism `run_plan` must use per unit, closing only that unit, not the whole
    run) -- logged in the test-writer report."""
    root = copy_skills_fixture_tree(tmp_path / "skills")
    skills = make_skill_registry(root)
    pins = skills.pin(["web_research", "exec_summary"])

    skill_md_path = root / "research/web_research/SKILL.md"
    skill_md_path.write_text(skill_md_path.read_text(encoding="utf-8") + "\ntampered mid-run\n", encoding="utf-8")

    import pytest

    with pytest.raises(Exception):  # noqa: B017, PT011 -- SkillPinMismatch or equivalent
        skills.load_pinned("web_research", pins)

    # The untouched skill must still load cleanly against the same pins.
    reloaded = skills.load_pinned("exec_summary", pins)
    assert reloaded.version == "2.1.0"
