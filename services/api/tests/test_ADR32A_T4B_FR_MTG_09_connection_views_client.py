"""ADR32A_T4B / FR_MTG_09: tilo-api's client for POST /internal/connections/views (ADR-0032 addendum 1, decision 6).

A scripted transport stands in for tilo-connectors. Every failure, whatever its kind, is "unknown": `None`, never a
raise, never a retry inside one call, and no token or id in a log line. No network, no live switch; tokens are
assembled at run time.
"""

from __future__ import annotations

import copy
import json
import logging
import secrets
import threading
from typing import Any

import pytest
from fastapi import HTTPException
from tilo_api import deps
from tilo_api.meeting_host_rpc import (
    MAX_VIEWS_REPLY_BYTES,
    MeetingHostRpc,
    Reply,
    RequestsTransport,
    TransportError,
)

URL = "https://tilo-connectors-" + secrets.token_hex(3) + ".a.run.app"
USER = "u_" + secrets.token_hex(4)
ORDER = ["gmail", "google_drive", "google_calendar", "meeting_host"]
GOOD = {
    "views": [
        {"connector": "gmail", "state": "connected", "scopes": ["https://www.googleapis.com/auth/gmail.readonly"],
         "connected_at": "2026-10-08T09:00:00.000Z"},
        {"connector": "google_drive", "state": "expired", "scopes": [], "connected_at": None},
        {"connector": "meeting_host", "state": "connected",
         "scopes": ["https://www.googleapis.com/auth/calendar.events.owned"],
         "connected_at": "2026-10-08T09:01:00.000Z"},
    ]
}  # fmt: skip


def reply(doc: Any, status: int = 200) -> Reply:
    return Reply(status, json.dumps(doc).encode())


class Scripted:
    def __init__(self, *replies: Any) -> None:
        self.replies, self.calls = list(replies), []

    def post(self, url: str, body: bytes, headers: dict[str, str], timeout_s: float) -> Reply:
        self.calls.append({"url": url, "json": json.loads(body), "headers": dict(headers), "timeout_s": timeout_s})
        got = self.replies.pop(0) if self.replies else TransportError()
        if isinstance(got, Exception):
            raise got
        return got


class Rig:
    def __init__(self, *replies: Any, fetch: Any = None, **kwargs: Any) -> None:
        self.token = "idtok." + secrets.token_hex(12)
        self.audiences: list[str] = []
        self.transport = Scripted(*replies)
        self.rpc = MeetingHostRpc(URL, transport=self.transport, token_for=fetch or self._fetch, **kwargs)

    def _fetch(self, audience: str) -> str:
        self.audiences.append(audience)
        return self.token

    def views(self, order: list[str] | None = None) -> Any:
        return self.rpc.connection_views(USER, order=ORDER if order is None else order)


def test_ADR32A_T4B_FR_MTG_09_a_good_answer_is_read_and_the_call_is_the_contracts() -> None:
    rig = Rig(reply(GOOD))
    got = rig.views()
    assert [(v.connector, v.state, v.connected_at) for v in got] == [
        ("gmail", "connected", "2026-10-08T09:00:00.000Z"),
        ("google_drive", "expired", None),
        ("meeting_host", "connected", "2026-10-08T09:01:00.000Z"),
    ]
    (call,) = rig.transport.calls
    assert call["url"] == URL + "/internal/connections/views" and call["json"] == {"user_id": USER}
    assert call["headers"]["Authorization"] == f"Bearer {rig.token}" and rig.audiences == [URL]
    assert call["timeout_s"] <= 10.0


def test_ADR32A_T4B_FR_MTG_09_no_views_is_an_empty_list_not_unknown() -> None:
    assert Rig(reply({"views": []})).views() == []


@pytest.mark.parametrize("status", [401, 403, 422, 500, 502, 503])
def test_ADR32A_T4B_FR_MTG_09_every_error_status_is_unknown_and_is_not_retried(status: int) -> None:
    code = {401: "unauthenticated", 403: "forbidden", 422: "invalid_request"}.get(status, "not_configured")
    rig = Rig(reply({"error": code}, status), reply(GOOD))
    assert rig.views() is None
    assert len(rig.transport.calls) == 1


def test_ADR32A_T4B_FR_MTG_09_a_lost_connection_or_a_token_failure_is_unknown() -> None:
    assert Rig(TransportError()).views() is None
    leak = "sk-" + secrets.token_hex(6)

    def no_token(audience: str) -> str:
        raise RuntimeError(leak)

    rig = Rig(reply(GOOD), fetch=no_token)
    assert rig.views() is None and rig.transport.calls == []


def test_ADR32A_T4B_FR_MTG_09_a_call_past_its_deadline_is_unknown_without_waiting_for_it() -> None:
    release = threading.Event()

    class Hanging:
        def post(self, *a: Any, **k: Any) -> Reply:
            release.wait(5)
            return reply(GOOD)

    rpc = MeetingHostRpc(URL, transport=Hanging(), token_for=lambda a: "t", views_timeout_s=0.2)
    try:
        assert rpc.connection_views(USER, order=ORDER) is None
    finally:
        release.set()


@pytest.mark.parametrize(
    "doc",
    [
        {"views": [{"connector": "gmail"}]},
        {"views": [], "parts": []},
        {"nope": 1},
        [],
        {"views": [{**GOOD["views"][0], "expires_at": "2026-10-08T09:00:00.000Z"}]},
        {"views": [{**GOOD["views"][0], "state": "revoked"}]},
        {"views": [{**GOOD["views"][1], "scopes": ["https://www.googleapis.com/auth/gmail.readonly"]}]},
        {"views": [{**GOOD["views"][1], "connected_at": "2026-10-08T09:00:00.000Z"}]},
        {"views": [GOOD["views"][0]] * 2},  # a connector twice
        {"views": [GOOD["views"][2], GOOD["views"][0]]},  # not in registry order
        {"views": [{**GOOD["views"][0], "connector": "lovable"}]},  # not in the registry's oauth2 order
        {"views": [{**GOOD["views"][0], "scopes": ["not a scope"]}]},
        {"views": [GOOD["views"][0]] * 33},
    ],
)
def test_ADR32A_T4B_FR_MTG_09_an_answer_that_breaks_the_contract_or_hb09_is_unknown_as_a_whole(doc: Any) -> None:
    assert Rig(reply(doc)).views() is None


def test_ADR32A_T4B_FR_MTG_09_a_body_that_is_not_json_or_is_over_the_cap_is_unknown() -> None:
    for body in (b"", b"{", b"\xff\xfe", b"[" * 100_000, b" " * (MAX_VIEWS_REPLY_BYTES + 1)):
        assert Rig(Reply(200, body)).views() is None


def test_ADR32A_T4B_FR_MTG_09_the_requests_transport_reads_up_to_256_kib_for_views_and_64_kib_elsewhere(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import requests

    seen: list[int] = []

    class Raw:
        def read(self, n: int, decode_content: bool = True) -> bytes:
            seen.append(n)
            return b"{}"

    class Resp:
        status_code, raw = 200, Raw()

        def __enter__(self) -> Resp:
            return self

        def __exit__(self, *a: Any) -> None:
            return None

    monkeypatch.setattr(requests, "post", lambda *a, **k: Resp())
    RequestsTransport().post(URL + "/internal/connections/views", b"{}", {}, 1.0)
    RequestsTransport().post(URL + "/internal/meeting-host/status", b"{}", {}, 1.0)
    assert seen == [MAX_VIEWS_REPLY_BYTES + 1, 65_536 + 1] and MAX_VIEWS_REPLY_BYTES == 262_144


def test_ADR32A_T4B_FR_MTG_09_nothing_the_call_carries_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    leak = "sk-" + secrets.token_hex(6)
    rigs = [
        Rig(reply({"error": "forbidden"}, 403)),
        Rig(TransportError()),
        Rig(reply({"views": [{"connector": leak}]})),
        Rig(reply(GOOD), fetch=lambda a: (_ for _ in ()).throw(RuntimeError(leak))),
    ]
    with caplog.at_level(logging.DEBUG):
        for rig in rigs:
            assert rig.views() is None
    text = caplog.text
    assert leak not in text and USER not in text and all(r.token not in text for r in rigs)
    assert "403" in text  # a status code is the one value a log line may carry


def test_ADR32A_T4B_FR_MTG_09_the_repr_holds_no_token_or_url() -> None:
    assert repr(Rig().rpc) == "MeetingHostRpc()"


# ---- the deps provider ------------------------------------------------------------------------


@pytest.fixture()
def cold(monkeypatch: pytest.MonkeyPatch) -> Any:
    deps.get_meeting_host_client.cache_clear()
    monkeypatch.delenv("TILO_CONNECTORS_URL", raising=False)
    yield
    deps.get_meeting_host_client.cache_clear()


def test_ADR32A_T4B_FR_MTG_09_the_provider_is_503_not_configured_unless_the_client_is_configured(cold: Any) -> None:
    with pytest.raises(HTTPException) as caught:
        deps.get_connection_views_rpc()
    assert (caught.value.status_code, caught.value.detail) == (503, "not_configured")


def test_ADR32A_T4B_FR_MTG_09_a_configured_provider_gives_a_callable_that_never_raises(
    cold: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = Rig(reply(GOOD), TransportError())
    monkeypatch.setattr(deps, "open_meeting_host_rpc", lambda env: rig.rpc)
    registry_ids = deps.get_connector_registry().ids()
    views = deps.get_connection_views_rpc()
    got = views(USER)
    assert [v.connector for v in got] == ["gmail", "google_drive", "meeting_host"]
    assert views(USER) is None  # the lost connection: unknown, not a raise
    assert "lovable" in registry_ids  # the order given to the client is the oauth2 subset
    assert rig.transport.calls[0]["json"] == {"user_id": USER}


def test_ADR32A_T4B_FR_MTG_09_the_provider_order_is_the_registrys_oauth2_ids(
    cold: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = Rig(reply(copy.deepcopy(GOOD)))
    monkeypatch.setattr(deps, "open_meeting_host_rpc", lambda env: rig.rpc)
    seen: list[list[str]] = []
    inner = rig.rpc.connection_views
    rig.rpc.connection_views = lambda user_id, *, order: (seen.append(list(order)), inner(user_id, order=order))[1]  # type: ignore[method-assign]
    deps.get_connection_views_rpc()(USER)
    registry = deps.get_connector_registry()
    assert seen == [[c for c in registry.ids() if registry.get(c)["auth"] == "oauth2"]]
