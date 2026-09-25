"""Event validator: contracts/event.schema.json plus contracts/event.rules.md's EV-01..EV-14
(P0-09, D-11). A service must not import from scripts/ (root CLAUDE.md), so this is a fresh
implementation that agrees with scripts/contracts_events.py on every fixture in contracts/, not
a reuse of it.

`EventValidator.problems(event, state=None)` runs the checks that need only the event itself:
schema, EV-01 (registered type), EV-02 (data schema), EV-04, EV-05, EV-06, EV-08, EV-09, the
state-independent half of EV-13 (an event whose own district is not in its own vis list) and
the state-independent half of EV-14 (a delivery that left Tilo with no cause at all). The
stream- and layout-dependent rules -- EV-10 (seq/id, and the stream's world_id), EV-11 (cause
resolves), EV-12 (layout ids), the layout half of EV-13 (vis names a real district) and the
stream half of EV-14 (an email delivery's cause must be the matching `data.transfer` out, same
outbox_id and artifact, mirroring scripts/contracts_events.py's `_is_send_of`) -- need a
`WorldState` and are run in addition when one is passed; `WorldWriter` is what builds and
updates it.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

import jsonschema
import yaml
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

BASE_URI = "https://contracts.tilo.example/"
LAYOUT_ID = re.compile(r"^(A_[0-9A-Za-z_]+|[LDBGI][0-9]{1,4})$")


def _repo_root_from_here() -> Path:
    # services/harness/src/tilo_harness/validator.py -> repo root is 4 parents up.
    return Path(__file__).resolve().parents[4]


def _load_schemas(contracts_dir: Path) -> dict[str, dict[str, Any]]:
    """Every contracts/**/*.schema.json (excluding fixtures), keyed by its path under contracts/
    without the .schema.json suffix -- same keying as scripts/contracts_codegen.py so error
    messages and $refs line up."""
    schemas: dict[str, dict[str, Any]] = {}
    for path in sorted(contracts_dir.glob("**/*.schema.json")):
        rel = path.relative_to(contracts_dir)
        if "fixtures" in rel.parts:
            continue
        schemas[rel.as_posix().removesuffix(".schema.json")] = json.loads(path.read_text(encoding="utf-8"))
    return schemas


def _layout_ids(layout: dict[str, Any]) -> set[str]:
    semantic = layout["semantic"]
    ids = {agent["id"] for agent in semantic["agents"]}
    ids |= {item["id"] for key in ("islands", "gates") for item in semantic[key]}
    for level in semantic["levels"]:
        ids.add(level["id"])
        for district in level["districts"]:
            ids.add(district["id"])
            ids |= {building["id"] for building in district["buildings"]}
    return ids


def _is_send_of(cause: dict[str, Any] | None, delivered: dict[str, Any]) -> bool:
    """EV-14 (stream half): `cause` is the `data.transfer` out of the outbox entry `delivered`
    names, same artifact -- a fresh implementation, agreeing with
    scripts/contracts_events.py's `_is_send_of` on every fixture, not a reuse of it (root
    CLAUDE.md: a service must not import from scripts/)."""
    if cause is None or cause["type"] != "data.transfer":
        return False
    sent, data = cause["data"], delivered["data"]
    pinned = (data["artifact"]["artifact_id"], data["artifact"]["version"])
    artifact = sent["artifact"]
    return (
        sent["direction"] == "out"
        and sent["outbox_id"] == data["outbox_id"]
        and artifact is not None
        and (artifact["artifact_id"], artifact["version"]) == pinned
    )


class WorldState:
    """What the stream- and layout-dependent rules (EV-10..EV-14) need: the world's layout ids
    (EV-12, EV-13) plus, as events are observed, the last seq written and every earlier event of
    this world seen so far, keyed by id (EV-10 duplicates, EV-11 cause, EV-14's cause lookup).
    `world_id` is optional and set by `WorldWriter` (not a constructor argument -- only
    `WorldState(layout: dict)` is public, see the ticket brief); when set, EV-10 also checks that
    every event observed or checked belongs to this world. `WorldWriter` is the only code that
    observes events into this; its update method is not part of this ticket's public surface."""

    def __init__(self, layout: dict[str, Any]) -> None:
        self.layout = layout
        self.layout_ids = _layout_ids(layout)
        self.last_seq = 0
        self.world_id: str | None = None
        self.seen: dict[str, dict[str, Any]] = {}

    @property
    def seen_ids(self) -> set[str]:
        return set(self.seen)

    def observe(self, event: dict[str, Any]) -> None:
        self.last_seq = event["seq"]
        self.seen[event["id"]] = event


class EventValidator:
    """Runs contracts/event.schema.json, the registry (EV-01) and event.rules.md's rules a
    single event -- or a single event plus a `WorldState` -- can check."""

    def __init__(self, schemas: dict[str, dict[str, Any]], registry_data: dict[str, Any]) -> None:
        self._schemas = schemas
        self.registry = registry_data
        self.registry_types: dict[str, Any] = registry_data["types"]
        self._jsonschema_registry = Registry().with_resources(
            (schema["$id"], Resource.from_contents(schema, default_specification=DRAFT202012))
            for schema in schemas.values()
        )
        self._validator_cache: dict[str, jsonschema.protocols.Validator] = {}

    @classmethod
    def from_repo(cls, root: Path | None = None) -> EventValidator:
        root = root if root is not None else _repo_root_from_here()
        contracts_dir = root / "contracts"
        schemas = _load_schemas(contracts_dir)
        registry_data = yaml.safe_load((contracts_dir / "events/registry.yaml").read_text(encoding="utf-8"))
        return cls(schemas, registry_data)

    def _schema_errors(self, name: str, instance: object) -> list[str]:
        uri = f"{BASE_URI}{name}.schema.json"
        validator = self._validator_cache.get(uri)
        if validator is None:
            validator = jsonschema.Draft202012Validator({"$ref": uri}, registry=self._jsonschema_registry)
            self._validator_cache[uri] = validator
        return [
            f"{'/'.join(map(str, error.absolute_path)) or '(root)'}: {error.message}"
            for error in validator.iter_errors(instance)
        ]

    def problems(self, event: dict[str, Any], state: WorldState | None = None) -> list[str]:
        problems = [f"schema: {message}" for message in self._schema_errors("event", event)]
        if problems:
            return problems

        entry = self.registry_types.get(event["type"])
        if entry is None:
            return [f"EV-01: {event['type']} is not a registered event type"]

        problems += [
            f"EV-02: {message}" for message in self._schema_errors(f"events/data/{event['type']}", event["data"])
        ]
        authz, data = event["authz"], event["data"]
        if authz is not None and not entry["side_effect"]:
            problems.append(f"EV-05: {event['type']} is not a side effect and carries no authz")
        if authz is not None and entry["side_effect"] and authz["by"] not in entry["authz_by"]:
            problems.append(f"EV-04: authz.by {authz['by']} is not one of {entry['authz_by']}")
        if authz is not None and authz["by"] == "policy" and data.get("policy_id", authz["ref"]) != authz["ref"]:
            problems.append("EV-06: authz.ref must equal data.policy_id")
        if "default" in (data.get("answered_by"), data.get("decided_by")) and event["severity"] != "nudge":
            problems.append("EV-08: an answer applied by default is posted with severity nudge")
        if {"origin_cost", "lookup_cost", "saved"} <= data.keys() and not math.isclose(
            data["saved"], data["origin_cost"] - data["lookup_cost"], abs_tol=1e-9
        ):
            problems.append("EV-09: saved must equal origin_cost minus lookup_cost")
        if isinstance(event["vis"], list) and event["district"] is not None and event["district"] not in event["vis"]:
            problems.append("EV-13: vis must include the event's own district")
        if event["type"] == "artifact.delivered" and data.get("outbox_id") is not None and event["cause"] is None:
            problems.append("EV-14: a delivery that left Tilo is caused by its data.transfer out")

        if state is not None:
            problems += self._stream_problems(event, state)
        return problems

    def _stream_problems(self, event: dict[str, Any], state: WorldState) -> list[str]:
        problems = []
        if state.world_id is not None and event["world_id"] != state.world_id:
            problems.append(f"EV-10: world_id {event['world_id']} does not belong to this world ({state.world_id})")
        if event["seq"] != state.last_seq + 1:
            problems.append(f"EV-10: seq {event['seq']} is not last_seq+1 ({state.last_seq + 1})")
        if event["id"] in state.seen:
            problems.append(f"EV-10: id {event['id']} repeats an earlier event of this world")
        if event["cause"] is not None and event["cause"] not in state.seen:
            problems.append(f"EV-11: cause {event['cause']} is not an earlier event of this world")
        for field in ("level", "district", "actor", "target"):
            value = event[field]
            if isinstance(value, str) and LAYOUT_ID.match(value) and value not in state.layout_ids:
                problems.append(f"EV-12: {field} {value} is not in the world's layout")
        if isinstance(event["vis"], list) and not set(event["vis"]) <= state.layout_ids:
            problems.append("EV-13: vis names a district that is not in the world's layout")
        if event["type"] == "artifact.delivered" and event["data"].get("outbox_id") is not None:
            cause = state.seen.get(event["cause"] or "")
            if not _is_send_of(cause, event):
                problems.append(f"EV-14: cause is not the data.transfer out of outbox {event['data']['outbox_id']}")
        return problems
