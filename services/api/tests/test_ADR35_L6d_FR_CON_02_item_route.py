"""ADR35_L6d / FR_CON_02: `GET /worlds/{id}/cards/{cid}/item`, the owner's show-me of the document a gate card pins.

A READ: the world's owner on a full web session sees the pinned document (allowlisted fields of the L5 formats, the
card's recipients) hash-checked from the artifact store. Everyone else gets the fields route's one 404 (no oracle),
a demo session 403; a corrupt, oversize or odd document is one fixed 409 and never its bytes. No network, no paid call.
"""

from __future__ import annotations

import json

import pytest
from _clint2_lib import NEW_RECIPIENT, wait_for
from _mtg09b_lib import block_network
from test_ADR35_L6b_FR_CON_02_run_documents import EVENT, SUBJECT, Live
from tilo_api import deps, item_fields


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    block_network(monkeypatch)


@pytest.fixture
def live(repo_root):
    made = []

    def make(**kw):
        made.append(Live(repo_root, **kw))
        return made[-1]

    yield make
    for item in made:
        item.close()


def item_url(lv, card_id: str) -> str:
    return f"/worlds/{lv.rf.world_id}/cards/{card_id}/item"


def see(lv, card_id: str):
    return lv.rf.flow.client.get(item_url(lv, card_id))


def test_ADR35_L6d_FR_CON_02_the_owner_sees_the_email_document_and_the_recipients_with_no_store(live):
    lv = live(fields={"subject": SUBJECT, "in_reply_to": "<m1@example.org>"})
    lv.start()
    card = lv.gate_card("create_draft")
    got = see(lv, card["id"])
    assert got.status_code == 200 and "no-store" in got.headers["Cache-Control"]
    stored = json.loads(lv.read(card["gate"]["action"]["item"]))
    assert got.json() == {**stored, "recipients": [NEW_RECIPIENT]}
    assert set(got.json()) <= {"kind", "subject", "body_text", "in_reply_to", "references", "recipients"}
    assert lv.rf.events("approval.resolved") == [] and lv.google.reached() == 0  # a read: nothing happened


def test_ADR35_L6d_FR_CON_02_the_owner_sees_a_file_document(live):
    lv = live(connector="google_drive", actions=("save_file",), fields={"name": "n.md"},
              destination="fld_tilo_reports", recipients=())  # fmt: skip
    lv.start()
    card = lv.gate_card("save_file")
    got = see(lv, card["id"])
    stored = json.loads(lv.read(card["gate"]["action"]["item"]))
    assert got.status_code == 200 and got.json() == {k: v for k, v in stored.items() if k != "origin"} | (
        {"origin": stored["origin"]} if "origin" in stored else {}
    )
    assert got.json()["kind"] == "file" and got.json()["name"] == "n.md" and "recipients" not in got.json()


def test_ADR35_L6d_FR_CON_02_the_owner_sees_a_calendar_event_document(live):
    lv = live(connector="google_calendar", actions=("create_event",), fields=EVENT, destination="primary",
              recipients=())  # fmt: skip
    lv.start()
    card = lv.gate_card("create_event")
    got = see(lv, card["id"])
    assert got.status_code == 200 and got.json() == {"kind": "calendar_event", **EVENT}


@pytest.mark.parametrize(
    "who, role, districts",
    [
        ("u_viewer1", "viewer", ()),
        ("u_appr1", "approver", ()),
        ("u_lead1", "team_lead", ("D9",)),
        ("u_lead2", "team_lead", ("D2",)),
    ],
)
def test_ADR35_L6d_FR_CON_02_everyone_but_the_owner_gets_the_same_404(live, who, role, districts):
    lv = live(fields={"subject": SUBJECT})
    lv.start()
    card = lv.gate_card("create_draft")
    lv.as_user(who, role, full=True, districts=districts)
    real, absent = see(lv, card["id"]), see(lv, "c_no_such_card")
    assert real.status_code == 404 and absent.status_code == 404 and real.text == absent.text
    assert SUBJECT not in real.text and NEW_RECIPIENT not in real.text


def test_ADR35_L6d_FR_CON_02_a_demo_session_is_refused(live):
    lv = live(fields={"subject": SUBJECT})
    lv.start()
    card = lv.gate_card("create_draft")
    lv.as_user("u_flow_owner", "owner", full=False)
    got = see(lv, card["id"])
    assert got.status_code == 403 and SUBJECT not in got.text


def test_ADR35_L6d_FR_CON_02_a_card_of_another_world_or_a_needs_fields_card_is_a_404(live):
    lv = live()
    lv.start()
    asked = lv.ask_card()  # a needs-subject card pins no item
    assert see(lv, asked["id"]).status_code == 404
    other = lv.rf.flow.client.get(f"/worlds/w_other/cards/{asked['id']}/item")
    assert other.status_code == 404


def test_ADR35_L6d_FR_CON_02_a_closed_or_answered_card_is_a_404(live):
    lv = live(fields={"subject": SUBJECT})
    lv.start()
    card = lv.gate_card("create_draft")
    assert lv.rf.answer(card["id"], "approve").status_code == 200
    assert see(lv, card["id"]).status_code == 404


def test_ADR35_L6d_FR_CON_02_a_changed_stored_document_is_refused_and_its_bytes_never_returned(live):
    lv = live(fields={"subject": SUBJECT})
    lv.start()
    card = lv.gate_card("create_draft")
    ref = card["gate"]["action"]["item"]
    forged = json.dumps({"kind": "email", "subject": "FORGED-MARKER", "body_text": "x"}).encode()
    blobs = lv.rf.rig.blobs._blobs
    for key in [k for k in blobs if k.endswith(f"{ref['version']:06d}")] or list(blobs):
        blobs[key] = forged
    got = see(lv, card["id"])
    assert got.status_code == 409 and got.json() == {"reason": "item_unavailable"} and "FORGED" not in got.text


def test_ADR35_L6d_FR_CON_02_an_oversize_document_is_refused(live, monkeypatch):
    lv = live(fields={"subject": SUBJECT})
    lv.start()
    card = lv.gate_card("create_draft")
    monkeypatch.setattr(item_fields, "MAX_DOCUMENT_CHARS", 40)
    got = see(lv, card["id"])
    assert got.status_code == 409 and got.json() == {"reason": "item_unavailable"} and SUBJECT not in got.text


def test_ADR35_L6d_FR_CON_02_only_the_allowlisted_fields_of_a_document_are_shown():
    raw = json.dumps(
        {"kind": "email", "subject": "s", "body_text": "b", "secret": "token", "bcc": "x@example.org",
         "attachments": [1]}
    ).encode()  # fmt: skip
    assert item_fields.shown_document(raw, ["a@example.org"]) == {
        "kind": "email", "subject": "s", "body_text": "b", "recipients": ["a@example.org"],
    }  # fmt: skip
    assert item_fields.shown_document(b'{"kind": "other"}', []) is None
    assert item_fields.shown_document(b"plain text, not a document", []) is None
    assert item_fields.shown_document(b'{"kind": "email", "subject": 7}', []) is None  # a wrong type is refused whole
    big = json.dumps({"kind": "file", "name": "f", "content_b64": "A" * 43_693}).encode()
    assert item_fields.shown_document(big, []) is None
    assert item_fields.shown_document(b"[" * 100_000, []) is None  # deep nesting never raises


def test_ADR35_L6d_FR_CON_02_a_world_with_no_run_or_unknown_ids_is_the_same_404(live):
    lv = live(fields={"subject": SUBJECT})
    lv.start()
    wait_for(lambda: lv.gate_card("create_draft"), what="gate")
    assert lv.rf.flow.client.get("/worlds/w_none/cards/c_none/item").status_code == 404


def test_ADR35_L6d_FR_CON_02_an_owner_of_another_world_gets_the_same_404(live):
    lv = live(fields={"subject": SUBJECT})
    lv.start()
    card = lv.gate_card("create_draft")
    lv.rf.flow.principal = deps.Principal(user_id="u_stranger", role="owner", world_id="w_other", full_session=True)
    real, absent = see(lv, card["id"]), see(lv, "c_no_such_card")
    assert real.status_code == 404 and real.text == absent.text and SUBJECT not in real.text
