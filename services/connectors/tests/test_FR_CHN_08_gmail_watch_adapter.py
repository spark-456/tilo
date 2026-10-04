"""FR-CHN-08: the Gmail adapter's watch, history and resync reads, the seam `tilo_channels.gmail_watch` uses.

PRD 11.6 FR-CHN-08 (Gmail push watch with polling fallback), 12.1 (least-privilege scopes; Gmail through
the `gmail` connector), 16.1 (no token in any error or log). Gmail API facts: users.watch returns
historyId and expiration (epoch milliseconds) and lasts 7 days; users.history.list answers 404 when
startHistoryId is older than the history Gmail keeps; users.getProfile returns the current historyId.
These are reads of the user's own mailbox at gmail.readonly: no outbox entry, no grant, no send scope.
API: services/channels/tests/API_FR_CHN_08.md "GmailAdapter (connectors side)".
"""

from __future__ import annotations

import logging

import pytest
from _chn08_gapi_lib import TOPIC, WATCH_TTL_MS, make_watch_env
from _gapi_lib import GMAIL_API, log_text
from _oauth_lib import GMAIL_READONLY, OWNER


def _requests(apis, path: str):
    return [r for r in apis.requests if r.url == GMAIL_API + path]


def _scopes_asked(g) -> set[str]:
    return {s for (_, connector, scopes) in g.spy.asked if connector == "gmail" for s in scopes}


def test_FR_CHN_08_watch_registers_the_inbox_on_the_topic_and_returns_history_and_expiry():
    g, apis = make_watch_env()

    info = g.gmail.watch(OWNER, topic_name=TOPIC, label_ids=["INBOX"])

    sent = _requests(apis, "/watch")
    assert len(sent) == 1 and sent[0].method == "POST"
    assert sent[0].json["topicName"] == TOPIC
    assert sent[0].json["labelIds"] == ["INBOX"]
    assert info["history_id"] == str(apis.current_history)
    assert info["expiration"] == pytest.approx((apis.now_ms + WATCH_TTL_MS) / 1000.0), "unix seconds"


def test_FR_CHN_08_watch_history_and_resync_ask_for_the_read_scope_only():
    g, apis = make_watch_env()
    apis.arrive(thread_id="thr_a")
    before = len(g.emitted)  # connection.established from connecting the account

    g.gmail.watch(OWNER, topic_name=TOPIC, label_ids=["INBOX"])
    g.gmail.list_history(OWNER, "1")
    g.gmail.recent_inbox(OWNER, max_results=10)
    g.gmail.stop_watch(OWNER)

    assert _scopes_asked(g) == {GMAIL_READONLY}, "no compose or send scope for watching"
    assert not any(r.url.endswith(("/messages/send", "/drafts")) for r in apis.requests)
    assert g.emitted[before:] == [], "watching is not a side effect: no data.transfer, no authz event"


@pytest.mark.parametrize("topic", ["", "gmail-push", "https://evil.example.net/topic", "projects/demo-tilo"])
def test_FR_CHN_08_watch_refuses_a_malformed_topic_before_calling_google(topic):
    from tilo_connectors.adapters import AdapterError

    g, apis = make_watch_env()

    with pytest.raises(AdapterError):
        g.gmail.watch(OWNER, topic_name=topic, label_ids=["INBOX"])
    assert _requests(apis, "/watch") == []


def test_FR_CHN_08_stop_watch_calls_users_stop():
    g, apis = make_watch_env()
    g.gmail.watch(OWNER, topic_name=TOPIC, label_ids=["INBOX"])

    g.gmail.stop_watch(OWNER)

    assert [r.method for r in _requests(apis, "/stop")] == ["POST"]
    assert apis.watching is None


def test_FR_CHN_08_list_history_returns_added_inbox_message_ids_in_order():
    g, apis = make_watch_env()
    start = str(apis.current_history)
    a = apis.arrive(thread_id="thr_a")
    apis.arrive(thread_id="thr_s", labels=("SENT",))  # the user's own sent mail: not new mail
    b = apis.arrive(thread_id="thr_b")

    page = g.gmail.list_history(OWNER, start)

    assert page["message_ids"] == [a["id"], b["id"]]
    assert page["history_id"] == str(apis.current_history)
    assert page["next_page_token"] is None
    asked = _requests(apis, "/history")[-1].params
    assert asked["startHistoryId"] == start
    assert asked["historyTypes"] == "messageAdded"
    assert asked["labelId"] == "INBOX"


def test_FR_CHN_08_list_history_passes_the_page_token_through():
    g, apis = make_watch_env()
    apis.history_page_size = 2
    start = str(apis.current_history)
    ids = [apis.arrive(thread_id=f"thr_{i}")["id"] for i in range(3)]

    first = g.gmail.list_history(OWNER, start)
    second = g.gmail.list_history(OWNER, start, page_token=first["next_page_token"])

    assert first["message_ids"] == ids[:2] and first["next_page_token"]
    assert second["message_ids"] == ids[2:] and second["next_page_token"] is None
    assert _requests(apis, "/history")[-1].params["pageToken"] == first["next_page_token"]


def test_FR_CHN_08_list_history_with_no_changes_returns_an_empty_list():
    g, apis = make_watch_env()

    page = g.gmail.list_history(OWNER, str(apis.current_history))

    assert page["message_ids"] == []
    assert page["history_id"] == str(apis.current_history)


@pytest.mark.parametrize("bad", ["", "12a", "-5", "1 OR 2", "../profile", "１２３"])
def test_FR_CHN_08_list_history_refuses_a_non_decimal_start_id_before_calling_google(bad):
    from tilo_connectors.adapters import AdapterError

    g, apis = make_watch_env()

    with pytest.raises(AdapterError):
        g.gmail.list_history(OWNER, bad)
    assert _requests(apis, "/history") == []


def test_FR_CHN_08_expired_start_history_id_raises_status_404_without_retrying():
    from tilo_connectors.adapters import AdapterError

    g, apis = make_watch_env()
    old = str(apis.current_history)
    apis.arrive(thread_id="thr_a")
    apis.expire_history()

    with pytest.raises(AdapterError) as caught:
        g.gmail.list_history(OWNER, old)

    assert caught.value.status == 404, "the watcher tells an expired cursor apart by status 404"
    assert len(_requests(apis, "/history")) == 1, "a 404 is final: no retry"
    assert g.sleeps == []


def test_FR_CHN_08_recent_inbox_reads_the_history_id_first_then_the_newest_inbox_ids():
    g, apis = make_watch_env()
    ids = [apis.arrive(thread_id=f"thr_{i}")["id"] for i in range(4)]

    result = g.gmail.recent_inbox(OWNER, max_results=3)

    assert result["message_ids"] == list(reversed(ids))[:3], "newest first, as Gmail lists them"
    assert result["history_id"] == str(apis.current_history)
    gmail_calls = [r.url for r in apis.requests if r.url in (GMAIL_API + "/profile", GMAIL_API + "/messages")]
    assert gmail_calls == [GMAIL_API + "/profile", GMAIL_API + "/messages"], (
        "history id taken before listing, so mail arriving in between is caught by the next history read"
    )
    listed = _requests(apis, "/messages")[-1].params
    labels = listed["labelIds"]
    assert (labels if isinstance(labels, list) else [labels]) == ["INBOX"]


def test_FR_CHN_08_recent_inbox_never_asks_for_more_than_the_batch_size():
    g, apis = make_watch_env()
    apis.arrive(thread_id="thr_a")

    g.gmail.recent_inbox(OWNER, max_results=500)

    assert int(_requests(apis, "/messages")[-1].params["maxResults"]) <= 50, "config/connectors.yaml batch_size"


def test_FR_CHN_08_adapter_errors_and_logs_hold_no_token(caplog):
    from tilo_connectors.adapters import AdapterError

    caplog.set_level(logging.DEBUG)
    g, apis = make_watch_env()
    apis.expire_history()
    apis.fail_next(403, when=lambda r: r.url.endswith("/watch"))

    errors = []
    for call in (
        lambda: g.gmail.watch(OWNER, topic_name=TOPIC, label_ids=["INBOX"]),
        lambda: g.gmail.list_history(OWNER, "1"),
    ):
        try:
            call()
        except AdapterError as exc:
            errors.append(str(exc))

    tokens = {r.token for r in apis.requests if r.token}
    assert tokens, "the adapter did authenticate"
    text = log_text(caplog) + "\n".join(errors)
    for token in tokens:
        assert token not in text
