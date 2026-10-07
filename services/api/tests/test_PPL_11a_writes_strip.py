"""PPL-11a slice C hardening (issue #464): `Writer.text` strips every non-ASCII Cc/Cf/Zl/Zp character before
ANY redactor and the schema, whatever the text contains. A redactor that removes a multi-line secret block (control
characters included, like the future FR-MEM-05 one) must not unlock a hidden-character bypass; ASCII controls are
never joined or stripped, and are refused again after the redactor. Code points are built with `u()`; the fake
secret is assembled at run time."""

from __future__ import annotations

import re
import unicodedata

import pytest
from _ppl11a_lib import ATTEST, OWNER, PRIYA, u

MEETING = {"title": "Weekly sync", "source": "upload", **ATTEST}
ITEM = {"title": "Water the plants", "source": {"kind": "manual", "ref": None}}
PERSON = {
    "display_name": "Nina Patel",
    "aliases": [],
    "email": "nina.patel@example.com",
    "time_zone": "Asia/Kolkata",
    "preferred_channel": "web",
}
ZW, RLO = u(0x200B), u(0x202E)
BAD = frozenset({"Cc", "Cf", "Zl", "Zp"})


def block() -> str:
    """A multi-line fake key block, assembled at run time, with ASCII and non-ASCII controls inside."""
    return "-----BEGIN " + "FAKE KEY-----\nabc" + u(0x200B) + "def\r\n-----END " + "FAKE KEY-----"


class BlockRedactor:
    """Removes a whole multi-line block (its controls with it) and records what it was given."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.pattern = re.compile(r"-----BEGIN FAKE KEY-----.*?-----END FAKE KEY-----", re.DOTALL)

    def __call__(self, text: str) -> str:
        self.calls.append(text)
        return self.pattern.sub("[REDACTED]", text)


class NewlineRedactor:
    """A hostile redactor: its replacement itself holds a line break."""

    def __call__(self, text: str) -> str:
        return text.replace("SECRET", "x\ny")


def hidden_in(value: object) -> bool:
    if isinstance(value, str):
        return any(not c.isascii() and unicodedata.category(c) in BAD for c in value)
    if isinstance(value, dict):
        return any(hidden_in(v) for v in value.values())
    if isinstance(value, list):
        return any(hidden_in(v) for v in value)
    return False


def rig_with(people_rig, redactor):
    rig = people_rig()
    rig.add_people()
    rig.redactor = redactor
    rig.as_user(PRIYA)
    return rig


def test_PPL_11a_PE_13_a_zero_width_link_is_refused_even_when_the_redactor_removes_a_multiline_block(people_rig):
    redactor = BlockRedactor()
    rig = rig_with(people_rig, redactor)
    before = rig.snapshot()
    for title in (
        f"https:{ZW}//evil.example/x {block()}",
        f"https{RLO}://evil.example {block()}",
        f"meet.google{ZW}.com {block()}",
    ):
        assert rig.post("/v1/meetings", {**MEETING, "title": title}).status_code == 422, title
    assert rig.snapshot() == before
    assert redactor.calls and not any(hidden_in(call) for call in redactor.calls), "cleaned before the redactor"


def test_PPL_11a_PE_24_a_bidi_override_title_is_cleaned_when_the_redactor_removes_a_multiline_block(people_rig):
    redactor = BlockRedactor()
    rig = rig_with(people_rig, redactor)
    meeting = rig.post("/v1/meetings", {**MEETING, "title": f"Pay {RLO}evil {block()}"})
    assert meeting.status_code == 201, meeting.text[:300]
    stored = rig.stored("meetings", meeting.json()["id"])
    assert stored["title"] == "Pay evil [REDACTED]" and not hidden_in(stored)
    item = rig.post("/v1/work-items", {**ITEM, "title": f"Pay {RLO}evil {block()}"})
    assert item.status_code == 201 and item.json()["title"] == "Pay evil [REDACTED]"


def test_PPL_11a_PE_24_no_text_field_stores_a_hidden_character_behind_a_block_removing_redactor(people_rig):
    """Every text field: a hidden character plus the block never leaves a Cc/Cf/Zl/Zp character in anything stored."""
    redactor = BlockRedactor()
    rig = rig_with(people_rig, redactor)
    junk = f"{ZW}{RLO}{u(0x2028)} {block()}"
    bodies = [
        ("/v1/meetings", {**MEETING, "title": f"A{junk}"}),
        ("/v1/meetings", {**MEETING, "series": f"q4{junk}"}),
        ("/v1/meetings", {**MEETING, "agenda": [{"title": f"A{junk}", "minutes": 5}]}),
        ("/v1/meetings", {**MEETING, "attendees": [{"name": f"As{junk}"}]}),
        ("/v1/work-items", {**ITEM, "title": f"W{junk}"}),
        ("/v1/work-items", {**ITEM, "due_text": f"tomorrow{junk}"}),
    ]
    for path, body in bodies:
        assert rig.post(path, body).status_code in (201, 422), body
    rig.as_user(OWNER)
    for body in (
        {**PERSON, "display_name": f"Ni{junk}"},
        {**PERSON, "aliases": [f"Ni{junk}"], "email": "nina.two@example.com"},  # PPL-11c: an address is the org's alone
    ):
        assert rig.post("/v1/people", body).status_code in (201, 422), body
    for name in ("meetings", "work_items", "persons"):
        for stored in getattr(rig.real, name).list(rig.org):
            assert not hidden_in(stored.record), (name, stored.record)
    assert not any(hidden_in(call) for call in redactor.calls), "every call saw cleaned text"


def test_PPL_11a_PE_24_ascii_controls_are_still_a_422_never_joined(people_rig):
    redactor = BlockRedactor()
    rig = rig_with(people_rig, redactor)
    before = rig.snapshot()
    for title in ("Line\nbreak", "Line\rbreak", "Tab\there", "Nul\x00x", "Del\x7fx", f"Line\n{ZW}break"):
        assert rig.post("/v1/meetings", {**MEETING, "title": title}).status_code == 422, repr(title)
    assert rig.post("/v1/work-items", {**ITEM, "title": "Line\nbreak"}).status_code == 422
    assert rig.snapshot() == before


def test_PPL_11a_PE_24_a_control_in_the_redactor_output_is_refused(people_rig):
    rig = rig_with(people_rig, NewlineRedactor())
    before = rig.snapshot()
    assert rig.post("/v1/meetings", {**MEETING, "title": "has SECRET inside"}).status_code == 422
    assert rig.post("/v1/work-items", {**ITEM, "title": "has SECRET inside"}).status_code == 422
    assert rig.snapshot() == before


@pytest.mark.parametrize("text", ["Plain title", "Caf" + u(0xE9) + " sync"])
def test_PPL_11a_PE_24_ordinary_text_still_passes_unchanged(people_rig, text):
    rig = rig_with(people_rig, BlockRedactor())
    response = rig.post("/v1/meetings", {**MEETING, "title": text})
    assert response.status_code == 201 and rig.stored("meetings", response.json()["id"])["title"] == text
