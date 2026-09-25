"""Shared fixtures and plain data factories for packages/policy acceptance tests (ticket P4-01,
PRD 10.4, docs/security/p4-policy-invariants.md).

No business logic lives here (root CLAUDE.md test-writer rule): every helper below either loads
a file unchanged or returns a literal dict shaped like the contract it names. The engine itself
(packages/policy/src/tilo_policy) does not exist yet; importing it is what makes these tests
fail for the right reason until the builder ships it (see API.md in this directory).

This directory has no __init__.py, so pytest's default "prepend" import mode puts it on
sys.path when collecting any test_*.py here, the same plain-module-import pattern
packages/providers/tests/conftest.py and tests/contracts/_lib.py use.
"""

from __future__ import annotations

import copy
import json
import pathlib
from typing import Any

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]


@pytest.fixture(scope="session")
def repo_root() -> pathlib.Path:
    return REPO_ROOT


def contracts_dir(repo_root: pathlib.Path) -> pathlib.Path:
    return repo_root / "contracts"


def load_json(path: pathlib.Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def list_fixtures(repo_root: pathlib.Path, relative: str) -> list[pathlib.Path]:
    """Every *.json directly under contracts/fixtures/<relative>/."""
    d = contracts_dir(repo_root) / "fixtures" / relative
    if not d.is_dir():
        return []
    return sorted(d.glob("*.json"))


@pytest.fixture()
def risk_table_path(repo_root: pathlib.Path) -> pathlib.Path:
    """PRD 10.4 tiers fixture: config/autonomy.yaml is not in the repo yet
    (spark-456/tilo#1), so tests always load an explicit fixture path rather than
    tilo_policy.load_risk_table()'s default."""
    return contracts_dir(repo_root) / "fixtures" / "policy.risk_tier_table" / "valid" / "prd_10_4_tiers.json"


@pytest.fixture()
def risk_table_invalid_paths(repo_root: pathlib.Path) -> list[pathlib.Path]:
    return list_fixtures(repo_root, "policy.risk_tier_table/invalid")


@pytest.fixture()
def crossref_valid_cases(repo_root: pathlib.Path) -> list[tuple[str, dict]]:
    return [(p.name, load_json(p)) for p in list_fixtures(repo_root, "outbox/crossref/valid")]


@pytest.fixture()
def crossref_invalid_cases(repo_root: pathlib.Path) -> list[tuple[str, dict]]:
    return [(p.name, load_json(p)) for p in list_fixtures(repo_root, "outbox/crossref/invalid")]


# ---------------------------------------------------------------------------
# Plain data factories (PRD 10.4 shapes). Every function returns a fresh, independent
# structure; callers mutate their own copy. Timestamps stay inside 2026-09-29, the same day
# used throughout contracts/fixtures/outbox/crossref, so "same UTC day" daily-cap tests need no
# date gymnastics.

OWNER = "u_owner"
WORLD = "w_village_basic"


def stamp(at: str, by: str = OWNER) -> dict:
    return {"by": by, "at": at}


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
    """A policy.schema.json record with every dimension defaulted for the L2 email-reply
    scenario used across FR-HIL-05 tests; override individual fields per test."""
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


def base_facts(**overrides: Any) -> dict:
    """Kwargs matching tilo_policy.SideEffectFacts's fields; tests pass this as **kwargs to the
    real dataclass once it exists (importing it is the point of these tests failing today)."""
    base = {
        "recipients": ("riya@example.com",),
        "known_recipients": ("riya@example.com",),
        "attachments": (),
        "external_share": False,
        "deletion": False,
        "money_or_legal": False,
        "safety_flags": False,
    }
    base.update(overrides)
    return base


def base_instruction(
    *,
    id_: str = "01JB5VQ0000000000000000131",
    type_: str = "channel.message_in",
    channel: str = "whatsapp",
    actor: str = OWNER,
    ts: str = "2026-09-29T09:41:50.000Z",
    destination: str = "thread-supplier-1",
    world_id: str = WORLD,
) -> dict:
    return {
        "id": id_,
        "type": type_,
        "actor": actor,
        "ts": ts,
        "world_id": world_id,
        "data": {"channel": channel, "destination": destination},
    }


def applied_entry(
    *,
    policy_id: str,
    at: str,
    instruction_id: str | None = None,
    credits: float = 0,
    outbox_id: str = "01JB5VQ0000000000000009999",
) -> dict:
    """One earlier `policy.applied` part, in the shape `decide`'s `applied` parameter takes
    (API.md "applied shape")."""
    return {
        "type": "policy.applied",
        "authz": {"by": "policy", "ref": policy_id, "at": at},
        "data": {
            "policy_id": policy_id,
            "gate_id": "G1",
            "outbox_id": outbox_id,
            "action_type": "post_status_update",
            "connector": "gmail",
            "destination": None,
            "district": "D1",
            "risk_tier": "T2",
            "level": "L3",
            "instruction_id": instruction_id,
            "undo_window_s": 60,
            "item": None,
        },
        "credits": credits,
    }


def deep_copy(value: Any) -> Any:
    return copy.deepcopy(value)
