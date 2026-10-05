"""Event validator: contracts/event.schema.json plus contracts/event.rules.md's EV-01..EV-15
(P0-09, D-11; EV-15, artifact versions the world recorded, is a stream rule like EV-10..EV-14).
A service must not import from scripts/ (root CLAUDE.md), so this is a fresh implementation
that agrees with scripts/contracts_events.py on every fixture in contracts/, not a reuse of it.

`EventValidator.problems(event, state=None)` runs the checks that need only the event itself:
finiteness and int64 range, D-11 UTF-8 round-trip (every string value and dict key, at any
nesting depth), schema, EV-01 (registered type), EV-02 (data schema), EV-04, EV-05, EV-06,
EV-08, EV-09, the state-independent half of EV-13 (an event whose own district is not in its own
vis list) and the state-independent half of EV-14 (a delivery that left Tilo with no cause at
all). The stream- and layout-dependent rules -- EV-10 (seq/id, and the stream's world_id), EV-11
(cause resolves), EV-12 (layout ids), the layout half of EV-13 (vis names a real district) and
the stream half of EV-14 (an email delivery's cause must be the matching `data.transfer` out,
same outbox_id and artifact, mirroring scripts/contracts_events.py's `_is_send_of`) -- need a
`WorldState` and are run in addition when one is passed; `WorldWriter` is what builds and
updates it.
"""

from __future__ import annotations

import functools
import json
import math
import re
from pathlib import Path
from typing import Any

import jsonschema
import yaml
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

LAYOUT_ID = re.compile(r"^(A_[0-9A-Za-z_]+|[LDBGI][0-9]{1,4})$")

# int64 range (Firestore's integer type, and every JSON consumer's safe integer ceiling for a
# whole number): anything outside this is rejected below, same as a non-finite float.
_INT64_MIN = -(2**63)
_INT64_MAX = 2**63 - 1


def _is_strict_python_int(_checker: Any, instance: Any) -> bool:
    """JSON Schema's "integer" type is defined over JSON numbers ("a JSON number with a zero
    fractional part"), so `jsonschema`'s stock Draft 2020-12 type checker deliberately accepts a
    `float` such as `2.0` for `type: "integer"`
    (`is_integer(checker, instance) or isinstance(instance, float) and instance.is_integer()`
    in `jsonschema._types`) -- that is spec-correct for JSON Schema in general, but wrong for
    this harness: `seq` (and every other "integer" field: `trace.tokens_in`, `.tokens_out`,
    `.latency_ms`, and the "integer" fields inside `events/data/*.schema.json`) round-trips
    through `MemoryStore` (which keeps the Python object as-is: seq 2.0 stored and compared with
    `==`, silently equal to 2) and `FirestoreStore` (`f"{event['seq']:08d}"`, which raises a raw
    `ValueError` for a float instead of the intended `EventRejected`) with different behaviour
    per store. This narrows "integer" to a real Python `int` -- excluding `bool`, which is an
    `int` subclass but never a legitimate value for any "integer"-typed field here -- so a float
    seq (or any other float given where an "integer" is declared) fails schema validation with a
    "schema: ..." problem and never reaches either store."""
    return isinstance(instance, int) and not isinstance(instance, bool)


# Same Draft 2020-12 validator class `jsonschema.Draft202012Validator` builds against, but with
# "integer" redefined by `_is_strict_python_int` above instead of the spec's JSON-number-based
# check -- built once at import time since a `TypeChecker`/validator class is immutable data.
_StrictIntValidator = jsonschema.validators.extend(
    jsonschema.Draft202012Validator,
    type_checker=jsonschema.Draft202012Validator.TYPE_CHECKER.redefine("integer", _is_strict_python_int),
)


def _segment(key: str) -> str:
    """A problem-path segment that is always valid UTF-8, so a message never carries the bad text it reports."""
    return key.encode("utf-8", "backslashreplace").decode("utf-8")


_MAX_DEPTH = 64
_MAX_VALUES = 100_000
_JSON_SCALARS = (str, int, float, bool, type(None))


def _json_tree_problems(event: Any) -> list[str]:
    """The event must be a JSON tree -- dict with str keys, list, str, int, float, bool or None,
    by exact type -- at most _MAX_DEPTH deep and _MAX_VALUES values. Checked iteratively before
    anything formats a value, so a Python-built event (tuple, Decimal, int key, cycle, very deep
    nesting, an object whose __str__ raises) is rejected instead of crashing the walkers below."""
    if type(event) is not dict:
        return ["schema: (root): an event is a JSON object"]
    too_many = [f"schema: (root): more than {_MAX_VALUES} values"]
    stack: list[tuple[Any, str, int]] = [(event, "", 0)]
    count = 1
    while stack:
        value, path, depth = stack.pop()
        label = path or "(root)"
        if depth > _MAX_DEPTH:
            return [f"schema: {label}: nested deeper than {_MAX_DEPTH} levels"]
        kind = type(value)
        if kind is dict:
            # Each child is counted against the cap before it is pushed, so a very wide
            # container is rejected without first stacking every one of its children.
            for key, child in value.items():
                if type(key) is not str:
                    return [f"schema: {label}: a key is not a string"]
                count += 1
                if count > _MAX_VALUES:
                    return too_many
                stack.append((child, f"{path}/{_segment(key)}" if path else _segment(key), depth + 1))
        elif kind is list:
            for index, child in enumerate(value):
                count += 1
                if count > _MAX_VALUES:
                    return too_many
                stack.append((child, f"{path}/{index}" if path else str(index), depth + 1))
        elif kind not in _JSON_SCALARS:
            return [f"schema: {label}: not a JSON value"]
    return []


def _finiteness_problems(value: Any, path: str = "") -> list[str]:
    """`jsonschema`'s `minimum`/`maximum` checks use Python `<`/`>`, which are False for both
    operands of any comparison against NaN, and JSON Schema's `number`
    type has no finiteness or range constraint of its own -- so `event.schema.json`'s
    `minimum: 0` on `credits` (and every other bare `number`/`integer` in the event) never
    rejects `float("nan")`, `float("inf")` or an integer outside what every store and every JSON
    consumer can round-trip. This walks the whole event (data included) and rejects any
    non-finite float or out-of-int64-range integer, reported with the same "schema: ..." prefix
    a `jsonschema` failure gets, so a caller filtering on that prefix sees both."""
    problems: list[str] = []
    label = path or "(root)"
    if isinstance(value, bool):
        return problems
    if isinstance(value, float):
        if not math.isfinite(value):
            problems.append(f"schema: {label}: {value!r} is not a finite JSON number")
    elif isinstance(value, int):
        if not (_INT64_MIN <= value <= _INT64_MAX):
            # bit_length, not repr: repr of an int past 4300 digits raises ValueError.
            problems.append(f"schema: {label}: a {value.bit_length()}-bit integer is outside the int64 range")
    elif isinstance(value, dict):
        for key, child in value.items():
            problems += _finiteness_problems(child, f"{path}/{_segment(key)}" if path else _segment(key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            problems += _finiteness_problems(child, f"{path}/{index}" if path else str(index))
    return problems


def _utf8_problems(value: Any, path: str = "") -> list[str]:
    """D-11: a string that cannot round-trip through UTF-8 -- e.g. a lone UTF-16 surrogate such
    as `json.loads('"a\\ud800"')` produces -- must never reach a store. JSON Schema's `string`
    type has no such constraint (jsonschema validates against the already-parsed Python object,
    not the wire bytes), so a lone surrogate sails through every "string"/"pattern"/"maxLength"
    check and would only fail later, differently, in each store (`MemoryStore` keeps it as-is;
    `FirestoreStore` raises a raw encoding error from the gRPC layer instead of `EventRejected`).
    This walks the whole event -- values and dict keys, at any nesting depth -- and rejects any
    string that does not survive `.encode("utf-8").decode("utf-8")`, reported with the same
    "schema: ..." prefix a `jsonschema` failure gets, so a caller filtering on that prefix sees
    every case (summary, a data string value, a data key, a nested item.label, ...) alike. A
    valid non-ASCII string (accented Latin, CJK, emoji) round-trips cleanly and is unaffected."""
    problems: list[str] = []
    label = path or "(root)"
    if isinstance(value, str):
        try:
            value.encode("utf-8").decode("utf-8")
        except UnicodeError:
            problems.append(f"schema: {label}: string is not valid, UTF-8-round-trippable text")
    elif isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}/{_segment(key)}" if path else _segment(key)
            if isinstance(key, str):
                try:
                    key.encode("utf-8").decode("utf-8")
                except UnicodeError:
                    problems.append(f"schema: {child_path}: key is not valid, UTF-8-round-trippable text")
            problems += _utf8_problems(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            problems += _utf8_problems(child, f"{path}/{index}" if path else str(index))
    return problems


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


_PROBLEM_CAP = 500
_CUT = " ...[cut]"


def _capped(problem: str) -> str:
    """A problem string of at most _PROBLEM_CAP characters; a longer one (jsonschema can echo a
    large value back) is cut and marked."""
    return problem if len(problem) <= _PROBLEM_CAP else problem[: _PROBLEM_CAP - len(_CUT)] + _CUT


@functools.cache
def repo_validator() -> EventValidator:
    """One shared validator over this repo's contracts/ (schemas are read once per process)."""
    return EventValidator.from_repo()


class EventRejected(Exception):
    """Raised by `WorldWriter.emit`/`.append` when an event fails `EventValidator.problems`;
    nothing is written to any store. Public per the ticket brief at `tilo_harness.validator`
    (re-exported from `tilo_harness.writer`, where it also lives, for callers written against
    that path)."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems) or "event rejected")
        self.problems = problems


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
        self.versions: dict[str, int] = {}  # artifact id -> the highest version this world recorded (EV-15)

    @property
    def seen_ids(self) -> set[str]:
        return set(self.seen)

    def observe(self, event: dict[str, Any]) -> None:
        self.last_seq = event["seq"]
        self.seen[event["id"]] = event
        if event["type"] in _RECORDS:
            ref = event["data"]["artifact"]
            self.versions[ref["artifact_id"]] = max(self.versions.get(ref["artifact_id"], 0), ref["version"])


_CONTINUES = {"artifact.versioned": "previous_version", "artifact.rolled_back": "restored_version"}
_RECORDS = ("artifact.created", *_CONTINUES)  # the artifact events that record a version


def _version_problem(event: dict[str, Any], versions: dict[str, int]) -> str | None:
    """EV-15: an artifact event names a version this world recorded; created starts an id at 1, versioned and
    rolled_back continue a recorded version and record the next one (AR-02). A fresh implementation that agrees with
    scripts/contracts_events.py's `_version_problems` on every fixture, not a reuse of it."""
    type_, data = event["type"], event["data"]
    if not type_.startswith("artifact."):
        return None
    art, version = data["artifact"]["artifact_id"], data["artifact"]["version"]
    top = versions.get(art, 0)
    if type_ == "artifact.created":
        why = "" if (version, top) == (1, 0) else "created starts an id this world never recorded at version 1"
    elif type_ in _CONTINUES:
        ok = 1 <= data[_CONTINUES[type_]] <= top and version == top + 1
        why = "" if ok else f"it must continue a recorded version as version {top + 1}"
    else:
        why = "" if 1 <= version <= top else "this world never recorded it"
    return f"EV-15: {type_} names version {version} of {art}; {why}" if why else None


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
        # This must NOT be `_StrictIntValidator({"$ref": uri}, ...)`. `jsonschema`'s
        # `$ref`/`descend` handling re-derives the validator class for whatever
        # the ref resolves to via `validators.validator_for(schema, default=cls)`, which reads
        # that schema's *own* `$schema` keyword and only falls back to `cls` (our strict
        # `_StrictIntValidator`) when the target has none. `event.schema.json` and every
        # `events/data/*.schema.json` declare their own top-level `$schema`
        # (`https://json-schema.org/draft/2020-12/schema`), so a `{"$ref": uri}` wrapper
        # resolving straight to one of those roots silently evolves back to the plain
        # `jsonschema.Draft202012Validator` -- our redefined "integer" type checker never runs,
        # and a float `seq` like `2.0` passes. Fragment refs *within* a schema (this harness's
        # only other use of `$ref`, e.g. `common.schema.json#/$defs/ulid`) resolve to a bare
        # subschema with no `$schema` of its own, so those keep the strict checker -- only a
        # ref straight to another schema *file's root* loses it. Instantiating the validator
        # directly on the already-loaded schema object (no `$ref` indirection for the entry
        # point) sidesteps this evolve() entirely, while `registry=` still resolves every
        # fragment ref inside it against the same shared schema set.
        schema = self._schemas[name]
        validator = self._validator_cache.get(name)
        if validator is None:
            validator = _StrictIntValidator(schema, registry=self._jsonschema_registry)
            self._validator_cache[name] = validator
        return [
            f"{'/'.join(map(str, error.absolute_path)) or '(root)'}: {error.message}"
            for error in validator.iter_errors(instance)
        ]

    def problems(self, event: dict[str, Any], state: WorldState | None = None) -> list[str]:
        tree_problems = _json_tree_problems(event)
        if tree_problems:
            return tree_problems
        try:
            return [_capped(problem) for problem in self._problems(event, state)]
        except Exception as error:  # fail closed: a validator crash rejects the event, it never escapes
            return [f"schema: (root): the event could not be validated ({type(error).__name__})"]

    def contract_problems(self, name: str, instance: object) -> list[str]:
        """Every violation of contracts/<name>.schema.json (e.g. "plan", "layout", "skill",
        "agents") by `instance`, each capped like `problems`."""
        try:
            return [_capped(problem) for problem in self._schema_errors(name, instance)]
        except Exception as error:  # fail closed, same as problems()
            return [f"(root): could not be validated against {name} ({type(error).__name__})"]

    def _problems(self, event: dict[str, Any], state: WorldState | None) -> list[str]:
        finiteness_problems = _finiteness_problems(event)
        if finiteness_problems:
            return finiteness_problems

        utf8_problems = _utf8_problems(event)
        if utf8_problems:
            return utf8_problems

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
        if (version_problem := _version_problem(event, state.versions)) is not None:
            problems.append(version_problem)
        return problems
