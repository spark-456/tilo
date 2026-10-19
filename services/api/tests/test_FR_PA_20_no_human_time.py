"""FR-PA-20 / decision D-4: "No human time tracking" and "no per-person human-time field exists in any contract".

These walk `contracts/` itself (the contracts win over prose), so they are guards, not route tests: they pass today and
must keep passing after the builder's change, which must not add a contract (a response shape that needs a schema is
"needs contract change", not a quiet addition) and must not add a human-time field to one.

Two readings of the row, and the one pinned here (BQ-PA20-4, `API_FR_PA_20.md` section 5): no schema names a field for
tracked human time (hours worked, time spent, man-days, a timesheet, billable time, person-minutes), and the only
schema that pairs a person with a measured time span is `attention.schema.json`, Tilo's own steering and review spans
that PRD 14.2 subtracts from time saved (MT-07, MT-08, FR-MTR-05). That schema predates FR-PA-20; the effort tracker
neither reads nor exposes it. A calendar entry's or a meeting's scheduled window is a plan, not tracked time.
"""

from __future__ import annotations

import json
import re
from typing import Any

from _api_lib import REPO_ROOT

CONTRACTS = REPO_ROOT / "contracts"
HUMAN_TIME_FIELD = re.compile(
    r"(^|_)(hours?|man_?hours?|man_?days?|timesheets?|billable|worked|time_?spent|spent_?time|human_?(time|minutes|hours?)"
    r"|person_?(minutes|hours?)|(effort|work|working|tracked|logged)_?(minutes|hours?|time))(_|$)",
    re.IGNORECASE,
)
PERSON_KEYS = {"user", "user_id", "owner", "person", "assignee", "by", "actor", "tester", "tester_id"}
MEASURED_SPAN = {"started_at", "ended_at"}
ATTENTION_ONLY = {"attention.schema.json"}  # PRD 14.2 steering and review spans (MT-07, MT-08)
PEOPLE_CONTRACTS = (
    "person", "meeting", "work_item", "pinboard_item", "mention", "calendar_entry", "plate", "minutes", "transcript",
    "team_lead", "meter",
)  # fmt: skip


def _schemas() -> dict[str, Any]:
    found = {
        str(p.relative_to(CONTRACTS)).replace("\\", "/"): json.loads(p.read_text("utf-8"))
        for p in CONTRACTS.rglob("*.schema.json")
    }
    assert len(found) > 50, "walked too few contracts; the check would be vacuous"
    return found


def _property_objects(node: Any) -> Any:
    """Every `properties` mapping at any depth."""
    if isinstance(node, dict):
        props = node.get("properties")
        if isinstance(props, dict):
            yield props
        for value in node.values():
            yield from _property_objects(value)
    elif isinstance(node, list):
        for item in node:
            yield from _property_objects(item)


def test_FR_PA_20_D_4_no_contract_has_a_field_for_tracked_human_time():
    hits = [
        (name, key)
        for name, doc in _schemas().items()
        for props in _property_objects(doc)
        for key in props
        if HUMAN_TIME_FIELD.search(key)
    ]
    assert hits == [], f"a contract names tracked human time: {hits}"


def test_FR_PA_20_D_4_the_only_schema_pairing_a_person_with_a_measured_span_is_the_attention_span():
    pairing = {
        name
        for name, doc in _schemas().items()
        for props in _property_objects(doc)
        if PERSON_KEYS & set(props) and MEASURED_SPAN <= set(props)
    }
    assert pairing == ATTENTION_ONLY, pairing  # a new one needs the architect, an ADR and an update of BQ-PA20-4


def test_FR_PA_20_D_4_the_people_contracts_hold_no_attention_or_effort_field():
    schemas = _schemas()
    leaks = []
    for stem in PEOPLE_CONTRACTS:
        for props in _property_objects(schemas[f"{stem}.schema.json"]):
            leaks += [
                (stem, key) for key in props if re.search(r"attention|effort|timesheet|time_?tracking", key, re.I)
            ]
    assert leaks == [], leaks


def test_FR_PA_20_the_attention_span_stays_ids_and_times_only_never_content():
    """MT-07: a span holds ids and times, so even the one schema with a person and a span carries no free text."""
    props = _schemas()["attention.schema.json"]["properties"]
    assert set(props) == {"id", "world_id", "run_id", "user", "kind", "started_at", "ended_at", "ref"}
    assert "additionalProperties" in _schemas()["attention.schema.json"]
    assert _schemas()["attention.schema.json"]["additionalProperties"] is False
