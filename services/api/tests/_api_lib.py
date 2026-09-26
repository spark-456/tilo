"""Factories and the principal/event-writer overrides for services/api acceptance tests (ticket
FR-HIL-09/SEC-07). Kept out of conftest.py under a package-unique module name: every test
directory in the repo has its own conftest.py, so `from conftest import ...` resolves to whichever
one was imported first when the whole suite runs together.

Split out of the ST-3a kill-switch-and-redaction branch (FR-HIL-07): only the factories and
doubles the roles/redaction tests (and the shared `client`/`store`/`writer` fixtures in
conftest.py) actually use are kept here.
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

from tilo_api import (
    app,  # noqa: F401  (imported for the `client` fixture below)
    deps,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]

OWNER = "u_owner"
WORLD = "w_village_basic"


# ---------------------------------------------------------------------------
# Contract fixture loading (mirrors tests/contracts/_lib.py's style; kept self-contained here
# since this ticket may not edit anything outside services/api/tests/).


def contracts_dir() -> pathlib.Path:
    return REPO_ROOT / "contracts"


def load_json(path: pathlib.Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Plain data factories (event.schema.json shapes; API_ST3a.md's Principal, WorldRecord,
# DistrictRecord, Store). Every function returns a fresh, independent structure; callers mutate
# their own copy. Timestamps stay inside 2026-09-29 (the same day contracts/fixtures/outbox/crossref
# and packages/policy/tests use) so same-UTC-day comparisons need no date gymnastics.


def ulid(n: int) -> str:
    """A common.schema.json#/$defs/ulid-shaped string: `[0-7][0-9A-HJKMNP-TV-Z]{25}`. An
    all-digit suffix after a leading '0' satisfies it (every digit is valid Crockford base32)."""
    return f"01JB5VQ0{n:018d}"


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
    districts: dict[str, deps.DistrictRecord | None] | None = None,
    run_id: str = RUN_ID,
) -> deps.WorldRecord:
    return deps.WorldRecord(owner=owner, districts=districts or {}, run_id=run_id)


def make_store(
    *,
    worlds: dict[str, deps.WorldRecord] | None = None,
    events: dict[str, list[dict]] | None = None,
) -> deps.Store:
    return deps.Store(worlds=worlds or {}, events=events or {})


def make_principal(
    *,
    user_id: str = OWNER,
    role: deps.Role = "owner",
    world_id: str | None = WORLD,
    domain: str | None = None,
    districts: tuple[str, ...] = (),
) -> deps.Principal:
    """world_id defaults to WORLD (this file's one fixture world) so every existing-owner-ish
    test is a member of the world it acts on without saying so; a test proving the membership-
    oracle finding passes world_id=None or a different world's id explicitly."""
    return deps.Principal(user_id=user_id, role=role, world_id=world_id, domain=domain, districts=districts)


def as_principal(principal: deps.Principal) -> None:
    app.dependency_overrides[deps.get_current_principal] = lambda: principal


# ---------------------------------------------------------------------------
# FakeEventWriter: the in-memory stand-in for "the harness is the only writer of events" (PRD
# 15.3), installed in every test via the `writer` fixture (conftest.py). The redaction routes
# never call it themselves, but the shared `client` fixture wires it up for every test regardless.


class FakeEventWriter:
    def __init__(self, store: deps.Store) -> None:
        self.store = store
        self._counters: dict[str, int] = {}

    def append(self, world_id: str, part: dict) -> dict:
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
