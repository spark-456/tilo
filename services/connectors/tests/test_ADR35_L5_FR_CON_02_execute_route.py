"""ADR35_L5 / FR_CON_02: POST /internal/side-effects/execute of tilo-connectors (ADR-0035 decision 5, LC-07 to LC-10).

Gmail, Drive and Calendar behind one route: HB-01 caller, the contract's closed schemas, items hash-checked first
(HB-03), a per-request Outbox (HB-04, SEC-03), HB-06 not_before. The rig is ADR-0032 T3's with FakeGoogleApis (Gmail,
Drive) and FakeHostCalendar behind one Transport: no network, no paid call, nothing reads the live switch. The item
documents are the L5 envelope (BQ-ADR35L5-1): UTF-8 JSON with a `kind`. Secrets and mail text are runtime sentinels.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import logging
import pathlib
import secrets
from typing import Any

import pytest
from _gapi_lib import DRIVE_ALL, GMAIL_ALL, FakeGoogleApis, b64url_decode, parse_raw
from _live_lib import no_external_network as no_external_network  # noqa: F401 - autouse guard
from _meeting_host_lib import CALENDAR_EVENTS_OWNED, EVENTS_URL, OWNER, FakeApiResponse, FakeHostCalendar
from test_ADR32_T3_host_routes import AUD, CALLER, HARNESS, Rig
from tilo_connectors.adapters import GMAIL_API, side_effect_marker
from tilo_connectors.host_routes import AUDIENCE_VAR, CALLER_VAR, MAX_BODY_BYTES
from tilo_connectors.side_effects import scan_for_side_effect_calls

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "tilo_connectors"
ROUTE = "/internal/side-effects/execute"
CONNECTED, NOW = "2026-10-09T09:00:00.000Z", "2026-10-09T09:40:00.000Z"  # the fixtures approve at 09:32:09.5
CONTRACTS = pathlib.Path(__file__).resolve().parents[3] / "contracts"
FIXTURES = CONTRACTS / "fixtures" / "meeting_host_rpc.execute_request" / "valid"
GUEST = "guest-" + secrets.token_hex(3) + "@example.org"
SUBJECT, BODY = "subj-" + secrets.token_hex(6), "body-" + secrets.token_hex(6)
TITLE = "title-" + secrets.token_hex(6)
START, END, ZONE = "2026-10-12T09:00:00.000Z", "2026-10-12T09:30:00.000Z", "Asia/Kolkata"
RECIPIENT = "supplier@example.org"


def raw_of(document: dict[str, Any]) -> bytes:
    return json.dumps(document, sort_keys=True, separators=(",", ":")).encode()


def pinned(ref: dict[str, Any], raw: bytes) -> dict[str, Any]:
    return {
        "artifact_id": ref["artifact_id"],
        "version": ref["version"],
        "content_sha256": hashlib.sha256(raw).hexdigest(),
        "content_b64": base64.b64encode(raw).decode(),
    }


def email_doc(**more: Any) -> dict[str, Any]:
    return {"kind": "email", "subject": SUBJECT, "body_text": BODY, **more}


def file_doc(name: str = "report.pdf", content: bytes = b"%PDF-1.7 " + secrets.token_bytes(8), **more: Any) -> dict:
    mime = "application/pdf"
    return {"kind": "file", "name": name, "mime_type": mime, "content_b64": base64.b64encode(content).decode(), **more}


def event_doc(**more: Any) -> dict[str, Any]:
    return {"kind": "calendar_event", "title": TITLE, "start": START, "end": END, "time_zone": ZONE, **more}


def fixture(name: str, documents: list[dict[str, Any]], **entry: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """(entry, request): a contract fixture's request with its entry changed and its items replaced by `documents`,
    the entry's item first, then its attachments in order."""
    body = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    body["entry"].update(entry)
    refs = [body["entry"]["item"], *body["entry"]["attachments"]]
    body["items"] = [pinned(r, raw_of(d)) for r, d in zip(refs, documents, strict=True)]
    return body["entry"], body


def guests_request(attendees: list[str] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """The T3 shape of a person-approved send, turned into create_event_with_guests (the gate names the action)."""
    ref = {"artifact_id": "art_event_draft", "version": 1}
    entry, body = fixture(
        "gmail_send_with_an_attachment", [event_doc(**({} if attendees is None else {"attendees": attendees}))],
        connector="google_calendar", action_type="create_event_with_guests", recipients=[GUEST], attachments=[],
        item=ref, destination="primary", modifiers=["new_recipients"],
    )  # fmt: skip
    body["evidence"]["reserved_by"]["data"].update(action_type="create_event_with_guests", item=ref)
    return entry, body


class Both:
    """Gmail and Drive on one fake, Calendar on the other, one list of everything that reached Google."""

    def __init__(self, apis: FakeGoogleApis, cal: FakeHostCalendar) -> None:
        self.apis, self.cal = apis, cal

    def request(self, method: str, url: str, **kw: Any) -> Any:
        return (self.cal if url.startswith(EVENTS_URL) else self.apis).request(method, url, **kw)

    def reached(self) -> int:
        return len(self.apis.requests) + len(self.cal.requests)


class Rig5:
    def __init__(self, *, connect_at: str | None = CONNECTED, scopes: dict[str, list[str]] | None = None) -> None:
        self.rig = Rig(connect_at=None)
        env = self.rig.env
        self.apis, self.cal = FakeGoogleApis(env.google), FakeHostCalendar(env.google)
        self.google = Both(self.apis, self.cal)
        self.rig.cal = self.google  # the runtime's transport_opener reads it per request
        if connect_at is not None:
            env.clock.set(connect_at)
            for name, granted in (scopes or self.default_scopes()).items():
                env.connect(OWNER, name, granted)
        env.clock.set(NOW)
        for thread in ("thr_supplier_1", "thr_customer_1"):  # the threads the fixtures reply into
            self.apis.seed_message(thread_id=thread)

    @staticmethod
    def default_scopes() -> dict[str, list[str]]:
        return {"gmail": GMAIL_ALL, "google_drive": DRIVE_ALL, "google_calendar": [CALENDAR_EVENTS_OWNED]}

    def post(self, body: Any = None, *, token: str | None = "good", raw: bytes | None = None) -> Any:
        bearer = {} if token is None else {"authorization": f"Bearer {self.rig.good if token == 'good' else token}"}
        data = raw if raw is not None else json.dumps(body).encode()
        return self.rig.client.post(ROUTE, content=data, headers=bearer)

    def run(self, request: dict[str, Any]) -> dict[str, Any]:
        response = self.post(request)
        assert response.status_code == 200, response.text
        return response.json()


def the_draft() -> tuple[dict[str, Any], dict[str, Any]]:
    return fixture("gmail_draft_approved_by_the_person", [email_doc(in_reply_to="<m1@example.org>")])


def the_send() -> tuple[dict[str, Any], dict[str, Any]]:
    return fixture("gmail_send_with_an_attachment", [email_doc(in_reply_to="<m2@example.org>"), file_doc("price.pdf")])


def the_event(**more: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    return fixture("calendar_event_without_guests", [event_doc(**more)])


def sent_ok(answer: dict[str, Any], entry: dict[str, Any]) -> str:
    assert answer["outcome"] == "sent" and answer["may_have_sent"] is None
    assert set(answer["result"]) == {"resource_id", "marker"}
    assert answer["result"]["marker"] == side_effect_marker(entry)
    return answer["result"]["resource_id"]


# ---- HB-01, the contract's closed request, the caps -------------------------------------------


@pytest.mark.parametrize("missing", [AUDIENCE_VAR, CALLER_VAR])
def test_ADR35_L5_FR_CON_02_unset_audience_or_caller_is_503_before_anything(missing: str) -> None:
    rig = Rig5()
    rig.rig.settings.pop(missing)
    response = rig.post(the_event()[1])
    assert (response.status_code, response.json()) == (503, {"error": "not_configured"})
    assert rig.rig.verifier.calls == [] and rig.google.reached() == 0


def test_ADR35_L5_FR_CON_02_the_caller_is_the_one_oidc_account_and_nothing_is_read_before() -> None:
    rig, body = Rig5(), the_event()[1]
    for token in (None, "unknown-" + secrets.token_hex(4)):
        assert rig.post(body, token=token).status_code == 401
    other = rig.rig.verifier.add(email=HARNESS)
    assert (rig.post(body, token=other).status_code, rig.post(body, token=other).json()) == (
        403,
        {"error": "forbidden"},
    )
    assert rig.post(raw=b"x" * (MAX_BODY_BYTES + 1), token=None).status_code == 401  # the caller before the body
    assert rig.google.reached() == 0
    assert CALLER not in rig.post(body, token=other).text and AUD not in rig.post(body, token=other).text


def _requests_that_break_the_contract() -> list[tuple[str, Any]]:
    good = the_event()[1]
    over = copy.deepcopy(good)
    over["items"] = good["items"] * 12
    cases = [("items_12", over), ("not_json", b"{nope"), ("items_empty", {**good, "items": []})]
    for key in ("entry", "evidence", "items"):
        cases.append((f"no_{key}", {k: v for k, v in good.items() if k != key}))
    for name, connector in (("meeting_host", "meeting_host"), ("lovable", "lovable")):
        cases.append((f"connector_{name}", {**good, "entry": {**good["entry"], "connector": connector}}))
    cases.append(("state_sent", {**good, "entry": {**good["entry"], "state": "sent"}}))
    cases.append(("token_at_top", {**good, "refresh_token": "t-" + secrets.token_hex(4)}))
    cases.append(("over_cap", b'{"entry":"' + b"x" * MAX_BODY_BYTES + b'"}'))
    return cases


@pytest.mark.parametrize(
    ("name", "body"), _requests_that_break_the_contract(), ids=lambda v: v if isinstance(v, str) else ""
)
def test_ADR35_L5_FR_CON_02_a_request_that_breaks_the_contract_is_422_and_nothing_happens(name: str, body: Any) -> None:
    rig = Rig5()
    response = rig.post(raw=body) if isinstance(body, bytes) else rig.post(body)
    assert (response.status_code, response.json()) == (422, {"error": "invalid_request"}), name
    assert rig.google.reached() == 0


# ---- HB-03: the items are checked first --------------------------------------------------------


def _tampered() -> list[tuple[str, Any]]:
    def swap(body: dict, **changes: Any) -> dict:
        out = copy.deepcopy(body)
        out["items"][0].update(changes)
        return out

    def other_bytes(body: dict) -> dict:
        return swap(body, content_b64=base64.b64encode(raw_of(event_doc(title="other"))).decode())

    return [
        ("hash", other_bytes),
        ("artifact", lambda b: swap(b, artifact_id="art_other_one")),
        ("version", lambda b: swap(b, version=9)),
        ("missing_attachment", lambda b: {**b, "items": b["items"][:1]}),
        ("extra_item", lambda b: {**b, "items": b["items"] + b["items"][:1]}),
        ("not_a_document", lambda b: swap(b, **pinned(b["items"][0], b"plain bytes, not JSON"))),
        ("wrong_kind", lambda b: swap(b, **pinned(b["items"][0], raw_of(email_doc())))),
    ]


_TAMPER_CASES = [("calendar", n) for n, _ in _tampered() if n != "missing_attachment"] + [
    ("mail_with_attachment", n) for n, _ in _tampered() if n not in ("not_a_document", "wrong_kind")
]


@pytest.mark.parametrize(("which", "name"), _TAMPER_CASES)
def test_ADR35_L5_FR_CON_02_an_item_that_fails_its_check_is_refused_with_zero_google_requests(
    which: str, name: str
) -> None:
    rig = Rig5()
    body = the_event()[1] if which == "calendar" else the_send()[1]
    changed = dict(_tampered())[name](body)
    answer = rig.run(changed)
    assert answer == {"outcome": "refused", "result": None, "may_have_sent": None, "parts": []}
    assert rig.google.reached() == 0


# ---- the actions: exact requests ---------------------------------------------------------------


def test_ADR35_L5_FR_CON_02_create_draft_is_drafts_create_with_the_pinned_text_and_a_stable_message_id() -> None:
    rig, (entry, body) = Rig5(), the_draft()
    rid = sent_ok(rig.run(body), entry)
    marker = side_effect_marker(entry)
    assert [(r.method, r.url) for r in rig.apis.requests] == [
        ("GET", GMAIL_API + "/drafts"),
        ("POST", GMAIL_API + "/drafts"),
    ]
    message = parse_raw(b64url_decode(rig.apis.requests[1].json["message"]["raw"]))
    assert message["To"] == RECIPIENT and message["Subject"] == SUBJECT and message["In-Reply-To"] == "<m1@example.org>"
    assert message["Message-ID"] == f"<tilo.{marker}@tilo.invalid>"
    assert message.get_body().get_content().strip() == BODY
    assert rid in rig.apis.drafts and rig.apis.sent() == []


def test_ADR35_L5_FR_CON_02_send_email_sends_the_pinned_content_with_its_attachment_never_a_re_read_draft() -> None:
    rig, (entry, body) = Rig5(), the_send()
    sent_ok(rig.run(body), entry)
    assert [(r.method, r.url) for r in rig.apis.requests] == [
        ("GET", GMAIL_API + "/messages"),
        ("POST", GMAIL_API + "/messages/send"),
    ]
    assert not [r for r in rig.apis.requests if "/drafts" in r.url], "LC-10: the Gmail draft is never read"
    (message,) = rig.apis.sent()
    assert message["Message-ID"] == f"<tilo.{side_effect_marker(entry)}@tilo.invalid>"
    assert message.get_body(("plain",)).get_content().strip() == BODY
    assert [p.get_filename() for p in message.iter_attachments()] == ["price.pdf"]
    assert message["To"] == "customer@example.org" and message["Cc"] is None and message["Bcc"] is None


def test_ADR35_L5_FR_CON_02_save_file_uploads_into_the_tilo_folder_with_the_marker_in_app_properties() -> None:
    rig = Rig5()
    rig.apis.seed_file(
        file_id="fld_tilo_reports", name="Tilo", content=None, mime_type="application/vnd.google-apps.folder"
    )
    rig.apis.files["fld_tilo_reports"].app_properties = {"tilo_role": "folder"}
    entry, body = fixture("drive_save_waiting_out_its_undo_window", [file_doc("q3.pdf", b"%PDF-1.7 q3")])
    rid = sent_ok(rig.run(body), entry)
    (upload,) = [r for r in rig.apis.requests if r.method == "POST" and "upload" in r.url]
    marker = side_effect_marker(entry)
    assert f'"tilo_save": "{marker}"' in upload.content.decode("latin-1") and b"%PDF-1.7 q3" in upload.content
    (saved,) = rig.apis.created_files()
    assert saved.id == rid and saved.name == "q3.pdf" and saved.app_properties["tilo_save"] == marker


def test_ADR35_L5_FR_CON_02_create_event_is_events_insert_on_the_own_primary_calendar_without_guests() -> None:
    rig, (entry, body) = Rig5(), the_event()
    rid = sent_ok(rig.run(body), entry)
    marker = side_effect_marker(entry)
    assert rid == marker, "the Calendar event id is derived from the outbox marker"
    get, post = rig.cal.requests
    assert (get.method, get.url) == ("GET", f"{EVENTS_URL}/{marker}")
    assert (post.method, post.url) == ("POST", EVENTS_URL)
    assert post.params == {"sendUpdates": "none", "fields": "id,status"}
    assert post.json == {
        "id": marker, "summary": TITLE, "start": {"dateTime": START, "timeZone": ZONE},
        "end": {"dateTime": END, "timeZone": ZONE}, "guestsCanInviteOthers": False, "guestsCanModify": False,
    }  # fmt: skip
    assert rig.cal.invitations() == [] and rig.apis.requests == []


def test_WORKSPACE_TOOLS_WT08_create_event_sends_only_pinned_reminders() -> None:
    rig, (entry, body) = Rig5(), the_event(reminders=[{"method": "popup", "minutes": 0}])
    sent_ok(rig.run(body), entry)
    assert rig.cal.posts()[0].json["reminders"] == {
        "useDefault": False,
        "overrides": [{"method": "popup", "minutes": 0}],
    }


@pytest.mark.parametrize(
    "reminders",
    [
        [{"method": "sms", "minutes": 0}],
        [{"method": "popup", "minutes": True}],
        [{"method": "popup", "minutes": 0}] * 6,
    ],
)
def test_WORKSPACE_TOOLS_WT08_bad_reminders_refused_before_google(reminders: list[dict]) -> None:
    rig = Rig5()
    assert rig.run(the_event(reminders=reminders)[1])["outcome"] == "refused"
    assert rig.google.reached() == 0


def update_request(destination: str) -> tuple[dict[str, Any], dict[str, Any]]:
    entry, body = the_event(reminders=[{"method": "popup", "minutes": 5}])
    entry.update(
        action_type="update_event",
        destination=destination,
        risk_tier="T2",
        idempotency_key="r_followups_1:U4:update_event:1",
    )
    body["evidence"]["reserved_by"]["data"].update(action_type="update_event", risk_tier="T2")
    return entry, body


def test_WORKSPACE_TOOLS_WT08_update_event_reads_own_guestless_event_then_patches_once(monkeypatch) -> None:
    rig = Rig5()
    original = rig.cal.request
    patches = []

    def request(method, url, **kw):
        if method == "PATCH":
            patches.append((url, kw))
            return FakeApiResponse(200, {"id": url.rsplit("/", 1)[-1]})
        if method == "GET":
            return FakeApiResponse(
                200,
                {
                    "id": url.rsplit("/", 1)[-1],
                    "status": "confirmed",
                    "organizer": {"self": True},
                    "attendees": [{"self": True}],
                },
            )
        return original(method, url, **kw)

    monkeypatch.setattr(rig.cal, "request", request)
    entry, body = update_request("own-event-1")
    assert sent_ok(rig.run(body), entry) == "own-event-1"
    assert len(patches) == 1
    url, kw = patches[0]
    assert url == f"{EVENTS_URL}/own-event-1"
    assert kw["params"]["sendUpdates"] == "none"
    assert kw["json"] == {
        "summary": TITLE,
        "start": {"dateTime": START, "timeZone": ZONE},
        "end": {"dateTime": END, "timeZone": ZONE},
        "reminders": {"useDefault": False, "overrides": [{"method": "popup", "minutes": 5}]},
        "extendedProperties": {"private": {"tilo_update": side_effect_marker(entry)}},
    }


@pytest.mark.parametrize(
    "event",
    [
        {"status": "confirmed", "organizer": {"self": False}, "attendees": []},
        {"status": "cancelled", "organizer": {"self": True}, "attendees": []},
        {"status": "tentative", "organizer": {"self": True}, "attendees": [{"email": GUEST}]},
    ],
)
@pytest.mark.parametrize("destination", ["", "has/slash", "bad.event", "\u00e9vent"])
def test_WORKSPACE_TOOLS_WT08_update_event_rejects_non_google_ids_before_requests(destination: str) -> None:
    rig = Rig5()
    assert rig.run(update_request(destination)[1])["outcome"] == "refused"
    assert rig.google.reached() == 0


@pytest.mark.parametrize("changes", [{"recipients": [GUEST]}, {"attachments": [{"artifact_id": "x", "version": 1}]}])
def test_WORKSPACE_TOOLS_WT08_update_event_refuses_recipients_and_attachments_before_google(changes) -> None:
    rig = Rig5()
    entry, body = update_request("own-event-1")
    entry.update(changes)
    body["entry"].update(changes)
    assert rig.run(body)["outcome"] == "refused"
    assert rig.google.reached() == 0


def test_WORKSPACE_TOOLS_WT08_update_event_requires_attendee_subfield_and_fails_closed(monkeypatch) -> None:
    rig = Rig5()
    monkeypatch.setattr(
        rig.cal,
        "request",
        lambda method, url, **kw: FakeApiResponse(
            200, {"id": "own-event-1", "status": "confirmed", "organizer": {"self": True}}
        ),
    )
    assert rig.run(update_request("own-event-1")[1])["outcome"] == "refused"


def test_WORKSPACE_TOOLS_WT08_update_event_id_echo_is_checked_on_get_and_patch(monkeypatch) -> None:
    for mismatch_method in ("GET", "PATCH"):
        rig = Rig5()
        calls = []

        def request(method, url, **kw):
            calls.append(method)
            if method == "GET":
                return FakeApiResponse(
                    200,
                    {
                        "id": "different-id" if mismatch_method == "GET" else "own-event-1",
                        "status": "confirmed",
                        "organizer": {"self": True},
                        "attendees": [],
                    },
                )
            return FakeApiResponse(200, {"id": "different-id"})

        monkeypatch.setattr(rig.cal, "request", request)
        assert rig.run(update_request("own-event-1")[1])["outcome"] == "refused"
        assert calls == (["GET"] if mismatch_method == "GET" else ["GET", "PATCH"])


def test_WORKSPACE_TOOLS_WT08_update_event_marker_is_idempotent(monkeypatch) -> None:
    rig = Rig5()
    entry, body = update_request("own-event-1")

    def request(method, url, **kw):
        return FakeApiResponse(
            200,
            {
                "id": "own-event-1",
                "status": "confirmed",
                "organizer": {"self": True},
                "attendees": [],
                "extendedProperties": {"private": {"tilo_update": side_effect_marker(entry)}},
            },
        )

    monkeypatch.setattr(rig.cal, "request", request)
    assert sent_ok(rig.run(body), entry) == "own-event-1"
    assert [request.method for request in rig.cal.requests] == ["GET"]


def test_WORKSPACE_TOOLS_WT08_update_event_refuses_foreign_cancelled_or_guest_event(monkeypatch, event) -> None:
    rig = Rig5()
    calls = []

    def request(method, url, **kw):
        calls.append(method)
        return FakeApiResponse(200, {"id": "own-event-1", **event})

    monkeypatch.setattr(rig.cal, "request", request)
    assert rig.run(update_request("own-event-1")[1])["outcome"] == "refused"
    assert calls == ["GET"]


@pytest.mark.parametrize("more", [{"attendees": [GUEST]}, {"guests": [GUEST]}, {"attendees": "x"}])
def test_ADR35_L5_FR_CON_02_create_event_with_any_guest_is_refused_before_any_google_request(more: dict) -> None:
    rig = Rig5()
    answer = rig.run(the_event(**more)[1])
    assert answer == {"outcome": "refused", "result": None, "may_have_sent": None, "parts": []}
    assert rig.google.reached() == 0, "LC-09 / FR-CAL-04"


def test_ADR35_L5_FR_CON_02_create_event_with_guests_is_the_t3_action_and_invites_exactly_the_approved_audience() -> (
    None
):
    rig, (entry, body) = Rig5(), guests_request()
    sent_ok(rig.run(body), entry)
    post = rig.cal.posts()[0]
    assert post.params == {"sendUpdates": "all", "fields": "id,status"}
    assert post.json["attendees"] == [{"email": GUEST}] and post.json["guestsCanInviteOthers"] is False
    assert rig.cal.invitations() == [(side_effect_marker(entry), GUEST)]


def test_ADR35_L5_FR_CON_02_guests_that_differ_from_the_entrys_recipients_are_refused_untouched() -> None:
    rig = Rig5()
    answer = rig.run(guests_request(["other-" + GUEST])[1])
    assert answer["outcome"] == "refused" and rig.google.reached() == 0


# ---- OB-03: a re-attempt after an ambiguous failure finds the first ---------------------------


def test_ADR35_L5_FR_CON_02_a_calendar_insert_whose_answer_was_lost_is_found_not_repeated() -> None:
    rig, (entry, body) = Rig5(), the_event()
    rig.cal.lose_answer_after_create()
    first = rig.run(body)
    assert (first["outcome"], first["may_have_sent"], first["result"]) == ("retry", True, None)
    sent_ok(rig.run(body), entry)
    assert len(rig.cal.created()) == 1 and len(rig.cal.posts()) == 1, (
        "the second attempt read the first, it did not insert"
    )


def test_ADR35_L5_FR_CON_02_a_send_whose_answer_was_lost_is_found_by_its_message_id_not_sent_twice() -> None:
    rig, (entry, body) = Rig5(), the_send()
    rig.apis.lose_response(lambda r: r.method == "POST" and r.url.endswith("/messages/send"))
    first = rig.run(body)
    assert (first["outcome"], first["may_have_sent"]) == ("retry", True)
    rid = sent_ok(rig.run(body), entry)
    assert len(rig.apis.sent()) == 1 and rid == rig.apis.sent_records()[0].id


def test_ADR35_L5_FR_CON_02_a_cancelled_earlier_event_is_possibly_sent_never_inserted_again() -> None:
    rig, (entry, body) = Rig5(), the_event()
    rig.cal.seed_event(side_effect_marker(entry), status="cancelled")
    answer = rig.run(body)
    assert answer["outcome"] == "possibly_sent" and rig.cal.posts() == []


# ---- the outcomes ------------------------------------------------------------------------------


def test_ADR35_L5_FR_CON_02_not_connected_is_retry_with_nothing_reached_never_not_configured() -> None:
    rig = Rig5(connect_at=None)
    answer = rig.run(the_event()[1])
    assert (answer["outcome"], answer["may_have_sent"], answer["result"]) == ("retry", False, None)
    assert rig.google.reached() == 0


def test_ADR35_L5_FR_CON_02_a_missing_scope_is_retry_with_nothing_reached() -> None:
    rig = Rig5(scopes={"google_calendar": ["https://www.googleapis.com/auth/calendar.readonly"]})
    answer = rig.run(the_event()[1])
    assert (answer["outcome"], answer["may_have_sent"]) == ("retry", False) and rig.google.reached() == 0


def test_ADR35_L5_FR_CON_02_google_rejecting_the_request_is_refused_and_a_5xx_is_retry_that_may_have_sent() -> None:
    rig = Rig5()
    rig.cal.fail_next(400, when=lambda r: r.method == "POST")
    assert rig.run(the_event()[1])["outcome"] == "refused"
    rig = Rig5()
    rig.cal.fail_next(503, when=lambda r: r.method == "POST")
    answer = rig.run(the_event()[1])
    assert (answer["outcome"], answer["may_have_sent"]) == ("retry", True)


def test_ADR35_L5_FR_CON_02_a_429_is_retry_that_did_not_send_and_carries_the_rate_limit_part() -> None:
    rig = Rig5()
    rig.cal.fail_next(429, headers={"retry-after": "7"}, when=lambda r: r.method == "POST")
    answer = rig.run(the_event()[1])
    assert (answer["outcome"], answer["may_have_sent"]) == ("retry", False)
    assert {"type": "connection.rate_limited", "connector": "google_calendar", "user_id": OWNER} in answer["parts"]


def test_ADR35_L5_FR_CON_02_a_401_gets_one_forced_refresh_and_then_goes_through() -> None:
    rig, (entry, body) = Rig5(), the_event()
    token = rig.rig.env.broker.access_token_for_adapter(
        OWNER, "google_calendar", required_scopes=[CALENDAR_EVENTS_OWNED]
    )
    rig.cal.reject_token(token)
    sent_ok(rig.run(body), entry)
    assert len(rig.cal.tokens_used()) == 2


def test_ADR35_L5_FR_CON_02_a_grant_made_after_the_approval_is_refused_with_zero_google_requests() -> None:
    rig = Rig5(connect_at="2026-10-09T09:35:00.000Z")  # the approval was at 09:32:09.5 (HB-06)
    answer = rig.run(the_event()[1])
    assert answer == {"outcome": "refused", "result": None, "may_have_sent": None, "parts": []}
    assert rig.google.reached() == 0


def test_ADR35_L5_FR_CON_02_an_entry_the_policy_check_refuses_is_refused_untouched() -> None:
    rig, body = Rig5(), the_event()[1]
    body["entry"]["risk_tier"] = "T3"  # create_event is T1 in config/autonomy.yaml: a wrong label is refused
    assert rig.run(body)["outcome"] == "refused" and rig.google.reached() == 0


def test_ADR35_L5_FR_CON_02_the_grant_used_is_the_world_owners_and_the_entry_is_not_kept() -> None:
    rig, (entry, body) = Rig5(), the_event()
    sent_ok(rig.run(body), entry)
    sent_ok(rig.run(body), entry)  # a new request is a new outbox: it reads Google's earlier event
    assert len(rig.cal.posts()) == 1 and rig.cal.tokens_used() <= set(rig.rig.env.google.issued_access)


# ---- nothing private leaves ---------------------------------------------------------------------


def test_ADR35_L5_FR_CON_02_no_mail_text_address_title_or_token_is_in_an_answer_or_a_log(caplog: Any) -> None:
    caplog.set_level(logging.DEBUG)
    rig = Rig5()
    answers = [rig.run(the_send()[1]), rig.run(guests_request()[1]), rig.run(the_draft()[1])]
    rig.cal.fail_next(503, when=lambda r: r.method == "POST")
    answers.append(rig.run(the_event()[1]))
    text = json.dumps(answers) + "\n".join(f"{r.getMessage()} {r.exc_text or ''}" for r in caplog.records)
    needles = [
        SUBJECT,
        BODY,
        TITLE,
        RECIPIENT,
        "customer@example.org",
        GUEST,
        "Bearer",
        rig.rig.env.settings.client_secret,
        "refresh_token",
    ]
    assert not [n for n in needles if n in text]
    assert all(set(a) == {"outcome", "result", "may_have_sent", "parts"} for a in answers)


def test_ADR35_L5_FR_CON_02_only_the_outbox_reaches_an_adapter_in_the_new_code() -> None:
    mine = [SRC / "side_effect_execute.py", SRC / "adapters" / "calendar_write.py", SRC / "host_routes.py"]
    assert scan_for_side_effect_calls(mine, allowed_path=SRC / "outbox.py") == []


# ---- security round 1 fixes ---------------------------------------------------------------------

REFUSED = {"outcome": "refused", "result": None, "may_have_sent": None, "parts": []}


@pytest.mark.parametrize("label", ["T1", "T2"])
def test_ADR35_L5_FR_CON_02_a_risk_tier_that_is_not_the_tables_is_refused_with_zero_requests(label: str) -> None:
    rig, body = Rig5(), guests_request()[1]  # create_event_with_guests is T3 in config/autonomy.yaml
    body["entry"].update(risk_tier=label, modifiers=[])  # the table says T3 for this action whatever the label
    body["evidence"]["reserved_by"]["data"]["risk_tier"] = label
    assert rig.run(body) == REFUSED and rig.google.reached() == 0


def test_ADR35_L5_FR_CON_02_an_approval_dated_in_the_future_is_refused_with_zero_requests() -> None:
    rig, body = Rig5(connect_at="2026-10-09T09:35:00.000Z"), the_event()[1]
    future = "2099-01-01T00:00:00.000Z"  # a forged time that would sit after the grant (HB-06)
    body["entry"]["authz"]["at"] = body["evidence"]["authorised_by"]["authz"]["at"] = future
    assert rig.run(body) == REFUSED and rig.google.reached() == 0


def _bad_item_bytes() -> list[tuple[str, bytes]]:
    good = raw_of(event_doc()).decode()
    return [
        ("bom", bytes([0xEF, 0xBB, 0xBF]) + good.encode()),
        ("utf16", good.encode("utf-16")),
        ("duplicate_key", good.replace('"kind":"calendar_event"', '"kind":"calendar_event","title":"x"').encode()),
        ("lone_surrogate", good.replace(TITLE, chr(92) + "ud800").encode()),
        ("invalid_utf8", good.encode() + bytes([0xFF])),
    ]


@pytest.mark.parametrize(("name", "raw"), _bad_item_bytes(), ids=lambda v: v if isinstance(v, str) else "")
def test_ADR35_L5_FR_CON_02_an_item_that_is_not_strict_utf8_json_is_refused_untouched(name: str, raw: bytes) -> None:
    rig, body = Rig5(), the_event()[1]
    body["items"] = [pinned(body["entry"]["item"], raw)]
    assert rig.run(body) == REFUSED and rig.google.reached() == 0, name


def test_ADR35_L5_FR_CON_02_an_item_that_is_also_its_own_attachment_is_refused_with_zero_requests() -> None:
    rig, (entry, body) = Rig5(), the_send()
    entry["attachments"] = [entry["item"]]
    body["items"] = [pinned(entry["item"], raw_of(email_doc())), pinned(entry["item"], raw_of(file_doc()))]
    assert rig.run(body) == REFUSED and rig.google.reached() == 0


@pytest.mark.parametrize("destination", ["other", "primary2", "fld_x"])
def test_ADR35_L5_FR_CON_02_a_calendar_destination_other_than_primary_is_refused_untouched(
    destination: str,
) -> None:
    rig, body = Rig5(), the_event()[1]
    body["entry"]["destination"] = destination
    assert rig.run(body) == REFUSED and rig.google.reached() == 0


def test_ADR35_L5_FR_CON_02_an_earlier_event_whose_organizer_is_not_the_person_is_not_taken_as_ours() -> None:
    rig, (entry, body) = Rig5(), the_event()
    rig.cal.seed_event(side_effect_marker(entry))
    original = rig.cal._body
    rig.cal._body = lambda ev: {**original(ev), "organizer": {"email": "x@example.org", "self": False}}
    answer = rig.run(body)
    assert answer["outcome"] == "possibly_sent" and rig.cal.posts() == []
    assert "organizer" in rig.cal.gets()[0].params["fields"]


def test_ADR35_L5_FR_CON_02_overlapping_calls_for_one_marker_run_one_after_the_other() -> None:
    import threading
    import time

    rig, body = Rig5(), the_event()[1]
    inside, release, seen = threading.Event(), threading.Event(), []
    real = rig.google.request

    def slow(method: str, url: str, **kw: Any) -> Any:
        seen.append(method)
        if len(seen) == 1:
            inside.set()
            release.wait(5)
        return real(method, url, **kw)

    rig.google.request = slow  # type: ignore[method-assign]
    results: list[Any] = []
    first = threading.Thread(target=lambda: results.append(rig.run(body)))
    second = threading.Thread(target=lambda: results.append(rig.run(body)))
    first.start()
    assert inside.wait(5)
    second.start()
    time.sleep(0.3)
    assert seen == ["GET"], "the second call waits for the first"
    release.set()
    first.join(10)
    second.join(10)
    assert [r["outcome"] for r in results] == ["sent", "sent"] and len(rig.cal.posts()) == 1
