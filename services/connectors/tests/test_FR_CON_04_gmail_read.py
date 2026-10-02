"""FR-CON-04: Gmail read, search and labels (PRD 12.2), at the declared minimal scopes.

Against the in-process FakeGoogleApis (no network, no account). API_FR_CON_04_05.md "GmailAdapter".
"""

from __future__ import annotations

import pytest
from _gapi_lib import GMAIL_API, ME, SUPPLIER, make_gapi_env
from _oauth_lib import GMAIL_READONLY, GMAIL_SEND, OWNER


def _seed_two_threads(g):
    first = g.apis.seed_message(thread_id="thr_a", from_=SUPPLIER, subject="Delivery date", body="When is delivery?")
    g.apis.seed_message(
        thread_id="thr_a",
        from_=ME,
        to=(SUPPLIER,),
        subject="Re: Delivery date",
        body="Checking.",
        references=first["message_id"],
        labels=("SENT",),
    )
    g.apis.seed_message(
        thread_id="thr_b",
        from_="news@example.org",
        subject="Weekly news",
        body="Newsletter",
        labels=("INBOX", "Label_7"),
    )
    return first


def test_FR_CON_04_search_threads_returns_the_matching_threads():
    g = make_gapi_env()
    _seed_two_threads(g)

    result = g.gmail.search_threads(OWNER, f"from:{SUPPLIER}")

    assert [t["id"] for t in result["threads"]] == ["thr_a"]
    assert all(isinstance(t["snippet"], str) for t in result["threads"])
    assert result["next_page_token"] is None
    searches = [r for r in g.apis.requests if r.url == f"{GMAIL_API}/threads"]
    assert searches and searches[-1].params["q"] == f"from:{SUPPLIER}", "the query is sent unchanged"


def test_FR_CON_04_list_threads_filters_by_label():
    g = make_gapi_env()
    _seed_two_threads(g)

    result = g.gmail.list_threads(OWNER, label_ids=["Label_7"])

    assert [t["id"] for t in result["threads"]] == ["thr_b"]


def test_FR_CON_04_list_threads_passes_the_next_page_token_on():
    g = make_gapi_env()
    for i in range(3):
        g.apis.seed_message(thread_id=f"thr_{i}", subject=f"Order {i}")

    first = g.gmail.list_threads(OWNER, max_results=2)

    assert len(first["threads"]) == 2
    assert first["next_page_token"] == "page2"


def test_FR_CON_04_max_results_never_exceeds_the_declared_batch_size():
    """connector.schema.json limits.batch_size (50 for gmail) caps every page asked for."""
    g = make_gapi_env()
    g.apis.seed_message(thread_id="thr_a")

    g.gmail.search_threads(OWNER, "delivery", max_results=500)

    asked = [int(r.params["maxResults"]) for r in g.apis.requests if r.url == f"{GMAIL_API}/threads"]
    assert asked and max(asked) <= 50


def test_FR_CON_04_get_message_returns_headers_body_and_attachment_metadata():
    g = make_gapi_env()
    seeded = g.apis.seed_message(
        thread_id="thr_a",
        from_=SUPPLIER,
        to=(ME,),
        subject="Invoice 88",
        body="Please find the invoice attached.\n",
        attachment=("invoice-88.pdf", "application/pdf", b"%PDF-1.7 " + b"x" * 100),
    )

    msg = g.gmail.get_message(OWNER, seeded["id"])

    assert msg["id"] == seeded["id"]
    assert msg["thread_id"] == "thr_a"
    assert SUPPLIER in msg["from"]
    assert msg["to"] == [ME]
    assert msg["cc"] == []
    assert msg["subject"] == "Invoice 88"
    assert msg["message_id"] == seeded["message_id"]
    assert "INBOX" in msg["label_ids"]
    assert msg["body_text"].strip() == "Please find the invoice attached."
    assert msg["attachments"] == [{"filename": "invoice-88.pdf", "mime_type": "application/pdf", "size": 109}]
    assert msg["untrusted"] is True
    gets = [r for r in g.apis.requests if r.url == f"{GMAIL_API}/messages/{seeded['id']}"]
    assert gets and gets[-1].params.get("format") == "full"


def test_FR_CON_04_get_thread_returns_every_message_in_order():
    g = make_gapi_env()
    first = _seed_two_threads(g)

    thread = g.gmail.get_thread(OWNER, "thr_a")

    assert thread["id"] == "thr_a"
    assert [m["subject"] for m in thread["messages"]] == ["Delivery date", "Re: Delivery date"]
    assert thread["messages"][0]["message_id"] == first["message_id"]
    assert all(m["untrusted"] is True for m in thread["messages"])


def test_FR_CON_04_list_labels_returns_id_name_and_type():
    g = make_gapi_env()

    labels = g.gmail.list_labels(OWNER)

    assert {"id": "Label_7", "name": "Suppliers", "type": "user"} in labels
    assert all(set(label) == {"id", "name", "type"} for label in labels)


def test_FR_CON_04_reads_ask_the_broker_for_exactly_the_declared_read_scope():
    g = make_gapi_env()
    seeded = g.apis.seed_message(thread_id="thr_a")

    g.gmail.search_threads(OWNER, "delivery")
    g.gmail.list_threads(OWNER)
    g.gmail.get_thread(OWNER, "thr_a")
    g.gmail.get_message(OWNER, seeded["id"])
    g.gmail.list_labels(OWNER)

    assert g.spy.asked, "reads must get their token from the broker"
    for user, connector, scopes in g.spy.asked:
        assert (user, connector) == (OWNER, "gmail")
        assert set(scopes) == {GMAIL_READONLY}, f"a read asked for {scopes}"


def test_FR_CON_04_reads_send_only_get_requests_and_need_no_grant():
    g = make_gapi_env()
    seeded = g.apis.seed_message(thread_id="thr_a")

    g.gmail.search_threads(OWNER, "delivery")
    g.gmail.get_message(OWNER, seeded["id"])
    g.gmail.list_labels(OWNER)

    assert g.apis.writes() == []
    assert g.apis.sent() == [] and g.apis.drafts == {}
    assert g.emitted == [] or all(p["type"] != "data.transfer" or p["data"]["direction"] == "in" for p in g.emitted)


def test_FR_CON_04_every_request_carries_a_bearer_token_from_the_broker():
    g = make_gapi_env()
    g.apis.seed_message(thread_id="thr_a")

    g.gmail.search_threads(OWNER, "delivery")

    assert g.apis.requests
    for req in g.apis.requests:
        assert req.token in g.env.google.issued_access


def test_FR_CON_04_read_without_the_read_scope_asks_for_consent_before_any_request():
    from tilo_connectors.tokens import InsufficientScope

    g = make_gapi_env(gmail_scopes=[GMAIL_SEND])

    with pytest.raises(InsufficientScope) as raised:
        g.gmail.search_threads(OWNER, "delivery")

    assert raised.value.missing == [GMAIL_READONLY]
    assert g.apis.requests == []
    assert g.env.service.scopes_needed(user_id=OWNER, connector="gmail", capabilities=["search"]) == [GMAIL_READONLY]


def test_FR_CON_04_read_for_a_user_with_no_gmail_connection_is_a_typed_error():
    from tilo_connectors.tokens import NotConnected

    g = make_gapi_env(gmail_scopes=None)

    with pytest.raises(NotConnected):
        g.gmail.list_labels(OWNER)

    assert g.apis.requests == []


def test_FR_CON_04_adapter_id_is_the_declared_connector_id():
    g = make_gapi_env()
    assert g.gmail.id == "gmail"
