"""FR-INT-01 (text files): .txt, .md and .json are accepted as uploads, read as UTF-8 text with the same caps and the
same screening as CSV, and stored under the artifact contract's text media types (a .txt is plain Markdown).

The route is the real `POST /intake` on the I2 rig; the pure extraction half is pinned in packages/planning.
"""

from __future__ import annotations

import json

import pytest
from test_I2_FR_INT_02_run_uploads import post, uploads  # noqa: F401  (the fixture)
from tilo_memory.artifacts import Scope
from tilo_planning.extraction import MAX_TEXT_CHARS, ExtractionError, extract, file_type, stored_text

CASES = [
    ("notes.txt", b"Meeting notes: ship the quote on Friday.", "text/markdown"),
    ("README.md", b"# Plan\n\n- call the vendor", "text/markdown"),
    ("data.json", json.dumps({"vendor": "Acme", "total": 42}).encode(), "application/json"),
    ("UPPER.TXT", b"Shouting file name", "text/markdown"),
]


@pytest.mark.parametrize(("name", "data", "media"), CASES)
def test_FR_INT_01_a_text_file_is_accepted_and_stored_as_text(uploads, name, data, media):  # noqa: F811
    client, _, artifacts, _ = uploads
    response = post(client, [("files", (name, data, "application/octet-stream"))])
    assert response.status_code == 201, response.text
    body = response.json()
    (file,) = body["files"]
    assert file["status"] == "ok" and file["kind"] == "converted", file
    scope = Scope("org_tilo", body["world_id"], "u_intake")
    assert artifacts.read(scope, file["artifact"]) == data
    assert artifacts.head(scope, file["artifact"]).record["media_type"] == media


@pytest.mark.parametrize(
    ("name", "data", "error"),
    [
        ("notes.txt", b"\xff\xfe broken", "not valid UTF-8 text"),
        ("notes.md", b"   \n", "empty file"),
        ("data.json", b"", "empty file"),
    ],
)
def test_FR_INT_01_a_bad_text_file_fails_before_it_is_stored(uploads, name, data, error):  # noqa: F811
    client, _, artifacts, _ = uploads
    file = post(client, [("files", (name, data, "text/plain"))]).json()["files"][0]
    assert file["status"] == "failed" and error in file["error"]
    assert artifacts.retention().records() == []


def test_FR_INT_01_an_injection_in_a_text_file_is_flagged_and_never_a_brief_source(uploads, store):  # noqa: F811
    from _api_contracts_lib import INJECTION_PHRASE, make_safety_provider

    client, _, artifacts, _ = uploads
    artifacts._screener = make_safety_provider()  # the store's one verdict, as for a flagged CSV
    body = post(client, [("files", ("trap.txt", INJECTION_PHRASE.encode(), "text/plain"))]).json()
    assert body["files"][0]["safety_flagged"]
    assert all(s["kind"] != "file" for s in store.tasks[body["task_id"]].brief["sources"])


def test_FR_INT_01_the_types_are_listed_and_read_by_the_same_extraction():
    for name in ("a.txt", "a.md", "a.json"):
        kind, _mime, magic = file_type(name)  # type: ignore[misc]
        assert kind == "converted" and magic == b""
    assert extract("a.md", b"# hi\n") == "# hi\n"
    assert stored_text("application/json", b'{"a": 1}') == '{"a": 1}'
    assert stored_text("text/markdown", "café".encode()) == "café"
    assert file_type("a.exe") is None and file_type("a.rtf") is None


def test_FR_INT_01_a_text_file_over_the_same_cap_as_csv_is_refused():
    with pytest.raises(ExtractionError, match="too large"):
        extract("big.txt", b"x" * (MAX_TEXT_CHARS + 1))
    with pytest.raises(ExtractionError, match="too large"):
        extract("big.json", b"x" * (4 * MAX_TEXT_CHARS + 1))
