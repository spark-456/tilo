"""FR-CON-11 hardening (issue #415, from the #409 security review): a native Google file only from tilo-render,
the id Drive returns is checked before it is stored, and a shared Tilo folder is refused. No network.
"""

from __future__ import annotations

import pytest
from _gapi_lib import DRIVE_UPLOAD_API, FOLDER_MIME, GAPPS, OOXML, FakeApiResponse, drive_case, enqueue, make_gapi_env
from _oauth_lib import OWNER

PPTX = OOXML + "presentationml.presentation"
BYTES = b"PK\x03\x04 ooxml bytes"


def _natives(g):
    return [f for f in g.apis.files.values() if f.mime_type.startswith(GAPPS) and f.mime_type != FOLDER_MIME]


def _deck(g, *, origin_kind, action="save_as_google_file", name="deck.pptx", artifact="art_415_1", **kw):
    item = g.artifacts.put_file(artifact, name=name, mime_type=PPTX, content=BYTES, origin_kind=origin_kind)
    return drive_case(item=item, action_type=action, **kw)


def _failed(g, case):
    return {e["id"]: e["state"] for e in g.outbox.dispatch_due()} == {case["entry"]["id"]: "failed"}


@pytest.mark.parametrize("origin", ["upload", "unit", "restore", None], ids=["upload", "unit", "restore", "unknown"])
def test_FR_CON_11_only_a_render_output_converts_to_a_native_google_file(origin):
    g = make_gapi_env()
    case = _deck(g, origin_kind=origin)
    enqueue(g.outbox, case)

    assert _failed(g, case)  # SideEffectRefused: final, before any request
    assert g.apis.requests == [] and g.spy.asked == [] and _natives(g) == []


def test_FR_CON_11_a_malformed_origin_is_refused_like_an_unknown_one():
    g = make_gapi_env()
    item = g.artifacts.put_file("art_415_2", name="deck.pptx", mime_type=PPTX, content=BYTES)
    g.artifacts._items[("art_415_2", 1)]["origin"] = "render"  # a string, not {kind: render}
    case = drive_case(item=item, action_type="save_as_google_file")
    enqueue(g.outbox, case)

    assert _failed(g, case) and g.apis.requests == []


def test_FR_CON_11_save_file_still_stores_an_uploaded_ooxml_file_unconverted():
    g = make_gapi_env()
    case = _deck(g, origin_kind="upload", action="save_file")
    enqueue(g.outbox, case)

    assert [e["state"] for e in g.outbox.dispatch_due()] == ["sent"] and _natives(g) == []


def test_FR_CON_11_the_extension_is_dropped_only_at_the_very_end_of_the_name():
    g = make_gapi_env()
    case = _deck(g, origin_kind="render", name="deck.pptx\n")  # `$` would match before the newline
    enqueue(g.outbox, case)

    g.outbox.dispatch_due()

    (made,) = _natives(g)
    assert made.name == "deck.pptx\n"


# -- the id Drive returns -----------------------------------------------------------------------------------


@pytest.mark.parametrize("action", ["save_file", "save_as_google_file"])
def test_FR_CON_11_an_id_drive_returns_that_is_not_a_valid_id_is_final_and_never_remembered(action):
    g = make_gapi_env()
    real = g.apis._drive_upload
    g.apis._drive_upload = lambda req: FakeApiResponse(200, {"id": "../files/x?y=1"})
    case = _deck(g, origin_kind="render", action=action)
    enqueue(g.outbox, case)

    assert _failed(g, case)
    assert not any("." in i or "/" in i for i in g.drive._known(g.drive._created, OWNER))
    g.apis._drive_upload = real
    assert g.outbox.dispatch_due() == []  # final: not retried, nothing more uploaded
    assert len([r for r in g.apis.writes() if r.url == DRIVE_UPLOAD_API]) <= 1


# -- a shared Tilo folder -----------------------------------------------------------------------------------


def _tilo(g):
    return next(f for f in g.apis.files.values() if f.mime_type == FOLDER_MIME and f.name == "Tilo")


@pytest.mark.parametrize(
    ("action", "origin"), [("save_file", "upload"), ("save_as_google_file", "render")], ids=["save_file", "native"]
)
def test_FR_CON_11_a_save_into_a_shared_tilo_folder_is_refused_before_the_upload(action, origin):
    g = make_gapi_env()
    enqueue(g.outbox, _deck(g, origin_kind=origin, action=action, artifact="art_415_a"))
    g.outbox.dispatch_due()  # the first save makes the Tilo folder
    _tilo(g).shared = True  # the user later shares it, so a save there reaches other people
    uploads = len([r for r in g.apis.writes() if r.url == DRIVE_UPLOAD_API])
    second = _deck(g, origin_kind=origin, action=action, artifact="art_415_b")
    enqueue(g.outbox, second)

    assert _failed(g, second)
    assert len([r for r in g.apis.writes() if r.url == DRIVE_UPLOAD_API]) == uploads


def test_FR_CON_11_a_shared_folder_named_as_the_destination_is_refused_too():
    g = make_gapi_env()
    enqueue(g.outbox, _deck(g, origin_kind="upload", action="save_file", artifact="art_415_c"))
    g.outbox.dispatch_due()
    _tilo(g).shared = True
    second = _deck(g, origin_kind="upload", action="save_file", artifact="art_415_d", destination=_tilo(g).id)
    enqueue(g.outbox, second)

    assert _failed(g, second)


def test_FR_CON_11_an_unshared_tilo_folder_still_takes_the_save():
    g = make_gapi_env()
    enqueue(g.outbox, _deck(g, origin_kind="upload", action="save_file", artifact="art_415_e"))
    enqueue(g.outbox, _deck(g, origin_kind="upload", action="save_file", artifact="art_415_f", name="b.pptx"))

    assert [e["state"] for e in g.outbox.dispatch_due()] == ["sent", "sent"]
