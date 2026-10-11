"""USER-MEETING-ROOM (ADR-0028, Proposed, 2026-10-08): the meeting room's five meeting.* types and plan.revised
(registry 1.3.0), meeting_room 1.0.0 and plan 1.1.0's revision unit. All additive: older plans, events and fixtures
stay valid (contracts-check validates every fixture; these tests pin the shapes the ADR's safety rests on)."""

from __future__ import annotations

import copy

import pytest
import yaml
from _lib import errors_for, list_fixtures, load_json, load_schema

TYPES = (
    "meeting.convened",
    "meeting.asked",
    "meeting.replied",
    "meeting.change_requested",
    "meeting.adjourned",
    "plan.revised",
)
BANNED = {"text", "body", "message", "reply", "recipients", "action_type", "risk_tier", "policy_id", "authz"}


def _version(value: str) -> tuple[int, ...]:
    return tuple(int(p) for p in value.split("."))


def _ref(name: str, key: str) -> dict:
    return {"$ref": f"https://contracts.tilo.example/{name}.schema.json#/$defs/{key}"}


@pytest.fixture(scope="module")
def entries(repo_root):
    raw = yaml.safe_load((repo_root / "contracts/events/registry.yaml").read_text(encoding="utf-8"))
    assert _version(raw["version"]) >= (1, 3, 0)
    return raw["types"]


@pytest.mark.parametrize("type_", TYPES)
def test_USER_MEETING_ROOM_each_type_is_registered_and_authorises_nothing(repo_root, registry, entries, type_):
    entry = entries[type_]
    assert entry["side_effect"] is False and "authz_by" not in entry
    event = load_json(repo_root / "contracts" / entry["fixture"])
    assert event["type"] == type_ and event["authz"] is None
    assert not errors_for(load_schema(repo_root, "event"), event, registry)
    data_schema = load_schema(repo_root, f"events/data/{type_}")
    assert not errors_for(data_schema, event["data"], registry)
    assert not BANNED & set(data_schema["properties"]), "words live in the archive; a room event carries no action"


def test_USER_MEETING_ROOM_a_proposal_names_what_changes_never_how(repo_root):
    proposal = load_schema(repo_root, "meeting_room")["$defs"]["proposal"]
    assert proposal["additionalProperties"] is False
    assert set(proposal["properties"]) == {"proposal_id", "units", "artifacts"}


def test_USER_MEETING_ROOM_request_bodies_cannot_widen_scope_or_set_caps(repo_root):
    defs = load_schema(repo_root, "meeting_room")["$defs"]
    assert set(defs["change_request"]["properties"]) == {"proposal_id", "text"}
    assert set(defs["convene_request"]["properties"]) == {"lead", "agents"}
    assert set(defs["ask_request"]["properties"]) == {"to", "text", "mode"}
    assert all(defs[k]["additionalProperties"] is False for k in ("change_request", "convene_request", "ask_request"))
    assert defs["as_role"]["enum"] == ["owner", "approver", "member"], "a Viewer never convenes"


@pytest.mark.parametrize(
    ("outcome", "change", "ok"),
    [
        ("failed", {"message_ref": None, "units": [], "artifacts": [], "proposal": None}, True),
        ("failed", {"units": [], "artifacts": [], "proposal": None}, False),
        ("declined", {"units": [], "artifacts": [], "proposal": None}, True),
        ("declined", {"message_ref": None, "units": [], "artifacts": [], "proposal": None}, False),
        ("answered", {"proposal": None}, True),
        ("answered", {"proposal": None, "units": []}, False),
        ("answered", {}, False),
        ("proposed_change", {}, True),
        ("proposed_change", {"proposal": None}, False),
    ],
)
def test_USER_MEETING_ROOM_replied_outcomes_bind_text_sources_and_proposal(repo_root, registry, outcome, change, ok):
    data = copy.deepcopy(load_json(repo_root / "contracts/fixtures/events/valid/meeting.replied.json")["data"])
    data.update(outcome=outcome, **change)
    found = errors_for(load_schema(repo_root, "events/data/meeting.replied"), data, registry)
    assert (not found) is ok, [e.message for e in found]


def test_USER_MEETING_ROOM_plan_revision_unit_is_both_fields_or_neither(repo_root, registry):
    plan = load_schema(repo_root, "plan")
    assert _version(plan["x-version"]) >= (1, 1, 0)
    unit = plan["$defs"]["unit"]
    assert unit["dependentRequired"] == {"revises": ["change"], "change": ["revises"]}
    assert "revises" not in unit["required"] and "change" not in unit["required"], "older plans stay valid"
    names = {p.name for p in list_fixtures(repo_root, "plan", "invalid")}
    assert {"revision_unit_without_change.json", "change_without_revises.json"} <= names
    revised = load_json(repo_root / "contracts/fixtures/plan/valid/revision_unit.json")
    assert not errors_for(plan, revised, registry)


@pytest.mark.parametrize(
    ("key", "body", "ok"),
    [
        ("change_request", {"proposal_id": "01JB5VQ00000000000000P0001", "text": "Redo it"}, True),
        ("change_request", {"proposal_id": "01JB5VQ00000000000000P0001", "text": "Redo it", "units": ["U1"]}, False),
        ("convene_request", {"lead": "A_l1", "agents": ["A_s1"], "credit_cap": 500}, False),
        ("ask_request", {"to": "A_l1", "text": "Why?", "mode": "thinking"}, True),
        ("ask_request", {"to": "u_owner", "text": "Why?", "mode": "quick"}, False),
    ],
)
def test_USER_MEETING_ROOM_request_bodies_validate(repo_root, registry, key, body, ok):
    found = errors_for(_ref("meeting_room", key), body, registry)
    assert (not found) is ok, [e.message for e in found]
