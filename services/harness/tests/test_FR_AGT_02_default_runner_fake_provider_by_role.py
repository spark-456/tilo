"""FR-AGT-02 ticket brief item 3: "Unit work is done by a UnitRunner protocol ... The default
runner calls the model through packages/providers by role: it gets a Mapping[str, ModelProvider]
keyed by role name (director, lead, specialist) and never names a model id; tests use
tilo_providers.fake.FakeModelProvider."

Resolved ambiguity (ticket brief names no class): the production `UnitRunner` implementation is
`tilo_harness.executor.DefaultUnitRunner(providers: Mapping[str, ModelProvider])`, one instance
per run, matching the ticket brief's exact wording ("it gets a Mapping[str, ModelProvider]").
Logged per CLAUDE.md's ambiguity rule; see the test-writer report.
"""

from __future__ import annotations

import json
import re

from agt_support import (
    CountingFakeModelProvider,
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

# PL-01: no model id may appear anywhere outside config/ and packages/providers. A harness-written
# event's data/trace must never contain one of the example profile ids from PRD 6.4 or a raw
# provider model name.
_MODEL_ID_PATTERN = re.compile(r"gemini|flash-3|lite-31|gpt-|claude-|flash-38|flash-37", re.IGNORECASE)


def test_FR_AGT_02_default_runner_calls_fake_model_provider_by_role_no_model_id_appears(tmp_path) -> None:
    from tilo_harness.executor import DefaultUnitRunner

    layout = build_layout(district_specs=[{"id": "D1", "lead": "A_lead", "specialists": ["A_s0"], "unit_ids": ["U1"]}])
    plan = build_plan([build_unit("U1", role="specialist")])
    config = load_config_sync(write_agents_config(tmp_path / "agents.yaml"))
    skills = make_skill_registry(copy_skills_fixture_tree(tmp_path / "skills"))
    writer, store = make_memory_writer(layout, world_id="w_default_runner")

    director_provider = CountingFakeModelProvider("director")
    lead_provider = CountingFakeModelProvider("lead")
    specialist_provider = CountingFakeModelProvider("specialist")
    runner = DefaultUnitRunner(
        providers={"director": director_provider, "lead": lead_provider, "specialist": specialist_provider}
    )

    run_plan_sync(plan, layout, writer=writer, config=config, skills=skills, runner=runner)

    assert specialist_provider.calls, (
        "FR-AGT-02: the default runner must call the specialist role's ModelProvider for a specialist unit's work"
    )

    events = store.read_events("org_demo", "w_default_runner")
    dump = json.dumps(events)
    assert not _MODEL_ID_PATTERN.search(dump), (
        f"PL-01: no event may name a model id, got a match in the written stream: {dump[:2000]}"
    )
