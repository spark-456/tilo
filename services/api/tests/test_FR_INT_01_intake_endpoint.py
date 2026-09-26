"""FR-INT-01 (PRD 7.1) HTTP surface: `POST /intake` on `tilo-api`. See conftest.py's module
docstring for the request/response contract this pass fixes. `packages/planning/tests/` covers
the deep per-limit / nothing-stored behaviour at the `tilo_planning.intake` unit level; these
tests check the HTTP contract a web/mobile client actually calls through.
"""

from __future__ import annotations

import statistics
import time

from _api_contracts_lib import assert_valid_event, make_docx_bytes, make_png_bytes


def _multipart_files(entries: list[tuple[str, bytes]]) -> list[tuple[str, tuple[str, bytes, str]]]:
    return [("files", (name, content, "application/octet-stream")) for name, content in entries]


def test_FR_INT_01_post_intake_returns_task_with_event_and_per_file_status(client, repo_root, registry):
    files = [
        ("brief.docx", make_docx_bytes("The quarterly numbers are strong.")),
        ("photo.png", make_png_bytes()),
        ("photo2.png", make_png_bytes()),
    ]

    response = client.post(
        "/intake",
        data={"text": "Prepare the weekly supplier summary."},
        files=_multipart_files(files),
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["task_id"]
    assert body["world_id"].startswith("w_")
    assert body["run_id"].startswith("r_")
    assert body["event"]["type"] == "world.requested"
    assert_valid_event(repo_root, registry, body["event"])

    assert len(body["files"]) == 3
    returned_names = {f["filename"] for f in body["files"]}
    assert returned_names == {name for name, _ in files}
    for file_status in body["files"]:
        assert file_status["status"] == "ok"
        assert file_status["artifact"]["version"] == 1


def test_FR_INT_01_post_intake_rejects_text_over_4000_chars(client):
    response = client.post("/intake", data={"text": "x" * 4001}, files=[])

    assert response.status_code == 422, response.text
    body = response.json()
    assert isinstance(body.get("error"), str) and body["error"]


def test_FR_INT_01_post_intake_rejects_more_than_10_files(client):
    files = [(f"f{i}.png", make_png_bytes()) for i in range(11)]

    response = client.post("/intake", data={"text": "Some task."}, files=_multipart_files(files))

    assert response.status_code == 422, response.text
    body = response.json()
    assert isinstance(body.get("error"), str) and body["error"]


def test_FR_INT_01_post_intake_rejects_disallowed_file_type(client):
    response = client.post(
        "/intake",
        data={"text": "Some task."},
        files=_multipart_files([("macro.exe", b"MZ...")]),
    )

    assert response.status_code == 422, response.text
    body = response.json()
    assert isinstance(body.get("error"), str) and body["error"]


def test_FR_INT_01_submit_p50_under_4s_via_http(client):
    files = [
        ("brief.docx", make_docx_bytes("The quarterly numbers are strong.")),
        ("photo.png", make_png_bytes()),
        ("photo2.png", make_png_bytes()),
    ]
    samples = []
    for _ in range(5):
        start = time.perf_counter()
        response = client.post(
            "/intake",
            data={"text": "Prepare the weekly supplier summary."},
            files=_multipart_files(files),
        )
        samples.append(time.perf_counter() - start)
        assert response.status_code == 201, response.text

    p50 = statistics.median(samples)
    assert p50 < 4.0, f"FR-INT-01: p50 POST /intake time {p50:.3f}s exceeds the 4s budget ({samples})"
