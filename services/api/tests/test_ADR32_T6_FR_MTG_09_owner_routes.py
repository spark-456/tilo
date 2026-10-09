"""ADR32_T6 / FR_MTG_09: the owner's own connection routes on tilo-api (ADR-0032 decisions 5 to 7, ADR-0024).

`GET /v1/meeting-host/connection` (status) and `POST /v1/meeting-host/disconnect` (abandon first, then connectors'
disconnect). The person is always the verified principal, never a path, query or body value. A scripted transport stands
in for tilo-connectors; the real outbox store and the real `Outbox` hold the entries. No network, no live switch; every
token is assembled at run time.
"""

from __future__ import annotations

import copy
import json
import logging
import secrets
from typing import Any

import pytest
import test_ADR32_T4_FR_MTG_09_host_rpc as t4  # the contract's own send fixture: ENTRY, EVIDENCE, NOW
from _mtg09b_lib import block_network
from _ppl11a_lib import OWNER
from tilo_api import deps, meeting_host
from tilo_api.meeting_host_rpc import HostRpcError, MeetingHostRpc, Reply, TransportError
from tilo_connectors import InMemoryOutboxStore, Outbox

ENTRY, EVIDENCE, NOW = t4.ENTRY, t4.EVIDENCE, t4.NOW
ENTRY_USER = ENTRY["authz"]["ref"]
URL = "https://tilo-connectors-" + secrets.token_hex(3) + ".a.run.app"
CONNECTED = {"state": "connected", "scope_ok": True}
REVOKED = {"type": "connection.revoked", "connector": "meeting_host", "user_id": ENTRY_USER}


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    block_network(monkeypatch)


class Transport:
    """Scripted connectors; on a `disconnect` call it also records what the outbox store held at that moment."""

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
            self.set(())
            self.p.app.dependency_overrides[deps.get_outbox_store] = lambda: self.store

        def set(self, replies: tuple) -> None:
            self.transport = Transport(self.store, *replies)
            rpc = MeetingHostRpc(URL, transport=self.transport, token_for=lambda audience: self.token)
            self.p.app.dependency_overrides[deps.get_meeting_host_client] = lambda: rpc

        def enqueue(self, *, user: str = ENTRY_USER, key: str = "1") -> str:
            """The contract's own entry, enqueued by the real outbox (its evidence is bound to it); further entries are
            copies put straight into the store under another id and another owner."""
            if self.store.get(ENTRY["id"]) is None:
                Outbox(self.store, {"meeting_host": object()}, emit=lambda p: None, clock=lambda: NOW,
                       world_id=ENTRY["world_id"]).enqueue(copy.deepcopy(ENTRY), copy.deepcopy(EVIDENCE))  # fmt: skip
                first = ENTRY["id"]
            else:
                first = None
            entry = copy.deepcopy(self.store.get(ENTRY["id"]))
            if first is None:
                entry["id"] = "01JB5VQ00000000000000000" + key.zfill(2)
                entry["idempotency_key"] += key
                assert self.store._insert_if_absent(entry)
            entry_id = entry["id"]
            self.store._by_id[entry_id]["authz"]["ref"] = user
            return entry_id

        def state(self, entry_id: str) -> str:
            return self.store.get(entry_id)["state"]

    return R()


# ---- GET /v1/meeting-host/connection ---------------------------------------------------------------------------

STATUS_ROWS = [
    ("connected", CONNECTED, {"state": "connected", "scope_ok": True}),
    ("expired", {"state": "expired", "scope_ok": False}, {"state": "expired", "scope_ok": False}),
    ("none", {"state": "none", "scope_ok": False}, {"state": "none", "scope_ok": False}),
]


@pytest.mark.parametrize(("name", "answer", "expected"), STATUS_ROWS, ids=[r[0] for r in STATUS_ROWS])
def test_ADR32_T6_FR_MTG_09_status_answers_the_contracts_fields_and_nothing_else(rig, name, answer, expected):
    rig.set((ok(answer),))
    response = rig.p.get("/v1/meeting-host/connection")
    assert (response.status_code, response.json()) == (200, expected)
    assert response.headers["cache-control"] == "no-store"
    assert rig.transport.calls[0]["path"] == "/internal/meeting-host/status"


@pytest.mark.parametrize(
    ("name", "reply"),
    [
        ("401", ok({"error": "unauthenticated"}, 401)),
        ("403", ok({"error": "forbidden"}, 403)),
        ("503 not_configured", ok({"error": "not_configured"}, 503)),
    ],
)
def test_ADR32_T6_FR_MTG_09_status_refused_by_connectors_is_a_fixed_503_not_configured(rig, name, reply):
    rig.set((reply,))
    response = rig.p.get("/v1/meeting-host/connection")
    assert (response.status_code, response.json()) == (503, {"detail": "not_configured"})
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "reply",
    [
        TransportError(),
        ok({"error": "boom"}, 500),
        ok("junk"),
        Reply(200, b"{"),
        ok({"state": "none", "scope_ok": True}),
    ],
)
def test_ADR32_T6_FR_MTG_09_status_that_failed_or_broke_the_contract_is_a_fixed_503_unknown(rig, reply):
    rig.set((reply,))
    response = rig.p.get("/v1/meeting-host/connection")
    assert (response.status_code, response.json()) == (503, {"detail": "unknown"})


def test_ADR32_T6_FR_MTG_09_status_is_503_not_configured_without_a_client(rig):
    rig.p.app.dependency_overrides.pop(deps.get_meeting_host_client)
    deps.get_meeting_host_client.cache_clear()
    response = rig.p.get("/v1/meeting-host/connection")
    assert (response.status_code, response.json()) == (503, {"detail": "not_configured"})


def test_ADR32_T6_FR_MTG_09_the_person_is_the_principal_never_a_query_or_header(rig):
    rig.set((ok(CONNECTED),))
    other = "u_" + secrets.token_hex(4)
    rig.p.get("/v1/meeting-host/connection", params={"user_id": other}, headers={"X-Tilo-User": other})
    assert rig.transport.calls[0]["json"] == {"user_id": OWNER}


def test_ADR32_T6_FR_MTG_09_status_needs_a_full_sign_in_session(rig):
    rig.p.sign_out()
    assert rig.p.get("/v1/meeting-host/connection").status_code == 401
    rig.p.as_user(OWNER)
    rig.p.full_session = False  # an anonymous demo session
    response = rig.p.get("/v1/meeting-host/connection")
    assert (response.status_code, response.json()) == (403, {"detail": "forbidden"}) and rig.transport.calls == []


def test_ADR32_T6_FR_MTG_09_a_viewer_role_reads_only_its_own_status(rig):
    rig.set((ok(CONNECTED),))
    rig.p.as_user("u_viewer", role="viewer", world_id="w_x")
    assert rig.p.get("/v1/meeting-host/connection").status_code == 200
    assert rig.transport.calls[0]["json"] == {"user_id": "u_viewer"}


# ---- POST /v1/meeting-host/disconnect --------------------------------------------------------------------------

REVOKED_OWN = {"revoked_at_provider": True, "parts": [{**REVOKED, "user_id": OWNER}]}


def test_ADR32_T6_FR_MTG_09_disconnect_abandons_the_owners_unsent_entries_before_it_calls_connectors(rig):
    mine, other = rig.enqueue(user=OWNER, key="1"), rig.enqueue(user="u_stranger", key="2")
    rig.set((ok(REVOKED_OWN),))
    response = rig.p.post("/v1/meeting-host/disconnect")
    assert (response.status_code, response.json()) == (200, {"disconnected": True, "revoked_at_provider": True})
    assert rig.transport.calls[0]["path"] == "/internal/meeting-host/disconnect"
    assert rig.transport.calls[0]["json"] == {"user_id": OWNER}
    assert rig.transport.at_call[0][mine] == "failed" and rig.transport.at_call[0][other] == "queued"  # abandon first
    assert (rig.state(mine), rig.state(other)) == ("failed", "queued")
    assert response.headers["cache-control"] == "no-store"


def test_ADR32_T6_FR_MTG_09_disconnect_never_touches_an_entry_that_may_have_gone_out(rig):
    entry_id = rig.enqueue(user=OWNER)
    rig.store._retries[entry_id] = {"ambiguous": True}
    rig.set((ok({"revoked_at_provider": False, "parts": []}),))
    assert rig.p.post("/v1/meeting-host/disconnect").status_code == 200
    assert rig.state(entry_id) == "queued" and rig.transport.at_call[0][entry_id] == "queued"


def test_ADR32_T6_FR_MTG_09_a_failed_disconnect_is_not_success_the_abandon_stays_and_a_retry_works(rig):
    entry_id = rig.enqueue(user=OWNER)
    rig.set((TransportError(), ok(REVOKED_OWN)))
    first = rig.p.post("/v1/meeting-host/disconnect")
    assert (first.status_code, first.json()) == (503, {"detail": "unknown"}) and rig.state(entry_id) == "failed"
    second = rig.p.post("/v1/meeting-host/disconnect")
    assert (second.status_code, second.json()["disconnected"]) == (200, True)  # idempotent: nothing left to abandon


def test_ADR32_T6_FR_MTG_09_a_refused_disconnect_is_503_not_configured_never_success(rig):
    rig.set((ok({"error": "forbidden"}, 403),))
    response = rig.p.post("/v1/meeting-host/disconnect")
    assert (response.status_code, response.json()) == (503, {"detail": "not_configured"})


def test_ADR32_T6_FR_MTG_09_an_outbox_that_cannot_be_read_stops_the_disconnect_before_the_call(rig, monkeypatch):
    monkeypatch.setattr(rig.store, "all_entries", lambda: (_ for _ in ()).throw(RuntimeError("down")))
    rig.set((ok(REVOKED_OWN),))
    response = rig.p.post("/v1/meeting-host/disconnect")
    assert (response.status_code, response.json()) == (503, {"detail": "unknown"}) and rig.transport.calls == []


def test_ADR32_T6_FR_MTG_09_only_the_owners_own_parts_are_applied_and_alerts_raise_nothing_here(rig):
    stranger = rig.enqueue(user="u_stranger")
    parts = [{**REVOKED, "user_id": "u_stranger"}, {"type": "alert.raised", "alert_id": "01JB5VQ0000000000000000777"}]
    rig.set((ok({"revoked_at_provider": False, "parts": parts}),))
    response = rig.p.post("/v1/meeting-host/disconnect")
    assert response.json() == {"disconnected": True, "revoked_at_provider": False} and rig.state(stranger) == "queued"


def test_ADR32_T6_FR_MTG_09_a_part_for_the_owner_in_the_answer_abandons_what_a_lease_had_held(rig):
    entry_id = rig.enqueue(user=OWNER)
    calls: list[str] = []
    real = meeting_host.abandon_unsent

    def spy(user: str, store: Any) -> int:
        calls.append(user)
        return real(user, store)

    rig.set((ok(REVOKED_OWN),))
    import tilo_api.meeting_host_routes as routes

    routes.abandon_unsent = spy  # type: ignore[attr-defined]
    try:
        assert rig.p.post("/v1/meeting-host/disconnect").status_code == 200
    finally:
        routes.abandon_unsent = real  # type: ignore[attr-defined]
    assert calls == [OWNER, OWNER] and rig.state(entry_id) == "failed"


def test_ADR32_T6_FR_MTG_09_the_id_comes_from_the_principal_and_a_body_is_closed(rig):
    rig.set((ok(REVOKED_OWN),))
    other = "u_" + secrets.token_hex(4)
    assert rig.p.post("/v1/meeting-host/disconnect", {"user_id": other}).status_code == 422
    assert rig.transport.calls == []
    assert rig.p.post("/v1/meeting-host/disconnect", params={"user_id": other}).status_code == 200  # query is ignored
    assert rig.transport.calls[0]["json"] == {"user_id": OWNER}


def test_ADR32_T6_FR_MTG_09_disconnect_takes_no_body_or_an_empty_object(rig):
    rig.set((ok(REVOKED_OWN), ok(REVOKED_OWN)))
    assert rig.p.client.post("/v1/meeting-host/disconnect").status_code == 200
    assert rig.p.post("/v1/meeting-host/disconnect", {}).status_code == 200


@pytest.mark.parametrize("who", ["anonymous", "demo", "viewer_role"])
def test_ADR32_T6_FR_MTG_09_disconnect_refuses_anyone_but_a_full_session(rig, who):
    entry_id = rig.enqueue(user=OWNER)
    if who == "anonymous":
        rig.p.sign_out()
    elif who == "demo":
        rig.p.full_session = False
    else:
        rig.p.as_user(OWNER, role="viewer", world_id="w_x")
        rig.p.full_session = False
    response = rig.p.post("/v1/meeting-host/disconnect")
    assert response.status_code in (401, 403) and rig.transport.calls == [] and rig.state(entry_id) == "queued"


def test_ADR32_T6_FR_MTG_09_the_61st_post_attempt_a_minute_is_429(rig):
    rig.set(tuple(ok(REVOKED_OWN) for _ in range(61)))
    codes = [rig.p.post("/v1/meeting-host/disconnect").status_code for _ in range(61)]
    assert codes[:60] == [200] * 60 and codes[60] == 429


def test_ADR32_T6_FR_MTG_09_no_token_or_id_token_is_in_an_answer_or_a_log(rig, caplog):
    caplog.set_level(logging.DEBUG)
    rig.set((TransportError(rig.token), ok({"state": "connected", "scope_ok": True}), TransportError(rig.token)))
    texts = [rig.p.post("/v1/meeting-host/disconnect").text, rig.p.get("/v1/meeting-host/connection").text]
    texts.append(rig.p.post("/v1/meeting-host/disconnect").text)
    assert rig.token not in "\n".join(texts + [r.getMessage() for r in caplog.records])


# ---- the client ---------------------------------------------------------------------------------------------------


def test_ADR32_T6_FR_MTG_09_the_client_disconnect_posts_the_id_and_validates_the_answer(rig):
    rig.set(
        (ok(REVOKED_OWN), ok({"revoked_at_provider": True}), ok({"revoked_at_provider": True, "parts": [], "x": 1}))
    )
    rpc = rig.p.app.dependency_overrides[deps.get_meeting_host_client]()
    got = rpc.disconnect(OWNER)
    assert (got.revoked_at_provider, len(got.parts)) == (True, 1)
    for _ in range(2):  # a missing field and an unknown field break the contract: unknown
        with pytest.raises(HostRpcError) as caught:
            rpc.disconnect(OWNER)
        assert caught.value.kind == "unknown"
    assert rig.transport.calls[0]["headers"]["Authorization"] == f"Bearer {rig.token}"


@pytest.mark.parametrize(
    ("reply", "kind"),
    [
        (ok({"error": "forbidden"}, 403), "refused"),
        (ok({"error": "invalid_request"}, 422), "refused"),
        (ok({"error": "not_configured"}, 503), "refused"),
        (ok({"error": "x"}, 500), "unknown"),
        (TransportError(), "unknown"),
    ],
)
def test_ADR32_T6_FR_MTG_09_the_client_disconnect_outcomes_follow_the_t4_conventions(rig, reply, kind):
    rig.set((reply,))
    rpc = rig.p.app.dependency_overrides[deps.get_meeting_host_client]()
    with pytest.raises(HostRpcError) as caught:
        rpc.disconnect(OWNER)
    assert caught.value.kind == kind


def test_ADR32_T6_FR_MTG_09_a_token_that_cannot_be_minted_is_not_sent(rig):
    rpc = MeetingHostRpc(
        URL, transport=rig.transport, token_for=lambda a: (_ for _ in ()).throw(RuntimeError(rig.token))
    )
    with pytest.raises(HostRpcError) as caught:
        rpc.disconnect(OWNER)
    assert caught.value.kind == "not_sent" and rig.transport.calls == []
