"""FR-CON-11: Google Slides, Docs and Sheets output through the Drive connector (PRD 12.2, 12.4).

Acceptance test: "A deck appears in the user's Drive folder and opens in Slides". A deck, doc or sheet
artifact (PPTX, DOCX, XLSX from tilo-render) is uploaded to the Tilo folder with Drive's upload-with-
conversion, so the stored file is a native Slides, Docs or Sheets file. Same outbox, grant, tier and
scope path as save_file (SEC-03); no network: the fake Google API behind the Transport seam.
"""

from __future__ import annotations

import pathlib

import pytest
import yaml
from _gapi_lib import DRIVE_UPLOAD_API, FOLDER_MIME, GAPPS, OOXML, drive_case, enqueue, make_gapi_env
from _oauth_lib import DRIVE_FILE, OWNER

ACTION = "save_as_google_file"
REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
PPTX, DOCX, XLSX = (
    OOXML + "presentationml.presentation",
    OOXML + "wordprocessingml.document",
    OOXML + "spreadsheetml.sheet",
)
KINDS = [  # (artifact media type, native type Google must store, editor URL prefix)
    pytest.param(PPTX, GAPPS + "presentation", "https://docs.google.com/presentation/d/", "deck.pptx", id="deck"),
    pytest.param(DOCX, GAPPS + "document", "https://docs.google.com/document/d/", "memo.docx", id="doc"),
    pytest.param(XLSX, GAPPS + "spreadsheet", "https://docs.google.com/spreadsheets/d/", "model.xlsx", id="sheet"),
]


def _case(g, *, media=PPTX, name="deck.pptx", artifact="art_deck_1", **kw):
    item = g.artifacts.put_file(artifact, name=name, mime_type=media, content=b"PK\x03\x04 ooxml bytes")
    return drive_case(item=item, action_type=ACTION, **kw)


def _states(entries):
    return {e["id"]: e["state"] for e in entries}


def _results(g):
    """The adapter's return value for each side effect the outbox ran (the outbox itself drops it)."""
    results, real = [], g.drive.execute_side_effect

    def wrapper(entry, grant):
        results.append(real(entry, grant))
        return results[-1]

    g.drive.execute_side_effect = wrapper
    return results


def _tilo(g):
    return next(f for f in g.apis.files.values() if f.mime_type == FOLDER_MIME and f.name == "Tilo")


def _natives(g):
    return [f for f in g.apis.files.values() if f.mime_type.startswith(GAPPS) and f.mime_type != FOLDER_MIME]


@pytest.mark.parametrize(("media", "native", "url", "name"), KINDS)
def test_FR_CON_11_a_deck_doc_or_sheet_becomes_a_native_google_file_in_the_tilo_folder(media, native, url, name):
    g = make_gapi_env()
    results = _results(g)
    case = _case(g, media=media, name=name)
    enqueue(g.outbox, case)

    settled = g.outbox.dispatch_due()

    assert _states(settled) == {case["entry"]["id"]: "sent"}
    (made,) = _natives(g)
    assert made.mime_type == native
    assert made.parents == [_tilo(g).id] and _tilo(g).parents == ["root"]
    assert made.name == name.rsplit(".", 1)[0]  # the OOXML extension is dropped; the name stays data
    (upload,) = [r for r in g.apis.writes() if r.url == DRIVE_UPLOAD_API]
    assert upload.params.get("uploadType") == "multipart"
    assert media.encode() in upload.content  # the media part is the OOXML file; Drive does the conversion
    assert results == [
        {"id": made.id, "folder_id": _tilo(g).id, "mime_type": native, "open_url": f"{url}{made.id}/edit"}
    ]


def test_FR_CON_11_a_native_file_tilo_made_can_be_listed_without_being_picked():
    g = make_gapi_env()
    enqueue(g.outbox, _case(g))
    g.outbox.dispatch_due()
    (made,) = _natives(g)

    listing = g.drive.list_folder(OWNER, _tilo(g).id)

    assert [f["id"] for f in listing["files"]] == [made.id]


# ---------------------------------------------------------------------------
# The same path as save_file (SEC-03)


def test_FR_CON_11_emits_one_data_transfer_with_the_entrys_authz_and_tier():
    g = make_gapi_env()
    case = _case(g)
    enqueue(g.outbox, case)

    g.outbox.dispatch_due()

    (part,) = [p for p in g.emitted if p["type"] == "data.transfer"]
    assert part["authz"] == case["entry"]["authz"]
    assert part["data"]["connector"] == "google_drive" and part["data"]["action_type"] == ACTION
    assert part["data"]["risk_tier"] == "T1" and part["data"]["artifact"] == case["entry"]["item"]


def test_FR_CON_11_a_direct_call_without_a_grant_is_refused_before_any_token_or_request():
    from tilo_connectors.errors import MissingGrant

    g = make_gapi_env()
    case = _case(g)

    with pytest.raises(MissingGrant):
        g.drive.execute_side_effect(case["entry"], None)

    assert g.apis.requests == [] and g.spy.asked == []


def test_FR_CON_11_adds_no_public_method_to_the_drive_adapter():
    g = make_gapi_env()
    for name in ("save_as_google_file", "create_slides", "create_doc", "create_sheet", "convert"):
        assert not hasattr(g.drive, name), f"DriveAdapter exposes a direct path: {name}"


def test_FR_CON_11_every_call_asks_for_drive_file_only():
    g = make_gapi_env()
    enqueue(g.outbox, _case(g))
    g.outbox.dispatch_due()

    assert g.spy.asked
    for user, connector, scopes in g.spy.asked:
        assert (user, connector) == (OWNER, "google_drive") and set(scopes) == {DRIVE_FILE}, scopes


def test_FR_CON_11_config_declares_the_action_with_drive_file_a_tier_and_an_approval_gate():
    from tilo_connectors.registry import load_registry

    drive = load_registry(REPO_ROOT / "config" / "connectors.yaml").get("google_drive")
    action = {a["id"]: a for a in drive["actions"]}[ACTION]
    tiers = yaml.safe_load((REPO_ROOT / "config" / "autonomy.yaml").read_text(encoding="utf-8"))["actions"]

    assert action["capability"] == "write" and action["gate_type"] == "approval"
    assert action["risk_tier"] == tiers[ACTION] == "T1"
    assert not action["irreversible"]
    for capability, scopes in drive["scopes"].items():  # no scope added for Slides, Docs or Sheets
        assert scopes == [DRIVE_FILE], capability


# ---------------------------------------------------------------------------
# Exactly once


def test_FR_CON_11_a_lost_upload_response_retried_makes_one_native_file():
    g = make_gapi_env()
    results = _results(g)
    case = _case(g)
    enqueue(g.outbox, case)
    g.apis.lose_response(lambda r: r.url == DRIVE_UPLOAD_API)

    assert g.outbox.dispatch_due() == []
    settled = g.outbox.dispatch_due()

    assert _states(settled) == {case["entry"]["id"]: "sent"}
    assert len(_natives(g)) == 1
    assert results[-1]["id"] == _natives(g)[0].id and results[-1]["open_url"].endswith(f"{_natives(g)[0].id}/edit")


def test_FR_CON_11_another_instance_retrying_a_lost_upload_makes_one_native_file():
    g = make_gapi_env()
    enqueue(g.outbox, _case(g))
    g.apis.lose_response(lambda r: r.url == DRIVE_UPLOAD_API)
    g.outbox.dispatch_due()

    other_outbox, _, _ = g.new_outbox()
    g.env.clock.advance(31)
    other_outbox.dispatch_due()

    assert len(_natives(g)) == 1


def test_FR_CON_11_the_same_idempotency_key_enqueued_twice_makes_one_native_file():
    g = make_gapi_env()
    first = _case(g, idempotency_key="r_village_basic_1:U9:save_as_google_file:0001")
    enqueue(g.outbox, first)
    enqueue(g.outbox, first)

    g.outbox.dispatch_due()
    g.outbox.dispatch_due()

    assert len(_natives(g)) == 1


# ---------------------------------------------------------------------------
# Failures map to the connector error taxonomy


@pytest.mark.parametrize(
    ("media", "kind"),
    [("application/pdf", "file"), ("text/markdown", "file"), (PPTX, "email")],
    ids=["pdf", "markdown", "not_a_file"],
)
def test_FR_CON_11_an_artifact_that_is_not_a_deck_doc_or_sheet_is_refused_without_a_request(media, kind):
    g = make_gapi_env()
    if kind == "email":
        item = g.artifacts.put_email("art_mail_1")
    else:
        item = g.artifacts.put_file("art_pdf_1", name="a.pdf", mime_type=media)
    case = drive_case(item=item, action_type=ACTION)
    enqueue(g.outbox, case)

    settled = g.outbox.dispatch_due()

    assert _states(settled) == {case["entry"]["id"]: "failed"}  # SideEffectRefused: final
    assert g.apis.writes() == [] and _natives(g) == []
    assert [p for p in g.emitted if p["type"] == "data.transfer"] == []


def test_FR_CON_11_drive_rejecting_the_conversion_is_final_and_nothing_is_emitted():
    g = make_gapi_env()
    case = _case(g)
    enqueue(g.outbox, case)
    g.apis.fail_next(400, when=lambda r: r.url == DRIVE_UPLOAD_API)

    settled = g.outbox.dispatch_due()

    assert _states(settled) == {case["entry"]["id"]: "failed"}
    assert [p for p in g.emitted if p["type"] == "data.transfer"] == []


def test_FR_CON_11_a_destination_other_than_the_tilo_folder_is_refused():
    g = make_gapi_env()
    own = g.apis.seed_folder(name="Tilo")  # the user's own folder, not the one Tilo made
    case = _case(g, destination=own)
    enqueue(g.outbox, case)

    settled = g.outbox.dispatch_due()

    assert _states(settled) == {case["entry"]["id"]: "failed"}
    assert not [r for r in g.apis.writes() if r.url == DRIVE_UPLOAD_API]


def test_FR_CON_11_a_429_stays_due_emits_rate_limited_and_succeeds_once_after_recovery():
    g = make_gapi_env()
    enqueue(g.outbox, _case(g))
    g.apis.fail_next(429, times=10, headers={"Retry-After": "1"}, when=lambda r: r.url == DRIVE_UPLOAD_API)

    assert g.outbox.dispatch_due() == []
    g.apis.clear_failures()
    g.outbox.dispatch_due()

    assert len(_natives(g)) == 1
    assert [p["data"]["connector"] for p in g.parts_of("connection.rate_limited")][:1] == ["google_drive"]


def test_FR_CON_11_a_5xx_stays_due_and_makes_one_native_file_after_recovery():
    g = make_gapi_env()
    enqueue(g.outbox, _case(g))
    g.apis.fail_next(503, times=10, when=lambda r: r.url == DRIVE_UPLOAD_API)

    assert g.outbox.dispatch_due() == []
    g.apis.clear_failures()
    g.outbox.dispatch_due()

    assert len(_natives(g)) == 1


def test_FR_CON_11_no_drive_connection_keeps_the_entry_due_and_writes_nothing():
    g = make_gapi_env(drive_scopes=None)
    enqueue(g.outbox, _case(g))

    assert g.outbox.dispatch_due() == []

    assert g.apis.writes() == []
    g.env.connect(OWNER, "google_drive", [DRIVE_FILE])
    assert [e["state"] for e in g.outbox.dispatch_due()] == ["sent"]


def test_FR_CON_11_save_file_still_stores_a_pptx_unconverted():
    g = make_gapi_env()
    item = g.artifacts.put_file("art_deck_2", name="deck.pptx", mime_type=PPTX, content=b"PK\x03\x04 ooxml bytes")
    enqueue(g.outbox, drive_case(item=item))

    g.outbox.dispatch_due()

    (stored,) = [f for f in g.apis.files.values() if f.name == "deck.pptx"]
    assert stored.mime_type == PPTX and _natives(g) == []
