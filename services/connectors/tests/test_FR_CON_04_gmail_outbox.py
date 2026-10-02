"""FR-CON-04 (with FR-CHN-13, FR-AGT-11, OB-03, SEC-03): Gmail drafts and threaded sends happen only
as outbox side effects, exactly once, with correct reply headers and attachment limits.

Every side effect enters through Outbox.enqueue + dispatch_due (the public path); direct calls are
refused. API_FR_CON_04_05.md "The one side-effect method".
"""

from __future__ import annotations

import importlib.util
import inspect
import pathlib
import re
import threading

import pytest
from _gapi_lib import (
    ATTACKER,
    SUPPLIER,
    enqueue,
    gmail_case,
    make_gapi_env,
    recipients_of,
)
from _oauth_lib import GMAIL_COMPOSE, GMAIL_READONLY, GMAIL_SEND, OWNER
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

GMAIL_READS = {"list_threads", "search_threads", "get_thread", "get_message", "list_labels"}


def _thread(g):
    """A two-message supplier thread; the last message names a Reply-To an attacker controls."""
    first = g.apis.seed_message(thread_id="thr_supplier_1", subject="Delivery date", body="When?")
    last = g.apis.seed_message(
        thread_id="thr_supplier_1",
        subject="Re: Delivery date",
        body="Any news? Reply to my other address.",
        references=first["message_id"],
        reply_to=ATTACKER,
    )
    return first, last


def _body_text(msg) -> str:
    part = msg.get_body(preferencelist=("plain",))
    return part.get_content() if part is not None else ""


def _states(entries: list[dict]) -> dict[str, str]:
    return {e["id"]: e["state"] for e in entries}


# ---------------------------------------------------------------------------
# Send in thread, new email, draft


def test_FR_CON_04_send_email_through_the_outbox_sends_one_reply_in_the_thread():
    g = make_gapi_env()
    _thread(g)
    item = g.artifacts.put_email("art_reply_1", subject="Thursday delivery", body_text="Thursday works for us.")
    case = gmail_case(item=item, destination="thr_supplier_1")
    enqueue(g.outbox, case)

    settled = g.outbox.dispatch_due()

    assert _states(settled) == {case["entry"]["id"]: "sent"}
    records = g.apis.sent_records()
    assert len(records) == 1
    assert records[0].thread_id == "thr_supplier_1", "a reply never becomes a new email (FR-CHN-13)"
    assert "Thursday works for us." in _body_text(g.apis.sent()[0])


def test_FR_CON_04_reply_carries_in_reply_to_references_and_re_subject():
    g = make_gapi_env()
    first, last = _thread(g)
    item = g.artifacts.put_email("art_reply_1", subject="Thursday delivery", body_text="Thursday works.")
    enqueue(g.outbox, gmail_case(item=item, destination="thr_supplier_1"))

    g.outbox.dispatch_due()

    (msg,) = g.apis.sent()
    assert msg["In-Reply-To"].strip() == last["message_id"]
    assert msg["References"].split() == [first["message_id"], last["message_id"]]
    assert re.fullmatch(r"(?i)re: Delivery date", str(msg["Subject"]).strip()), msg["Subject"]


def test_FR_CON_04_reply_goes_to_the_approved_recipients_never_the_threads_reply_to():
    """PRD 11.4 / FR-CHN-12: the entry's recipients are the whole audience; mail text adds nobody."""
    g = make_gapi_env()
    _thread(g)
    item = g.artifacts.put_email("art_reply_1")
    enqueue(g.outbox, gmail_case(item=item, destination="thr_supplier_1", recipients=(SUPPLIER,)))

    g.outbox.dispatch_due()

    (msg,) = g.apis.sent()
    assert recipients_of(msg) == {SUPPLIER}
    assert msg["Cc"] is None and msg["Bcc"] is None


def test_FR_CON_04_new_email_has_no_thread_and_no_in_reply_to():
    g = make_gapi_env()
    item = g.artifacts.put_email("art_new_1", subject="Order 4471", body_text="Please confirm order 4471.")
    enqueue(g.outbox, gmail_case(item=item, destination=None, recipients=("buyer@example.net",)))

    g.outbox.dispatch_due()

    sends = [r for r in g.apis.writes() if r.url.endswith("/messages/send")]
    assert len(sends) == 1
    assert "threadId" not in (sends[0].json or {})
    (msg,) = g.apis.sent()
    assert msg["In-Reply-To"] is None
    assert str(msg["Subject"]) == "Order 4471"
    assert recipients_of(msg) == {"buyer@example.net"}


def test_FR_CON_04_create_draft_through_the_outbox_saves_one_draft_and_sends_nothing():
    g = make_gapi_env()
    _thread(g)
    item = g.artifacts.put_email("art_draft_1", body_text="Draft: Thursday works.")
    case = gmail_case(action_type="create_draft", item=item, destination="thr_supplier_1")
    enqueue(g.outbox, case)

    settled = g.outbox.dispatch_due()

    assert _states(settled) == {case["entry"]["id"]: "sent"}
    assert g.apis.sent() == []
    drafts = g.apis.draft_messages()
    assert len(drafts) == 1
    assert "Draft: Thursday works." in _body_text(drafts[0])
    draft_posts = [r for r in g.apis.writes() if r.url.endswith("/drafts")]
    assert draft_posts[0].json["message"]["threadId"] == "thr_supplier_1"


def test_FR_CON_04_each_side_effect_emits_one_data_transfer_with_the_entrys_authz():
    g = make_gapi_env()
    _thread(g)
    send = gmail_case(item=g.artifacts.put_email("art_reply_1"), destination="thr_supplier_1")
    draft = gmail_case(
        action_type="create_draft", item=g.artifacts.put_email("art_draft_1"), destination="thr_supplier_1"
    )
    enqueue(g.outbox, send)
    enqueue(g.outbox, draft)

    g.outbox.dispatch_due()

    transfers = [p for p in g.emitted if p["type"] == "data.transfer" and p["data"]["direction"] == "out"]
    by_id = {p["data"]["outbox_id"]: p for p in transfers}
    assert set(by_id) == {send["entry"]["id"], draft["entry"]["id"]}
    for case in (send, draft):
        part = by_id[case["entry"]["id"]]
        assert part["authz"] == case["entry"]["authz"], "SEC-11 / OB-01: the approval travels with the send"
        assert part["data"]["action_type"] == case["entry"]["action_type"]
        assert part["data"]["artifact"] == case["entry"]["item"]


def test_FR_CON_04_side_effects_ask_only_for_their_capabilitys_scope_plus_read():
    g = make_gapi_env()
    _thread(g)
    enqueue(g.outbox, gmail_case(item=g.artifacts.put_email("art_reply_1"), destination="thr_supplier_1"))
    g.outbox.dispatch_due()
    send_scopes = {s for _, _, scopes in g.spy.asked for s in scopes}
    assert GMAIL_SEND in send_scopes
    assert send_scopes <= {GMAIL_SEND, GMAIL_READONLY}

    g.spy.asked.clear()
    enqueue(
        g.outbox,
        gmail_case(action_type="create_draft", item=g.artifacts.put_email("art_d"), destination="thr_supplier_1"),
    )
    g.outbox.dispatch_due()
    draft_scopes = {s for _, _, scopes in g.spy.asked for s in scopes}
    assert GMAIL_COMPOSE in draft_scopes
    assert draft_scopes <= {GMAIL_COMPOSE, GMAIL_READONLY}


# ---------------------------------------------------------------------------
# SEC-03: no path to a side effect except the outbox


def test_FR_CON_04_execute_side_effect_is_a_declared_side_effect_method():
    from tilo_connectors.side_effects import SIDE_EFFECT_METHOD_NAMES

    assert "execute_side_effect" in SIDE_EFFECT_METHOD_NAMES


def test_FR_CON_04_direct_call_without_a_grant_is_refused_before_any_token_or_request():
    from tilo_connectors.errors import MissingGrant

    g = make_gapi_env()
    _thread(g)
    case = gmail_case(item=g.artifacts.put_email("art_reply_1"), destination="thr_supplier_1")

    with pytest.raises(MissingGrant):
        g.gmail.execute_side_effect(case["entry"], None)

    assert g.apis.requests == []
    assert g.spy.asked == [], "no token is handed out for a send nobody authorised"


def test_FR_CON_04_direct_call_with_a_forged_grant_is_refused():
    from tilo_connectors.errors import MissingGrant
    from tilo_connectors.outbox import Grant

    g = make_gapi_env()
    _thread(g)
    case = gmail_case(item=g.artifacts.put_email("art_reply_1"), destination="thr_supplier_1")
    forged = Grant(world_id=case["entry"]["world_id"], idempotency_key=case["entry"]["idempotency_key"])

    with pytest.raises(MissingGrant):
        g.gmail.execute_side_effect(case["entry"], forged)

    assert g.apis.requests == [] and g.apis.sent() == []


def test_FR_CON_04_gmail_adapter_has_no_direct_draft_or_send_method():
    g = make_gapi_env()
    for action in ("create_draft", "send_email", "send_reply", "send"):
        assert not hasattr(g.gmail, action), f"GmailAdapter exposes a direct path: {action}"
    public = {
        name
        for name, value in inspect.getmembers(type(g.gmail))
        if not name.startswith("_") and callable(value) and not isinstance(value, property)
    }
    assert public == GMAIL_READS | {"execute_side_effect"}, sorted(public)


def test_FR_CON_04_adapter_modules_never_call_a_side_effect_method(outbox_module_path):
    """SEC-03's static scan over the new adapters package: only outbox.py calls one."""
    from tilo_connectors.side_effects import scan_for_side_effect_calls

    spec = importlib.util.find_spec("tilo_connectors.adapters")
    assert spec is not None and spec.submodule_search_locations, "tilo_connectors.adapters must be a package"
    paths = [p for d in spec.submodule_search_locations for p in pathlib.Path(d).rglob("*.py")]

    assert scan_for_side_effect_calls(paths, allowed_path=outbox_module_path) == []


# ---------------------------------------------------------------------------
# Exactly once (OB-03, FR-CHN-13, FR-AGT-11)


def test_FR_CON_04_a_lost_send_response_retried_still_sends_exactly_once():
    g = make_gapi_env()
    _thread(g)
    case = gmail_case(item=g.artifacts.put_email("art_reply_1"), destination="thr_supplier_1")
    enqueue(g.outbox, case)
    g.apis.lose_response(lambda r: r.method == "POST" and r.url.endswith("/messages/send"))

    first = g.outbox.dispatch_due()  # Google sent it; Tilo never heard back
    assert first == [], "an ambiguous failure is not final"
    assert len(g.apis.sent()) == 1

    second = g.outbox.dispatch_due()

    assert _states(second) == {case["entry"]["id"]: "sent"}
    assert len(g.apis.sent()) == 1, "the retry found the earlier send and did not send again"
    transfers = [p for p in g.emitted if p["type"] == "data.transfer"]
    assert len({p["data"]["outbox_id"] for p in transfers}) == 1


def test_FR_CON_04_a_lost_draft_response_retried_still_saves_one_draft():
    g = make_gapi_env()
    _thread(g)
    enqueue(
        g.outbox,
        gmail_case(action_type="create_draft", item=g.artifacts.put_email("art_d1"), destination="thr_supplier_1"),
    )
    g.apis.lose_response(lambda r: r.method == "POST" and r.url.endswith("/drafts"))

    g.outbox.dispatch_due()
    g.outbox.dispatch_due()

    assert len(g.apis.drafts) == 1


def test_FR_CON_04_another_instance_retrying_after_a_lost_response_sends_once():
    """Two tilo-connectors instances on one store: fresh adapters keep no memory of the first try."""
    g = make_gapi_env()
    _thread(g)
    enqueue(g.outbox, gmail_case(item=g.artifacts.put_email("art_reply_1"), destination="thr_supplier_1"))
    g.apis.lose_response(lambda r: r.method == "POST" and r.url.endswith("/messages/send"))
    g.outbox.dispatch_due()

    other_outbox, _, _ = g.new_outbox()
    g.env.clock.advance(31)  # past the first instance's lease
    other_outbox.dispatch_due()

    assert len(g.apis.sent()) == 1


def test_FR_CON_04_a_concurrent_dispatch_storm_sends_once():
    g = make_gapi_env()
    _thread(g)
    enqueue(g.outbox, gmail_case(item=g.artifacts.put_email("art_reply_1"), destination="thr_supplier_1"))
    outboxes = [g.outbox] + [g.new_outbox()[0] for _ in range(5)]
    barrier = threading.Barrier(len(outboxes))
    errors: list[BaseException] = []

    def run(ob):
        try:
            barrier.wait()
            for _ in range(3):
                ob.dispatch_due()
        except BaseException as exc:  # surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(ob,)) for ob in outboxes]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert errors == []
    assert len(g.apis.sent()) == 1


def test_FR_CON_04_message_id_is_stable_per_key_and_different_across_keys():
    g = make_gapi_env()
    _thread(g)
    case = gmail_case(item=g.artifacts.put_email("art_reply_1"), destination="thr_supplier_1")
    enqueue(g.outbox, case)
    g.apis.lose_response(lambda r: r.method == "POST" and r.url.endswith("/messages/send"))
    g.outbox.dispatch_due()
    first_id = g.apis.sent()[0]["Message-ID"]

    other = make_gapi_env()
    _thread(other)
    other.artifacts.put_email("art_reply_1")
    enqueue(other.outbox, case)  # the same world and key, another instance and mailbox state
    other.outbox.dispatch_due()
    again_id = other.apis.sent()[0]["Message-ID"]

    third = gmail_case(item=g.artifacts.put_email("art_reply_2"), destination="thr_supplier_1")
    enqueue(g.outbox, third)
    g.outbox.dispatch_due()
    ids = {str(m["Message-ID"]) for m in g.apis.sent()}

    assert first_id and str(first_id) == str(again_id)
    assert len(ids) == 2, "a different idempotency key is a different message"


def test_FR_CON_04_two_different_keys_are_two_sends():
    g = make_gapi_env()
    _thread(g)
    enqueue(g.outbox, gmail_case(item=g.artifacts.put_email("art_a"), destination="thr_supplier_1"))
    enqueue(g.outbox, gmail_case(item=g.artifacts.put_email("art_b"), destination="thr_supplier_1"))

    g.outbox.dispatch_due()

    assert len(g.apis.sent()) == 2


# ---------------------------------------------------------------------------
# Attachments: size and type limits (PRD 11.4: attaching is T3; Gmail's limits)


def _attachment_case(g, *names_and_sizes: tuple[str, int], mime: str = "application/pdf"):
    refs = []
    for i, (name, size) in enumerate(names_and_sizes):
        refs.append(g.artifacts.put_file(f"art_att_{i}", name=name, mime_type=mime, content=b"a" * size))
    item = g.artifacts.put_email("art_reply_att", body_text="Terms attached.")
    return gmail_case(item=item, destination="thr_supplier_1", attachments=refs)


def test_FR_CON_04_an_attachment_within_the_limits_is_attached():
    g = make_gapi_env()
    _thread(g)
    case = _attachment_case(g, ("terms.pdf", 2048))
    enqueue(g.outbox, case)

    settled = g.outbox.dispatch_due()

    assert _states(settled) == {case["entry"]["id"]: "sent"}
    (msg,) = g.apis.sent()
    files = [(p.get_filename(), len(p.get_payload(decode=True))) for p in msg.iter_attachments()]
    assert files == [("terms.pdf", 2048)]


def test_FR_CON_04_attachments_over_the_size_limit_fail_the_entry_and_send_nothing():
    g = make_gapi_env(max_attachment_bytes=4096)
    _thread(g)
    case = _attachment_case(g, ("a.pdf", 3000), ("b.pdf", 1097))  # 4097 bytes in total
    enqueue(g.outbox, case)

    settled = g.outbox.dispatch_due()

    assert _states(settled) == {case["entry"]["id"]: "failed"}, "a refusal is final, not retried"
    assert g.apis.sent() == [] and g.apis.writes() == []
    assert [p for p in g.emitted if p["type"] == "data.transfer"] == []
    assert g.outbox.dispatch_due() == [], "a failed entry is never picked up again"


def test_FR_CON_04_the_default_attachment_limit_is_25_mib():
    from tilo_connectors.adapters import MAX_ATTACHMENT_BYTES

    assert MAX_ATTACHMENT_BYTES == 25 * 1024 * 1024
    g = make_gapi_env()
    _thread(g)
    case = _attachment_case(g, ("big.pdf", MAX_ATTACHMENT_BYTES + 1))
    enqueue(g.outbox, case)

    settled = g.outbox.dispatch_due()

    assert _states(settled) == {case["entry"]["id"]: "failed"}
    assert g.apis.writes() == []


@pytest.mark.parametrize(
    "name", ["setup.exe", "invoice.pdf.EXE", "run.bat", "macro.vbs", "tool.js", "app.msi", "disk.iso", "go.ps1"]
)
def test_FR_CON_04_a_blocked_attachment_type_fails_the_entry(name):
    g = make_gapi_env()
    _thread(g)
    case = _attachment_case(g, (name, 100), mime="application/octet-stream")
    enqueue(g.outbox, case)

    settled = g.outbox.dispatch_due()

    assert _states(settled) == {case["entry"]["id"]: "failed"}
    assert g.apis.writes() == []


def test_FR_CON_04_blocked_extensions_include_the_pinned_minimum():
    from tilo_connectors.adapters import BLOCKED_ATTACHMENT_EXTENSIONS

    pinned = {
        ".exe",
        ".bat",
        ".cmd",
        ".com",
        ".scr",
        ".pif",
        ".msi",
        ".js",
        ".jse",
        ".vbs",
        ".vbe",
        ".ps1",
        ".jar",
        ".dll",
        ".cpl",
        ".hta",
        ".iso",
        ".lnk",
    }
    assert pinned <= set(BLOCKED_ATTACHMENT_EXTENSIONS)
    assert all(ext == ext.lower() and ext.startswith(".") for ext in BLOCKED_ATTACHMENT_EXTENSIONS)


# ---------------------------------------------------------------------------
# Property: artifact text never adds a recipient or a header (FR-CHN-12)

_plain = st.text(alphabet=st.characters(blacklist_categories=("Cc", "Cs", "Zl", "Zp")), max_size=40)
_header_like = st.sampled_from(
    ["\r\nBcc: " + ATTACKER, "\nCc: " + ATTACKER, "\r\n\r\nTo: " + ATTACKER, "", " Re:", "é中"]
)


@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    subject=st.tuples(_plain, _header_like, _plain).map("".join),
    body=st.tuples(_plain, _header_like, _plain).map("".join),
    reply=st.booleans(),
)
def test_FR_CON_04_property_no_artifact_text_adds_a_recipient(subject, body, reply):
    g = make_gapi_env()
    if reply:
        _thread(g)
    item = g.artifacts.put_email("art_prop", subject=subject.strip() or "x", body_text=body)
    case = gmail_case(item=item, destination="thr_supplier_1" if reply else None, recipients=(SUPPLIER,))
    enqueue(g.outbox, case)

    settled = g.outbox.dispatch_due()  # never raises

    sent = g.apis.sent()
    if sent:
        assert len(sent) == 1
        assert recipients_of(sent[0]) == {SUPPLIER}
        assert ATTACKER not in str(sent[0]["Bcc"] or "") + str(sent[0]["Cc"] or "")
    else:
        assert _states(settled) == {case["entry"]["id"]: "failed"}
    if not any(c in subject for c in "\r\n"):
        assert len(sent) == 1, "ordinary text is sent, not refused"


def test_FR_CON_04_owner_of_picks_the_mailbox_for_an_entry():
    """The entry names a world; the adapter uses that world's owner's connection."""
    g = make_gapi_env()
    _thread(g)
    enqueue(g.outbox, gmail_case(item=g.artifacts.put_email("art_reply_1"), destination="thr_supplier_1"))

    g.outbox.dispatch_due()

    assert g.spy.asked and {u for u, _, _ in g.spy.asked} == {OWNER}
