"""FR-CON-05: Drive adapter — picker-based read; write to a Tilo folder (PRD 12.2, 12.6).

Acceptance test: "Files outside the picked set are never read". Writes are outbox side effects at
the least scope (drive.file), exactly once. API_FR_CON_04_05.md "DriveAdapter".
"""

from __future__ import annotations

import inspect

import pytest
from _gapi_lib import DRIVE_API, DRIVE_UPLOAD_API, FOLDER_MIME, drive_case, enqueue, make_gapi_env
from _oauth_lib import DRIVE_FILE, OTHER, OWNER
from hypothesis import given, settings
from hypothesis import strategies as st

DRIVE_READS = {"get_metadata", "list_folder", "download"}


def _states(entries: list[dict]) -> dict[str, str]:
    return {e["id"]: e["state"] for e in entries}


def _tilo_folders(g) -> list:
    return [f for f in g.apis.files.values() if f.mime_type == FOLDER_MIME and f.name == "Tilo"]


# ---------------------------------------------------------------------------
# Read: the picked set


def test_FR_CON_05_a_picked_file_can_be_read_metadata_and_content():
    g = make_gapi_env()
    fid = g.apis.seed_file(name="Q3 figures.pdf", content=b"%PDF-1.7 q3", parents=("folder_user_1",))
    g.picks.add(OWNER, [fid])

    meta = g.drive.get_metadata(OWNER, fid)
    data = g.drive.download(OWNER, fid)

    assert meta == {
        "id": fid,
        "name": "Q3 figures.pdf",
        "mime_type": "application/pdf",
        "size": 11,
        "parents": ["folder_user_1"],
    }
    assert data == b"%PDF-1.7 q3"


@pytest.mark.parametrize("call", ["get_metadata", "download", "list_folder"])
def test_FR_CON_05_a_file_outside_the_picked_set_is_never_read(call):
    from tilo_connectors.adapters import NotPicked

    g = make_gapi_env()
    picked = g.apis.seed_file(name="picked.pdf")
    secret = g.apis.seed_file(name="salaries.xlsx")
    g.picks.add(OWNER, [picked])

    with pytest.raises(NotPicked):
        getattr(g.drive, call)(OWNER, secret)

    assert g.apis.reads_naming(secret) == [], "no request may name a file outside the picked set"


def test_FR_CON_05_another_users_picks_open_nothing():
    from tilo_connectors.adapters import NotPicked

    g = make_gapi_env()
    fid = g.apis.seed_file(name="theirs.pdf")
    g.picks.add(OTHER, [fid])

    with pytest.raises(NotPicked):
        g.drive.download(OWNER, fid)

    assert g.apis.reads_naming(fid) == []


def test_FR_CON_05_a_picked_folder_lists_its_files_and_those_can_be_read():
    g = make_gapi_env()
    folder = g.apis.seed_folder(name="Reports")
    child = g.apis.seed_file(name="march.pdf", content=b"march", parents=(folder,))
    g.apis.seed_file(name="elsewhere.pdf", parents=("root",))
    g.picks.add(OWNER, [folder])

    listing = g.drive.list_folder(OWNER, folder)

    assert [f["id"] for f in listing["files"]] == [child]
    assert listing["files"][0]["name"] == "march.pdf"
    assert listing["next_page_token"] is None
    assert g.drive.download(OWNER, child) == b"march"


def test_FR_CON_05_listing_an_unpicked_folder_is_refused_before_any_request():
    from tilo_connectors.adapters import NotPicked

    g = make_gapi_env()
    folder = g.apis.seed_folder(name="Private")
    g.apis.seed_file(name="diary.txt", parents=(folder,))

    with pytest.raises(NotPicked):
        g.drive.list_folder(OWNER, folder)

    assert g.apis.reads_naming(folder) == []


@settings(max_examples=30, deadline=None)
@given(
    n_files=st.integers(min_value=2, max_value=7),
    data=st.data(),
)
def test_FR_CON_05_property_no_sequence_of_reads_touches_an_unpicked_file(n_files, data):
    from tilo_connectors.adapters import NotPicked

    g = make_gapi_env()
    ids = [g.apis.seed_file(name=f"file{i}.txt", content=f"content {i}".encode()) for i in range(n_files)]
    picked = data.draw(st.sets(st.sampled_from(ids), max_size=n_files - 1), label="picked")
    g.picks.add(OWNER, picked)
    calls = data.draw(
        st.lists(st.tuples(st.sampled_from(["get_metadata", "download"]), st.sampled_from(ids)), min_size=1, max_size=8)
    )

    for call, fid in calls:
        if fid in picked:
            getattr(g.drive, call)(OWNER, fid)
        else:
            with pytest.raises(NotPicked):
                getattr(g.drive, call)(OWNER, fid)

    for fid in set(ids) - set(picked):
        assert g.apis.reads_naming(fid) == []


def test_FR_CON_05_a_download_over_the_limit_never_fetches_the_content():
    from tilo_connectors.adapters import FileTooLarge

    g = make_gapi_env(max_download_bytes=1000)
    fid = g.apis.seed_file(name="huge.bin", content=b"z" * 1001)
    g.picks.add(OWNER, [fid])

    with pytest.raises(FileTooLarge):
        g.drive.download(OWNER, fid)

    assert not [r for r in g.apis.requests if r.params.get("alt") == "media"]


def test_FR_CON_05_the_default_download_limit_is_25_mib():
    from tilo_connectors.adapters import MAX_DOWNLOAD_BYTES, FileTooLarge

    assert MAX_DOWNLOAD_BYTES == 25 * 1024 * 1024
    g = make_gapi_env()
    fid = g.apis.seed_file(name="huge.bin", content=b"z" * (MAX_DOWNLOAD_BYTES + 1))
    g.picks.add(OWNER, [fid])

    with pytest.raises(FileTooLarge):
        g.drive.download(OWNER, fid)


def test_FR_CON_05_every_drive_call_asks_the_broker_for_drive_file_only():
    g = make_gapi_env()
    folder = g.apis.seed_folder(name="Reports")
    fid = g.apis.seed_file(name="a.pdf", parents=(folder,))
    g.picks.add(OWNER, [folder, fid])
    g.drive.list_folder(OWNER, folder)
    g.drive.get_metadata(OWNER, fid)
    g.drive.download(OWNER, fid)
    enqueue(g.outbox, drive_case(item=g.artifacts.put_file("art_report_1")))
    g.outbox.dispatch_due()

    assert g.spy.asked
    for user, connector, scopes in g.spy.asked:
        assert (user, connector) == (OWNER, "google_drive")
        assert set(scopes) == {DRIVE_FILE}, scopes


# ---------------------------------------------------------------------------
# Write: save_file to the Tilo folder, through the outbox only


def test_FR_CON_05_save_file_through_the_outbox_creates_the_tilo_folder_and_the_file():
    g = make_gapi_env()
    item = g.artifacts.put_file(
        "art_report_1", name="Q3 report.pdf", mime_type="application/pdf", content=b"%PDF-1.7 report"
    )
    case = drive_case(item=item, destination=None)
    enqueue(g.outbox, case)

    settled = g.outbox.dispatch_due()

    assert _states(settled) == {case["entry"]["id"]: "sent"}
    (folder,) = _tilo_folders(g)
    assert folder.parents == ["root"]
    saved = [f for f in g.apis.files.values() if f.mime_type != FOLDER_MIME and f.name == "Q3 report.pdf"]
    assert len(saved) == 1
    assert saved[0].parents == [folder.id]
    assert saved[0].content == b"%PDF-1.7 report"
    assert saved[0].mime_type == "application/pdf"
    uploads = [r for r in g.apis.writes() if r.url == DRIVE_UPLOAD_API]
    assert len(uploads) == 1 and uploads[0].params.get("uploadType") == "multipart"


def test_FR_CON_05_later_saves_reuse_the_one_tilo_folder():
    g = make_gapi_env()
    enqueue(g.outbox, drive_case(item=g.artifacts.put_file("art_r1", name="one.pdf")))
    g.outbox.dispatch_due()
    (folder,) = _tilo_folders(g)
    enqueue(g.outbox, drive_case(item=g.artifacts.put_file("art_r2", name="two.pdf"), destination=folder.id))
    enqueue(g.outbox, drive_case(item=g.artifacts.put_file("art_r3", name="three.pdf"), destination=None))

    g.outbox.dispatch_due()

    assert len(_tilo_folders(g)) == 1
    names = sorted(f.name for f in g.apis.files.values() if f.parents == [folder.id])
    assert names == ["one.pdf", "three.pdf", "two.pdf"]


def test_FR_CON_05_another_instance_finds_the_existing_tilo_folder():
    g = make_gapi_env()
    enqueue(g.outbox, drive_case(item=g.artifacts.put_file("art_r1", name="one.pdf")))
    g.outbox.dispatch_due()

    other_outbox, _, _ = g.new_outbox()
    enqueue(other_outbox, drive_case(item=g.artifacts.put_file("art_r2", name="two.pdf")))
    other_outbox.dispatch_due()

    assert len(_tilo_folders(g)) == 1


def test_FR_CON_05_a_folder_the_user_made_is_not_the_tilo_folder_and_is_never_written():
    g = make_gapi_env()
    own = g.apis.seed_folder(name="Tilo")  # the user's own folder, even if it has the same name
    g.picks.add(OWNER, [own])
    case = drive_case(item=g.artifacts.put_file("art_r1"), destination=own)
    enqueue(g.outbox, case)

    settled = g.outbox.dispatch_due()

    assert _states(settled) == {case["entry"]["id"]: "failed"}
    assert not [r for r in g.apis.writes() if r.url == DRIVE_UPLOAD_API]
    assert not [f for f in g.apis.files.values() if own in f.parents]
    assert [p for p in g.emitted if p["type"] == "data.transfer"] == []


def test_FR_CON_05_a_file_tilo_saved_can_be_read_without_being_picked():
    g = make_gapi_env()
    enqueue(g.outbox, drive_case(item=g.artifacts.put_file("art_r1", name="mine.pdf", content=b"saved bytes")))
    g.outbox.dispatch_due()
    saved = next(f for f in g.apis.files.values() if f.name == "mine.pdf")

    assert g.drive.download(OWNER, saved.id) == b"saved bytes"


def test_FR_CON_05_the_file_name_is_data_never_a_path():
    g = make_gapi_env()
    name = "../../Shared/payroll\r\nContent-Type: text/html.pdf"
    enqueue(g.outbox, drive_case(item=g.artifacts.put_file("art_r1", name=name)))

    g.outbox.dispatch_due()

    (folder,) = _tilo_folders(g)
    created = [f for f in g.apis.files.values() if f.mime_type != FOLDER_MIME]
    assert len(created) == 1
    assert created[0].parents == [folder.id]
    assert created[0].content == b"%PDF-1.7 fake report"


def test_FR_CON_05_save_emits_one_data_transfer_with_the_entrys_authz():
    g = make_gapi_env()
    case = drive_case(item=g.artifacts.put_file("art_r1"))
    enqueue(g.outbox, case)

    g.outbox.dispatch_due()

    (part,) = [p for p in g.emitted if p["type"] == "data.transfer"]
    assert part["authz"] == case["entry"]["authz"]
    assert part["data"] == {
        "connector": "google_drive",
        "action_type": "save_file",
        "direction": "out",
        "artifact": case["entry"]["item"],
        "outbox_id": case["entry"]["id"],
        "risk_tier": "T1",
    }


# ---------------------------------------------------------------------------
# Exactly once


def test_FR_CON_05_a_lost_upload_response_retried_uploads_exactly_once():
    g = make_gapi_env()
    case = drive_case(item=g.artifacts.put_file("art_r1", name="once.pdf"))
    enqueue(g.outbox, case)
    g.apis.lose_response(lambda r: r.url == DRIVE_UPLOAD_API)

    assert g.outbox.dispatch_due() == []
    settled = g.outbox.dispatch_due()

    assert _states(settled) == {case["entry"]["id"]: "sent"}
    assert len([f for f in g.apis.files.values() if f.name == "once.pdf"]) == 1


def test_FR_CON_05_a_lost_folder_creation_response_still_makes_one_tilo_folder():
    g = make_gapi_env()
    enqueue(g.outbox, drive_case(item=g.artifacts.put_file("art_r1", name="once.pdf")))
    g.apis.lose_response(lambda r: r.method == "POST" and r.url == f"{DRIVE_API}/files")

    g.outbox.dispatch_due()
    g.outbox.dispatch_due()

    assert len(_tilo_folders(g)) == 1
    assert len([f for f in g.apis.files.values() if f.name == "once.pdf"]) == 1


def test_FR_CON_05_another_instance_retrying_a_lost_upload_uploads_once():
    g = make_gapi_env()
    enqueue(g.outbox, drive_case(item=g.artifacts.put_file("art_r1", name="once.pdf")))
    g.apis.lose_response(lambda r: r.url == DRIVE_UPLOAD_API)
    g.outbox.dispatch_due()

    other_outbox, _, _ = g.new_outbox()
    g.env.clock.advance(31)
    other_outbox.dispatch_due()

    assert len([f for f in g.apis.files.values() if f.name == "once.pdf"]) == 1


# ---------------------------------------------------------------------------
# SEC-03


def test_FR_CON_05_direct_save_without_a_grant_is_refused_before_any_token_or_request():
    from tilo_connectors.errors import MissingGrant

    g = make_gapi_env()
    case = drive_case(item=g.artifacts.put_file("art_r1"))

    with pytest.raises(MissingGrant):
        g.drive.execute_side_effect(case["entry"], None)

    assert g.apis.requests == [] and g.spy.asked == []


def test_FR_CON_05_drive_adapter_has_no_direct_write_method():
    g = make_gapi_env()
    for action in ("save_file", "upload", "create_file", "create_folder", "send_reply"):
        assert not hasattr(g.drive, action), f"DriveAdapter exposes a direct path: {action}"
    public = {
        name
        for name, value in inspect.getmembers(type(g.drive))
        if not name.startswith("_") and callable(value) and not isinstance(value, property)
    }
    assert public == DRIVE_READS | {"execute_side_effect"}, sorted(public)
    assert g.drive.id == "google_drive"


def test_FR_CON_05_reads_send_only_get_requests():
    g = make_gapi_env()
    fid = g.apis.seed_file(name="a.pdf")
    g.picks.add(OWNER, [fid])

    g.drive.get_metadata(OWNER, fid)
    g.drive.download(OWNER, fid)

    assert g.apis.writes() == []
