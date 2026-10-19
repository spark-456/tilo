"""ADR35_L6b / FR_CON_02: the run path's converter makes the L5 item documents (BQ-ADR35L5-1, BQ-ADR35L6-1).

The converter is deterministic and generic over the action type: declared fields plus the unit's body artifact give
the `kind` JSON that tilo-connectors parses. Only these tests import tilo_connectors' own parser (`checked_documents`)
to prove the round trip; tilo-api's source never does. A field nobody declared is `Needs`, never taken from the text.
"""

from __future__ import annotations

import ast
import base64
import hashlib
import json
import pathlib

import pytest
from tilo_api import item_documents
from tilo_api.item_documents import DocumentRefused, Needs, build_document
from tilo_connectors.side_effect_execute import checked_documents

SRC = pathlib.Path(item_documents.__file__).parent
BODY = b"# Quarterly note\n\nHello there, this is the text.\n"
EMAIL = {"subject": "Quarterly note for the team"}
EVENT = {"title": "Review", "start": "2026-10-12T09:00:00.000Z", "end": "2026-10-12T09:30:00.000Z",
         "time_zone": "Asia/Kolkata"}  # fmt: skip
REF = {"artifact_id": "art_01JB5VQ0000000000000000001", "version": 2}


def parsed(action: str, raw: bytes, *, attachments: list | None = None):
    """The document as tilo-connectors' own `checked_documents` reads it, from the item as the stub posts it."""
    entry = {"item": REF, "attachments": attachments or []}
    items = [{**REF, "content_sha256": hashlib.sha256(raw).hexdigest(), "content_b64": base64.b64encode(raw).decode()}]
    documents = checked_documents(entry, items)
    assert documents is not None, f"connectors refused the {action} document"
    return documents.get(REF["artifact_id"], REF["version"])


def make(action: str, fields: dict, **more) -> bytes:
    built = build_document(action, fields, body=BODY, media_type="text/markdown", **more)
    assert isinstance(built, bytes), built
    return built


@pytest.mark.parametrize("action", ["create_draft", "send_email"])
def test_ADR35_L6b_FR_CON_02_an_email_document_round_trips_through_connectors_own_parser(action):
    document = parsed(action, make(action, EMAIL))
    assert document == {"kind": "email", "subject": EMAIL["subject"], "body_text": BODY.decode()}


def test_ADR35_L6b_FR_CON_02_a_reply_names_its_message_and_a_threaded_reply_without_one_is_refused():
    reply = {**EMAIL, "in_reply_to": "<m1@example.org>", "references": "<m0@example.org> <m1@example.org>"}
    assert parsed("send_email", make("send_email", reply, threaded=True))["in_reply_to"] == "<m1@example.org>"
    with pytest.raises(DocumentRefused, match="name the message"):
        build_document("send_email", EMAIL, body=BODY, media_type="text/markdown", threaded=True)
    with pytest.raises(DocumentRefused, match="in_reply_to"):
        make("send_email", {**EMAIL, "in_reply_to": "not an id"})


@pytest.mark.parametrize("action", ["save_file", "save_as_google_file"])
def test_ADR35_L6b_FR_CON_02_a_file_document_carries_the_bodys_bytes_and_the_stores_media_type(action):
    document = parsed(action, make(action, {"name": "note.md"}))
    assert (document["kind"], document["name"], document["mime_type"]) == ("file", "note.md", "text/markdown")
    assert document["content"] == BODY and "origin" not in document  # nothing invents a render origin
    declared = parsed(action, make(action, {"name": "n.txt", "mime_type": "text/plain"}))
    assert declared["mime_type"] == "text/plain"
    rendered = parsed(action, make(action, {"name": "n"}, origin={"kind": "render"}))
    assert rendered["origin"] == {"kind": "render"}
    assert "origin" not in parsed(action, make(action, {"name": "n"}, origin={"kind": "unit"}))


@pytest.mark.parametrize("action", ["create_event", "create_event_with_guests"])
def test_ADR35_L6b_FR_CON_02_an_event_document_round_trips_with_no_attendees_inside(action):
    document = parsed(action, make(action, EVENT))
    assert document == {"kind": "calendar_event", **EVENT}  # the guests are the entry's recipients, not the document's


def test_ADR35_L6b_FR_CON_02_a_missing_or_blank_field_is_needs_never_taken_from_the_text():
    assert build_document("send_email", {}, body=BODY, media_type="text/markdown") == Needs(("subject",))
    assert build_document("send_email", {"subject": "  "}, body=BODY, media_type="text/markdown") == Needs(("subject",))
    assert build_document("save_file", {}, body=BODY, media_type="text/markdown") == Needs(("name",))
    half = {"title": "Review", "end": EVENT["end"]}
    assert build_document("create_event", half, body=b"x", media_type="text/markdown") == Needs(
        ("start", "time_zone")
    )  # the body's first line is "# Quarterly note": it never becomes the subject


def test_ADR35_L6b_FR_CON_02_the_same_inputs_make_the_same_bytes_and_hash():
    first, second = make("send_email", EMAIL), make("create_draft", dict(reversed(EMAIL.items())))
    assert first == second and hashlib.sha256(first).hexdigest() == hashlib.sha256(second).hexdigest()
    assert json.loads(first) == json.loads(second) and b" " not in first.split(b"body_text")[0]


@pytest.mark.parametrize("bad", ["a\r\nBcc: x@example.org", "a\nb", "a\x00b", "a‮b", "a b", "a​b"])
@pytest.mark.parametrize("action, field", [("send_email", "subject"), ("save_file", "name"), ("create_event", "title")])
def test_ADR35_L6b_FR_CON_02_header_injection_characters_are_refused_at_conversion(action, field, bad):
    fields = {**EVENT, **EMAIL, "name": "x"} | {field: bad}
    with pytest.raises(DocumentRefused, match="line breaks or hidden characters"):
        build_document(action, fields, body=BODY, media_type="text/markdown")


def test_ADR35_L6b_FR_CON_02_other_bad_values_are_refused_with_a_plain_reason():
    for action, fields, word in [
        ("save_file", {"name": "../x"}, "slash"),
        ("send_email", {"subject": "s" * 151}, "150"),
        ("create_event", {**EVENT, "start": "tomorrow"}, "date and time"),
        ("create_event", {**EVENT, "time_zone": "Asia/Kolkata; DROP"}, "time zone"),
        ("save_file", {"name": "a", "mime_type": "text"}, "file type"),
        ("send_email", {"subject": 5}, "some text"),
    ]:
        with pytest.raises(DocumentRefused, match=word):
            build_document(action, fields, body=BODY, media_type="text/markdown")


def test_ADR35_L6b_FR_CON_02_a_document_over_the_item_cap_is_refused_before_any_card():
    big = ("x" * (item_documents.MAX_DOCUMENT + 1)).encode()
    for action, fields in [("send_email", EMAIL), ("save_file", {"name": "big.txt"})]:
        with pytest.raises(DocumentRefused, match="KiB"):
            build_document(action, fields, body=big, media_type="text/markdown")
    assert len(make("send_email", EMAIL)) <= item_documents.MAX_DOCUMENT


def test_ADR35_L6b_FR_CON_02_guests_are_refused_for_create_event_and_not_for_the_guest_action():
    for key in ("attendees", "guests"):
        with pytest.raises(DocumentRefused, match="guest"):
            build_document("create_event", {**EVENT, key: ["a@example.org"]}, body=b"x", media_type="text/markdown")
    assert build_document("create_event", {**EVENT, "attendees": []}, body=b"x", media_type="text/markdown")
    assert b"attendees" not in make("create_event_with_guests", {**EVENT, "attendees": ["a@example.org"]})


def test_ADR35_L6b_FR_CON_02_a_body_that_is_not_text_and_an_unknown_action_are_refused():
    with pytest.raises(DocumentRefused, match="not text"):
        build_document("send_email", EMAIL, body=b"\xff\xfe\x00", media_type="text/markdown")
    with pytest.raises(DocumentRefused, match="no document"):
        build_document("read_email", EMAIL, body=BODY, media_type="text/markdown")
    assert item_documents.kind_of("read_email") is None


def test_ADR35_L6b_FR_CON_02_every_live_google_write_action_has_a_document_kind():
    config = pathlib.Path(__file__).resolve().parents[3] / "config" / "connectors.yaml"
    import yaml  # noqa: PLC0415

    connectors = yaml.safe_load(config.read_text(encoding="utf-8"))
    actions = {a["id"] for c in connectors if c["id"] in ("gmail", "google_drive", "google_calendar")
               for a in c["actions"]}  # fmt: skip
    writes = actions - {"read_email", "search_email", "read_file", "list_files", "read_events"}
    assert writes == set(item_documents.KIND_OF)


def test_ADR35_L6b_FR_CON_02_the_new_modules_import_no_connectors_token_live_or_adapter_code():
    for name in ("item_documents.py", "item_fields.py"):
        tree = ast.parse((SRC / name).read_text(encoding="utf-8"))
        names = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module]
        names += [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
        assert not [n for n in names if n.startswith("tilo_connectors")], name
