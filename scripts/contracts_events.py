"""Event contract checks for `just contracts-check` (ticket P0-03, FR-WLD-03).

Registry-driven rules EV-01 to EV-15 from contracts/event.rules.md, applied to the event fixtures,
the fixture streams and contracts/events/registry.yaml itself. The harness validator (P0-09) runs
the same rules on every event before it is written. `validate(key, instance)` returns JSON Schema
error messages for contracts/<key>.schema.json.
"""

from __future__ import annotations

import json
import math
import pprint
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

Validate = Callable[[str, object], list[str]]
PLACEHOLDER = re.compile(r"\{([^{}]*)\}")
RULE_FILE = re.compile(r"^ev(\d{2})_")
LAYOUT_ID = re.compile(r"^(A_[0-9A-Za-z_]+|[LDBGI][0-9]{1,4})$")


def load_registry(contracts: Path) -> dict[str, Any]:
    return yaml.safe_load((contracts / "events/registry.yaml").read_text(encoding="utf-8"))


def side_effect_list(event_schema: dict[str, Any]) -> list[str]:
    """The side-effect types event.schema.json requires authz for (its root if, EV-03)."""
    return sorted(event_schema["if"]["properties"]["type"]["enum"])


def check_registry(
    contracts: Path, schemas: dict[str, dict], registry: dict[str, Any], validate: Validate
) -> list[str]:
    errors = [f"events/registry.yaml: {message}" for message in validate("events/registry", registry)]
    if errors:
        return errors
    types: dict[str, dict[str, Any]] = registry["types"]
    data_types = {key.removeprefix("events/data/") for key in schemas if key.startswith("events/data/")}
    errors += [f"events/data/{t}.schema.json names no registered type" for t in sorted(data_types - set(types))]
    for type_, entry in types.items():
        if [entry["family"], entry["verb"]] != type_.split(".", 1):
            errors.append(f"events/registry.yaml {type_}: family and verb must spell the type")
        if entry["data_schema"] != f"events/data/{type_}.schema.json" or type_ not in data_types:
            errors.append(
                f"events/registry.yaml {type_}: data_schema must be events/data/{type_}.schema.json and exist"
            )
        if entry["fixture"] != f"fixtures/events/valid/{type_}.json" or not (contracts / entry["fixture"]).is_file():
            errors.append(f"events/registry.yaml {type_}: fixture must be fixtures/events/valid/{type_}.json and exist")
        required = set(schemas.get(f"events/data/{type_}", {}).get("required", []))
        for field in ("story_template", "trace_row"):
            for name in PLACEHOLDER.findall(entry[field]):
                if name not in ("actor", "target") and not (name.startswith("data.") and name[5:] in required):
                    errors.append(
                        f"events/registry.yaml {type_}.{field}: {{{name}}} is not actor, target or data.<required>"
                    )
    side_effects = sorted(t for t, entry in types.items() if entry["side_effect"])
    if side_effects != side_effect_list(schemas["event"]):
        errors.append(f"event.schema.json EV-03 list must equal the registry's side-effect types {side_effects}")
    return errors


def event_problems(event: Any, registry: dict[str, Any], validate: Validate) -> list[str]:
    """Problems of one event, each starting with "schema" or its rule id; empty when valid."""
    problems = [f"schema: {message}" for message in validate("event", event)]
    if problems:
        return problems
    entry = registry["types"].get(event["type"])
    if entry is None:
        return [f"EV-01: {event['type']} is not registered"]
    problems += [f"EV-02: {message}" for message in validate(f"events/data/{event['type']}", event["data"])]
    authz, data = event["authz"], event["data"]
    if authz is not None and not entry["side_effect"]:
        problems.append(f"EV-05: {event['type']} is not a side effect and carries no authz")
    if authz is not None and entry["side_effect"] and authz["by"] not in entry["authz_by"]:
        problems.append(f"EV-04: authz.by {authz['by']} is not one of {entry['authz_by']}")
    if authz is not None and authz["by"] == "policy" and data.get("policy_id", authz["ref"]) != authz["ref"]:
        problems.append("EV-06: authz.ref must equal data.policy_id")
    if "default" in (data.get("answered_by"), data.get("decided_by")) and event["severity"] != "nudge":
        problems.append("EV-08: an answer applied by default is posted as a nudge")
    if {"origin_cost", "lookup_cost", "saved"} <= data.keys() and not math.isclose(
        data["saved"], data["origin_cost"] - data["lookup_cost"], abs_tol=1e-9
    ):
        problems.append("EV-09: saved must equal origin_cost minus lookup_cost")
    if isinstance(event["vis"], list) and event["district"] is not None and event["district"] not in event["vis"]:
        problems.append("EV-13: vis must include the district the event renders in")
    if event["type"] == "artifact.delivered" and data.get("outbox_id") is not None and event["cause"] is None:
        problems.append("EV-14: a delivery that left Tilo is caused by its data.transfer out")
    return problems


def layout_ids(layout: dict[str, Any]) -> set[str]:
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
    """EV-14: cause is the data.transfer out of the outbox entry the delivery names, same artifact."""
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


CONTINUES = {"artifact.versioned": "previous_version", "artifact.rolled_back": "restored_version"}


def _version_problems(event: dict[str, Any], recorded: set[tuple[str, int]], where: str) -> list[str]:
    """EV-15: artifact events name versions this world recorded; adds the version the event records."""
    type_, data = event["type"], event["data"]
    if not type_.startswith("artifact."):
        return []
    artifact_id, version = data["artifact"]["artifact_id"], data["artifact"]["version"]
    named = data[CONTINUES[type_]] if type_ in CONTINUES else version
    created = type_ == "artifact.created"
    bad = version != 1 if created else (artifact_id, named) not in recorded
    if created or type_ in CONTINUES:
        recorded.add((artifact_id, version))
    why = "not 1" if created else "which this world never recorded"
    return [f"EV-15: {where} {type_} names {artifact_id} version {named}, {why}"] if bad else []


def stream_problems(events: list[dict[str, Any]], known: set[str]) -> list[str]:
    """EV-10 to EV-15 over one stream that already passed event_problems."""
    problems = []
    if len({event["world_id"] for event in events}) != 1:
        problems.append("EV-10: a stream holds one world")
    seen: dict[str, dict[str, Any]] = {}
    recorded: set[tuple[str, int]] = set()
    for previous, event in zip([None, *events], events, strict=False):
        where = f"seq {event['seq']}"
        if previous is not None and event["seq"] <= previous["seq"]:
            problems.append(f"EV-10: {where} does not increase")
        if event["id"] in seen:
            problems.append(f"EV-10: {where} repeats id {event['id']}")
        if event["cause"] is not None and event["cause"] not in seen:
            problems.append(f"EV-11: {where} cause is not an earlier event of this world")
        seen[event["id"]] = event
        for field in ("level", "district", "actor", "target"):
            value = event[field]
            if isinstance(value, str) and LAYOUT_ID.match(value) and value not in known:
                problems.append(f"EV-12: {where} {field} {value} is not in the world's layout")
        if isinstance(event["vis"], list) and not set(event["vis"]) <= known:
            problems.append(f"EV-13: {where} vis names a district that is not in the world's layout")
        if (
            event["type"] == "artifact.delivered"
            and event["data"]["outbox_id"] is not None
            and not _is_send_of(seen.get(event["cause"] or ""), event)
        ):
            problems.append(f"EV-14: {where} cause is not the data.transfer out of outbox {event['data']['outbox_id']}")
        problems += _version_problems(event, recorded, where)
    return problems


def round_trip(event: dict[str, Any], module: Any, data_model: str) -> bool:
    """A valid event loads into the generated Event and data models and dumps back unchanged."""

    def same(model: Any, data: Any) -> bool:
        try:
            return model.model_validate(data).model_dump(mode="json", by_alias=True, exclude_unset=True) == data
        except ValueError:
            return False

    return same(module.Event, event) and same(getattr(module, data_model), event["data"])


def check_event_fixtures(
    contracts: Path, registry: dict[str, Any], validate: Validate, module: Any, data_model: Callable[[str], str]
) -> list[str]:
    """fixtures/events/{valid,invalid,registry/invalid} and fixtures/streams/{,invalid/}*.jsonl."""
    errors = []
    folder = contracts / "fixtures/events"
    for path in sorted((folder / "valid").glob("*.json")):
        event = json.loads(path.read_text(encoding="utf-8"))
        if problems := event_problems(event, registry, validate):
            errors.append(f"fixtures/events/valid/{path.name} fails: {problems[:3]}")
        elif path.stem.split("--")[0] != event["type"]:
            errors.append(f"fixtures/events/valid/{path.name} must be named <type>.json or <type>--<case>.json")
        elif not round_trip(event, module, data_model(event["type"])):
            errors.append(f"fixtures/events/valid/{path.name} does not round-trip through the generated models")
    for path in sorted((folder / "invalid").glob("*.json")):
        problems = event_problems(json.loads(path.read_text(encoding="utf-8")), registry, validate)
        if not any(p.startswith(("schema", "EV-02")) for p in problems):
            errors.append(f"fixtures/events/invalid/{path.name} must fail event.schema.json or its data schema")
    for path in sorted((folder / "registry/invalid").glob("*.json")):
        problems = event_problems(json.loads(path.read_text(encoding="utf-8")), registry, validate)
        match = RULE_FILE.match(path.name)
        rule = f"EV-{match.group(1)}" if match else "EV-??"
        if any(p.startswith(("schema", "EV-02")) for p in problems) or not any(p.startswith(rule) for p in problems):
            errors.append(f"fixtures/events/registry/invalid/{path.name} must pass the schemas and break {rule} only")
    layouts = [
        json.loads(p.read_text(encoding="utf-8")) for p in sorted((contracts / "fixtures/layout/valid").glob("*.json"))
    ]
    streams = contracts / "fixtures/streams"
    for path in sorted([*streams.glob("*.jsonl"), *streams.glob("invalid/*.jsonl")]):
        name = f"fixtures/streams/{path.relative_to(streams).as_posix()}"
        events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        bad = [(e.get("seq"), problems[:2]) for e in events if (problems := event_problems(e, registry, validate))]
        if bad or not events:
            errors.append(f"{name}: events fail {bad[:3]}")
            continue
        matches = [layout for layout in layouts if layout["world_id"] == events[0]["world_id"]]
        if len(matches) != 1:
            errors.append(f"{name}: needs exactly one fixtures/layout/valid/ layout for {events[0]['world_id']}")
            continue
        found = stream_problems(events, layout_ids(matches[0]))
        if path.parent.name == "invalid":
            match = RULE_FILE.match(path.name)
            rule = f"EV-{match.group(1)}" if match else "EV-??"
            if not found or any(not p.startswith(rule) for p in found):
                errors.append(f"{name} must break {rule} only, found {found[:3]}")
            continue
        errors += [f"{name}: {problem}" for problem in found]
        errors += [
            f"{name}: seq {e['seq']} does not round-trip"
            for e in events
            if not round_trip(e, module, data_model(e["type"]))
        ]
    return errors


def python_constants(registry: dict[str, Any], data_model: Callable[[str], str]) -> str:
    """Registry constants appended to the generated Python module."""
    types = list(registry["types"])
    side = [t for t in types if registry["types"][t]["side_effect"]]
    lines = [
        "",
        "",
        "# Event registry constants from contracts/events/registry.yaml (FR-WLD-03).",
        "from typing import Final  # noqa: E402",
        "",
        "type RegisteredEventType = Literal[",
        *(f"    {json.dumps(t)}," for t in types),
        "]",
        "",
        "EVENT_TYPES: Final[tuple[RegisteredEventType, ...]] = (",
        *(f"    {json.dumps(t)}," for t in types),
        ")",
        "",
        "SIDE_EFFECT_EVENT_TYPES: Final[frozenset[RegisteredEventType]] = frozenset(",
        "    {",
        *(f"        {json.dumps(t)}," for t in side),
        "    }",
        ")",
        "",
        "EVENT_DATA_MODELS: Final[dict[RegisteredEventType, type[BaseModel]]] = {",
        *(f"    {json.dumps(t)}: {data_model(t)}," for t in types),
        "}",
        "",
        "EVENT_REGISTRY: Final[EventRegistry] = EventRegistry.model_validate(",
        *("    " + line for line in pprint.pformat(registry, width=100, sort_dicts=False).splitlines()),
        ")",
        "",
    ]
    return "\n".join(lines)


def typescript_constants(registry: dict[str, Any], data_model: Callable[[str], str]) -> str:
    """Registry constants and the discriminated union on `type`, appended to the generated TypeScript."""
    types = list(registry["types"])
    side = [t for t in types if registry["types"][t]["side_effect"]]
    return "\n".join(
        [
            "",
            "/** Event registry constants from contracts/events/registry.yaml (FR-WLD-03). */",
            "export const EVENT_TYPES = [",
            *(f"  {json.dumps(t)}," for t in types),
            "] as const;",
            "export type RegisteredEventType = (typeof EVENT_TYPES)[number];",
            "",
            "export const SIDE_EFFECT_EVENT_TYPES: readonly RegisteredEventType[] = [",
            *(f"  {json.dumps(t)}," for t in side),
            "];",
            "",
            "/** The data payload of each registered type. */",
            "export interface EventDataByType {",
            *(f"  {json.dumps(t)}: {data_model(t)};" for t in types),
            "}",
            "",
            "/** A registered TiloEvent, discriminated on `type`. */",
            "export type RegisteredEvent = {",
            '  [T in RegisteredEventType]: Omit<Event, "type" | "data"> & { type: T; data: EventDataByType[T] };',
            "}[RegisteredEventType];",
            "",
            "export const EVENT_REGISTRY: EventRegistry & {",
            "  types: { readonly [T in RegisteredEventType]: EventRegistryEntry };",
            "} = " + json.dumps(registry, indent=2) + ";",
            "",
        ]
    )
