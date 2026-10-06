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


# -- #415 leftovers: PossiblySent on a bad id, `shared` asked on the upload, a non-boolean `shared` -----------


def _with(resp, **fields):
    return FakeApiResponse(resp.status_code, {**resp.json(), **fields})


def _alerting_outbox(g):
    from tilo_connectors.outbox import Outbox

    alerts: list = []
    clock = g.env.clock
    return Outbox(
        g.store, {"google_drive": g.drive}, emit=g.env.emitted.append, clock=clock, alert=alerts.append
    ), alerts


def _states(outbox):
    return {e["id"]: e["state"] for e in outbox.dispatch_due()}


def test_FR_CON_11_a_bad_id_after_the_upload_alerts_a_person():
    g = make_gapi_env()
    g.apis._drive_upload = lambda req: FakeApiResponse(200, {"id": "../files/x?y=1", "shared": False})
    outbox, alerts = _alerting_outbox(g)
    case = _deck(g, origin_kind="render")
    enqueue(outbox, case)

    assert _states(outbox) == {case["entry"]["id"]: "failed"}
    assert [a["data"]["alert_id"] for a in alerts] == [case["entry"]["id"]]  # the file exists: not a quiet refusal
    assert outbox.dispatch_due() == []


def test_FR_CON_11_a_bad_id_on_an_earlier_attempts_file_alerts_a_person():
    g = make_gapi_env()
    real = g.apis._drive
    found = FakeApiResponse(200, {"files": [{"id": "a/b", "parents": []}]})
    g.apis._drive = lambda req, path: (
        found
        if req.method == "GET" and path == "/files" and "tilo_save" in str(req.params.get("q"))
        else real(req, path)
    )
    outbox, alerts = _alerting_outbox(g)
    case = _deck(g, origin_kind="render")
    enqueue(outbox, case)

    assert _states(outbox) == {case["entry"]["id"]: "failed"}
    assert [a["data"]["alert_id"] for a in alerts] == [case["entry"]["id"]]
    assert [r for r in g.apis.requests if r.url == DRIVE_UPLOAD_API] == []


def test_FR_CON_11_the_upload_asks_for_the_shared_flag():
    g = make_gapi_env()
    enqueue(g.outbox, _deck(g, origin_kind="render"))
    g.outbox.dispatch_due()

    (upload,) = [r for r in g.apis.requests if r.url == DRIVE_UPLOAD_API]
    assert upload.params["fields"] == "id,shared"


@pytest.mark.parametrize("shared", [True, None, "false", "False", 0, "", "true"], ids=repr)
def test_FR_CON_11_a_saved_file_not_provably_unshared_alerts_a_person(shared):
    g = make_gapi_env()
    real = g.apis._drive_upload
    g.apis._drive_upload = lambda req: _with(real(req), shared=shared)  # shared after the check, or an odd answer
    outbox, alerts = _alerting_outbox(g)
    case = _deck(g, origin_kind="render")
    enqueue(outbox, case)

    assert _states(outbox) == {case["entry"]["id"]: "failed"}
    assert [a["data"]["alert_id"] for a in alerts] == [case["entry"]["id"]]
    assert outbox.dispatch_due() == []  # never retried


@pytest.mark.parametrize("shared", [None, "false", 0, "", "true"], ids=repr)
def test_FR_CON_11_a_folder_check_that_is_not_the_boolean_false_refuses_before_the_upload(shared):
    g = make_gapi_env()
    enqueue(g.outbox, _deck(g, origin_kind="upload", action="save_file", artifact="art_415_h"))
    g.outbox.dispatch_due()  # the first save makes the Tilo folder
    uploads = len([r for r in g.apis.writes() if r.url == DRIVE_UPLOAD_API])
    real = g.apis._drive

    def drive(req, path):
        out = real(req, path)
        if req.method == "GET" and path == f"/files/{_tilo(g).id}":
            return _with(out, shared=shared)
        return out

    g.apis._drive = drive
    second = _deck(g, origin_kind="upload", action="save_file", artifact="art_415_i")
    enqueue(g.outbox, second)

    assert _failed(g, second)
    assert len([r for r in g.apis.writes() if r.url == DRIVE_UPLOAD_API]) == uploads


# -- an earlier attempt's file (OB-03): shared and parent id are checked on the retry too ------------------------


def _earlier_attempt(g, **file):
    """Make the `tilo_save` lookup answer with an earlier attempt's file (a lost answer, then a retry)."""
    real = g.apis._drive
    found = FakeApiResponse(200, {"files": [file]})
    g.apis._drive = lambda req, path: (
        found
        if req.method == "GET" and path == "/files" and "tilo_save" in str(req.params.get("q"))
        else real(req, path)
    )


@pytest.mark.parametrize("shared", [True, None, "false", 0, "true", "<missing>"], ids=repr)
def test_FR_CON_11_an_earlier_attempts_file_not_provably_unshared_alerts_a_person(shared):
    g = make_gapi_env()
    file = {"id": "f_old", "parents": ["p_old"]}
    if shared != "<missing>":
        file["shared"] = shared
    _earlier_attempt(g, **file)
    outbox, alerts = _alerting_outbox(g)
    case = _deck(g, origin_kind="render")
    enqueue(outbox, case)

    assert _states(outbox) == {case["entry"]["id"]: "failed"}  # never `sent` with no alert
    assert [a["data"]["alert_id"] for a in alerts] == [case["entry"]["id"]]
    assert outbox.dispatch_due() == []


def test_FR_CON_11_an_earlier_attempts_lookup_asks_for_the_shared_flag():
    g = make_gapi_env()
    _earlier_attempt(g, id="f_old", parents=["p_old"], shared=False)
    enqueue(g.outbox, _deck(g, origin_kind="render"))
    g.outbox.dispatch_due()

    (lookup,) = [r for r in g.apis.requests if "tilo_save" in str(r.params.get("q"))]
    assert lookup.params["fields"] == "files(id,parents,shared)"


def test_FR_CON_11_an_earlier_attempts_unshared_file_is_found_and_the_entry_is_sent():
    g = make_gapi_env()
    _earlier_attempt(g, id="f_old", parents=["p_old"], shared=False)
    outbox, alerts = _alerting_outbox(g)
    case = _deck(g, origin_kind="render")
    enqueue(outbox, case)

    assert _states(outbox) == {case["entry"]["id"]: "sent"} and alerts == []
    assert [r for r in g.apis.requests if r.url == DRIVE_UPLOAD_API] == []


@pytest.mark.parametrize("parent", ["../x", "a/b", "", 7, None], ids=repr)
def test_FR_CON_11_an_earlier_attempts_file_with_a_bad_parent_id_alerts_a_person(parent):
    g = make_gapi_env()
    _earlier_attempt(g, id="f_old", parents=[parent], shared=False)  # a good file id, a bad parent id
    outbox, alerts = _alerting_outbox(g)
    case = _deck(g, origin_kind="render")
    enqueue(outbox, case)

    assert _states(outbox) == {case["entry"]["id"]: "failed"}
    assert [a["data"]["alert_id"] for a in alerts] == [case["entry"]["id"]]
    assert [r for r in g.apis.requests if r.url == DRIVE_UPLOAD_API] == []
