"""ADR35_L4 / FR_CON_02: the person's public connect routes (ADR-0035 decisions 2 and 3, LC-03, LC-05, LC-06).

`POST /v1/connectors/connect|callback|disconnect`. The person is the verified principal on a full sign-in session and
nothing else. A scripted transport stands in for tilo-connectors; the real outbox store holds the entries. tilo-api
never logs, stores or echoes the one-time `code`, the `state` or a token: every one is assembled at run time here.
"""

from __future__ import annotations

import json
import logging
import secrets
from typing import Any

import pytest
import test_ADR32_T4_FR_MTG_09_host_rpc as t4
from _mtg09b_lib import block_network
from _ppl11a_lib import OWNER
from tilo_api import deps
from tilo_api.meeting_host_rpc import HostRpcError, MeetingHostRpc, Reply, TransportError
from tilo_connectors import InMemoryOutboxStore, Outbox

ENTRY, EVIDENCE, NOW = t4.ENTRY, t4.EVIDENCE, t4.NOW
ENTRY_USER = ENTRY["authz"]["ref"]
URL = "https://tilo-connectors-" + secrets.token_hex(3) + ".a.run.app"
START = "/v1/connectors/connect"
CALLBACK = "/v1/connectors/callback"
DISCONNECT = "/v1/connectors/disconnect"
ALERT_ID = "01JB5VQ0000000000000000777"


def _authorize(state: str) -> str:
    return "https://accounts.google.com/o/oauth2/v2/auth?client_id=abc.apps&response_type=code&state=" + state


def _revoked(connector: str, user: str = OWNER) -> dict[str, Any]:
    return {"type": "connection.revoked", "connector": connector, "user_id": user}


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    block_network(monkeypatch)


class Transport:
    def __init__(self, store: InMemoryOutboxStore, *replies: Any) -> None:
        self.store, self.replies, self.calls, self.at_call = store, list(replies), [], []

    def post(self, url: str, body: bytes, headers: dict[str, str], timeout_s: float) -> Reply:
        self.calls.append({"path": url.removeprefix(URL), "json": json.loads(body), "headers": dict(headers)})
        self.at_call.append({e["id"]: e["state"] for e in self.store.all_entries()})
        got = self.replies.pop(0) if self.replies else TransportError()
        if isinstance(got, Exception):
            raise got
        return got


def ok(doc: Any, status: int = 200) -> Reply:
    return Reply(status, json.dumps(doc).encode())


@pytest.fixture()
def rig(people_rig):
    class R:
        def __init__(self) -> None:
            self.p = people_rig()
            self.p.add_people()
            self.store = InMemoryOutboxStore()
            self.token = "idtok." + secrets.token_hex(12)
            self.code = "4/0A" + secrets.token_hex(16)  # Google's one-time code
            self.state = secrets.token_urlsafe(24)
            self.set(())
            self.p.app.dependency_overrides[deps.get_outbox_store] = lambda: self.store

        def set(self, replies: tuple) -> None:
            self.transport = Transport(self.store, *replies)
            rpc = MeetingHostRpc(URL, transport=self.transport, token_for=lambda audience: self.token)
            self.p.app.dependency_overrides[deps.get_meeting_host_client] = lambda: rpc

        def enqueue(self, user: str = ENTRY_USER) -> str:
            Outbox(
                self.store,
                {"meeting_host": object()},
                emit=lambda p: None,
                clock=lambda: NOW,
                world_id=ENTRY["world_id"],
            ).enqueue(json.loads(json.dumps(ENTRY)), json.loads(json.dumps(EVIDENCE)))
            self.store._by_id[ENTRY["id"]]["authz"]["ref"] = user
            return ENTRY["id"]

        def callback_body(self, **over: Any) -> dict[str, Any]:
            return {"state": self.state, "code": self.code, **over}

    return R()


# ---- connect ----------------------------------------------------------------------------------------------------


def test_ADR35_L4_FR_CON_02_connect_returns_the_authorize_url_and_asks_connectors_for_the_principal(rig):
    url = _authorize(rig.state)
    rig.set((ok({"authorize_url": url}),))
    response = rig.p.post(START, {"connector": "gmail", "capabilities": ["read"]})
    assert (response.status_code, response.json()) == (200, {"authorize_url": url})
    assert response.headers["cache-control"] == "no-store"
    call = rig.transport.calls[0]
    assert call["path"] == "/internal/connections/start"
    assert call["json"] == {"user_id": OWNER, "connector": "gmail", "capabilities": ["read"]}
    assert call["headers"]["Authorization"] == f"Bearer {rig.token}"


def test_ADR35_L4_FR_CON_02_connect_with_nothing_missing_answers_a_null_url(rig):
    rig.set((ok({"authorize_url": None}),))
    response = rig.p.post(START, {"connector": "google_calendar", "capabilities": ["read", "write"]})
    assert (response.status_code, response.json()) == (200, {"authorize_url": None})


@pytest.mark.parametrize(
    "body",
    [
        {"connector": "gmail", "capabilities": ["read"], "user_id": "u_other"},  # identity is never a body field
        {"connector": "nonesuch", "capabilities": ["read"]},
        {"connector": "lovable", "capabilities": ["send"]},  # not an oauth2 connector of the registry
        {"connector": "gmail", "capabilities": ["list"]},  # a capability Gmail does not declare
        {"connector": "gmail", "capabilities": []},
        {"connector": "gmail", "capabilities": ["read", "read"]},
        {"connector": "gmail"},
        {"capabilities": ["read"]},
        {"connector": "GMAIL", "capabilities": ["read"]},
    ],
)
def test_ADR35_L4_FR_CON_02_connect_body_is_closed_and_checked_against_the_registry(rig, body):
    rig.set((ok({"authorize_url": None}),))
    assert rig.p.post(START, body).status_code == 422
    assert rig.transport.calls == []


@pytest.mark.parametrize(
    ("reply", "detail"),
    [
        (ok({"error": "unauthenticated"}, 401), "not_configured"),
        (ok({"error": "forbidden"}, 403), "not_configured"),
        (ok({"error": "invalid_request"}, 422), "not_configured"),
        (ok({"error": "not_configured"}, 503), "not_configured"),
        (TransportError(), "unknown"),
        (ok({"error": "x"}, 500), "unknown"),
        (ok("junk"), "unknown"),
        (Reply(200, b"{"), "unknown"),
        (ok({"authorize_url": "https://evil.example/o/oauth2/v2/auth?x=1"}), "unknown"),
        (ok({"authorize_url": "https://accounts.google.com/o/oauth2/v2/auth?a=1&client_secret=s"}), "unknown"),
    ],
)
def test_ADR35_L4_FR_CON_02_connect_failures_are_fixed_503_codes(rig, reply, detail):
    rig.set((reply,))
    response = rig.p.post(START, {"connector": "gmail", "capabilities": ["read"]})
    assert (response.status_code, response.json()) == (503, {"detail": detail})
    assert response.headers["cache-control"] == "no-store"


def test_ADR35_L4_FR_CON_02_without_a_client_every_route_is_503_not_configured(rig):
    rig.p.app.dependency_overrides.pop(deps.get_meeting_host_client)
    deps.get_meeting_host_client.cache_clear()
    for path, body in (
        (START, {"connector": "gmail", "capabilities": ["read"]}),
        (CALLBACK, rig.callback_body()),
        (DISCONNECT, {"connector": "gmail"}),
    ):
        response = rig.p.post(path, body)
        assert (response.status_code, response.json()) == (503, {"detail": "not_configured"})


# ---- callback ---------------------------------------------------------------------------------------------------

GRANTED = {
    "connector": "gmail",
    "scope_lines": ["Read your Gmail messages"],
    "parts": [{"type": "connection.established", "connector": "gmail", "user_id": OWNER}],
}


def test_ADR35_L4_FR_CON_02_callback_hands_code_and_state_to_connectors_and_answers_connector_and_lines(rig):
    rig.set((ok(GRANTED),))
    response = rig.p.post(CALLBACK, rig.callback_body())
    assert (response.status_code, response.json()) == (
        200,
        {"connector": "gmail", "scope_lines": ["Read your Gmail messages"]},
    )
    assert response.headers["cache-control"] == "no-store"
    call = rig.transport.calls[0]
    assert call["path"] == "/internal/connections/callback"
    assert call["json"] == {"user_id": OWNER, "state": rig.state, "code": rig.code}
    assert rig.code not in response.text and rig.state not in response.text


def test_ADR35_L4_FR_CON_02_callback_with_googles_error_word_sends_error_and_no_code(rig):
    rig.set((ok({"error": "not_granted"}, 400),))
    response = rig.p.post(CALLBACK, {"state": rig.state, "error": "access_denied"})
    assert (response.status_code, response.json()) == (400, {"detail": "not_granted"})
    assert rig.transport.calls[0]["json"] == {"user_id": OWNER, "state": rig.state, "error": "access_denied"}


@pytest.mark.parametrize("code", ["start_again", "not_granted", "wrong_account"])
def test_ADR35_L4_FR_CON_02_callbacks_own_400s_are_one_fixed_code_each(rig, code):
    rig.set((ok({"error": code}, 400),))
    response = rig.p.post(CALLBACK, rig.callback_body())
    assert (response.status_code, response.json()) == (400, {"detail": code})
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    ("reply", "detail"),
    [
        (ok({"error": "forbidden"}, 403), "not_configured"),
        (ok({"error": "invalid_request"}, 422), "not_configured"),
        (ok({"error": "not_configured"}, 503), "not_configured"),
        (ok({"error": "invalid_request"}, 400), "unknown"),  # a 400 that is not one of the three is not trusted
        (ok({"error": "boom"}, 500), "unknown"),
        (TransportError(), "unknown"),
        (ok({"connector": "gmail", "scope_lines": [], "parts": []}), "unknown"),  # none granted is not a 200
        (ok({**GRANTED, "extra": 1}), "unknown"),
    ],
)
def test_ADR35_L4_FR_CON_02_callback_other_failures_are_fixed_503_codes(rig, reply, detail):
    rig.set((reply,))
    response = rig.p.post(CALLBACK, rig.callback_body())
    assert (response.status_code, response.json()) == (503, {"detail": detail})


@pytest.mark.parametrize(
    "body",
    [
        lambda r: {"state": r.state},  # neither code nor error
        lambda r: r.callback_body(error="access_denied"),  # both
        lambda r: {"state": "short", "code": r.code},
        lambda r: r.callback_body(code="bad code!"),
        lambda r: r.callback_body(user_id="u_other"),
        lambda r: r.callback_body(state=None),
        lambda r: {"state": r.state, "error": "Access Denied"},
    ],
)
def test_ADR35_L4_FR_CON_02_callback_body_is_closed_exactly_one_of_code_and_error_and_never_echoed(rig, body):
    sent = body(rig)
    rig.set((ok(GRANTED),))
    response = rig.p.post(CALLBACK, sent)
    assert response.status_code == 422 and rig.transport.calls == []
    for value in (rig.code, rig.state, "bad code!", "Access Denied"):
        assert value not in response.text


def test_ADR35_L4_FR_CON_02_callback_parts_of_another_user_are_dropped_and_the_own_ones_are_applied(rig):
    mine = rig.enqueue(user=OWNER)
    parts = [
        {"type": "connection.expired", "connector": "meeting_host", "user_id": OWNER},
        {"type": "connection.expired", "connector": "meeting_host", "user_id": "u_stranger"},
        {"type": "alert.raised", "alert_id": ALERT_ID},
    ]
    rig.set((ok({**GRANTED, "parts": parts}),))
    assert rig.p.post(CALLBACK, rig.callback_body()).status_code == 200
    assert rig.store.get(mine)["state"] == "failed"  # abandon_unsent, exactly like T6


def test_ADR35_L4_FR_CON_02_a_stranger_part_abandons_nothing(rig):
    other = rig.enqueue(user="u_stranger")
    parts = [{"type": "connection.revoked", "connector": "meeting_host", "user_id": "u_stranger"}]
    rig.set((ok({**GRANTED, "parts": parts}),))
    assert rig.p.post(CALLBACK, rig.callback_body()).status_code == 200
    assert rig.store.get(other)["state"] == "queued"


# ---- disconnect -------------------------------------------------------------------------------------------------


def test_ADR35_L4_FR_CON_02_disconnect_of_a_person_connector_posts_the_id_and_answers_the_revoke(rig):
    parts = [_revoked(c) for c in ("gmail", "google_drive", "google_calendar")]
    rig.set((ok({"revoked_at_provider": True, "parts": parts}),))
    response = rig.p.post(DISCONNECT, {"connector": "gmail"})
    assert (response.status_code, response.json()) == (
        200,
        {"disconnected": True, "revoked_at_provider": True, "revoke_pending": False},
    )
    assert rig.transport.calls[0]["path"] == "/internal/connections/disconnect"
    assert rig.transport.calls[0]["json"] == {"user_id": OWNER, "connector": "gmail"}


def test_ADR35_L4_FR_CON_02_disconnecting_the_bot_connector_abandons_its_unsent_entries_before_the_call(rig):
    entry_id = rig.enqueue(user=OWNER)
    rig.set((ok({"revoked_at_provider": True, "parts": [_revoked("meeting_host")]}),))
    assert rig.p.post(DISCONNECT, {"connector": "meeting_host"}).status_code == 200
    assert rig.transport.at_call[0][entry_id] == "failed" and rig.store.get(entry_id)["state"] == "failed"


def test_ADR35_L4_FR_CON_02_a_kept_revoke_is_pending_and_only_its_alert_id_is_logged(rig, caplog):
    caplog.set_level(logging.WARNING)
    parts = [_revoked("gmail"), {"type": "alert.raised", "alert_id": ALERT_ID}]
    rig.set((ok({"revoked_at_provider": False, "parts": parts}),))
    body = rig.p.post(DISCONNECT, {"connector": "gmail"}).json()
    assert body == {"disconnected": True, "revoked_at_provider": False, "revoke_pending": True}
    assert ALERT_ID in caplog.text


@pytest.mark.parametrize(
    ("reply", "detail"),
    [
        (ok({"error": "forbidden"}, 403), "not_configured"),
        (ok({"error": "not_configured"}, 503), "not_configured"),
        (TransportError(), "unknown"),
        (ok({"error": "x"}, 500), "unknown"),
        (ok({"revoked_at_provider": True}), "unknown"),
    ],
)
def test_ADR35_L4_FR_CON_02_a_failed_disconnect_is_never_success(rig, reply, detail):
    rig.set((reply,))
    response = rig.p.post(DISCONNECT, {"connector": "google_drive"})
    assert (response.status_code, response.json()) == (503, {"detail": detail})


@pytest.mark.parametrize("body", [{}, {"connector": "gmail", "user_id": "u_other"}, {"connector": "nonesuch"}])
def test_ADR35_L4_FR_CON_02_disconnect_body_is_closed_and_the_connector_is_the_registrys(rig, body):
    rig.set((ok({"revoked_at_provider": False, "parts": []}),))
    assert rig.p.post(DISCONNECT, body).status_code == 422 and rig.transport.calls == []


def test_ADR35_L4_FR_CON_02_an_unreadable_outbox_stops_a_bot_disconnect_before_the_call(rig, monkeypatch):
    monkeypatch.setattr(rig.store, "all_entries", lambda: (_ for _ in ()).throw(RuntimeError("down")))
    rig.set((ok({"revoked_at_provider": True, "parts": []}),))
    response = rig.p.post(DISCONNECT, {"connector": "meeting_host"})
    assert (response.status_code, response.json()) == (503, {"detail": "unknown"}) and rig.transport.calls == []


# ---- who may call, the limit, the cap, the logs -----------------------------------------------------------------

ROUTES = [
    (START, {"connector": "gmail", "capabilities": ["read"]}),
    (CALLBACK, None),
    (DISCONNECT, {"connector": "gmail"}),
]


@pytest.mark.parametrize("who", ["anonymous", "demo"])
@pytest.mark.parametrize("path", [r[0] for r in ROUTES])
def test_ADR35_L4_FR_CON_02_only_a_full_session_may_connect_anonymous_is_401_and_demo_is_403(rig, who, path):
    body = dict(ROUTES)[path] or rig.callback_body()
    rig.set((ok(GRANTED),))
    if who == "anonymous":
        rig.p.sign_out()
    else:
        rig.p.full_session = False
    response = rig.p.post(path, body)
    assert response.status_code == (401 if who == "anonymous" else 403) and rig.transport.calls == []
    assert rig.code not in response.text and rig.state not in response.text


def test_ADR35_L4_FR_CON_02_the_61st_post_attempt_a_minute_is_429(rig):
    rig.set(tuple(ok({"authorize_url": None}) for _ in range(61)))
    body = {"connector": "gmail", "capabilities": ["read"]}
    codes = [rig.p.post(START, body).status_code for _ in range(61)]
    assert codes[:60] == [200] * 60 and codes[60] == 429


def test_ADR35_L4_FR_CON_02_the_identity_is_the_principals_never_a_query_or_header(rig):
    rig.set((ok({"authorize_url": None}),))
    other = "u_" + secrets.token_hex(4)
    rig.p.post(
        START,
        {"connector": "gmail", "capabilities": ["read"]},
        params={"user_id": other},
        headers={"X-Tilo-User": other},
    )
    assert rig.transport.calls[0]["json"]["user_id"] == OWNER


def test_ADR35_L4_FR_CON_02_code_state_and_tokens_are_in_no_answer_and_no_log(rig, caplog):
    caplog.set_level(logging.DEBUG)
    texts: list[str] = []
    for reply in (
        TransportError(rig.code + rig.state),
        ok({"error": "forbidden"}, 403),
        ok({"error": "start_again"}, 400),
        ok({"error": "x"}, 500),
        ok(GRANTED),
    ):
        rig.set((reply,))
        texts.append(rig.p.post(CALLBACK, rig.callback_body()).text)
    rig.set((TransportError(rig.token),))
    texts.append(rig.p.post(START, {"connector": "gmail", "capabilities": ["read"]}).text)
    texts.append(rig.p.post(CALLBACK, rig.callback_body(code="bad code!")).text)
    logged = "\n".join(texts + [r.getMessage() for r in caplog.records] + [str(r.args) for r in caplog.records])
    for secret in (rig.code, rig.state, rig.token):
        assert secret not in logged


# ---- the client -------------------------------------------------------------------------------------------------


def test_ADR35_L4_FR_CON_02_the_client_maps_each_failure_to_a_fixed_error(rig):
    rig.set((ok({"error": "start_again"}, 400), ok({"error": "nope"}, 400), TransportError(), ok(GRANTED)))
    rpc = rig.p.app.dependency_overrides[deps.get_meeting_host_client]()
    with pytest.raises(HostRpcError) as caught:
        rpc.connect_callback(OWNER, state=rig.state, code=rig.code)
    assert (caught.value.kind, caught.value.code) == ("rejected", "start_again")
    with pytest.raises(HostRpcError) as caught:
        rpc.connect_callback(OWNER, state=rig.state, code=rig.code)
    assert (caught.value.kind, caught.value.code) == ("unknown", None)
    with pytest.raises(HostRpcError) as caught:
        rpc.connect_disconnect(OWNER, "gmail")
    assert caught.value.kind == "unknown"
    got = rpc.connect_callback(OWNER, state=rig.state, code=rig.code)
    assert got.connector == "gmail" and repr(rpc) == "MeetingHostRpc()"


def test_ADR35_L4_FR_CON_02_a_400_on_any_other_route_is_not_a_callback_refusal(rig):
    rig.set((ok({"error": "start_again"}, 400),))
    rpc = rig.p.app.dependency_overrides[deps.get_meeting_host_client]()
    with pytest.raises(HostRpcError) as caught:
        rpc.connect_start(OWNER, "gmail", ["read"])
    assert (caught.value.kind, caught.value.code) == ("unknown", None)
