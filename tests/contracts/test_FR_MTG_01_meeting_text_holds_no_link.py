"""FR-MTG-01 and people.rules.md PE-13: a meeting's free text (title, agenda title, attendee name) holds
no join link (meeting 1.2.0, ADR-0016 decision 14, issue #464). The schema refuses the link forms and the
invisible characters that could hide one, and keeps text that only looks like a link. Astral characters
are the validator's (tilo-api), not the schema's.
"""

from __future__ import annotations

import re
import unicodedata

import _people_lib as pl
import pytest

FIELDS = {"title": ("title",), "agenda_title": ("agenda", 0, "title"), "attendee_name": ("attendees", 0, "name")}

LINKS = [
    "g.co/meet/abc-defg-hij",
    "teams.live.com/meet/123",
    "webex.com/meet/x",
    "Notes at example.com/x",
    "Notes at EXAMPLE.ORG/Room",
    "Room at meet.example.org:8443/room",
    "acme.zoom.us",
    "Join on zoom.us.",
    "Call on whereby.com",
    "Use teams.microsoft.com",
    "MEET.GOOGLE.COM",
    "https://intranet/room",
    "https:\\\\intranet",
    "https:/\\intranet",
]
HIDDEN = [  # an invisible character that splits `://` or a host
    "https:\u034f//intranet/room",
    "https:\ufe0f//intranet/room",
    "https:/\ufe0e/intranet",
    "zoom.u\ufe0fs",
    "https:\u3164//intranet/room",
    "https:\u2800//intranet/room",
    "https:\u115f//intranet",
    "https:\uffa0//intranet",
    "https:\u180b//intranet",
    "https:\u17b4//intranet",
    "\ufe0fPlan",
    "1\u034fPlan",
]
LOOKALIKES = [
    "Q4 plan v2.1",
    "Review of a.b notes",
    "Node.js/React decision",
    "Vue.JS/Svelte",
    "Sales/Marketing sync",
    "1:1 w/ Priya",
    "Ratio 3:2 / budget",
    "Planning: / Retro",
    "Zoom usage review",
    "zoom.usage stats",
    "Kickoff with example.com team",
    "U.S./EU trade",
    "Q1.FY25/Q2",
    "Team \u2764\ufe0f retro",
    "1\ufe0f\u20e3 Budget",
    "#\ufe0f\u20e3 tags",
    "\u1820\u180b\u1821",
    "Priya \U0001f389",
]


def text_fields(schema: dict) -> list[dict]:
    defs = schema["$defs"]
    return [
        schema["properties"]["title"],
        defs["agenda_item"]["properties"]["title"],
        defs["attendee"]["properties"]["name"],
    ]


@pytest.mark.parametrize("field", sorted(FIELDS))
@pytest.mark.parametrize("text", LINKS + HIDDEN)
def test_FR_MTG_01_meeting_text_refuses_a_link_or_a_hidden_one(repo_root, registry, field, text):
    pl.assert_invalid(
        repo_root, registry, "meeting", pl.put(pl.meeting(), FIELDS[field], text), None, f"{field} {text!r}"
    )


@pytest.mark.parametrize("field", sorted(FIELDS))
@pytest.mark.parametrize("text", LOOKALIKES)
def test_FR_MTG_01_meeting_text_keeps_text_that_only_looks_like_a_link(repo_root, registry, field, text):
    pl.assert_valid(
        repo_root, registry, "meeting", pl.put(pl.meeting(), FIELDS[field], text), None, f"{field} {text!r}"
    )


def test_FR_MTG_01_the_three_text_fields_share_one_rule(repo_root):
    title, agenda, name = text_fields(pl.load_contract(repo_root, "meeting"))
    assert title["pattern"] == agenda["pattern"] == name["pattern"]
    assert title["not"] == agenda["not"] == name["not"]


def test_FR_MTG_01_PE_13_every_bmp_control_format_and_separator_character_is_refused(repo_root):
    pattern = text_fields(pl.load_contract(repo_root, "meeting"))[0]["pattern"]
    leaked = [
        f"U+{cp:04X}"
        for cp in range(0x10000)
        if not 0xD800 <= cp <= 0xDFFF
        and unicodedata.category(chr(cp)) in {"Cc", "Cf", "Zl", "Zp"}
        and re.search(pattern, f"a{chr(cp)}b")
    ]
    assert not leaked, f"the meeting text pattern lets these through: {leaked[:10]}"
