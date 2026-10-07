"""CL-LIVE-1 (CONNECTORS-LIVE slice 1; user wish 7 Oct 2026: agents may work with connectors): `real_adapters`
builds one REAL Google adapter per configured connector, READ-ONLY by construction. Reads reach the transport with
no gate; the one write door (`execute_side_effect`, SEC-03) refuses with a named error until CL-LIVE-2, so a plan
that asks for a send, a save or an invite changes nothing at Google. Fake transport and broker only: no network,
no real token.

API pinned in API_CL_LIVE_1.md. Fails now because `tilo_connectors.real` does not exist.
"""

from __future__ import annotations

import inspect

import pytest
from _cl_live_lib import (
    CALENDAR_EVENTS,
    CONNECTORS_YAML,
    DRIVE_API,
    GMAIL_API,
    GOOGLE_CONNECTORS,
    REAL_PY,
    WRITE_REFUSAL,
    make_real_env,
    read_everything,
    real,
)
from _cl_live_lib import clean_process_env as clean_process_env  # autouse fixture
from _cl_live_lib import socket_guard as socket_guard  # autouse fixture
from _gapi_lib import drive_case, enqueue, gmail_case
from _oauth_lib import OWNER

GMAIL_READS = {
    "list_threads",
    "search_threads",
    "get_thread",
    "get_message",
    "list_labels",
    "recent_inbox",
    "list_history",
}
DRIVE_READS = {"get_metadata", "list_folder", "download"}
CALENDAR_READS = {"list_events"}
READS = {"gmail": GMAIL_READS, "google_drive": DRIVE_READS, "google_calendar": CALENDAR_READS}


def _entry(connector: str, action: str) -> dict:
    """A minimal outbox-shaped entry. The refusal must not depend on its content, its grant or its artifacts."""
    return {
        "id": "01JB5VQ0000000000000009900",
        "idempotency_key": "r_live:U9:" + action,
        "world_id": "w_live",
        "run_id": "r_live",
        "connector": connector,
        "action_type": action,
        "recipients": ["buyer@example.net"],
        "attachments": [],
        "item": {"artifact_id": "art_missing", "version": 1},
        "destination": None,
    }


def test_CL_LIVE_1_returns_one_adapter_per_configured_connector_in_the_mock_adapters_shape():
    """Same dict shape as `dev_run.mock_adapters()`: connector id -> adapter, so the run code is untouched. The run's
    `bank_run.drive` counts `adapter.sent` for every adapter, so each has an (empty) `sent`."""
    g = make_real_env()

    adapters = g.build()

    assert set(adapters) == set(g.registry.ids())
    assert set(GOOGLE_CONNECTORS) <= set(adapters)
    for connector_id, adapter in adapters.items():
        assert adapter.id == connector_id
        assert callable(adapter.execute_side_effect)
        assert len(adapter.sent) == 0, "nothing was sent: the run counts this"
        assert not hasattr(adapter, "send_reply"), "no direct send path (SEC-03)"
    assert g.transport.requests == [], "building the adapters needs no Google call"


def test_CL_LIVE_1_gmail_reads_reach_the_transport_and_need_no_gate():
    g = make_real_env()
    gmail = g.build()["gmail"]

    threads = gmail.list_threads(OWNER, max_results=5)
    found = gmail.search_threads(OWNER, "from:supplier", max_results=5)
    thread = gmail.get_thread(OWNER, "thr_1")
    message = gmail.get_message(OWNER, "msg_1")

    assert threads["threads"][0]["snippet"] == g.markers.snippet  # the caller gets the content; nothing else does
    assert found["threads"][0]["id"] == "thr_1"
    assert thread["messages"][0]["subject"] == g.markers.subject
    assert message["body_text"] == g.markers.body and message["untrusted"] is True
    assert g.transport.requests, "reads reach Google"
    assert all(r.method == "GET" and r.url.startswith(GMAIL_API) for r in g.transport.requests)
    assert g.transport.writes() == []
    assert g.emitted == [], "a read emits nothing and asks no gate"


def test_CL_LIVE_1_drive_read_of_a_typed_id_reaches_the_transport_and_other_ids_never_do():
    from tilo_connectors.adapters import NotPicked

    g = make_real_env()
    drive = g.build()["google_drive"]

    meta = drive.get_metadata(OWNER, "file_1")
    content = drive.download(OWNER, "file_1")

    assert meta["name"] == g.markers.drive_name and content.decode() == g.markers.drive_text
    assert all(r.method == "GET" and r.url.startswith(DRIVE_API) for r in g.transport.requests)
    before = len(g.transport.requests)
    with pytest.raises(NotPicked):
        drive.download(OWNER, "file_other")  # drive.file: only what the user typed or picked
    assert len(g.transport.requests) == before, "an id the user did not give is refused before any request names it"


def test_CL_LIVE_1_calendar_read_reaches_the_transport_and_needs_no_gate():
    from _connectors_lib import add_seconds

    g = make_real_env()
    calendar = g.build()["google_calendar"]
    now = g.env.clock()

    page = calendar.list_events(OWNER, page_size=10, time_min=now, time_max=add_seconds(now, 86400))

    assert [e.title for e in page.events] == [g.markers.event_title]
    (request,) = g.transport.requests
    assert request.method == "GET" and request.url == CALENDAR_EVENTS


def test_CL_LIVE_1_every_adapters_write_door_refuses_with_the_named_error_before_anything_else():
    """SEC-03's one write door. Read-only by construction: even a well-formed entry, with a grant the outbox minted,
    never gets as far as the broker or the transport."""
    from tilo_connectors.adapters import SideEffectRefused

    g = make_real_env()
    adapters = g.build()
    actions = {
        "gmail": ("send_email", "create_draft"),
        "google_drive": ("save_file", "save_as_google_file"),
        "google_calendar": ("create_event",),
        "meeting_host": ("create_meeting_event",),  # an invite
        "lovable": ("build_handoff",),
    }
    asked_before = list(g.spy.asked)
    for connector_id, adapter in adapters.items():
        for action in actions.get(connector_id, ("anything",)):
            for grant in (object(), None):
                with pytest.raises(real().RealWritesDisabled) as info:
                    adapter.execute_side_effect(_entry(connector_id, action), grant)
                assert isinstance(info.value, SideEffectRefused), "final for the outbox: the entry fails, never retries"
                assert str(info.value) == WRITE_REFUSAL
    assert g.transport.requests == []
    assert g.spy.asked == asked_before, "the broker is not even asked for a token"


@pytest.mark.parametrize(
    ("build_case", "connector"),
    [
        (lambda item: gmail_case(item=item, destination="thr_1"), "gmail"),
        (lambda item: gmail_case(action_type="create_draft", item=item, destination="thr_1"), "gmail"),
        (lambda item: drive_case(item=item), "google_drive"),
        (lambda item: drive_case(item=item, action_type="save_as_google_file"), "google_drive"),
    ],
    ids=["send_email", "create_draft", "save_file", "save_as_google_file"],
)
def test_CL_LIVE_1_a_plan_that_asks_for_a_send_or_a_save_through_the_outbox_changes_nothing_at_google(
    build_case, connector
):
    """The whole public path: enqueue, then `dispatch_due`. The entry ends `failed` (final), and not one request of any
    kind (read or write) went out: the refusal comes before the adapter's own earlier-attempt lookup."""
    from tilo_connectors.outbox import Outbox
    from tilo_connectors.store import InMemoryOutboxStore

    g = make_real_env()
    outbox = Outbox(InMemoryOutboxStore(), g.build(), emit=g.emitted.append, clock=g.env.clock)
    case = build_case({"artifact_id": "art_reply_1", "version": 1})
    enqueue(outbox, case)

    settled = outbox.dispatch_due()

    assert {e["id"]: e["state"] for e in settled} == {case["entry"]["id"]: "failed"}
    assert g.transport.requests == []
    assert g.transport.writes() == []
    assert [e for e in g.emitted if e["type"] == "data.transfer"] == [], (
        "nothing was sent, so nothing is recorded as sent"
    )


def test_CL_LIVE_1_the_public_surface_is_the_pinned_reads_and_the_one_refusing_door():
    """No other way to write: nothing but the pinned read methods, `id`, `sent` and `execute_side_effect` is public."""
    from tilo_connectors.side_effects import SIDE_EFFECT_METHOD_NAMES

    g = make_real_env()
    adapters = g.build()
    assert {k: set(v) for k, v in real().READ_METHODS.items()} == READS
    for connector_id, adapter in adapters.items():
        public = {n for n in dir(adapter) if not n.startswith("_") and callable(getattr(adapter, n))}
        assert public == READS.get(connector_id, set()) | {"execute_side_effect"}, connector_id
        assert not (public & (SIDE_EFFECT_METHOD_NAMES - {"execute_side_effect"}))
    assert not hasattr(adapters["gmail"], "watch") and not hasattr(adapters["gmail"], "stop_watch"), (
        "a Gmail watch is a POST: not part of the read set"
    )


def test_CL_LIVE_1_no_non_get_request_goes_out_over_the_whole_read_surface():
    g = make_real_env()
    adapters = g.build()

    read_everything(adapters, g.env)

    assert g.transport.requests
    assert {r.method for r in g.transport.requests} == {"GET"}
    assert g.transport.writes() == []


def test_CL_LIVE_1_real_module_exists_and_never_references_a_side_effect_name():
    """SEC-03's static scan: only outbox.py may call or name a side-effect method. real.py may define one."""
    from tilo_connectors.side_effects import scan_for_side_effect_calls

    assert REAL_PY.is_file(), "services/connectors/src/tilo_connectors/real.py is the pinned module"
    outbox = REAL_PY.parent / "outbox.py"
    assert scan_for_side_effect_calls([REAL_PY], allowed_path=outbox) == []


def test_CL_LIVE_1_real_adapters_signature_is_the_pinned_one():
    sig = inspect.signature(real().real_adapters)
    params = sig.parameters
    assert list(params)[:3] == ["broker", "registry", "transport"]
    for name in ("user_id", "environ", "mode", "providers_fake", "picks", "clock", "emit", "sleep"):
        assert params[name].kind is inspect.Parameter.KEYWORD_ONLY, name
    assert params["mode"].default == "live" and params["providers_fake"].default is False
    assert params["user_id"].default is inspect.Parameter.empty
    assert CONNECTORS_YAML.is_file()
