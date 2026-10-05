"""PPL-40b / FR-PB-01, FR-PB-08, FR-CAL-01: the fixtures behind S-28 Pinboards and S-29 Calendar are contract-valid.

The JSON under apps/web/src/people/fixtures/ is what the two screens read. Every record validates
against its schema in contracts/ (agenda rows and free/busy against the `$defs` of
calendar_entry.schema.json), and the files agree with each other and with the PPL-40a ones: pins
cite meetings that exist, mentions tag members of the pin's team, every agenda row cites a record
whose title and date it repeats, and a teammate's free/busy holds intervals and nothing else
(PE-04). Run with `uv run pytest tests/web -q`.
"""

from __future__ import annotations

import json
import pathlib
from datetime import datetime, timedelta, timezone
from typing import Any

import jsonschema
import pytest
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
CONTRACTS = REPO_ROOT / "contracts"
FIXTURES = REPO_ROOT / "apps" / "web" / "src" / "people" / "fixtures"
SIGNED_IN = "u_owner"
IST = timezone(timedelta(hours=5, minutes=30))

# fixture file -> the schema (a file, or a file#def) each record must satisfy
SCHEMAS = {
    "pins": "pinboard_item",
    "mentions": "mention",
    "calendar_entries": "calendar_entry",
    "agenda_items": "calendar_entry#agenda_item",
    "free_busy": "calendar_entry#free_busy",
    "calendar_meetings": "meeting",
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


def _validator(target: str) -> jsonschema.protocols.Validator:
    name, _, definition = target.partition("#")
    path = CONTRACTS / f"{name}.schema.json"
    schema = json.loads(path.read_text(encoding="utf-8"))
    if definition:
        schema = {"$ref": f"{schema['$id']}#/$defs/{definition}"}
    return jsonschema.Draft202012Validator(schema, registry=_registry())


def _local(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(IST)


@pytest.mark.parametrize(("file", "schema"), sorted(SCHEMAS.items()))
def test_PPL_40b_every_record_validates_against_its_schema(file: str, schema: str) -> None:
    records = _load(file)
    assert records, f"{file}.json is empty"
    validator = _validator(schema)
    for record in records:
        errors = [e.message for e in validator.iter_errors(record)]
        assert errors == [], f"{file}: {record.get('id', record.get('title'))}: {errors}"


def test_PPL_40b_pins_have_one_owner_at_most_and_a_personal_pin_has_none() -> None:
    pins = _load("pins")
    assert len({p["id"] for p in pins}) == len(pins)
    for pin in pins:
        assert pin["owner"] is None or isinstance(pin["owner"], str)  # never a list (FR-PB-07)
        if pin["scope"]["kind"] == "personal":
            assert pin["owner"] is None, pin["id"]
    unowned = [
        p["id"] for p in pins if p["scope"]["kind"] == "team" and p["owner"] is None and p["status"] != "removed"
    ]
    assert unowned == [
        "pb_venue_open",
        "pb_rollout_plan",
    ], "the Unowned lane lists exactly the null-owner entries"


def test_PPL_40b_the_fixtures_hold_every_case_the_screens_must_hide_or_show() -> None:
    pins = _load("pins")
    team = [p for p in pins if p["scope"]["kind"] == "team"]
    assert {p["status"] for p in team} == {"active", "proposed", "removed"}
    assert any(p["status"] == "proposed" and p["set_up_by"] != SIGNED_IN for p in team)
    assert any(p["status"] == "proposed" and p["set_up_by"] == SIGNED_IN for p in team)
    personal_of = {p["scope"]["user"] for p in pins if p["scope"]["kind"] == "personal"}
    assert personal_of == {SIGNED_IN, "u_priya"}, "a teammate's personal pin is there to be hidden"
    states = {e["state"] for e in _load("calendar_entries")}
    assert states == {"accepted", "proposed", "cancelled"}
    assert {e["owner"] for e in _load("calendar_entries")} == {SIGNED_IN, "u_priya"}


def test_PPL_40b_mentions_tag_members_of_the_pins_team_and_never_a_personal_pin() -> None:
    pins = {p["id"]: p for p in _load("pins")}
    persons = {p["id"]: p for p in _load("persons")}
    for mention in _load("mentions"):
        pin = pins[mention["pin_id"]]
        assert pin["scope"]["kind"] == "team", "PE-06: a personal pin takes no mention"
        assert mention["team"] == pin["scope"]["team"]
        teams = {m["team"] for m in persons[mention["user"]]["memberships"]}
        assert mention["team"] in teams, "PE-06: a non-member cannot be tagged"
    assert any(m["removed"] for m in _load("mentions")), "a removed tag is there to be hidden"


def test_PPL_40b_pin_sources_name_meetings_that_exist() -> None:
    meetings = {m["id"] for m in _load("meetings") + _load("calendar_meetings")}
    known_elsewhere = {"mt_priya_sync"}  # cited by a PPL-40a work item, no record of its own
    for pin in _load("pins"):
        source = pin["source"]
        if source and source["kind"] == "meeting":
            assert source["ref"] in meetings | known_elsewhere, pin["id"]


def test_PPL_40b_agenda_rows_cite_a_record_and_repeat_its_title_and_date() -> None:
    titles = {("work_item", i["id"]): (i["title"], i["due"]) for i in _load("work_items")}
    titles |= {("pinboard_item", p["id"]): (p["title"], p["due"]) for p in _load("pins")}
    meetings = _load("meetings") + _load("calendar_meetings")
    titles |= {
        ("meeting", m["id"]): (m["title"], _local(m["scheduled"]["start"]).date().isoformat())
        for m in meetings
        if m["scheduled"]
    }
    for row in _load("agenda_items"):
        cited = (row["source"]["kind"], row["source"]["id"])
        title, date = titles[cited]
        assert row["title"] == title, cited
        assert _local(row["start"]).date().isoformat() == date, cited
        assert row["state"] == "confirmed" and row["shared"] is False


def test_PPL_40b_free_busy_is_intervals_only_and_within_31_days() -> None:
    persons = {p["id"] for p in _load("persons")}
    for fb in _load("free_busy"):
        assert set(fb) == {"user", "from", "to", "busy"}, "PE-04: no title, source or count"
        assert fb["user"] in persons and fb["user"] != SIGNED_IN
        span = _local(fb["to"]) - _local(fb["from"])
        assert timedelta(0) < span <= timedelta(days=31)
        for interval in fb["busy"]:
            assert set(interval) == {"start", "end"}
            assert interval["start"] < interval["end"]


def test_PPL_40b_teammate_busy_matches_their_own_accepted_entry_and_not_a_title() -> None:
    (fb,) = _load("free_busy")
    dentist = next(e for e in _load("calendar_entries") if e["owner"] == fb["user"])
    assert {"start": dentist["start"], "end": dentist["end"]} in fb["busy"]
