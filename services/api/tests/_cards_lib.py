"""Shared helpers and plain data factories for ticket ST-3b acceptance tests (services/api,
package tilo_api, module family tilo_api.cards — FR-HIL-01, FR-HIL-02, PRD 10.2, 10.3, 9.5).

No business logic lives here (root CLAUDE.md test-writer rule): every helper either loads a
fixture file unchanged, mutates a copy of one, or is a plain recording test double (FakeClock,
FakeEventWriter). The CardStore itself (services/api/src/tilo_api/cards.py) does not exist yet;
importing it is what makes these tests fail for the right reason until a builder ships it (see
API_ST3b.md in this directory).

Deliberately self-contained: this ticket must not import services/api/tests/_api_lib.py or any
other test directory's conftest.py (root worktree rule — those files belong to parallel
tickets), so the small schema-loading/registry helpers below are an independent copy of the
pattern tests/contracts/_lib.py already uses, not a second source of truth for the schemas
themselves (they still read straight from contracts/).

This directory has no __init__.py, so pytest's default "prepend" import mode puts it on
sys.path when collecting any test_*.py here, the same plain-module-import pattern
packages/policy/tests/_policy_lib.py and tests/contracts/_lib.py use.
"""

from __future__ import annotations

import copy
import datetime as dt
import json
import pathlib
from typing import Any

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]

_TS_FMT = "%Y-%m-%dT%H:%M:%S.%fZ"

# ---------------------------------------------------------------------------
# Contracts: schema loading, $ref registry, fixtures.


def contracts_dir(repo_root: pathlib.Path = REPO_ROOT) -> pathlib.Path:
    return repo_root / "contracts"


def load_json(path: pathlib.Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_card_schema(repo_root: pathlib.Path = REPO_ROOT) -> dict[str, Any]:
    return load_json(contracts_dir(repo_root) / "card.schema.json")


def build_registry(repo_root: pathlib.Path = REPO_ROOT) -> Registry:
    """A referencing.Registry with every *.schema.json under contracts/ loaded, keyed by its
    declared $id, so card.schema.json's $refs into common.schema.json resolve."""
    resources: list[tuple[str, Resource]] = []
    for path in sorted(contracts_dir(repo_root).glob("**/*.schema.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        uri = data.get("$id") or path.resolve().as_uri()
        resources.append((uri, Resource.from_contents(data, default_specification=DRAFT202012)))
    return Registry().with_resources(resources)


def card_errors(instance: Any, registry: Registry, repo_root: pathlib.Path = REPO_ROOT) -> list[str]:
    """jsonschema validation error messages for `instance` against card.schema.json; empty when
    valid. CardStore.submit's own SubmitResult.errors is expected to be exactly this shape
    (strings), so a builder can lean on jsonschema directly."""
    schema = load_card_schema(repo_root)
    cls = jsonschema.validators.validator_for(schema, default=jsonschema.Draft202012Validator)
    cls.check_schema(schema)
    validator = cls(schema, registry=registry)
    return [e.message for e in validator.iter_errors(instance)]


def fixtures_dir(kind: str, repo_root: pathlib.Path = REPO_ROOT) -> pathlib.Path:
    assert kind in ("valid", "invalid")
    return contracts_dir(repo_root) / "fixtures" / "card" / kind


def list_card_fixtures(kind: str, repo_root: pathlib.Path = REPO_ROOT) -> list[pathlib.Path]:
    d = fixtures_dir(kind, repo_root)
    if not d.is_dir():
        return []
    return sorted(p for p in d.glob("*.json"))


def valid_card_fixture_cases(repo_root: pathlib.Path = REPO_ROOT) -> list[tuple[str, dict]]:
    return [(p.stem, load_json(p)) for p in list_card_fixtures("valid", repo_root)]


def invalid_card_fixture_cases(repo_root: pathlib.Path = REPO_ROOT) -> list[tuple[str, dict]]:
    return [(p.stem, load_json(p)) for p in list_card_fixtures("invalid", repo_root)]


def load_valid_card(name: str, repo_root: pathlib.Path = REPO_ROOT) -> dict:
    """Loads contracts/fixtures/card/valid/<name>.json by stem, e.g. "gate_send_reply"."""
    path = fixtures_dir("valid", repo_root) / f"{name}.json"
    assert path.is_file(), f"missing fixture {path}"
    return load_json(path)


# ---------------------------------------------------------------------------
# Timestamp helpers (contracts/common.schema.json#/$defs/timestamp: RFC 3339, ms precision, Z).


def add_seconds(ts: str, seconds: float) -> str:
    parsed = dt.datetime.strptime(ts, _TS_FMT).replace(tzinfo=dt.UTC)
    moved = parsed + dt.timedelta(seconds=seconds)
    millis = moved.microsecond // 1000
    return moved.strftime("%Y-%m-%dT%H:%M:%S.") + f"{millis:03d}Z"


# ---------------------------------------------------------------------------
# Plain card mutation helpers (deep copy in, deep copy out; callers own the result).


def clone_card(
    card: dict,
    *,
    id_: str | None = None,
    created_at: str | None = None,
    building: str | None = None,
) -> dict:
    mutated = copy.deepcopy(card)
    if id_ is not None:
        mutated["id"] = id_
    if created_at is not None:
        mutated["created_at"] = created_at
    if building is not None:
        mutated["header"]["building"] = building
    return mutated


def new_ulid(seed: str) -> str:
    """A schema-valid ULID (common.schema.json#/$defs/ulid: Crockford base32, 26 chars,
    first char 0-7) built deterministically from a short seed, for tests that just need
    distinct, valid-shaped ids and don't care about real ULID monotonicity."""
    alphabet = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
    digest = 0
    for ch in seed:
        digest = (digest * 131 + ord(ch)) % (32**25)
    body = []
    n = digest
    for _ in range(25):
        body.append(alphabet[n % 32])
        n //= 32
    return "0" + "".join(reversed(body))


# ---------------------------------------------------------------------------
# Test doubles (plain recorders; no business logic). CardStore's Clock/EventWriter Protocols
# are structural, so these satisfy them without importing tilo_api.cards.


def principal(role: str = "owner", user_id: str = "u_owner", world_id: str | None = "w_01", districts=()):
    """A verified-principal test double (deps.Principal), the only source of who answers."""
    from tilo_api.deps import Principal

    return Principal(user_id=user_id, role=role, world_id=world_id, districts=tuple(districts))


OWNER_P = principal()


def answer_client(store, who, *, from_channels: bool = False):
    """A TestClient over build_router(store) with `who` as the verified principal and, when
    from_channels, the request authenticated as tilo-channels."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from tilo_api import cards, deps

    app = FastAPI()
    app.include_router(cards.build_router(store))
    app.dependency_overrides[deps.get_current_principal] = lambda: who
    app.dependency_overrides[cards.get_channels_caller] = lambda: from_channels
    return TestClient(app)


class FakeClock:
    def __init__(self, start: str) -> None:
        self._now = start

    def now(self) -> str:
        return self._now

    def set(self, ts: str) -> None:
        self._now = ts

    def advance(self, seconds: float) -> None:
        self._now = add_seconds(self._now, seconds)


class FakeEventWriter:
    def __init__(self) -> None:
        self.parts: list[dict] = []

    def write(self, part: dict) -> None:
        self.parts.append(part)

    def of_type(self, type_: str) -> list[dict]:
        return [p for p in self.parts if p.get("type") == type_]
