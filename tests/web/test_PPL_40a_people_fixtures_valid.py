"""PPL-40a / FR-PA-03: the fixtures behind S-26 Meetings and S-27 My plate are contract-valid.

The JSON under apps/web/src/people/fixtures/ is what the two screens read (nothing else). Every
record validates against its schema in contracts/, and the files agree with each other: one
signed-in person, every cited utterance has a quote, every minutes document belongs to a meeting
that has minutes (PE-05, PE-03). `quotes.json` is the one file with no schema: the API cuts an
evidence quote from the transcript (PE-05) and no contract names that read model yet.

Run with `uv run pytest tests/web -q`.
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

import jsonschema
import pytest
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
CONTRACTS = REPO_ROOT / "contracts"
FIXTURES = REPO_ROOT / "apps" / "web" / "src" / "people" / "fixtures"
SIGNED_IN = "u_owner"

SCHEMAS = {
    "persons": "person",
    "meetings": "meeting",
    "minutes": "minutes",
    "work_items": "work_item",
}


def _load(name: str) -> Any:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def _registry() -> Registry:
    resources = []
    for path in sorted(CONTRACTS.glob("**/*.schema.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        uri = data.get("$id") or path.resolve().as_uri()
        resources.append((uri, Resource.from_contents(data, default_specification=DRAFT202012)))
    return Registry().with_resources(resources)


def _validator(schema_name: str) -> jsonschema.protocols.Validator:
    schema = json.loads((CONTRACTS / f"{schema_name}.schema.json").read_text(encoding="utf-8"))
    return jsonschema.Draft202012Validator(schema, registry=_registry())


@pytest.mark.parametrize(("file", "schema"), sorted(SCHEMAS.items()))
def test_PPL_40a_every_record_validates_against_its_schema(file: str, schema: str) -> None:
    records = _load(file)
    assert records, f"{file}.json is empty"
    validator = _validator(schema)
    for record in records:
        errors = [e.message for e in validator.iter_errors(record)]
        assert errors == [], f"{file}: {record.get('id', record.get('meeting_id'))}: {errors}"


def test_PPL_40a_plate_holds_only_the_signed_in_persons_items() -> None:
    items = _load("work_items")
    assert {i["owner"] for i in items} == {SIGNED_IN}
    assert len({i["id"] for i in items}) == len(items)
    assert not [i for i in items if i["status"] == "proposed"], "PE-03: proposed items are unread"
    assert {m["owner"] for m in _load("meetings")} == {SIGNED_IN}, "PE-05: meetings are owner-only"


def test_PPL_40a_minutes_belong_to_meetings_that_have_them() -> None:
    meetings = {m["id"]: m for m in _load("meetings")}
    for minutes in _load("minutes"):
        meeting = meetings[minutes["meeting_id"]]
        assert meeting["status"] == "minuted"
        assert meeting["minutes"] is not None
    minuted = {m["id"] for m in meetings.values() if m["status"] == "minuted"}
    assert minuted == {m["meeting_id"] for m in _load("minutes")}


def test_PPL_40a_every_cited_utterance_has_a_quote() -> None:
    quotes = _load("quotes")
    for minutes in _load("minutes"):
        cited: set[str] = set()
        for key in ("summary", "decisions", "action_items", "agenda"):
            for entry in minutes[key]:
                cited.update(entry["evidence"])
        assert cited <= set(quotes[minutes["meeting_id"]]), minutes["meeting_id"]
    for item in _load("work_items"):
        if item["source"]["kind"] == "meeting":
            meeting_id = item["source"]["ref"].split("#")[0]
            assert set(item["source"]["evidence"]) <= set(quotes[meeting_id]), item["id"]
