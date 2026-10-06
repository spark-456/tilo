"""FR-CON-04 / FR-CHN-11 (BQ-278 n, BQ-274 e): the Gmail adapter's message surfaces a `headers` map.

The channels service reads the replied-to message's Message-ID, In-Reply-To, References and Authentication-Results
from it. Names are lower-cased the way Gmail returns them in the adapter, only those four are kept (nothing else
leaves the adapter: no Received chain, no X- header, no Cookie-like value), and where a name occurs twice the FIRST
one wins: Gmail prepends its own Authentication-Results above whatever the sender wrote.

Against the in-process FakeGoogleApis (no network, no account).
"""

from __future__ import annotations

from _gapi_lib import GMAIL_API, ME, SUPPLIER, make_gapi_env
from _oauth_lib import OWNER

HEADER_NAMES = {"message-id", "in-reply-to", "references", "authentication-results"}
GMAIL_RESULT = (
    "mx.google.com; spf=pass smtp.mailfrom=supplier.example; dmarc=pass (p=NONE) header.from=supplier.example"
)
FORGED = "mx.google.com; dmarc=pass header.from=supplier.example"


def _seed(g, *, extra=(), references: str | None = None) -> dict:
    return g.apis.seed_message(
        thread_id="thr_h",
        from_=SUPPLIER,
        to=(ME,),
        subject="Delivery date",
        body="When is delivery?",
        references=references,
        extra_headers=extra,
    )


def test_FR_CON_04_message_headers_map_is_lower_cased_and_holds_only_the_four_names() -> None:
    g = make_gapi_env()
    seeded = _seed(
        g,
        references="<a@x.example> <b@x.example>",
        extra=[
            ("AUTHENTICATION-RESULTS", GMAIL_RESULT),
            ("Received", "from evil.example by mx.google.com; Fri, 02 Oct 2026"),
            ("X-Api-Token", "should-never-leave-the-adapter"),
            ("Subject-Extra", "nope"),
        ],
    )

    msg = g.gmail.get_message(OWNER, seeded["id"])

    assert msg["headers"] == {
        "message-id": seeded["message_id"],
        "in-reply-to": "<b@x.example>",
        "references": "<a@x.example> <b@x.example>",
        "authentication-results": GMAIL_RESULT,
    }
    assert set(msg["headers"]) <= HEADER_NAMES
    assert all(name == name.lower() for name in msg["headers"])
    assert msg["message_id"] == seeded["message_id"]  # the existing field is unchanged


def test_FR_CON_04_message_headers_map_holds_no_name_that_is_absent_from_the_message() -> None:
    g = make_gapi_env()
    seeded = _seed(g)

    msg = g.gmail.get_message(OWNER, seeded["id"])

    assert msg["headers"] == {"message-id": seeded["message_id"]}


def test_FR_CON_04_the_first_authentication_results_header_wins_over_a_sender_written_one() -> None:
    g = make_gapi_env()
    seeded = _seed(
        g,
        extra=[
            ("Authentication-Results", "mx.google.com; dmarc=fail header.from=supplier.example"),
            ("Authentication-Results", FORGED),  # the sender wrote this one, lower in the header block
        ],
    )

    msg = g.gmail.get_message(OWNER, seeded["id"])

    assert msg["headers"]["authentication-results"].endswith("dmarc=fail header.from=supplier.example")


def test_FR_CON_04_get_thread_messages_carry_the_headers_map_too() -> None:
    g = make_gapi_env()
    seeded = _seed(g, extra=[("Authentication-Results", GMAIL_RESULT)])

    thread = g.gmail.get_thread(OWNER, "thr_h")

    (message,) = thread["messages"]
    assert message["headers"] == {
        "message-id": seeded["message_id"],
        "authentication-results": GMAIL_RESULT,
    }


def test_FR_CON_04_metadata_only_read_returns_the_headers_map() -> None:
    g = make_gapi_env()
    seeded = _seed(g, extra=[("Authentication-Results", GMAIL_RESULT)])

    msg = g.gmail.get_message(OWNER, seeded["id"], headers=["Message-ID", "Authentication-Results"])

    assert msg["headers"]["authentication-results"] == GMAIL_RESULT
    assert msg["headers"]["message-id"] == seeded["message_id"]
    gets = [r for r in g.apis.requests if r.url == f"{GMAIL_API}/messages/{seeded['id']}"]
    assert gets[-1].params.get("format") == "metadata"
