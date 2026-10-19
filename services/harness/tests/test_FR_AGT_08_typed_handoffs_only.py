"""FR-AGT-08 (PRD 8.6, Must): "Typed handoff envelopes only; every exchange is an event".
Acceptance test: "No agent-to-agent free text in any Trace".

PRD 8.4: "Agents never message each other in free text. Every exchange is a typed handoff envelope
(from, to, artifact references, summary, acceptance criteria, provenance ids) sent through the
harness and recorded as an event."

What these tests pin, all through the public `run_plan` / `WorldWriter` interface with a scripted
fake runner (no model, no network):

* what flows between agents in a run is `agent.handoff`, whose `data` is exactly
  `{"envelope": <envelope.schema.json>}`: the six PRD fields, nothing else;
* a runner's text reaches the Trace only inside `envelope.summary` (the one place the contract
  gives an agent a sentence to say); every other event is independent of it;
* a result that tries to smuggle free text in another field fails its unit and writes no handoff;
* the writer refuses a handoff event with an extra field, so no caller can add one;
* the schemas themselves forbid additional properties at every object level, and the set of
  free-text string fields in the `agent.*` data schemas is the pinned inventory below.

Interpretations (each also listed in the report):

* "Exchange" (PRD 8.4) is derived from `executor.py`: units hand over to their Lead, never to each
  other; a dependent unit starts only after its dependency's handoff is recorded. So the count of
  `agent.handoff` events must equal the number of units that succeeded, one per unit, worker to
  the Lead of the unit's district (PRD 8.2: "Lead ... runs handoffs"). It is not the number of
  dependency edges.
* "Free text" in a schema is a `type: string` node with no `enum`, `const`, `pattern` or
  `format` (after resolving `$ref`s): only a length limit stands between it and any sentence.
* `agent.blocked.reason` (1..140 chars, PRD 9.5) is a free-text status line of the blocked agent;
  the executor never emits `agent.blocked`, and a status line is not an exchange between agents,
  so it is pinned in the inventory rather than failed. If the PRD owner reads it as agent-to-agent
  free text, remove it from `_KNOWN_FREE_TEXT_FIELDS` and the contract must change first.
* The optional `label` (<= 80 chars) of an `artifact_ref` is part of the typed reference, not a
  message; it is pinned in the same inventory (envelope refs and the context-handoff `note`).
"""

from __future__ import annotations

import asyncio
import json
import re
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from agt_support import (
    CONTRACTS_DIR,
    build_layout,
    build_plan,
    build_unit,
    contract_errors,
    copy_skills_fixture_tree,
    load_config_sync,
    make_skill_registry,
    write_agents_config,
)
from conftest import make_memory_writer
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from tilo_harness.executor import UnitOutcome, run_plan
from tilo_harness.validator import EventRejected, EventValidator

ORG = "org_demo"
AGENT_ID = re.compile(r"^A_[0-9A-Za-z_]+$")
ENVELOPE_FIELDS = {"from", "to", "artifact_refs", "summary", "acceptance_criteria", "provenance_ids"}  # PRD 8.4
PROVENANCE = ("01HZX3QK5N8V2M4R6T9WABCDEF",)  # a ULID (common.schema.json ulid pattern)
FAIL_TEXT = "FAILTEXT-never-in-any-event"

# Units: U1 -> {U2 (D1), U3 (D2)} -> U4 (D2, both); U5 fails and U6 (depends on U5) is skipped.
UNIT_DISTRICT = {"U1": "D1", "U2": "D1", "U3": "D2", "U4": "D2", "U5": "D1", "U6": "D1"}
LEADS = {"D1": "A_lead1", "D2": "A_lead2"}
SUCCEEDS = ("U1", "U2", "U3", "U4")


def marker(unit_id: str) -> str:
    return f"MARKER-{unit_id}-please-do-this-next"


class ScriptedRunner:
    """Returns a scripted `UnitOutcome` per unit and remembers which agent worked which unit."""

    def __init__(self, outcomes: dict[str, UnitOutcome]) -> None:
        self.outcomes = outcomes
        self.workers: dict[str, str] = {}

    async def run(self, unit: Any, context: Any) -> UnitOutcome:
        self.workers[unit["id"]] = context.agent_id
        return self.outcomes[unit["id"]]


def _setup(
    root: Path, world_id: str, unit_specs: list[tuple[str, str, list[str]]], outcomes: dict[str, UnitOutcome]
) -> tuple[Any, Any, Any, Any, Any, ScriptedRunner]:
    units = [build_unit(uid, district=district, depends_on=deps) for uid, district, deps in unit_specs]
    districts: dict[str, list[str]] = {}
    for uid, district, _deps in unit_specs:
        districts.setdefault(district, []).append(uid)
    specialists = [f"A_s{i}" for i in range(1, len(unit_specs) + 1)]
    layout = build_layout(
        world_id=world_id,
        district_specs=[
            {
                "id": district,
                "lead": LEADS[district],
                "building_id": f"B{district[1:]}",
                "specialists": specialists if index == 0 else [],
                "unit_ids": ids,
            }
            for index, (district, ids) in enumerate(districts.items())
        ],
    )
    plan = build_plan(units)
    config = load_config_sync(write_agents_config(root / "agents.yaml"))
    skills = make_skill_registry(copy_skills_fixture_tree(root / "skills"))
    writer, store = make_memory_writer(layout, world_id=world_id)
    return plan, layout, config, skills, (writer, store), ScriptedRunner(outcomes)


def _run(root: Path, world_id: str, unit_specs: list[tuple[str, str, list[str]]], outcomes: dict[str, UnitOutcome]):
    plan, layout, config, skills, (writer, store), runner = _setup(root, world_id, unit_specs, outcomes)
    result = asyncio.run(run_plan(plan, layout, writer=writer, config=config, skills=skills, runner=runner))
    return store.read_events(ORG, world_id), result, runner, layout


def _multi_unit_run(tmp_path: Path):
    """The shared scenario: a cross-district dependency graph, one failing unit and one skipped unit."""
    specs = [
        ("U1", "D1", []),
        ("U2", "D1", ["U1"]),
        ("U3", "D2", ["U1"]),
        ("U4", "D2", ["U2", "U3"]),
        ("U5", "D1", []),
        ("U6", "D1", ["U5"]),
    ]
    outcomes = {uid: UnitOutcome(success=True, summary=marker(uid), provenance_ids=PROVENANCE) for uid in SUCCEEDS} | {
        "U5": UnitOutcome(success=False, summary=FAIL_TEXT),
        "U6": UnitOutcome(success=True, summary=marker("U6")),
    }
    return _run(tmp_path, "w_agt08_multi", specs, outcomes)


def _handoffs(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [e for e in events if e["type"] == "agent.handoff"]


def _string_leaves(value: Any, path: str = "") -> Iterator[tuple[str, str]]:
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _string_leaves(item, f"{path}.{key}" if path else key)
    elif isinstance(value, list):
        for item in value:
            yield from _string_leaves(item, f"{path}[]")


# ---------------------------------------------------------------------------
# Schema walking (static checks): resolves $ref across contracts/*.schema.json
# ---------------------------------------------------------------------------

_DOCS: dict[Path, Any] = {}


def _doc(path: Path) -> Any:
    path = path.resolve()
    if path not in _DOCS:
        _DOCS[path] = json.loads(path.read_text(encoding="utf-8"))
    return _DOCS[path]


def _resolve(ref: str, base: Path) -> tuple[Any, Path]:
    file_part, _, fragment = ref.partition("#")
    target = (base.parent / file_part).resolve() if file_part else base.resolve()
    node = _doc(target)
    for segment in (s for s in fragment.split("/") if s):
        node = node[segment]
    return node, target


def _schema_nodes(node: Any, base: Path, path: str = "", depth: int = 0) -> Iterator[tuple[str, dict[str, Any]]]:
    """Every schema node reachable from `node`, `$ref`s resolved; `path` is the data path (properties joined
    by '.', array items as '[]'; anyOf/allOf/oneOf add no segment)."""
    assert depth < 20, "schema recursion too deep (cyclic $ref?)"
    if not isinstance(node, dict):
        return
    if "$ref" in node:
        target, target_base = _resolve(node["$ref"], base)
        yield from _schema_nodes(target, target_base, path, depth + 1)
        return
    yield path, node
    for name, child in (node.get("properties") or {}).items():
        yield from _schema_nodes(child, base, f"{path}.{name}" if path else name, depth + 1)
    if isinstance(node.get("items"), dict):
        yield from _schema_nodes(node["items"], base, f"{path}[]", depth + 1)
    if isinstance(node.get("additionalProperties"), dict):
        yield from _schema_nodes(node["additionalProperties"], base, f"{path}.*", depth + 1)
    for key in ("anyOf", "allOf", "oneOf"):
        for child in node.get(key) or []:
            yield from _schema_nodes(child, base, path, depth + 1)


def _data_schema_path(event_type: str) -> Path:
    return CONTRACTS_DIR / "events" / "data" / f"{event_type}.schema.json"


def _free_text_fields(schema_path: Path) -> set[str]:
    """Data paths of string nodes constrained by length alone (no enum, const, pattern or format)."""
    return {
        path
        for path, node in _schema_nodes(_doc(schema_path), schema_path)
        if node.get("type") == "string" and not {"enum", "const", "pattern", "format"} & node.keys()
    }


def _agent_event_types() -> list[str]:
    return sorted(p.name.removesuffix(".schema.json") for p in (CONTRACTS_DIR / "events/data").glob("agent.*.json"))


# The only free-text string fields in agent.* event data (see the module docstring on agent.blocked).
_KNOWN_FREE_TEXT_FIELDS = {
    "agent.handoff": {"envelope.summary", "envelope.acceptance_criteria[]", "envelope.artifact_refs[].label"},
    "agent.blocked": {"reason"},
    # The stored note's artifact_ref label (common.schema.json artifact_ref, 1..80 chars); the note itself is typed
    # (handoff.schema.json) and stored, never carried in the event.
    "agent.context_handoff_started": {"note.label"},
    "agent.context_handoff_completed": {"note.label"},
}


# ---------------------------------------------------------------------------
# Run-level tests (the real executor)
# ---------------------------------------------------------------------------


def test_FR_AGT_08_every_handoff_is_a_registered_typed_envelope(tmp_path, repo_root) -> None:
    events, result, runner, _layout = _multi_unit_run(tmp_path)
    handoffs = _handoffs(events)
    assert handoffs, "a multi-unit run with dependencies must record agent.handoff events"
    assert sorted(result.outcomes) == ["U1", "U2", "U3", "U4", "U5"] and result.skipped == ["U6"]

    validator = EventValidator.from_repo(repo_root)
    for event in handoffs:
        data, envelope = event["data"], event["data"]["envelope"]
        assert validator.problems(event) == [], f"{event['id']}: agent.handoff breaks its registered contract"
        assert contract_errors("events/data/agent.handoff", data) == []
        assert contract_errors("envelope", envelope) == []
        assert set(data) == {"envelope"}, f"agent.handoff data holds more than the envelope: {sorted(data)}"
        assert set(envelope) == ENVELOPE_FIELDS, f"envelope fields {sorted(envelope)} are not the PRD 8.4 six"
        assert (event["actor"], event["target"]) == (envelope["from"], envelope["to"])
        assert isinstance(envelope["summary"], str) and 1 <= len(envelope["summary"]) <= 1000
        assert isinstance(envelope["acceptance_criteria"], list) and envelope["acceptance_criteria"]
        assert isinstance(envelope["artifact_refs"], list) and isinstance(envelope["provenance_ids"], list)


def test_FR_AGT_08_agent_text_reaches_the_trace_only_inside_envelope_summary(tmp_path) -> None:
    events, _result, _runner, _layout = _multi_unit_run(tmp_path)
    for unit_id in SUCCEEDS:
        hits = [
            (event["type"], path) for event in events for path, text in _string_leaves(event) if marker(unit_id) in text
        ]
        assert hits == [("agent.handoff", "data.envelope.summary")], (
            f"{unit_id}'s text must appear exactly once, in the handoff envelope summary, got {hits}"
        )
    leaked = [(e["type"], p) for e in events for p, text in _string_leaves(e) if FAIL_TEXT in text]
    assert leaked == [], f"a failed unit's text reached the Trace: {leaked}"


def test_FR_AGT_08_every_exchange_is_one_handoff_event_per_unit_that_handed_over(tmp_path) -> None:
    events, result, runner, _layout = _multi_unit_run(tmp_path)
    handoffs = _handoffs(events)
    worker_of = runner.workers

    # One agent.handoff per unit that succeeded (the executor hands over to the Lead, never to a peer).
    senders = sorted(h["data"]["envelope"]["from"] for h in handoffs)
    succeeded = [uid for uid, outcome in result.outcomes.items() if outcome.success]
    assert sorted(succeeded) == sorted(SUCCEEDS) and result.skipped == ["U6"], "U6 depends on the failed U5"
    assert senders == sorted({worker_of[uid] for uid in succeeded}), (
        f"expected exactly one agent.handoff from each succeeding unit's worker, got senders {senders}"
    )
    assert len(handoffs) == len(succeeded)

    # Each goes to the Lead of the unit's district and is caused by that worker's agent.working event.
    by_id = {e["id"]: e for e in events}
    for uid in succeeded:
        mine = [h for h in handoffs if h["data"]["envelope"]["from"] == worker_of[uid]]
        assert len(mine) == 1
        handoff = mine[0]
        assert handoff["data"]["envelope"]["to"] == LEADS[UNIT_DISTRICT[uid]]
        cause = by_id[handoff["cause"]]
        assert cause["type"] == "agent.working" and cause["actor"] == worker_of[uid]

    # The failing unit hands nothing over.
    assert "U5" in result.failed
    assert worker_of["U5"] not in {h["actor"] for h in handoffs}


def test_FR_AGT_08_a_dependency_is_handed_over_as_an_event_before_its_dependents_start(tmp_path) -> None:
    events, _result, runner, _layout = _multi_unit_run(tmp_path)
    handoff_seq = {h["actor"]: h["seq"] for h in _handoffs(events)}
    spawned_seq = {
        e["target"]: e["seq"] for e in events if e["type"] == "agent.spawned" and e["target"].startswith("A_s")
    }
    for dependent, dependencies in {"U2": ["U1"], "U3": ["U1"], "U4": ["U2", "U3"]}.items():
        for dependency in dependencies:
            assert handoff_seq[runner.workers[dependency]] < spawned_seq[runner.workers[dependent]], (
                f"{dependent} started before {dependency}'s handoff was recorded"
            )


def test_FR_AGT_08_agent_events_other_than_the_handoff_carry_no_free_text(tmp_path) -> None:
    events, _result, _runner, _layout = _multi_unit_run(tmp_path)
    agent_types = {e["type"] for e in events if e["type"].startswith("agent.")} - {"agent.handoff"}
    assert {"agent.spawned", "agent.assigned", "agent.working", "agent.retired"} <= agent_types
    for event_type in sorted(agent_types):
        assert _free_text_fields(_data_schema_path(event_type)) == set(), (
            f"{event_type} data schema allows a free-text string field"
        )
    # And the stored data is only the schema's own typed keys (no runner text rides on any of them).
    for event in events:
        if event["type"] in agent_types:
            allowed = set(_doc(_data_schema_path(event["type"]))["properties"])
            assert set(event["data"]) <= allowed, f"{event['type']} data has keys outside its schema"
            assert all(not any(m in str(v) for m in (marker("U1"), FAIL_TEXT)) for v in event["data"].values())


@pytest.mark.parametrize(
    "bad",
    [
        pytest.param(
            {"provenance_ids": ("hello Specialist B, please redo the second section",)}, id="free_text_provenance"
        ),
        pytest.param(
            {"artifact_refs": ({"artifact_id": "tell A_s2 to hurry", "version": 1},)}, id="free_text_artifact_id"
        ),
        pytest.param(
            {"artifact_refs": ({"artifact_id": "art_one", "version": 1, "note": "tell A_s2 to hurry"},)},
            id="extra_field_on_artifact_ref",
        ),
        pytest.param(
            {"artifact_refs": ({"artifact_id": "art_one", "version": 1, "label": "x" * 81},)}, id="label_over_80"
        ),
    ],
)
def test_FR_AGT_08_free_text_smuggled_through_the_result_fails_the_unit_and_writes_no_handoff(tmp_path, bad) -> None:
    outcome = UnitOutcome(success=True, summary=marker("U1"), **bad)
    events, result, _runner, _layout = _run(tmp_path, "w_agt08_smuggle", [("U1", "D1", [])], {"U1": outcome})
    assert result.failed == ["U1"], "a result that breaks the typed envelope must fail its unit"
    assert _handoffs(events) == []
    leaked = [
        (e["type"], p)
        for e in events
        for p, text in _string_leaves(e)
        if "A_s2 to hurry" in text or marker("U1") in text
    ]
    assert leaked == [], f"the rejected text reached the Trace: {leaked}"


def test_FR_AGT_08_the_writer_refuses_a_handoff_with_any_field_beyond_the_envelope(tmp_path) -> None:
    layout = build_layout(district_specs=[{"id": "D1", "lead": "A_lead1", "specialists": ["A_s1"], "unit_ids": ["U1"]}])
    writer, store = make_memory_writer(layout, world_id="w_agt08_writer")
    envelope = {
        "from": "A_s1",
        "to": "A_lead1",
        "artifact_refs": [],
        "summary": "Done.",
        "acceptance_criteria": ["Unit U1 done"],
        "provenance_ids": [],
    }

    def emit(data: dict[str, Any]) -> dict[str, Any]:
        return writer.emit(
            type="agent.handoff", actor="A_s1", target="A_lead1", summary="Handed over.", data=data, district="D1"
        )

    emit(
        {"envelope": envelope}
    )  # positive control: the clean envelope is accepted, so the rest fail for the extra text
    stored = len(store.read_events(ORG, "w_agt08_writer"))
    for data in (
        {"envelope": envelope, "message": "also, please check the figures"},
        {"envelope": envelope | {"message": "also, please check the figures"}},
        {"envelope": envelope | {"note": "free text"}},
        {"envelope": {k: v for k, v in envelope.items() if k != "summary"}},
        {"message": "free text instead of an envelope"},
    ):
        with pytest.raises(EventRejected):
            emit(data)
    assert len(store.read_events(ORG, "w_agt08_writer")) == stored, "a rejected handoff must write nothing"


@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(text=st.text(alphabet=st.characters(blacklist_categories=("Cs",)), max_size=1200))
def test_FR_AGT_08_property_runner_text_changes_nothing_outside_the_envelope_summary(text: str) -> None:
    def signature(summary: str) -> tuple[list[tuple[Any, ...]], list[dict[str, Any]]]:
        with tempfile.TemporaryDirectory() as raw:
            outcome = UnitOutcome(success=True, summary=summary, provenance_ids=PROVENANCE)
            events, _result, _runner, _layout = _run(Path(raw), "w_agt08_prop", [("U1", "D1", [])], {"U1": outcome})
        others = [
            (e["type"], e["actor"], e["target"], e["summary"], json.dumps(e["data"], sort_keys=True))
            for e in events
            if e["type"] != "agent.handoff"
        ]
        return others, [h["data"]["envelope"] for h in _handoffs(events)]

    baseline_others, _ = signature("baseline")
    others, envelopes = signature(text)
    assert others == baseline_others, "runner text changed an event other than the handoff"
    assert len(envelopes) == 1
    assert envelopes[0]["summary"] == (text or "Finished unit U1.")[:1000]
    assert set(envelopes[0]) == ENVELOPE_FIELDS


# ---------------------------------------------------------------------------
# Static checks on the contracts
# ---------------------------------------------------------------------------


def test_FR_AGT_08_handoff_data_schema_is_registered_and_wraps_the_envelope_schema() -> None:
    registry = (CONTRACTS_DIR / "events/registry.yaml").read_text(encoding="utf-8")
    block = registry.split("  agent.handoff:\n", 1)[1].split("\n  agent.", 1)[0]
    assert "data_schema: events/data/agent.handoff.schema.json" in block
    schema = _doc(_data_schema_path("agent.handoff"))
    assert schema["required"] == ["envelope"] and set(schema["properties"]) == {"envelope"}
    assert schema["properties"]["envelope"] == {"$ref": "../../envelope.schema.json"}


def test_FR_AGT_08_envelope_schema_has_exactly_the_prd_fields() -> None:
    envelope = _doc(CONTRACTS_DIR / "envelope.schema.json")
    assert set(envelope["required"]) == ENVELOPE_FIELDS
    assert set(envelope["properties"]) == ENVELOPE_FIELDS


def test_FR_AGT_08_handoff_and_envelope_schemas_forbid_additional_properties_at_every_level() -> None:
    for schema_path in (_data_schema_path("agent.handoff"), CONTRACTS_DIR / "envelope.schema.json"):
        objects = [
            (path, node)
            for path, node in _schema_nodes(_doc(schema_path), schema_path)
            if node.get("type") == "object" or "properties" in node
        ]
        assert objects, f"{schema_path.name}: no object nodes found, the walker is broken"
        open_objects = [path or "(root)" for path, node in objects if node.get("additionalProperties") is not False]
        assert open_objects == [], f"{schema_path.name}: objects that allow extra properties: {open_objects}"
    # The walk reaches the envelope's nested object (artifact_ref) through $ref.
    paths = {p for p, _ in _schema_nodes(_doc(_data_schema_path("agent.handoff")), _data_schema_path("agent.handoff"))}
    assert "envelope.artifact_refs[]" in paths


def test_FR_AGT_08_every_agent_event_data_schema_forbids_additional_properties() -> None:
    types = _agent_event_types()
    assert "agent.handoff" in types and len(types) >= 14
    for event_type in types:
        path = _data_schema_path(event_type)
        open_objects = [
            p or "(root)"
            for p, node in _schema_nodes(_doc(path), path)
            if (node.get("type") == "object" or "properties" in node) and node.get("additionalProperties") is not False
        ]
        assert open_objects == [], f"{event_type}: objects that allow extra properties: {open_objects}"


def test_FR_AGT_08_free_text_fields_in_agent_event_data_are_the_pinned_inventory() -> None:
    found = {t: fields for t in _agent_event_types() if (fields := _free_text_fields(_data_schema_path(t)))}
    assert found == _KNOWN_FREE_TEXT_FIELDS, (
        "the free-text string fields in agent.* event data changed: a new one is a new route for agent-to-agent "
        f"free text (PRD 8.4); found {found}"
    )
