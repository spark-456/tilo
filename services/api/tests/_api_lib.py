"""Factories, schema validation and the principal override for services/api acceptance tests
(ticket ST-3a). Kept out of conftest.py under a package-unique module name: every test
directory in the repo has its own conftest.py, so `from conftest import ...` resolves to
whichever one was imported first when the whole suite runs together.
"""

from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass
from typing import Any

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

# tilo_api.deps is this ticket's own pinned addition (API_ST3a.md); it does not exist on the
# tests/P4-01 base this branch starts from, so this import fails at collection time with
# ModuleNotFoundError until the builder adds it. That failure is the "right reason" this
# directory's tests fail today.
from tilo_api import (
    app,  # noqa: F401  (imported for the `client` fixture below)
    deps,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]

OWNER = "u_owner"
WORLD = "w_village_basic"


# ---------------------------------------------------------------------------
# Contract schema validation (mirrors tests/contracts/_lib.py and
# packages/policy/tests/conftest.py's style; kept self-contained here since this ticket may not
# edit anything outside services/api/tests/).


def contracts_dir() -> pathlib.Path:
    return REPO_ROOT / "contracts"


def load_json(path: pathlib.Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def build_registry() -> Registry:
    resources: list[tuple[str, Resource]] = []
    for path in sorted(contracts_dir().glob("**/*.schema.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        uri = data.get("$id") or path.resolve().as_uri()
        resources.append((uri, Resource.from_contents(data, default_specification=DRAFT202012)))
    return Registry().with_resources(resources)


_REGISTRY = build_registry()


def validate_event(event: dict) -> None:
    """event.schema.json, plus its type's data schema (events/data/<type>.schema.json) -- the
    two checks EV-02 needs. Raises jsonschema.ValidationError with a clear path on failure."""
    event_schema = load_json(contracts_dir() / "event.schema.json")
    validator_cls = jsonschema.validators.validator_for(event_schema, default=jsonschema.Draft202012Validator)
    validator_cls(event_schema, registry=_REGISTRY).validate(event)

    data_schema_path = contracts_dir() / "events" / "data" / f"{event['type']}.schema.json"
    data_schema = load_json(data_schema_path)
    validator_cls = jsonschema.validators.validator_for(data_schema, default=jsonschema.Draft202012Validator)
    validator_cls(data_schema, registry=_REGISTRY).validate(event["data"])


# ---------------------------------------------------------------------------
# Plain data factories (policy.schema.json, event.schema.json shapes; API_ST3a.md's Principal,
# WorldRecord, DistrictRecord, Store). Every function returns a fresh, independent structure;
# callers mutate their own copy. Timestamps stay inside 2026-09-29 (the same day
# contracts/fixtures/outbox/crossref and packages/policy/tests use) so same-UTC-day comparisons
# need no date gymnastics.


def stamp(at: str, by: str = OWNER) -> dict:
    return {"by": by, "at": at}


def ulid(n: int) -> str:
    """A common.schema.json#/$defs/ulid-shaped string: `[0-7][0-9A-HJKMNP-TV-Z]{25}`. An
    all-digit suffix after a leading '0' satisfies it (every digit is valid Crockford base32)."""
    return f"01JB5VQ0{n:018d}"


def base_policy(
    *,
    id_: str = "pol_test",
    action_type: str = "send_email",
    level: str = "L2",
    owner: str = OWNER,
    connectors: tuple[str, ...] = ("gmail",),
    recipients: tuple[str, ...] = (),
    domains: tuple[str, ...] = ("example.com",),
    districts: tuple[str, ...] = (),
    per_day: int | None = 20,
    credits: float | None = 50,
    undo_window_s: int = 60,
    expiry: str | None = None,
    team_lead_domains: tuple[str, ...] = (),
    history: list[dict] | None = None,
    created_at: str = "2026-09-29T09:30:00.000Z",
) -> dict:
    """A policy.schema.json record; override individual fields per test. Mirrors
    packages/policy/tests/conftest.py's base_policy so fixtures built here would also be valid
    input to tilo_policy.decide's `policies` list."""
    hist = history if history is not None else [{"by": owner, "at": created_at, "change": "Created", "level": level}]
    return {
        "id": id_,
        "owner": owner,
        "action_type": action_type,
        "scope": {
            "connectors": list(connectors),
            "recipients": list(recipients),
            "domains": list(domains),
            "districts": list(districts),
        },
        "limits": {"per_day": per_day, "credits": credits},
        "conditions": {"no_attachments": True, "no_new_recipients": True, "no_safety_flags": True},
        "level": level,
        "undo_window_s": undo_window_s,
        "expiry": expiry,
        "notify_channel": "whatsapp",
        "team_lead_domains": list(team_lead_domains),
        "created_by": stamp(created_at, owner),
        "changed_by": None,
        "history": hist,
    }


def base_event(
    *,
    seq: int,
    type_: str,
    data: dict,
    world_id: str = WORLD,
    actor: str = OWNER,
    target: str | None = None,
    district: str | None = None,
    vis: Any = "all",
    authz: dict | None = None,
    summary: str = "test event",
    ts: str = "2026-09-29T09:30:00.000Z",
    cause: str | None = None,
) -> dict:
    """An event.schema.json record with every non-payload field defaulted."""
    return {
        "v": "1.0",
        "id": ulid(seq),
        "seq": seq,
        "ts": ts,
        "world_id": world_id,
        "run_id": "r_village_basic_1",
        "type": type_,
        "actor": actor,
        "target": target or world_id,
        "level": None,
        "district": district,
        "item": None,
        "severity": "info",
        "credits": 0,
        "summary": summary,
        "cause": cause,
        "vis": vis,
        "authz": authz,
        "data": data,
        "trace": {
            "model_role": None,
            "profile": None,
            "tokens_in": None,
            "tokens_out": None,
            "tool": None,
            "latency_ms": None,
            "archive_ref": None,
        },
    }


def make_district(name: str, summary: str) -> deps.DistrictRecord:
    return deps.DistrictRecord(name=name, summary=summary)


RUN_ID = "r_village_basic_1"  # matches base_event's own default run_id, so a fixture built from
# base_event() and one stamped by FakeEventWriter for the same world compare equal on run_id.


def make_world(
    *,
    owner: str = OWNER,
    owner_channels: tuple[str, ...] = ("web", "whatsapp", "email"),
    districts: dict[str, deps.DistrictRecord | None] | None = None,
    run_id: str = RUN_ID,
) -> deps.WorldRecord:
    return deps.WorldRecord(owner=owner, owner_channels=owner_channels, districts=districts or {}, run_id=run_id)


def make_store(
    *,
    worlds: dict[str, deps.WorldRecord] | None = None,
    policies: dict[str, dict] | None = None,
    policy_worlds: dict[str, str] | None = None,
    events: dict[str, list[dict]] | None = None,
) -> deps.Store:
    return deps.Store(
        worlds=worlds or {},
        policies=policies or {},
        policy_worlds=policy_worlds or {},
        events=events or {},
    )


def make_principal(
    *,
    user_id: str = OWNER,
    role: str = "owner",
    world_id: str | None = WORLD,
    domain: str | None = None,
    districts: tuple[str, ...] = (),
) -> deps.Principal:
    """world_id defaults to WORLD (this file's one fixture world) so every existing-owner-ish
    test is a member of the world it acts on without saying so; a test proving the round-1
    membership-oracle finding (ST-3a round 2) passes world_id=None or a different world's id
    explicitly."""
    return deps.Principal(user_id=user_id, role=role, world_id=world_id, domain=domain, districts=districts)


def as_principal(principal: deps.Principal):
    app.dependency_overrides[deps.get_current_principal] = lambda: principal


# ---------------------------------------------------------------------------
# FakeEventWriter: the in-memory stand-in for "the harness is the only writer of events" (PRD
# 15.3), installed in every test via the `writer` fixture (conftest.py). It is the one place
# id/seq/ts/run_id are stamped, on purpose (PI-18): tilo-api hands it an unstamped *part* and this
# double is what proves, by recording every call, that tilo-api never computed those fields
# itself (round-1 finding: tilo-api invented run_id = f"r_{world_id}" and rescanned
# store.events[world_id] for the next seq on every single event, O(n) per call inside an O(n)
# loop). A per-world counter here is O(1) per call instead.

_EVENT_PART_KEYS = (
    "type",
    "actor",
    "target",
    "level",
    "district",
    "item",
    "severity",
    "credits",
    "summary",
    "cause",
    "vis",
    "authz",
    "data",
)

_STAMPED_ONLY_KEYS = ("id", "seq", "ts", "run_id")

_ALLOWED_PART_KEYS = frozenset(_EVENT_PART_KEYS) | {"trace"}


@dataclass
class RecordedWrite:
    world_id: str
    part: dict  # exactly what tilo-api passed, before this double stamped anything


class FakeEventWriter:
    def __init__(self, store: deps.Store) -> None:
        self.store = store
        self.calls: list[RecordedWrite] = []
        self._counters: dict[str, int] = {}

    def append(self, world_id: str, part: dict) -> dict:
        self.calls.append(RecordedWrite(world_id=world_id, part=dict(part)))
        seq = self._counters.get(world_id, 0) + 1
        self._counters[world_id] = seq
        world = self.store.worlds.get(world_id)
        run_id = world.run_id if world is not None else f"r_{world_id[:44]}"
        trace = part.get(
            "trace",
            {
                "model_role": None,
                "profile": None,
                "tokens_in": None,
                "tokens_out": None,
                "tool": None,
                "latency_ms": None,
                "archive_ref": None,
            },
        )
        event = {
            "v": "1.0",
            "id": ulid(seq),
            "seq": seq,
            "ts": part.get("ts") or "2026-09-29T09:30:00.000Z",
            "world_id": world_id,
            "run_id": run_id,
            "type": part["type"],
            "actor": part.get("actor", "system"),
            "target": part.get("target", world_id),
            "level": part.get("level"),
            "district": part.get("district"),
            "item": part.get("item"),
            "severity": part.get("severity", "info"),
            "credits": part.get("credits", 0),
            "summary": (part.get("summary") or "")[:140] or "test event",
            "cause": part.get("cause"),
            "vis": part.get("vis", "all"),
            "authz": part.get("authz"),
            "data": part.get("data", {}),
            "trace": trace,
        }
        self.store.events.setdefault(world_id, []).append(event)
        return event


def make_writer(store: deps.Store) -> FakeEventWriter:
    return FakeEventWriter(store)


def assert_part_carries_no_stamped_fields(part: dict) -> None:
    """PI-18: the event part tilo-api hands to EventWriter.append carries none of the four fields
    only a writer may set, and no key outside the part shape API_ST3a.md pins."""
    for key in _STAMPED_ONLY_KEYS:
        assert key not in part, f"tilo-api must not stamp {key!r} itself; found it in the part it built"
    unexpected = set(part) - _ALLOWED_PART_KEYS
    assert not unexpected, f"event part carries unexpected keys: {unexpected}"
