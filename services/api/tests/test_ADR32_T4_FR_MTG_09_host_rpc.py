"""ADR32_T4 / FR_MTG_09: tilo-api's side of the meeting-host RPC (ADR-0032 decisions 6, 7, 8, HB-07).

A scripted transport stands in for tilo-connectors; the real `Outbox` (tilo-api's own, over an in-memory store) runs the
stub, so every row of the ADR's table is checked by what the outbox does with it. The base request is the contract's own
valid fixture. No network, no paid call, no live switch; every token is assembled at run time.
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
from tilo_api import deps, meeting_host
from tilo_api.meeting_host_rpc import (
    HostRpcError,
    HostRpcNotConfigured,
    MeetingHostRpc,
    MeetingHostStub,
    Reply,
    TransportError,
    open_meeting_host_rpc,
)
from tilo_connectors import InMemoryOutboxStore, Outbox
from tilo_connectors._schema import host_rpc_validator
from tilo_connectors.adapters import side_effect_marker
from tilo_connectors.meeting_host import HostReceipt
from tilo_connectors.outbox import RetryPolicy
from tilo_memory.artifacts import ArtifactCorrupt, ArtifactNotFound

CONTRACTS = pathlib.Path(__file__).resolve().parents[3] / "contracts"
BASE = json.loads((CONTRACTS / "fixtures/meeting_host_rpc.send_request/valid/owner_and_one_invitee.json").read_text())
ENTRY, EVIDENCE, DRAFT = BASE["entry"], BASE["evidence"], BASE["draft"]
RAW = base64.b64decode(DRAFT["content_b64"])
OWNER, STRANGER = ENTRY["authz"]["ref"], "u_" + secrets.token_hex(4)
URL = "https://tilo-connectors-" + secrets.token_hex(3) + ".a.run.app"
NOW = "2026-10-08T09:33:00.000Z"
CONNECTOR = "meeting_host"


def body(obj: Any) -> bytes:
    return json.dumps(obj).encode()


def receipt(**over: Any) -> dict[str, Any]:
    doc = json.loads(RAW)
    made = {
        "world_id": ENTRY["world_id"], "outbox_id": ENTRY["id"], "meeting_id": doc["meeting_id"], "owner": doc["owner"],
        "draft": dict(ENTRY["item"]), "event_ref": side_effect_marker(ENTRY), "conference": "success",
    }  # fmt: skip
    return {**made, **over}


def answer(outcome: str, *, may_have_sent: bool | None = None, parts: list | None = None, **over: Any) -> Reply:
    doc = {
        "outcome": outcome, "receipt": receipt(**over) if outcome == "sent" else None,
        "may_have_sent": may_have_sent, "parts": parts or [],
    }  # fmt: skip
    return Reply(200, body(doc))


def part(kind: str = "connection.revoked", user: str = OWNER) -> dict[str, str]:
    return {"type": kind, "connector": CONNECTOR, "user_id": user}


class Scripted:
    """The transport: records every call, answers from a script (a Reply, or an exception to raise)."""

    def __init__(self, *replies: Any) -> None:
        self.replies, self.calls = list(replies), []

    def post(self, url: str, body: bytes, headers: dict[str, str], timeout_s: float) -> Reply:
        self.calls.append({"url": url, "json": json.loads(body), "headers": dict(headers), "timeout_s": timeout_s})
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


class Rig:
    def __init__(self, *replies: Any, fetch: Any = None, read_draft: Any = None, attempts: int = 8) -> None:
        self.token = "idtok." + secrets.token_hex(12)
        self.audiences: list[str] = []
        self.transport = Scripted(*replies)
        self.sunk: list[dict[str, Any]] = []
        self.rpc = MeetingHostRpc(URL, transport=self.transport, token_for=fetch or self._fetch)
        self.receipts: list[HostReceipt] = []
        self.stub = MeetingHostStub(self.rpc, read_draft or (lambda ref: RAW), self.sunk.append, self.receipts.append)
        self.stub.hand_evidence(ENTRY["id"], EVIDENCE)
        self.store = InMemoryOutboxStore()
        self.transfers: list[dict] = []
        retry = RetryPolicy(max_attempts=attempts, max_delay_s=0, backoff_base_s=0, ambiguous_delay_s=0)
        self.outbox = Outbox(
            self.store, {CONNECTOR: self.stub}, emit=self.transfers.append, clock=lambda: NOW,
            world_id=ENTRY["world_id"], retry=retry,
        )  # fmt: skip

    def _fetch(self, audience: str) -> str:
        self.audiences.append(audience)
        return self.token

    def run(self) -> dict[str, Any]:
        self.outbox.enqueue(copy.deepcopy(ENTRY), copy.deepcopy(EVIDENCE))
        self.outbox.dispatch_due()
        return self.store.get(ENTRY["id"])

    def alerts(self) -> list[dict]:
        return [p for _oid, p in self.store._pending_alerts_of(None)]

    def ambiguous(self) -> bool:
        return bool(self.store.retry_state(ENTRY["id"])["ambiguous"])


def err(status: int, code: str) -> Reply:
    return Reply(status, body({"error": code}))


# the ADR-0032 decision 6 table: what connectors answers -> what the outbox ends up with
SENT, FAILED, DUE = "sent", "failed", "due"
ROWS = [
    ("sent", answer("sent"), SENT, False, False),
    ("refused", answer("refused"), FAILED, False, False),
    ("401", err(401, "unauthenticated"), FAILED, False, False),
    ("403", err(403, "forbidden"), FAILED, False, False),
    ("422", err(422, "invalid_request"), FAILED, False, False),
    ("503 not_configured", err(503, "not_configured"), FAILED, False, False),
    ("possibly_sent", answer("possibly_sent"), FAILED, False, True),
    ("sent, event_ref not the marker", answer("sent", event_ref="0" * 32), FAILED, False, True),
    ("sent, other world", answer("sent", world_id="w_other"), FAILED, False, True),
    ("sent, other outbox id", answer("sent", outbox_id="01JB5VQ0000000000000009999"), FAILED, False, True),
    ("sent, other meeting", answer("sent", meeting_id="mt_other"), FAILED, False, True),
    ("sent, other owner", answer("sent", owner="u_other"), FAILED, False, True),
    ("sent, other draft version", answer("sent", draft={**ENTRY["item"], "version": 2}), FAILED, False, True),
    ("retry, nothing reached Google", answer("retry", may_have_sent=False), DUE, False, False),
    ("retry, may have sent", answer("retry", may_have_sent=True), DUE, True, False),
    ("502", Reply(502, b""), DUE, True, False),
    ("500", Reply(500, b"oops"), DUE, True, False),
    ("503 from the platform, no contract body", Reply(503, b"<html>no instance</html>"), DUE, True, False),
    ("200, not the contract", Reply(200, body({"outcome": "maybe"})), DUE, True, False),
    ("200, not JSON", Reply(200, b"nope"), DUE, True, False),
    ("sent without a receipt", Reply(200, body({**json.loads(answer("refused").body), "outcome": "sent"})),
     DUE, True, False),
    ("timeout after the send", TransportError(), DUE, True, False),
]  # fmt: skip


@pytest.mark.parametrize(("name", "reply", "end", "ambiguous", "alerted"), ROWS, ids=[r[0] for r in ROWS])
def test_ADR32_T4_FR_MTG_09_every_answer_maps_to_the_outbox_outcome_of_the_adr_table(
    name, reply, end, ambiguous, alerted
):
    rig = Rig(reply)
    settled = rig.run()
    if end == SENT:
        assert settled["state"] == "sent" and len(rig.transfers) == 1 and len(rig.receipts) == 1
    else:
        assert rig.transfers == [] and rig.receipts == []
        assert (settled["state"] == "failed") == (end == FAILED), settled["state"]
    assert rig.ambiguous() is ambiguous and bool(rig.alerts()) is alerted, (name, rig.alerts())
    assert len(rig.transport.calls) == 1, "no retry on the send itself"


def test_ADR32_T4_FR_MTG_09_a_timeout_after_the_send_is_ambiguous_never_failed_and_raises_the_alert():
    rig = Rig(TransportError(), attempts=1)  # the retries are used up: still due, never failed, a person is alerted
    settled = rig.run()
    assert settled["state"] != "failed" and rig.ambiguous() and rig.alerts() and rig.transfers == []


def test_ADR32_T4_FR_MTG_09_a_retry_that_reached_nothing_is_not_ambiguous_and_stays_due():
    rig = Rig(answer("retry", may_have_sent=False))
    assert rig.run()["state"] != "failed" and not rig.ambiguous() and rig.alerts() == []


def test_ADR32_T4_FR_MTG_09_the_receipt_is_stored_through_the_run_only_when_hb07_holds():
    rig = Rig(answer("sent"))
    rig.run()
    assert [r.event_ref for r in rig.receipts] == [side_effect_marker(ENTRY)]
    assert rig.receipts[0].draft == ENTRY["item"] and rig.receipts[0].owner == OWNER


def test_ADR32_T4_FR_MTG_09_the_request_is_the_contract_and_carries_the_id_token_for_the_connectors_audience():
    rig = Rig(answer("sent"))
    rig.run()
    call = rig.transport.calls[0]
    assert call["url"] == URL + "/internal/meeting-host/send" and rig.audiences == [URL]
    assert call["headers"]["Authorization"] == "Bearer " + rig.token
    assert call["json"] == {"entry": ENTRY, "evidence": EVIDENCE, "draft": DRAFT}
    assert host_rpc_validator("send_request").is_valid(call["json"])
    assert rig.token not in json.dumps(call["json"]) and 20 <= call["timeout_s"] < 30  # under the 30 s outbox lease


def test_ADR32_T4_FR_MTG_09_a_token_that_cannot_be_minted_sends_nothing_and_is_a_clean_retry():
    def broken(audience: str) -> str:
        raise RuntimeError("metadata server down " + audience)

    rig = Rig(fetch=broken)
    settled = rig.run()
    assert rig.transport.calls == [] and settled["state"] != "failed" and not rig.ambiguous()


def test_ADR32_T4_FR_MTG_09_a_missing_evidence_or_unreadable_draft_is_refused_before_anything_is_posted():
    rig = Rig(answer("sent"), read_draft=lambda ref: (_ for _ in ()).throw(ArtifactCorrupt("AR-01")))
    assert rig.run()["state"] == "failed" and rig.transport.calls == [] and rig.alerts() == []
    rig = Rig(answer("sent"))
    rig.stub._evidence.clear()
    assert rig.run()["state"] == "failed" and rig.transport.calls == []


def test_ADR32_T4_FR_MTG_09_the_draft_posted_is_the_stored_bytes_bound_by_their_hash():
    rig = Rig(answer("sent"))
    rig.run()
    posted = rig.transport.calls[0]["json"]["draft"]
    assert (
        posted["content_sha256"] == hashlib.sha256(RAW).hexdigest() and base64.b64decode(posted["content_b64"]) == RAW
    )


# --- parts: what the broker emitted come back in the answer to the call that caused them ---


@pytest.mark.parametrize("kind", ["connection.revoked", "connection.expired"])
def test_ADR32_T4_FR_MTG_09_own_connection_parts_reach_the_sink_even_when_the_send_is_refused(kind):
    rig = Rig(answer("refused", parts=[part(kind)]))
    rig.run()
    assert rig.sunk == [{"type": kind, "authz": None, "data": {"connector": CONNECTOR}, "user_id": OWNER}]


def test_ADR32_T4_FR_MTG_09_a_part_for_another_user_is_dropped_in_code_and_an_alert_part_is_handed_on():
    alert = {"type": "alert.raised", "alert_id": "01JB5VQ0000000000000009311"}
    parts = [
        part("connection.revoked", STRANGER),
        part("connection.expired", OWNER),
        part("connection.expired", STRANGER),
    ]
    rig = Rig(answer("sent", parts=[*parts, alert]))
    rig.run()
    assert [(p["type"], p.get("user_id")) for p in rig.sunk] == [("connection.expired", OWNER), ("alert.raised", None)]
    assert rig.sunk[1]["data"] == {"alert_id": alert["alert_id"], "card_id": None}


def test_ADR32_T4_FR_MTG_09_a_sink_that_raises_never_fails_the_call():
    rig = Rig(answer("sent", parts=[part()]))

    def boom(_part: dict) -> None:
        raise RuntimeError("sink down")

    rig.stub._sink = boom
    assert rig.run()["state"] == "sent"


def test_ADR32_T4_FR_MTG_09_on_connection_event_takes_expired_like_revoked_but_not_rate_limited():
    def run(kind: str, connector: str = CONNECTOR) -> tuple[int, str]:
        store = InMemoryOutboxStore()
        out = Outbox(store, {CONNECTOR: object()}, emit=lambda p: None, clock=lambda: NOW, world_id=ENTRY["world_id"])
        out.enqueue(copy.deepcopy(ENTRY), copy.deepcopy(EVIDENCE))
        sunk = {"type": kind, "authz": None, "data": {"connector": connector}, "user_id": OWNER}
        return meeting_host.on_connection_event(sunk, outbox_store=store), store.get(ENTRY["id"])["state"]

    assert run("connection.revoked")[0] == 1 and run("connection.expired") == (1, "failed")
    assert run("connection.rate_limited") == (0, "queued") and run("connection.expired", "gmail") == (0, "queued")


# --- secrecy ---


def test_ADR32_T4_FR_MTG_09_the_id_token_is_in_no_log_error_or_repr(caplog):
    caplog.set_level(logging.DEBUG)
    seen: list[str] = []
    for _name, reply, *_rest in ROWS:
        rig = Rig(reply)
        rig.transport.replies = [reply if not isinstance(reply, Exception) else TransportError(rig.token)]
        rig.run()
        seen += [repr(rig.rpc), repr(rig.stub), json.dumps(rig.store.all_entries(), default=str)]
        try:
            rig.rpc.status(OWNER)
        except Exception as exc:  # noqa: BLE001 - whatever it raises must not hold the token
            seen.append(f"{exc!r} {exc}")
        assert rig.token not in "\n".join(seen + [r.getMessage() for r in caplog.records]), _name


def test_ADR32_T4_FR_MTG_09_a_transport_failure_carrying_the_token_is_not_echoed():
    rig = Rig()
    rig.transport.replies = [TransportError(rig.token)]
    with pytest.raises(HostRpcError) as caught:
        rig.rpc.status(OWNER)
    assert rig.token not in f"{caught.value!r} {caught.value}" and caught.value.__cause__ is None


# --- status ---


def test_ADR32_T4_FR_MTG_09_status_posts_only_the_principals_own_id_and_returns_the_state():
    rig = Rig(Reply(200, body({"state": "connected", "scope_ok": True})))
    got = rig.rpc.status(OWNER)
    assert (got.state, got.scope_ok) == ("connected", True)
    assert rig.transport.calls[0]["json"] == {"user_id": OWNER}
    assert rig.transport.calls[0]["url"] == URL + "/internal/meeting-host/status"


@pytest.mark.parametrize(
    "reply",
    [err(503, "not_configured"), err(401, "unauthenticated"), err(403, "forbidden"), Reply(502, b""), Reply(200, b"{}"),
     Reply(200, body({"state": "none", "scope_ok": True})), TransportError()],
)  # fmt: skip
def test_ADR32_T4_FR_MTG_09_a_failing_status_call_is_a_host_rpc_error(reply):
    with pytest.raises(HostRpcError):
        Rig(reply).rpc.status(OWNER)


# --- configuration (decision 8) ---


@pytest.mark.parametrize(
    "url",
    ["", "http://x.a.run.app", "https://user@x.a.run.app", "https://x.a.run.app:8443", "https://x.a.run.app/path",
     "https://x.a.run.app/", "https://x.a.run.app?q=1", "https://X.a.run.app", "https://x.example.com",
     "https://127.0.0.1", "https://x.a.run.app.evil.com", "https://-x.a.run.app", "https://x.a.run.app.",
     "https://run.app"],
)  # fmt: skip
def test_ADR32_T4_FR_MTG_09_only_an_https_run_app_host_of_the_exact_shape_is_accepted(url):
    with pytest.raises(HostRpcNotConfigured):
        open_meeting_host_rpc({"TILO_CONNECTORS_URL": url}, transport=Scripted(), token_for=lambda a: "t")


def test_ADR32_T4_FR_MTG_09_a_good_url_builds_and_unset_is_not_configured():
    assert open_meeting_host_rpc({"TILO_CONNECTORS_URL": URL}, transport=Scripted(), token_for=lambda a: "t")
    with pytest.raises(HostRpcNotConfigured):
        open_meeting_host_rpc({}, transport=Scripted(), token_for=lambda a: "t")


@pytest.fixture
def cold_seam(monkeypatch):
    monkeypatch.delenv("TILO_CONNECTORS_URL", raising=False)
    deps.get_meeting_host_client.cache_clear()
    yield
    deps.get_meeting_host_client.cache_clear()


def test_ADR32_T4_FR_MTG_09_the_client_seam_is_503_not_configured_unset_and_never_echoes_a_bad_value(
    cold_seam, monkeypatch
):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as unset:
        deps.get_meeting_host_client()
    monkeypatch.setenv("TILO_CONNECTORS_URL", "http://secret-host-" + secrets.token_hex(3))
    with pytest.raises(HTTPException) as bad:
        deps.get_meeting_host_client()
    for caught in (unset, bad):
        assert (caught.value.status_code, caught.value.detail) == (503, "not_configured")
        assert "secret-host" not in f"{caught.value!r} {caught.value.detail}"


def test_ADR32_T4_FR_MTG_09_the_client_seam_builds_once_and_a_failed_build_waits_30_seconds(cold_seam, monkeypatch):
    from fastapi import HTTPException

    now = [1000.0]
    monkeypatch.setattr(deps, "meeting_host_clock", lambda: now[0])
    monkeypatch.setenv("TILO_CONNECTORS_URL", "http://bad.example.test")
    opened: list[int] = []
    real = deps.open_meeting_host_rpc
    monkeypatch.setattr(deps, "open_meeting_host_rpc", lambda *a, **k: (opened.append(1), real(*a, **k))[1])
    for _ in range(2):
        with pytest.raises(HTTPException):
            deps.get_meeting_host_client()
    assert len(opened) == 1, "inside the 30 s window the build is not tried again"
    monkeypatch.setenv("TILO_CONNECTORS_URL", URL)
    now[0] += 31
    first = deps.get_meeting_host_client()
    assert deps.get_meeting_host_client() is first and len(opened) == 2, "fixed setting: no restart, then cached"


# --- security round 1 follow-ups ---


def test_ADR32_T4_FR_MTG_09_the_stub_demands_the_outbox_grant_before_anything_is_read_or_posted():
    from tilo_connectors.errors import MissingGrant
    from tilo_connectors.outbox import Grant

    read: list[Any] = []
    rig = Rig(answer("sent"), read_draft=lambda ref: read.append(ref) or RAW)
    with pytest.raises(MissingGrant):
        rig.stub.execute_side_effect(copy.deepcopy(ENTRY), Grant(ENTRY["world_id"], ENTRY["idempotency_key"]))
    assert read == [] and rig.transport.calls == []


def test_ADR32_T4_FR_MTG_09_only_the_stub_may_reach_the_client_send():
    """Not a registered SEC-03 name (that scan allows only outbox.py): this scan pins tilo-api's own rule instead."""
    import ast

    src = pathlib.Path(meeting_host.__file__).parent
    assert not hasattr(MeetingHostRpc, "send")
    for path in src.rglob("*.py"):
        if path.name == "meeting_host_rpc.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        assert not any(
            getattr(n, "attr", None) == "send_invitation" or getattr(n, "id", None) == "send_invitation"
            for n in ast.walk(tree)
        ), f"{path.name} reaches the RPC client's send_invitation"
    assert {n for n in dir(MeetingHostRpc) if not n.startswith("_")} == {
        "status",
        "send_invitation",
        "connection_views",  # ADR-0032a T4b: a read with no side effect
    }
    tree = ast.parse((src / "meeting_host_rpc.py").read_text(encoding="utf-8"))
    callers = [
        c.name
        for c in ast.walk(tree)
        if isinstance(c, ast.FunctionDef)
        and any(isinstance(n, ast.Attribute) and n.attr == "send_invitation" for n in ast.walk(c))
    ]
    assert callers == ["execute_side_effect"]


def test_ADR32_T4_FR_MTG_09_one_deadline_covers_the_token_fetch_and_the_request():
    import threading

    stuck = threading.Event()

    def hang(*_a: Any) -> Any:
        stuck.wait(5)
        raise RuntimeError

    slow_token = MeetingHostRpc(URL, transport=Scripted(), token_for=hang, timeout_s=0.2)
    with pytest.raises(HostRpcError) as no_token:
        slow_token.status(OWNER)
    assert no_token.value.kind == "not_sent"
    slow_post = MeetingHostRpc(URL, transport=type("T", (), {"post": hang})(), token_for=lambda a: "t", timeout_s=0.2)
    with pytest.raises(HostRpcError) as lost:
        slow_post.status(OWNER)
    assert lost.value.kind == "unknown"
    stuck.set()


@pytest.mark.parametrize(
    ("raises", "final"),
    [(ArtifactCorrupt("AR-01"), True), (ArtifactNotFound("gone"), False), (OSError("blob store down"), False)],
)
def test_ADR32_T4_FR_MTG_09_only_a_hash_mismatch_of_the_draft_is_final(raises, final):
    def read(ref: Any) -> bytes:
        raise raises

    rig = Rig(answer("sent"), read_draft=read)
    settled = rig.run()
    assert (settled["state"] == "failed") is final and rig.transport.calls == [] and not rig.ambiguous()
