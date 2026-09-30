"""Property test (root CLAUDE.md ticket loop: "Property tests ... for invariants: ... seq
strictly increasing"). `test_D_11_seq_invariant_property.py` already covers this for direct
`WorldWriter.emit`/`.append` calls; this file covers the same invariant through the executor,
where several units run concurrently and only `seq`'s single-writer discipline (PRD 9.3) is
supposed to keep the stream dense and ordered regardless of how many units overlap.

Generates small random dependency graphs (independent unit clusters chained together) and random
concurrency caps, and asserts the resulting event stream's `seq` is always exactly 1..N.
"""

from __future__ import annotations

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
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st


def _layered_plan(layer_sizes: list[int]) -> tuple[dict, list[str], list[str]]:
    """`layer_sizes` units in layer 0 are independent; each unit in layer k (k>0) depends on
    every unit in layer k-1 -- a small DAG with both independent and sequential stretches."""
    unit_ids: list[str] = []
    specialists: list[str] = []
    units = []
    previous_layer: list[str] = []
    counter = 0
    for layer_index, size in enumerate(layer_sizes):
        this_layer: list[str] = []
        for _ in range(size):
            uid = f"U{counter}"
            counter += 1
            unit_ids.append(uid)
            specialists.append(f"A_s{counter}")
            units.append(build_unit(uid, depends_on=list(previous_layer)))
            this_layer.append(uid)
        previous_layer = this_layer
    return build_plan(units), unit_ids, specialists


@settings(max_examples=15, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    layer_sizes=st.lists(st.integers(min_value=1, max_value=3), min_size=1, max_size=4),
    max_specialists=st.integers(min_value=1, max_value=4),
)
def test_FR_AGT_02_seq_is_always_1_to_n_regardless_of_concurrency_shape(
    tmp_path_factory, layer_sizes, max_specialists
) -> None:
    tmp_path = tmp_path_factory.mktemp("seq_prop")
    plan, unit_ids, specialists = _layered_plan(layer_sizes)
    layout = build_layout(
        district_specs=[{"id": "D1", "lead": "A_lead", "specialists": specialists, "unit_ids": unit_ids}]
    )
    config = load_config_sync(
        write_agents_config(tmp_path / "agents.yaml", limits={"max_specialists": max_specialists})
    )
    skills = make_skill_registry(copy_skills_fixture_tree(tmp_path / "skills"))
    writer, store = make_memory_writer(layout, world_id="w_seq_prop")
    runner = RecordingRunner(release_immediately=True)

    run_plan_sync(plan, layout, writer=writer, config=config, skills=skills, runner=runner)

    events = store.read_events("org_demo", "w_seq_prop")
    seqs = [e["seq"] for e in events]
    assert seqs == list(range(1, len(events) + 1)), f"seq must stay dense and strictly increasing, got {seqs}"
    assert sorted(runner.starts) == sorted(unit_ids), "every unit must have run exactly once"
