"""FR-WLD-03 (ticket P0-03 section 4): "a small ordered Village-tier fixture stream
`contracts/fixtures/streams/village-basic.jsonl` (a few dozen events for one world: requested ->
planned -> started -> agents spawned/working/handoff -> building constructing/operational/
completed -> an approval gate -> artifact delivered -> world completed), consistent with a
matching layout fixture under `contracts/fixtures/layout/valid/`, for the renderer's fixture
player (P0-08b) and the harness skeleton (P0-09)."

This does not re-validate the renderer or the harness (both later tickets); it only checks the
fixture itself is the ordered, internally-consistent stream those tickets will read: one JSON
object per line, each a valid TiloEvent against event.schema.json and its own data schema,
`seq` strictly increasing (FR-WLD-04's own invariant) for one `world_id`, the named milestone
types appear in the stated relative order, and that `world_id` also names a fixture under
`contracts/fixtures/layout/valid/`.
"""

from __future__ import annotations

import json

from _events_lib import data_schema_path
from _lib import errors_for, load_schema

STREAM_REL = "contracts/fixtures/streams/village-basic.jsonl"

# PRD 9.1 tier: village is 3-6 agents (PRD 9.1, common.schema.json#/$defs/tier).
MILESTONE_ORDER = (
    "world.requested",
    "world.planned",
    "world.started",
    "agent.spawned",
    "agent.working",
    "agent.handoff",
    "building.constructing",
    "building.operational",
    "approval.requested",
    "approval.resolved",
    "building.completed",
    "artifact.delivered",
    "world.completed",
)


def _stream_path(repo_root):
    return repo_root / STREAM_REL


def _load_lines(path):
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [json.loads(line) for line in lines]


def test_FR_WLD_03_village_basic_stream_exists(repo_root):
    assert _stream_path(repo_root).is_file(), f"FR-WLD-03: {STREAM_REL} must exist"


def test_FR_WLD_03_village_basic_stream_has_a_few_dozen_events(repo_root):
    path = _stream_path(repo_root)
    assert path.is_file(), "FR-WLD-03: see the stream-exists test"
    events = _load_lines(path)
    assert 20 <= len(events) <= 80, f"FR-WLD-03: {STREAM_REL} should hold a few dozen events, got {len(events)}"


def test_FR_WLD_03_village_basic_stream_is_one_world(repo_root):
    path = _stream_path(repo_root)
    assert path.is_file(), "FR-WLD-03: see the stream-exists test"
    events = _load_lines(path)
    world_ids = {e.get("world_id") for e in events}
    assert len(world_ids) == 1, f"FR-WLD-03: {STREAM_REL} must be a stream for one world, got {world_ids}"


def test_FR_WLD_03_village_basic_stream_seq_strictly_increases(repo_root):
    """FR-WLD-04's own invariant ('seq strictly increasing per world') applies to any fixture
    stream, not just the renderer's live path."""
    path = _stream_path(repo_root)
    assert path.is_file(), "FR-WLD-03: see the stream-exists test"
    events = _load_lines(path)
    seqs = [e.get("seq") for e in events]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs), (
        f"FR-WLD-03: {STREAM_REL} seq must strictly increase, got {seqs[:10]}..."
    )


def test_FR_WLD_03_village_basic_stream_events_validate(repo_root, registry):
    path = _stream_path(repo_root)
    assert path.is_file(), "FR-WLD-03: see the stream-exists test"
    events = _load_lines(path)
    event_schema = load_schema(repo_root, "event")
    failures = []
    for i, instance in enumerate(events):
        event_errors = errors_for(event_schema, instance, registry)
        if event_errors:
            failures.append((i, instance.get("type"), [e.message for e in event_errors][:1]))
            continue
        type_ = instance.get("type")
        data_path = data_schema_path(repo_root, type_) if isinstance(type_, str) else None
        if data_path is not None and data_path.is_file():
            data_errors = errors_for(json.loads(data_path.read_text(encoding="utf-8")), instance.get("data"), registry)
            if data_errors:
                failures.append((i, type_, [e.message for e in data_errors][:1]))
    assert not failures, f"FR-WLD-03: {STREAM_REL} line(s) failed validation: {failures[:5]}"


def test_FR_WLD_03_village_basic_stream_covers_the_milestone_types_in_order(repo_root):
    path = _stream_path(repo_root)
    assert path.is_file(), "FR-WLD-03: see the stream-exists test"
    events = _load_lines(path)
    types_in_order = [e.get("type") for e in events]

    missing = [t for t in MILESTONE_ORDER if t not in types_in_order]
    assert not missing, f"FR-WLD-03: {STREAM_REL} is missing milestone type(s): {missing}"

    # Each milestone's first occurrence must come after the previous milestone's first
    # occurrence, i.e. the narrative in the ticket's own order.
    positions = [types_in_order.index(t) for t in MILESTONE_ORDER]
    ordered = list(zip(MILESTONE_ORDER, positions))
    assert positions == sorted(positions), (
        f"FR-WLD-03: {STREAM_REL} milestones are out of the ticket's stated order: {ordered}"
    )


def test_FR_WLD_03_village_basic_stream_has_a_matching_layout_fixture(repo_root):
    path = _stream_path(repo_root)
    assert path.is_file(), "FR-WLD-03: see the stream-exists test"
    events = _load_lines(path)
    world_id = events[0].get("world_id") if events else None
    assert world_id, "FR-WLD-03: see the one-world test"

    layout_dir = repo_root / "contracts/fixtures/layout/valid"
    assert layout_dir.is_dir(), "FR-WLD-03: contracts/fixtures/layout/valid/ must exist (P0-02)"
    matches = []
    for p in sorted(layout_dir.glob("*.json")):
        try:
            layout = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(layout, dict) and layout.get("world_id") == world_id:
            matches.append(p)
    assert matches, (
        f"FR-WLD-03: no contracts/fixtures/layout/valid/*.json fixture has world_id={world_id!r} to match {STREAM_REL}"
    )
