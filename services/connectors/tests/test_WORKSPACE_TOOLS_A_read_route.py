"""WORKSPACE_TOOLS ticket A / ADR-0048 WT-02, WT-03, WT-06: POST /internal/workspace/read of tilo-connectors.

The rig is ADR-0032 T3's (HB-01 caller, FakeGoogle tokens, FakeKms, in-memory store) with `FakeWorkspace` as the one
Transport for Gmail, Calendar and Drive. No network, no paid call, nothing reads the live switch. Mail, event and
file text are runtime sentinels.
"""

from __future__ import annotations

import base64
import json
import secrets
from typing import Any

import pytest
from _gapi_lib import DRIVE_FILE, GMAIL_COMPOSE, GMAIL_READONLY
from _live_lib import no_external_network as no_external_network  # noqa: F401 - autouse guard
from _meeting_host_lib import OWNER
from _workspace_lib import EVENTS, GAPPS, FakeWorkspace, file_part, header_list, text_part
from test_ADR32_T3_host_routes import Rig
from tilo_connectors.host_routes import MAX_BODY_BYTES
from tilo_connectors.tokens import TokenBroker

ROUTE = "/internal/workspace/read"
CALENDAR_READONLY = "https://www.googleapis.com/auth/calendar.readonly"
CONNECTED, NOW = "2026-10-09T09:00:00.000Z", "2026-10-09T09:40:00.000Z"
SENTINEL = "words-" + secrets.token_hex(6)


class WRig:
    def __init__(self, scopes: dict[str, list[str]] | None = None) -> None:
        self.rig = Rig(connect_at=None)
        self.google = FakeWorkspace()
        self.rig.cal = self.google  # the runtime's transport_opener reads it per request
        env = self.rig.env
        env.clock.set(CONNECTED)
        granted = {"gmail": [GMAIL_READONLY], "google_calendar": [CALENDAR_READONLY], "google_drive": [DRIVE_FILE]}
        for name, scope in (granted if scopes is None else scopes).items():
            env.connect(OWNER, name, scope)
        env.clock.set(NOW)

    def raw(self, body: Any, *, token: str | None = "good") -> Any:
        headers = {} if token is None else {"authorization": f"Bearer {self.rig.good if token == 'good' else token}"}
        return self.rig.client.post(ROUTE, content=json.dumps(body).encode(), headers=headers)

    def read(self, tool: str, args: dict[str, Any], user: str = OWNER) -> dict[str, Any]:
        response = self.raw({"user_id": user, "tool": tool, "args": args})
        assert response.status_code == 200, response.text
        return response.json()


def mail(subject: str = "Hello", sender: str = "Ana <ana@example.org>", **more: Any) -> dict[str, Any]:
    headers = header_list(From=sender, Subject=subject, Date="Fri, 09 Oct 2026 10:00:00 +0530", **more)
    return {"mimeType": "text/plain", "headers": headers, **text_part(SENTINEL)}


# ---- search_email, read_email -------------------------------------------------------------------------------


def test_WORKSPACE_TOOLS_A_WT02_search_email_lists_closed_summaries_from_metadata_only() -> None:
    rig = WRig()
    rig.google.add_message("m1", mail("Quarterly plan"), ("INBOX", "UNREAD"), snippet="a &amp; b")
    rig.google.add_message("m2", mail("Lunch"), ("INBOX",))
    got = rig.read("search_email", {"query": "from:ana newer_than:7d", "max_results": 2})
    assert got["outcome"] == "ok" and got["tool"] == "search_email" and got["connected_at"] == CONNECTED
    first, second = got["result"]["messages"]
    assert set(first) == {"id", "thread_id", "sender", "subject", "date", "snippet", "unread"}
    assert (first["id"], first["subject"], first["unread"], first["snippet"]) == ("m1", "Quarterly plan", True, "a & b")
    assert first["sender"] == "Ana <ana@example.org>" and first["date"] == "2026-10-09T04:30:00.000Z"
    assert second["unread"] is False
    listed = rig.google.seen("/messages")[0][2]
    assert listed["q"] == "from:ana newer_than:7d" and listed["maxResults"] == 2
    fetched = [r[2] for r in rig.google.requests if r[1].endswith("/messages/m1")]
    assert fetched and all(p["format"] == "metadata" for p in fetched)  # no body leaves Google for a search


def test_WORKSPACE_TOOLS_A_WT03_read_email_gives_text_headers_and_attachment_names_only() -> None:
    rig = WRig()
    payload = {
        "mimeType": "multipart/mixed",
        "headers": header_list(
            From="Ana <ana@example.org>",
            To="me@example.org, Bo <bo@example.org>",
            Cc="c@example.org",
            Subject="Plan",
            Date="Fri, 09 Oct 2026 10:00:00 +0530",
        ),  # fmt: skip
        "parts": [text_part(SENTINEL), file_part("plan.pdf", "application/pdf", 1234)],
    }
    rig.google.add_message("m1", payload)
    got = rig.read("read_email", {"message_id": "m1"})["result"]
    assert got["body_text"] == SENTINEL and got["body_kind"] == "text" and got["truncated"] is False
    assert got["to"] == ["me@example.org", "bo@example.org"] and got["cc"] == ["c@example.org"]
    assert got["attachments"] == [{"filename": "plan.pdf", "mime_type": "application/pdf", "size": 1234}]
    assert not rig.google.seen("attachments")  # an attachment's bytes are never fetched


def test_WORKSPACE_TOOLS_A_WT03_read_email_cuts_at_20000_and_strips_html_when_there_is_no_text_part() -> None:
    rig = WRig()
    rig.google.add_message("big", {**mail(), **text_part("x" * 25_000)})
    big = rig.read("read_email", {"message_id": "big"})["result"]
    assert (len(big["body_text"]), big["truncated"]) == (20_000, True)
    html = f"<style>p{{color:red}}</style><p>Hi <b>{SENTINEL}</b></p><script>alert(1)</script>"
    rig.google.add_message("web", {**mail(), **text_part(html, "text/html")})
    web = rig.read("read_email", {"message_id": "web"})["result"]
    assert web["body_kind"] == "html_stripped" and SENTINEL in web["body_text"]
    assert "<" not in web["body_text"] and "alert" not in web["body_text"] and "color" not in web["body_text"]
    rig.google.add_message("none", {"mimeType": "image/png", "headers": mail()["headers"], "body": {"size": 5}})
    none = rig.read("read_email", {"message_id": "none"})["result"]
    assert (none["body_kind"], none["body_text"], none["truncated"]) == ("none", "", False)


def test_WORKSPACE_TOOLS_A_WT02_unknown_message_is_not_found() -> None:
    assert WRig().read("read_email", {"message_id": "nope"})["outcome"] == "not_found"


# ---- read_events ----------------------------------------------------------------------------------------------


def event(eid: str, **more: Any) -> dict[str, Any]:
    start = {"dateTime": "2026-10-17T10:00:00+05:30"}
    end = {"dateTime": "2026-10-17T11:00:00+05:30"}
    return {"id": eid, "status": "confirmed", "summary": "Standup", "start": start, "end": end, **more}


WINDOW = {"start": "2026-10-17T00:00:00+05:30", "end": "2026-10-24T00:00:00+05:30"}


def test_WORKSPACE_TOOLS_A_WT02_read_events_maps_the_pe13_fields_and_skips_removed_events() -> None:
    rig = WRig()
    rig.google.events = [
        event(
            "e1",
            summary=f"Call https://zoom.us/j/1 {SENTINEL}",
            attendees=[{"self": True}, {"email": "x@y.org"}],
            description="secret",
            location="Room 1",
        ),  # fmt: skip
        event("e2", status="cancelled"),
        event("e3", attendees=[{"self": True, "responseStatus": "declined"}]),
        event("e4", start={"date": "2026-10-18"}, end={"date": "2026-10-19"}, summary="Holiday"),
    ]
    got = rig.read("read_events", WINDOW)
    assert got["outcome"] == "ok" and got["result"]["truncated"] is False
    first, allday = got["result"]["events"]
    assert set(first) == {"id", "title", "start", "end", "all_day", "attendee_count"}
    assert first["start"] == "2026-10-17T04:30:00.000Z" and first["attendee_count"] == 1
    assert "[removed]" in first["title"] and "zoom" not in first["title"]
    assert (allday["all_day"], allday["start"], allday["end"]) == (True, "2026-10-18", "2026-10-19")
    asked = rig.google.seen("/events")[0][2]
    assert (asked["timeMin"], asked["timeMax"]) == ("2026-10-16T18:30:00.000Z", "2026-10-23T18:30:00.000Z")
    assert asked["singleEvents"] == "true" and asked["orderBy"] == "startTime"
    assert "description" not in asked["fields"] and "location" not in asked["fields"]
    assert "secret" not in json.dumps(got) and "Room 1" not in json.dumps(got) and "x@y.org" not in json.dumps(got)


def test_WORKSPACE_TOOLS_A_WT02_read_events_says_truncated_when_more_were_there() -> None:
    rig = WRig()
    rig.google.events = [event(f"e{n}") for n in range(5)]
    got = rig.read("read_events", {**WINDOW, "max_results": 3})["result"]
    assert len(got["events"]) == 3 and got["truncated"] is True


@pytest.mark.parametrize(
    "window",
    [
        {"start": "2026-10-17T00:00:00Z", "end": "2026-10-17T00:00:00Z"},
        {"start": "2026-10-18T00:00:00Z", "end": "2026-10-17T00:00:00Z"},
        {"start": "2026-10-01T00:00:00Z", "end": "2026-11-02T00:00:00Z"},
    ],
)
def test_WORKSPACE_TOOLS_A_WT02_read_events_window_must_end_after_start_within_31_days(window: dict[str, str]) -> None:
    rig = WRig()
    response = rig.raw({"user_id": OWNER, "tool": "read_events", "args": window})
    assert (response.status_code, response.json()) == (422, {"error": "invalid_request"})
    assert rig.google.requests == []


# ---- list_files, read_file ------------------------------------------------------------------------------------


def test_WORKSPACE_TOOLS_A_WT02_list_files_escapes_the_query_and_hides_folders() -> None:
    rig = WRig()
    rig.google.add_file("f1", "Budget", GAPPS + "spreadsheet")
    rig.google.add_file("d1", "Tilo", GAPPS + "folder")
    got = rig.read("list_files", {"query": "it's a \\ test", "max_results": 5})
    assert [f["id"] for f in got["result"]["files"]] == ["f1"]
    assert set(got["result"]["files"][0]) == {"id", "name", "mime_type", "modified_at"}
    asked = rig.google.seen("/files")[0][2]
    quoted = "it\\'s a \\\\ test"
    assert asked["q"] == f"(name contains '{quoted}' or fullText contains '{quoted}') and trashed = false"
    assert asked["orderBy"] == "modifiedTime desc"
    rig.read("list_files", {})
    assert rig.google.seen("/files")[1][2]["q"] == "trashed = false"


@pytest.mark.parametrize(
    ("mime", "export", "content"),
    [(GAPPS + "document", "text/plain", b"doc text"), (GAPPS + "presentation", "text/plain", b"slides"),
     (GAPPS + "spreadsheet", "text/csv", b"a,b\n1,2")],
)  # fmt: skip
def test_WORKSPACE_TOOLS_A_WT03_read_file_exports_google_files_as_text(mime: str, export: str, content: bytes) -> None:
    rig = WRig()
    rig.google.add_file("f1", "Thing", mime, content)
    got = rig.read("read_file", {"file_id": "f1"})["result"]
    assert got == {"id": "f1", "name": "Thing", "mime_type": mime, "text": content.decode(), "pdf_b64": None,
                   "truncated": False}  # fmt: skip
    assert rig.google.seen("/export")[0][2]["mimeType"] == export


def test_WORKSPACE_TOOLS_A_WT03_read_file_text_file_is_cut_at_32000_and_a_pdf_comes_as_base64() -> None:
    rig = WRig()
    rig.google.add_file("t1", "notes.txt", "text/plain", ("é" * 40_000).encode(), size="80000")
    got = rig.read("read_file", {"file_id": "t1"})["result"]
    assert (len(got["text"]), got["truncated"]) == (32_000, True)
    pdf = b"%PDF-1.7 " + secrets.token_bytes(16)
    rig.google.add_file("p1", "a.pdf", "application/pdf", pdf, size=str(len(pdf)))
    got = rig.read("read_file", {"file_id": "p1"})["result"]
    assert (got["text"], got["truncated"], base64.b64decode(got["pdf_b64"])) == (None, False, pdf)


def test_WORKSPACE_TOOLS_A_WT03_read_file_refuses_big_pdfs_other_types_and_files_it_cannot_see() -> None:
    rig = WRig()
    rig.google.add_file("big", "big.pdf", "application/pdf", b"%PDF", size=str(4 * 1024 * 1024 + 1))
    assert rig.read("read_file", {"file_id": "big"})["outcome"] == "too_large"
    assert not [r for r in rig.google.requests if r[2].get("alt") == "media"]  # not even downloaded
    rig.google.add_file("w", "a.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", b"x")
    assert rig.read("read_file", {"file_id": "w"})["outcome"] == "unsupported_type"
    rig.google.add_file("fo", "Dir", GAPPS + "folder")
    assert rig.read("read_file", {"file_id": "fo"})["outcome"] == "unsupported_type"
    assert rig.read("read_file", {"file_id": "unpicked"})["outcome"] == "not_found"  # Google's 404 under drive.file


# ---- outcomes, scopes ------------------------------------------------------------------------------------------

CALLS = [
    ("search_email", {"query": "x"}, GMAIL_READONLY),
    ("read_email", {"message_id": "m1"}, GMAIL_READONLY),
    ("read_events", WINDOW, CALENDAR_READONLY),
    ("list_files", {}, DRIVE_FILE),
    ("read_file", {"file_id": "f1"}, DRIVE_FILE),
]


@pytest.mark.parametrize(("tool", "args", "scope"), CALLS)
def test_WORKSPACE_TOOLS_A_WT06_each_tool_asks_the_broker_for_exactly_its_capability_scope(
    tool: str, args: dict[str, Any], scope: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig, asked = WRig(), []
    real = TokenBroker.access_token_for_adapter

    def spy(self: Any, user_id: str, connector: str, *, required_scopes: Any, **kw: Any) -> str:
        asked.append(list(required_scopes))
        return real(self, user_id, connector, required_scopes=required_scopes, **kw)

    monkeypatch.setattr(TokenBroker, "access_token_for_adapter", spy)
    rig.google.add_message("m1", mail())
    rig.google.add_file("f1", "t", "text/plain", b"x")
    rig.read(tool, args)
    assert asked and all(a == [scope] for a in asked)


@pytest.mark.parametrize(("tool", "args", "scope"), CALLS)
def test_WORKSPACE_TOOLS_A_WT06_no_grant_is_not_connected_and_a_missing_scope_is_missing_scope(
    tool: str, args: dict[str, Any], scope: str
) -> None:
    none = WRig(scopes={})
    assert none.read(tool, args) == {"tool": tool, "outcome": "not_connected", "connected_at": None, "result": None,
                                     "parts": []}  # fmt: skip
    assert none.google.requests == []
    wrong = WRig(scopes={"gmail": [GMAIL_COMPOSE], "google_calendar": [GMAIL_COMPOSE], "google_drive": [GMAIL_COMPOSE]})
    got = wrong.read(tool, args)
    assert (got["outcome"], got["connected_at"], got["result"]) == ("missing_scope", None, None)
    assert wrong.google.requests == []


def test_WORKSPACE_TOOLS_A_WT06_a_refused_refresh_is_expired_with_the_connection_part() -> None:
    rig = WRig()
    rig.rig.env.google.refresh_mode = "invalid_grant"
    rig.rig.env.clock.advance(3 * 3600)  # the access token is past its life: the broker must refresh
    got = rig.read("search_email", {"query": "x"})
    assert (got["outcome"], got["result"], got["connected_at"]) == ("expired", None, None)
    assert got["parts"] == [{"type": "connection.expired", "connector": "gmail", "user_id": OWNER}]
    assert rig.google.requests == []
    again = rig.read("search_email", {"query": "x"})  # the stored state is now expired: still expired, no part
    assert again["outcome"] == "expired"


def test_WORKSPACE_TOOLS_A_WT06_no_readable_connected_at_fails_closed_as_expired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = WRig()
    monkeypatch.setattr(TokenBroker, "connected_at", lambda self, user_id, connector: None)
    got = rig.read("search_email", {"query": "x"})
    assert (got["outcome"], got["connected_at"]) == ("expired", None) and rig.google.requests == []


@pytest.mark.parametrize("status", [500, 503, 429, 400])
def test_WORKSPACE_TOOLS_A_WT03_google_failing_is_unavailable_and_a_429_says_so(status: int) -> None:
    rig = WRig()
    rig.google.status, rig.google.retry_after = status, "2"
    got = rig.read("search_email", {"query": "x"})
    assert (got["outcome"], got["result"], got["connected_at"]) == ("unavailable", None, None)
    assert [p["type"] for p in got["parts"]] == (["connection.rate_limited"] if status == 429 else [])
    assert len(rig.google.requests) == 1  # one attempt: the tool loop decides whether to try again


def test_WORKSPACE_TOOLS_A_WT03_the_answer_holds_no_token_and_no_field_outside_the_result_defs() -> None:
    rig = WRig()
    rig.google.add_message("m1", mail())
    text = json.dumps(rig.read("read_email", {"message_id": "m1"}))
    issued = rig.rig.env.google.issued_access
    assert issued and not any(token in text for token in issued)
    assert set(json.loads(text)) == {"tool", "outcome", "connected_at", "result", "parts"}


# ---- HB-01 and the request contract ------------------------------------------------------------------------------


def test_WORKSPACE_TOOLS_A_HB01_caller_and_configuration_are_checked_before_anything_is_read() -> None:
    rig = WRig()
    body = {"user_id": OWNER, "tool": "search_email", "args": {"query": "x"}}
    assert rig.raw(body, token=None).status_code == 401
    assert rig.raw(body, token="unknown-" + secrets.token_hex(4)).status_code == 401
    other = WRig()
    other.rig.settings.clear()
    assert (other.raw(body).status_code, other.raw(body).json()) == (503, {"error": "not_configured"})
    assert rig.google.requests == []


def test_WORKSPACE_TOOLS_A_HB01_other_accounts_are_403_wrong_claims_401_and_the_body_names_no_caller() -> None:
    rig = WRig()
    body = {"user_id": OWNER, "tool": "search_email", "args": {"query": "x"}}
    other = rig.rig.verifier.add(email="harness-" + secrets.token_hex(3) + "@demo-tilo.example.test")
    assert rig.raw(body, token=other).status_code == 403
    assert rig.raw({**body, "caller": "x@example.test"}).status_code == 422
    for over in (
        {"email_verified": False},
        {"aud": "https://other.example.test"},
        {"iss": "https://evil.example.test"},
    ):
        assert rig.raw(body, token=rig.rig.verifier.add(**over)).status_code == 401
    assert rig.google.requests == []


@pytest.mark.parametrize(
    "body",
    [
        {"user_id": OWNER, "tool": "send_email", "args": {"query": "x"}},  # a write is no read tool
        {"user_id": OWNER, "tool": "search_email", "args": {"message_id": "m1"}},  # another tool's args
        {"user_id": OWNER, "tool": "search_email", "args": {"query": "x", "world_id": "w_1"}},  # no world, ever
        {"user_id": "owner@example.com", "tool": "search_email", "args": {"query": "x"}},  # an address is no user id
        {"user_id": OWNER, "tool": "read_file", "args": {"file_id": "https://drive.example/f"}},
        {"user_id": OWNER, "tool": "search_email", "args": {"query": "x\n"}},
        {"user_id": OWNER, "tool": "search_email", "args": {"query": "x"}, "extra": 1},
    ],
)
def test_WORKSPACE_TOOLS_A_HB01_a_body_that_breaks_the_contract_is_422_and_reads_nothing(body: dict[str, Any]) -> None:
    rig = WRig()
    response = rig.raw(body)
    assert (response.status_code, response.json()) == (422, {"error": "invalid_request"})
    assert rig.google.requests == []


def test_WORKSPACE_TOOLS_A_HB01_a_body_over_64_kib_is_refused_unread() -> None:
    rig = WRig()
    response = rig.rig.client.post(
        ROUTE, content=b" " * (MAX_BODY_BYTES + 1), headers={"authorization": f"Bearer {rig.rig.good}"}
    )
    assert response.status_code == 422 and rig.google.requests == []


def test_WORKSPACE_TOOLS_A_WT06_nothing_here_reaches_a_write_method() -> None:
    rig = WRig()
    rig.google.add_message("m1", mail())
    rig.google.add_file("f1", "t", "text/plain", b"x")
    for tool, args, _ in CALLS:
        rig.read(tool, args)
    assert {r[0] for r in rig.google.requests} == {"GET"}
    assert EVENTS in {r[1] for r in rig.google.requests}
