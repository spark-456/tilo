"""FR-CON-04 / FR-CON-05 builder tests for the round-1 review findings on #160-#162: a side effect never
waits inside the outbox lease; racing Drive saves stay exactly once; attachment names and recipients are
checked as sent; unencodable text is final; a download fetches only the checked id; Retry-After is capped.
"""

from __future__ import annotations

import pytest
from _gapi_lib import (
    DRIVE_UPLOAD_API,
    FOLDER_MIME,
    GMAIL_API,
    FakeApiResponse,
    drive_case,
    enqueue,
    gmail_case,
    make_gapi_env,
)
from _oauth_lib import OWNER


def _states(entries: list[dict]) -> list[str]:
    return [e["state"] for e in entries]


def _post_to(suffix: str):
    return lambda r: r.method == "POST" and r.url.endswith(suffix)


def _case(g, kind: str) -> dict:
    if kind == "drive":
        return drive_case(item=g.artifacts.put_file("art_f1", name="once.pdf"))
    g.apis.seed_message(thread_id="thr_supplier_1")
    action = "create_draft" if kind == "draft" else "send_email"
    return gmail_case(action_type=action, item=g.artifacts.put_email("art_e1"), destination="thr_supplier_1")


def _effects(g, kind: str) -> int:
    if kind == "drive":
        return len([f for f in g.apis.files.values() if f.name == "once.pdf"])
    return len(g.apis.drafts) if kind == "draft" else len(g.apis.sent())


@pytest.mark.parametrize(
    "kind, when",
    [
        ("send", _post_to("/messages/send")),
        ("draft", _post_to("/drafts")),
        ("send", lambda r: r.method == "GET" and "/threads/" in r.url),  # a read inside the side effect
        ("drive", lambda r: r.url == DRIVE_UPLOAD_API),
    ],
)
def test_FR_CON_04_a_429_inside_a_side_effect_never_waits_past_the_lease(kind, when):
    """A wait longer than the 30 s lease would let a second instance claim the entry and act, then the
    first would wake and act again. The side effect gives up at once; the entry stays due."""
    g = make_gapi_env()
    enqueue(g.outbox, _case(g, kind))
    other, _, _ = g.new_outbox()
    g.apis.fail_next(429, headers={"Retry-After": "50"}, when=when)
    woke: list[float] = []

    def sleep_past_the_lease(seconds: float) -> None:  # what a real 50 s sleep would allow
        woke.append(seconds)
        g.env.clock.advance(31)
        other.dispatch_due()

    g.gmail._sleep = g.drive._sleep = sleep_past_the_lease

    assert g.outbox.dispatch_due() == []
    g.env.clock.advance(31)
    other.dispatch_due()
    g.outbox.dispatch_due()

    assert woke == [], "a side effect never sleeps"
    assert _effects(g, kind) == 1
    assert len(g.parts_of("connection.rate_limited")) == 1


def test_FR_CON_05_a_retry_finds_the_save_in_any_tilo_folder():
    """The upload landed in folder A, then a racing instance made folder B with a smaller id: the retry
    looks the marker up in every folder and never uploads twice."""
    g = make_gapi_env()
    enqueue(g.outbox, drive_case(item=g.artifacts.put_file("art_x", name="x.txt")))
    g.apis.lose_response(lambda r: r.url == DRIVE_UPLOAD_API)
    g.outbox.dispatch_due()
    (first,) = [f for f in g.apis.files.values() if f.mime_type == FOLDER_MIME]
    smaller = g.apis.seed_folder(name="Tilo")
    g.apis.files["a0000race"] = g.apis.files.pop(smaller)
    g.apis.files["a0000race"].id = "a0000race"
    g.apis.files["a0000race"].app_properties = dict(first.app_properties)

    g.env.clock.advance(31)
    assert _states(g.outbox.dispatch_due()) == ["sent"]
    assert len([f for f in g.apis.files.values() if f.name == "x.txt"]) == 1


def test_FR_CON_05_racing_first_saves_adopt_the_smallest_tilo_folder():
    """Two instances both find no Tilo folder and both create one: each re-lists after creating and
    saves into the smallest id, so every save lands in one folder."""
    g = make_gapi_env()
    enqueue(g.outbox, drive_case(item=g.artifacts.put_file("art_1", name="one.pdf")))
    other, _, _ = g.new_outbox()
    real, raced = g.apis.request, []

    def request(method, url, **kw):
        creating = method == "POST" and url.endswith("/drive/v3/files")
        if creating and not raced:  # the other instance wins the race to create, with its own entry
            raced.append(True)
            enqueue(other, drive_case(item=g.artifacts.put_file("art_2", name="two.pdf")))
            other.dispatch_due()
        return real(method, url, **kw)

    g.apis.request = request
    g.outbox.dispatch_due()

    folders = sorted(f.id for f in g.apis.files.values() if f.mime_type == FOLDER_MIME)
    assert len(folders) == 2, "the race really happened"
    saved = {f.name: f.parents for f in g.apis.files.values() if f.mime_type != FOLDER_MIME}
    assert saved == {"one.pdf": [folders[0]], "two.pdf": [folders[0]]}


@pytest.mark.parametrize(
    "name", ["malware.exe\x00", "malware.exe\x01", "a.exe\u200b", "a.exe::$DATA", "a.exe:x.pdf", "a\u202eexe.pdf"]
)
def test_FR_CON_04_attachment_names_are_checked_as_sent(name):
    g = make_gapi_env()
    g.apis.seed_message(thread_id="thr_supplier_1")
    ref = g.artifacts.put_file("art_bad", name=name, mime_type="application/octet-stream", content=b"MZ")
    enqueue(g.outbox, gmail_case(item=g.artifacts.put_email("art_e"), destination="thr_supplier_1", attachments=[ref]))

    assert _states(g.outbox.dispatch_due()) == ["failed"]
    assert g.apis.writes() == []


@pytest.mark.parametrize(
    "recipient", ["j\u00fcrgen@example.com", "a@ex\u00e4mple.com", "\u202eam@example.com", "a@example.com\u200b"]
)
def test_FR_CON_04_a_recipient_that_is_not_plain_ascii_is_refused_before_any_request(recipient):
    """SMTP would write it as an RFC 2047 encoded-word inside the address: To would no longer be it."""
    g = make_gapi_env()
    enqueue(g.outbox, gmail_case(item=g.artifacts.put_email("art_e"), destination=None, recipients=(recipient,)))

    assert _states(g.outbox.dispatch_due()) == ["failed"]
    assert g.apis.requests == [] and g.spy.asked == []


@pytest.mark.parametrize("field", ["subject", "body_text"])
def test_FR_CON_04_text_utf8_cannot_encode_is_final_not_retried(field):
    g = make_gapi_env()
    item = g.artifacts.put_email("art_e", **{field: "ok \ud800 bad"})
    enqueue(g.outbox, gmail_case(item=item, destination=None))

    assert _states(g.outbox.dispatch_due()) == ["failed"]
    assert g.outbox.dispatch_due() == [] and g.apis.requests == []


def test_FR_CON_05_download_fetches_only_the_checked_id():
    from tilo_connectors.adapters import AdapterError

    g = make_gapi_env()
    picked = g.apis.seed_file(name="picked.pdf")
    secret = g.apis.seed_file(name="salaries.xlsx")
    g.picks.add(OWNER, [picked])
    real = g.apis.request

    def request(method, url, **kw):  # a crafted metadata answer naming another file
        if url.endswith(f"/files/{picked}") and (kw.get("params") or {}).get("alt") != "media":
            return FakeApiResponse(200, {"id": secret, "name": "x", "mimeType": "text/plain", "size": "1"})
        return real(method, url, **kw)

    g.apis.request = request
    with pytest.raises(AdapterError):
        g.drive.download(OWNER, picked)
    assert g.apis.reads_naming(secret) == []


def test_FR_CON_04_a_huge_retry_after_is_capped_not_parsed():
    from tilo_connectors.adapters import RateLimited

    g = make_gapi_env()
    g.apis.fail_next(429, times=3, headers={"Retry-After": "9" * 5000})

    with pytest.raises(RateLimited) as raised:
        g.gmail.list_labels(OWNER)

    assert raised.value.retry_after_s == 999_999_999 and g.sleeps == []
    assert [r.url for r in g.apis.requests] == [f"{GMAIL_API}/labels"]


def test_FR_CON_04_a_world_scoped_outbox_never_sends_another_worlds_entry():
    """#151 (FR-WLD-07) with the Gmail adapter: Outbox(world_id="w1") never reaches execute_side_effect for an
    entry of another world; that world's own outbox sends it exactly once."""
    from tilo_connectors.outbox import Outbox

    g = make_gapi_env()
    case = gmail_case(item=g.artifacts.put_email("art_e"), destination=None)
    entry = enqueue(g.outbox, case)
    assert entry["world_id"] != "w1"
    connectors = {"gmail": g.gmail, "google_drive": g.drive}

    w1 = Outbox(g.store, connectors, emit=g.env.emitted.append, clock=g.env.clock, world_id="w1")
    assert w1.dispatch_due() == []
    assert g.apis.requests == [] and g.spy.asked == [], "no token, no request for another world's entry"
    assert g.store.get(entry["id"])["state"] == "queued"

    own = Outbox(g.store, connectors, emit=g.env.emitted.append, clock=g.env.clock, world_id=entry["world_id"])
    assert _states(own.dispatch_due()) == ["sent"]
    assert len(g.apis.sent()) == 1
