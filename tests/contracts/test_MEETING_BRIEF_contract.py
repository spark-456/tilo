"""MEETING-BRIEF (ADR-0047): meeting.schema.json 1.3.0 and meeting_brief.schema.json 1.0.0.

The meeting gains three optional fields (absent, never null) and drops `brief` when discarded or deleted; the brief
is closed, holds no recipient, time or link, and every talk point cites a source. Rules that compare documents
(MB-01 to MB-12, `contracts/meeting_brief.rules.md`) are the brief generator's and routes' tests.
"""

from __future__ import annotations

import json
import re

import _people_lib as pl
import pytest

BRIEF_REF = {"artifact_id": "art_brief_weekly1", "version": 1}
POINT = {"text": "Confirm the launch date.", "evidence": [{"kind": "agenda", "index": 0}]}
BRIEF = {
    "v": "1.0",
    "meeting_id": "mt_weekly1",
    "generated_at": "2026-10-13T08:45:00.000Z",
    "flagged": False,
    "agenda_points": [{"title": "Launch date", "minutes": 15, "talk_points": [POINT]}],
    "carry_over": [{"text": "Launch on 2 November.", "kind": "decision", "from_meeting": "mt_q4", "item": "d0"}],
}


def test_MEETING_BRIEF_FR_MTG_03_meeting_switches_and_brief_are_optional_never_null(repo_root, registry):
    schema = pl.load_contract(repo_root, "meeting")
    assert tuple(map(int, schema["x-version"].split("."))) >= (1, 3, 0)
    assert not {"brief_requested", "auto_report", "brief"} & set(schema["required"])
    pl.assert_valid(repo_root, registry, "meeting", pl.meeting())
    on = pl.with_(pl.meeting(), brief_requested=True, auto_report=False, brief=BRIEF_REF)
    pl.assert_valid(repo_root, registry, "meeting", on)
    for field, bad in (("brief_requested", None), ("auto_report", None), ("brief", None), ("auto_report", "yes")):
        pl.assert_invalid(repo_root, registry, "meeting", pl.with_(on, **{field: bad}), why=f"{field}={bad!r}")
    pl.assert_invalid(repo_root, registry, "meeting", pl.with_(on, brief={**BRIEF_REF, "label": "Brief"}))


@pytest.mark.parametrize("status", ["discarded", "deleted"])
def test_MEETING_BRIEF_FR_MTG_10_a_discarded_or_deleted_meeting_keeps_no_brief(repo_root, registry, status):
    gone = pl.with_(pl.meeting(), status=status, transcript=None, minutes=None, minutes_confirmed_by=None)
    pl.assert_valid(repo_root, registry, "meeting", gone)
    pl.assert_invalid(repo_root, registry, "meeting", pl.with_(gone, brief=BRIEF_REF), why=status)


def test_MEETING_BRIEF_FR_WLD_02_brief_schema_is_closed_and_holds_no_recipient_time_or_link(repo_root, registry):
    schema = pl.load_contract(repo_root, "meeting_brief")
    assert schema["$id"] == "https://contracts.tilo.example/meeting_brief.schema.json"
    assert (schema["x-version"], schema["title"], schema["additionalProperties"]) == ("1.0.0", "MeetingBrief", False)
    assert "allOf" not in schema
    for name, part in schema["$defs"].items():
        if part.get("type") == "object":
            assert part["additionalProperties"] is False, f"$defs/{name} must be closed"
    names = set(re.findall(r'"([a-z_]+)":', json.dumps(schema["properties"]) + json.dumps(schema["$defs"])))
    assert not names & {"recipients", "to", "email", "url", "link", "send_at", "when", "start", "owner"}
    pl.assert_valid(repo_root, registry, "meeting_brief", BRIEF)
    for extra in ({"recipients": ["a@example.com"]}, {"send_at": "2026-10-13T09:00:00.000Z"}):
        pl.assert_invalid(repo_root, registry, "meeting_brief", {**BRIEF, **extra}, why=str(extra))


@pytest.mark.parametrize(
    "text", ["See https://example.com/x", "Notes at example.org/q4 now", "Use meet.google.com", "two\nlines"]
)
def test_MEETING_BRIEF_PE_13_talk_point_text_is_one_link_free_line(repo_root, registry, text):
    bad = pl.put(BRIEF, ("agenda_points", 0, "talk_points", 0, "text"), text)
    pl.assert_invalid(repo_root, registry, "meeting_brief", bad, why=text)


def test_MEETING_BRIEF_FR_AGT_12_every_talk_point_cites_one_to_ten_known_sources(repo_root, registry):
    at = ("agenda_points", 0, "talk_points", 0, "evidence")
    prior = {"kind": "prior", "meeting_id": "mt_q4", "item": "ai12"}
    pl.assert_valid(repo_root, registry, "meeting_brief", pl.put(BRIEF, at, [POINT["evidence"][0], prior]))
    for bad in (
        [],
        [{"kind": "agenda", "index": 20}],
        [{"kind": "transcript", "id": "u0001"}],
        [dict(prior, item="x1")],
    ):
        pl.assert_invalid(repo_root, registry, "meeting_brief", pl.put(BRIEF, at, bad), why=str(bad))


@pytest.mark.parametrize(
    ("kind", "item", "ok"),
    [("decision", "d0", True), ("decision", "ai1", False), ("open_action", "ai1", True), ("open_action", "d0", False)],
)
def test_MEETING_BRIEF_FR_MTG_06_carry_over_kind_matches_its_item(repo_root, registry, kind, item, ok):
    doc = pl.put(pl.put(BRIEF, ("carry_over", 0, "kind"), kind), ("carry_over", 0, "item"), item)
    (pl.assert_valid if ok else pl.assert_invalid)(repo_root, registry, "meeting_brief", doc)


def test_MEETING_BRIEF_rules_file_numbers_mb_01_to_mb_12(repo_root):
    text = (repo_root / "contracts" / "meeting_brief.rules.md").read_text(encoding="utf-8")
    assert re.findall(r"^\| (MB-\d\d) \|", text, flags=re.M) == [f"MB-{n:02d}" for n in range(1, 13)]
