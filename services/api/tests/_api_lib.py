"""Factories and the principal override for services/api acceptance tests (ticket FR-HIL-09/
SEC-07). Kept out of conftest.py under a package-unique module name: every test directory in the
repo has its own conftest.py, so `from conftest import ...` resolves to whichever one was imported
first when the whole suite runs together.

Split out of the ST-3a kill-switch-and-redaction branch (FR-HIL-07): only the factories the
roles/redaction tests (and the shared `client`/`store` fixtures in conftest.py) actually use are
kept here.
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

from tilo_api import app, deps

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


def make_world(
    *,
    owner: str = OWNER,
    districts: dict[str, deps.DistrictRecord | None] | None = None,
) -> deps.WorldRecord:
    return deps.WorldRecord(owner=owner, districts=districts or {})


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
    districts: tuple[str, ...] = (),
) -> deps.Principal:
    """world_id defaults to WORLD (this file's one fixture world) so every existing-owner-ish
    test is a member of the world it acts on without saying so; a test proving the membership-
    oracle finding passes world_id=None or a different world's id explicitly."""
    return deps.Principal(user_id=user_id, role=role, world_id=world_id, districts=districts)


def as_principal(principal: deps.Principal) -> None:
    app.dependency_overrides[deps.get_current_principal] = lambda: principal
