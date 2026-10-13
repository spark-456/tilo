# ruff: noqa: F811
"""ADR35_L6 / FR_CON_02: tilo-api's live Google stubs (ADR-0035 decision 5 LC-07/08, decision 6 LC-09/10, ticket L6).

A scripted transport stands in for tilo-connectors; the real `Outbox` (tilo-api's own, over an in-memory store) runs
the stub, so every row of the answer table is checked by what the outbox does with it. The request bases are the
contract's own valid execute fixtures with items rebuilt as the BQ-ADR35L5-1 documents. The last tests reach the real
connectors app in process with Google faked at the adapters' transport. No network, no paid call, no live switch.
"""

from __future__ import annotations

import ast
import base64
import copy
import hashlib
import json
import pathlib
import secrets
import types
from typing import Any

import pytest
import test_ADR32_T4_FR_MTG_09_host_rpc as t4
from _adr35_l6_lib import (
    EVENTS_URL,
    NOW,
    FakeGoogle,
    InProcessConnectors5,
    email_doc,
    event_doc,
    file_doc,
    raw_of,
)
from _clint2_lib import ArtifactRig
from _mtg09b_lib import block_network
from _ppl11a_lib import OWNER
from test_ADR35_L4_FR_CON_02_connect_routes import CALLBACK, DISCONNECT, ok, rig  # noqa: F401 - the L4 rig fixture
from tilo_api import connector_rpc, deps, meeting_host
from tilo_api.connector_rpc import NO_DRAFT, PERSON_CONNECTORS, ConnectorRpcStub
from tilo_api.meeting_host_rpc import HostRpcError, MeetingHostRpc, Reply, TransportError
from tilo_api.runs import Run, _GateFailed
from tilo_connectors import InMemoryOutboxStore, Outbox
from tilo_connectors._schema import host_rpc_validator
from tilo_connectors.adapters import side_effect_marker
from tilo_connectors.errors import MissingGrant
from tilo_connectors.outbox import Grant, RetryPolicy
from tilo_connectors.side_effect_execute import checked_documents
from tilo_connectors.side_effects import scan_for_side_effect_calls
from tilo_memory.artifacts import ArtifactCorrupt, ArtifactNotFound

CONTRACTS = pathlib.Path(__file__).resolve().parents[3] / "contracts"
FIXTURES = CONTRACTS / "fixtures" / "meeting_host_rpc.execute_request" / "valid"
SRC = pathlib.Path(connector_rpc.__file__).parent
ROUTE = "/internal/side-effects/execute"
STRANGER = "u_" + secrets.token_hex(4)


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    block_network(monkeypatch)


def fixture(name: str) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    body = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    return body["entry"], body["evidence"], body["items"]


DRAFT, DRAFT_EV, _ = fixture("gmail_draft_approved_by_the_person")
SEND, SEND_EV, _ = fixture("gmail_send_with_an_attachment")
EVENT, EVENT_EV, _ = fixture("calendar_event_without_guests")
SAVE, SAVE_EV, _ = fixture("drive_save_waiting_out_its_undo_window")
RAW = raw_of(email_doc(in_reply_to="<m1@example.org>"))
MARKER = side_effect_marker(DRAFT)


def answer(outcome: str, *, may_have_sent: bool | None = None, parts: list | None = None, **over: Any) -> Reply:
    result = {"resource_id": "dr_1", "marker": MARKER, **over} if outcome == "sent" else None
    doc = {"outcome": outcome, "result": result, "may_have_sent": may_have_sent, "parts": parts or []}
    assert host_rpc_validator("execute_answer").is_valid(doc), doc
    return Reply(200, t4.body(doc))


def part(kind: str = "connection.revoked", user: str = DRAFT["authz"]["ref"], connector: str = "gmail") -> dict:
    return {"type": kind, "connector": connector, "user_id": user}


class Rig:
    def __init__(self, *replies: Any, read: Any = None, entry: Any = DRAFT, evidence: Any = DRAFT_EV, **kw: Any):
        self.entry, self.evidence = entry, evidence
        self.token = "idtok." + secrets.token_hex(12)
        self.transport = t4.Scripted(*replies)
        self.rpc = MeetingHostRpc(  # a frozen deadline clock: `20 <= timeout_s < 30` then holds exactly, load or not
            t4.URL, transport=self.transport, token_for=kw.get("fetch") or (lambda a: self.token), clock=lambda: 0.0
        )
        self.sunk: list[dict[str, Any]] = []
        self.read_calls: list[dict[str, Any]] = []
        self.owner = kw.get("owner", entry["authz"]["ref"])
        self.stub = ConnectorRpcStub(entry["connector"], self.rpc).bound(
            read or self._read, self.sunk.append, self.owner
        )
        if kw.get("hand", True):
            self.stub.hand_evidence(entry["id"], evidence)
        self.store = InMemoryOutboxStore()
        self.transfers: list[dict] = []
        retry = RetryPolicy(max_attempts=kw.get("attempts", 8), max_delay_s=0, backoff_base_s=0, ambiguous_delay_s=0)
        self.outbox = Outbox(
            self.store, {entry["connector"]: self.stub}, emit=self.transfers.append, clock=lambda: NOW,
            world_id=entry["world_id"], retry=retry,
        )  # fmt: skip

    def _read(self, ref: dict[str, Any]) -> bytes:
        self.read_calls.append(ref)
        return RAW

    def run(self) -> dict[str, Any]:
        self.outbox.enqueue(copy.deepcopy(self.entry), copy.deepcopy(self.evidence))
        self.outbox.dispatch_due()
        return self.store.get(self.entry["id"])

    def alerts(self) -> list[dict]:
        return [p for _oid, p in self.store._pending_alerts_of(None)]

    def ambiguous(self) -> bool:
        return bool(self.store.retry_state(self.entry["id"])["ambiguous"])


# ---- the answer table: what connectors answers -> what the outbox ends up with ---------------------------------

SENT, FAILED, DUE = "sent", "failed", "due"
ROWS = [
    ("sent", answer("sent"), SENT, False, False),
    ("refused", answer("refused"), FAILED, False, False),
    ("401", t4.err(401, "unauthenticated"), FAILED, False, False),
    ("403", t4.err(403, "forbidden"), FAILED, False, False),
    ("422", t4.err(422, "invalid_request"), FAILED, False, False),
    ("503 not_configured", t4.err(503, "not_configured"), FAILED, False, False),
    ("possibly_sent", answer("possibly_sent"), FAILED, False, True),
    ("sent, marker not the entry's", answer("sent", marker="0" * 32), FAILED, False, True),
    ("retry, nothing reached Google", answer("retry", may_have_sent=False), DUE, False, False),
    ("retry, may have sent", answer("retry", may_have_sent=True), DUE, True, False),
    ("502", Reply(502, b""), DUE, True, False),
    ("500", Reply(500, b"oops"), DUE, True, False),
    ("503 from the platform, no contract body", Reply(503, b"<html>no instance</html>"), DUE, True, False),
    ("200, not the contract", Reply(200, t4.body({"outcome": "maybe"})), DUE, True, False),
    ("200, not JSON", Reply(200, b"nope"), DUE, True, False),
    (
        "sent without a result",
        Reply(200, t4.body({"outcome": "sent", "result": None, "may_have_sent": None, "parts": []})),
        DUE, True, False,
    ),
    (
        "refused with a result",
        Reply(200, t4.body({"outcome": "refused", "result": {"resource_id": "x", "marker": MARKER},
                            "may_have_sent": None, "parts": []})),
        DUE, True, False,
    ),
    ("timeout after the send", TransportError(), DUE, True, False),
]  # fmt: skip


@pytest.mark.parametrize(("name", "reply", "end", "ambiguous", "alerted"), ROWS, ids=[r[0] for r in ROWS])
def test_ADR35_L6_FR_CON_02_every_answer_maps_to_the_outbox_outcome_of_the_adr_table(
    name, reply, end, ambiguous, alerted
):
    rig = Rig(reply)
    settled = rig.run()
    if end == SENT:
        assert settled["state"] == "sent" and len(rig.transfers) == 1
    else:
        assert rig.transfers == []
        assert (settled["state"] == "failed") == (end == FAILED), settled["state"]
    assert rig.ambiguous() is ambiguous and bool(rig.alerts()) is alerted, (name, rig.alerts())
    assert len(rig.transport.calls) == 1, "no retry on the execute itself"


def test_ADR35_L6_FR_CON_02_a_timeout_after_the_call_is_ambiguous_never_failed_and_raises_the_alert():
    rig = Rig(TransportError(), attempts=1)
    settled = rig.run()
    assert settled["state"] != "failed" and rig.ambiguous() and rig.alerts() and rig.transfers == []


def test_ADR35_L6_FR_CON_02_a_token_that_cannot_be_minted_sends_nothing_and_is_a_clean_retry():
    def broken(audience: str) -> str:
        raise RuntimeError("metadata server down " + audience)

    rig = Rig(fetch=broken)
    settled = rig.run()
    assert rig.transport.calls == [] and settled["state"] != "failed" and not rig.ambiguous()


def test_ADR35_L6_FR_CON_02_the_request_is_the_contract_with_the_pinned_bytes_and_the_runs_owner():
    rig = Rig(answer("sent"), owner="u_bound_" + secrets.token_hex(3))  # the run's owner, not the evidence copy's
    rig.run()
    call = rig.transport.calls[0]
    assert call["url"] == t4.URL + ROUTE and call["headers"]["Authorization"] == "Bearer " + rig.token
    assert call["json"]["entry"] == {**DRAFT, "state": "queued"}
    assert DRAFT_EV["world_owner"] != rig.owner and call["json"]["evidence"] == {**DRAFT_EV, "world_owner": rig.owner}
    (item,) = call["json"]["items"]
    assert item == {
        "artifact_id": DRAFT["item"]["artifact_id"], "version": DRAFT["item"]["version"],
        "content_sha256": hashlib.sha256(RAW).hexdigest(), "content_b64": base64.b64encode(RAW).decode(),
    }  # fmt: skip
    assert host_rpc_validator("execute_request").is_valid(call["json"])
    assert rig.token not in json.dumps(call["json"]) and 20 <= call["timeout_s"] < 30


def test_ADR35_L6_FR_CON_02_items_are_the_entrys_item_then_its_attachments_and_connectors_own_parser_takes_them():
    docs = {
        (SEND["item"]["artifact_id"], SEND["item"]["version"]): raw_of(email_doc()),
        **{(a["artifact_id"], a["version"]): raw_of(file_doc(f"f{i}.txt")) for i, a in enumerate(SEND["attachments"])},
    }
    rig = Rig(
        answer("refused"), entry=SEND, evidence=SEND_EV, read=lambda ref: docs[(ref["artifact_id"], ref["version"])]
    )
    rig.run()
    body = rig.transport.calls[0]["json"]
    refs = [SEND["item"], *SEND["attachments"]]
    assert [(i["artifact_id"], i["version"]) for i in body["items"]] == [(r["artifact_id"], r["version"]) for r in refs]
    assert host_rpc_validator("execute_request").is_valid(body)
    parsed = checked_documents(body["entry"], body["items"])  # the L5 parser, only in a test: the round trip
    assert parsed is not None
    assert parsed.get(refs[0]["artifact_id"], refs[0]["version"])["kind"] == "email"
    assert parsed.get(refs[1]["artifact_id"], refs[1]["version"])["kind"] == "file"


# ---- SEC-03: the grant first, nothing read, nothing posted -----------------------------------------------------


def test_ADR35_L6_FR_CON_02_a_call_without_the_outbox_grant_reads_and_posts_nothing():
    rig = Rig(answer("sent"))
    with pytest.raises(MissingGrant):
        rig.stub.execute_side_effect(copy.deepcopy(DRAFT), Grant(DRAFT["world_id"], "r_other:U1:create_draft:1"))
    assert rig.read_calls == [] and rig.transport.calls == [] and rig.token not in repr(rig.stub)


def test_ADR35_L6_FR_CON_02_a_stub_the_seam_made_has_no_run_and_cannot_send():
    bare = ConnectorRpcStub("gmail", Rig().rpc)  # what deps.get_connector_adapters hands out, before a run binds it
    rig = Rig(answer("sent"))
    rig.outbox = Outbox(
        rig.store, {"gmail": bare}, emit=rig.transfers.append, clock=lambda: NOW, world_id=DRAFT["world_id"],
        retry=RetryPolicy(max_delay_s=0, backoff_base_s=0),
    )  # fmt: skip
    bare.hand_evidence(DRAFT["id"], DRAFT_EV)
    settled = rig.run()
    assert settled["state"] != "failed" and rig.transport.calls == [] and not rig.ambiguous()


def test_ADR35_L6_FR_CON_02_missing_evidence_or_a_foreign_connector_is_refused_before_anything_is_read():
    rig = Rig(answer("sent"), hand=False)
    assert rig.run()["state"] == "failed" and rig.read_calls == [] and rig.transport.calls == []
    rig = Rig(answer("sent"))
    rig.stub.connector = "google_drive"  # a stub serves only its own connector's entries
    assert rig.run()["state"] == "failed" and rig.read_calls == [] and rig.transport.calls == []


# ---- reading the pinned items: AR-01 mismatch is final, any other read error is a retry -------------------------


def test_ADR35_L6_FR_CON_02_a_hash_mismatch_is_final_and_a_read_error_is_a_clean_retry():
    rig = Rig(answer("sent"), read=lambda ref: (_ for _ in ()).throw(ArtifactCorrupt("AR-01")))
    assert rig.run()["state"] == "failed" and rig.transport.calls == [] and rig.alerts() == []
    for error in (ArtifactNotFound("gone"), RuntimeError("store down"), TimeoutError()):
        rig = Rig(answer("sent"), read=lambda ref, e=error: (_ for _ in ()).throw(e))
        settled = rig.run()
        assert settled["state"] != "failed" and rig.transport.calls == [] and not rig.ambiguous()


@pytest.mark.parametrize("raw", [b"not json", b"[1]", b'{"subject":"x"}', b'{"kind":"unknown"}', b""])
def test_ADR35_L6_FR_CON_02_a_pinned_item_that_is_no_document_is_refused_before_a_call(raw):
    rig = Rig(answer("sent"), read=lambda ref: raw)
    assert rig.run()["state"] == "failed" and rig.transport.calls == [] and rig.alerts() == []


def test_ADR35_L6_FR_CON_02_a_request_over_the_connectors_cap_is_refused_before_a_call():
    big = raw_of(file_doc("big.bin", secrets.token_bytes(60_000)))
    rig = Rig(answer("sent"), read=lambda ref: big)
    assert rig.run()["state"] == "failed" and rig.transport.calls == [] and not rig.ambiguous()
    with pytest.raises(HostRpcError) as caught:
        rig.rpc.execute_entry(DRAFT, DRAFT_EV, [{"x": "y" * 70_000}])
    assert caught.value.kind == "refused"


# ---- parts -----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["connection.revoked", "connection.expired"])
def test_ADR35_L6_FR_CON_02_own_connection_parts_reach_the_sink_even_when_refused(kind):
    rig = Rig(answer("refused", parts=[part(kind)]))
    rig.run()
    owner = rig.owner
    assert rig.sunk == [{"type": kind, "authz": None, "data": {"connector": "gmail"}, "user_id": owner}]


def test_ADR35_L6_FR_CON_02_parts_of_another_user_are_dropped_and_an_alert_is_handed_on():
    alert = {"type": "alert.raised", "alert_id": "01JB5VQ0000000000000009311"}
    rig = Rig(answer("sent", parts=[part("connection.revoked", STRANGER), part("connection.expired"), alert]))
    rig.run()
    assert [(p["type"], p.get("user_id")) for p in rig.sunk] == [
        ("connection.expired", rig.owner),
        ("alert.raised", None),
    ]


# ---- the seam: stubs only for a configured, signed-in session ---------------------------------------------------


def test_ADR35_L6_FR_CON_02_the_seam_gives_one_stub_per_live_connector_only_when_configured(monkeypatch):
    monkeypatch.delenv("TILO_CONNECTORS_URL", raising=False)
    deps.get_meeting_host_client.cache_clear()
    assert deps.get_connector_adapters() == {}  # unconfigured: nothing could ever be sent
    monkeypatch.setenv("TILO_CONNECTORS_URL", t4.URL)
    deps.get_meeting_host_client.cache_clear()
    try:
        adapters = deps.get_connector_adapters()
        assert set(adapters) == set(PERSON_CONNECTORS) == {"gmail", "google_drive", "google_calendar"}
        assert all(isinstance(a, ConnectorRpcStub) and a.connector == n for n, a in adapters.items())
        monkeypatch.setattr(deps, "_demo", lambda request: object())
        assert deps.get_connector_adapters(types.SimpleNamespace()) == {}  # a demo session never sends
    finally:
        deps.get_meeting_host_client.cache_clear()


def test_ADR35_L6_FR_CON_02_the_person_connectors_are_the_contracts_execute_enum():
    schema = json.loads((CONTRACTS / "meeting_host_rpc.schema.json").read_text(encoding="utf-8"))
    enum = schema["$defs"]["execute_request"]["then"]["properties"]["entry"]["properties"]["connector"]["enum"]
    assert list(PERSON_CONNECTORS) == enum


# ---- SEC-03 and the one caller of the call -----------------------------------------------------------------------


def test_ADR35_L6_FR_CON_02_only_the_stub_may_reach_the_clients_execute_entry():
    """Not a registered SEC-03 name (that scan allows only outbox.py): this scan pins tilo-api's own rule instead."""
    for path in SRC.rglob("*.py"):
        if path.name in ("meeting_host_rpc.py", "connector_rpc.py"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        assert not any(
            getattr(n, "attr", None) == "execute_entry" or getattr(n, "id", None) == "execute_entry"
            for n in ast.walk(tree)
        ), f"{path.name} reaches the RPC client's execute_entry"
    for name in ("meeting_host_rpc.py", "connector_rpc.py"):
        tree = ast.parse((SRC / name).read_text(encoding="utf-8"))
        callers = [
            c.name
            for c in ast.walk(tree)
            if isinstance(c, ast.FunctionDef)
            and any(isinstance(n, ast.Attribute) and n.attr == "execute_entry" for n in ast.walk(c))
        ]
        assert callers == (["execute_side_effect"] if name == "connector_rpc.py" else []), (name, callers)


def test_ADR35_L6_FR_CON_02_sec_03_no_side_effect_call_outside_the_outbox_in_tilo_api():
    from tilo_connectors import outbox  # noqa: PLC0415

    found = scan_for_side_effect_calls(sorted(SRC.rglob("*.py")), allowed_path=pathlib.Path(outbox.__file__))
    assert found == [], found


def test_ADR35_L6_FR_CON_02_the_stub_module_holds_no_token_broker_adapter_or_live_import():
    tree = ast.parse((SRC / "connector_rpc.py").read_text(encoding="utf-8"))
    modules = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module] + [
        a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names
    ]
    assert not [
        m for m in modules if m.startswith("tilo_connectors.") and m.split(".")[1] in ("tokens", "live", "adapters")
    ]


# ---- LC-10: draft before send --------------------------------------------------------------------------------------


class Draftable:
    """A world with a real artifact store, a real outbox store and a `Run._draft_first` to ask."""

    def __init__(self) -> None:
        self.art, self.store = ArtifactRig(), InMemoryOutboxStore()
        self.world = DRAFT["world_id"]
        self.scope = self.art.scope(self.world, owner=DRAFT["authz"]["ref"])
        self.stub = ConnectorRpcStub("gmail", Rig().rpc)
        self.run = types.SimpleNamespace(
            adapters={"gmail": self.stub}, _drafted={}, world_id=self.world, scope=self.scope,
            seams=types.SimpleNamespace(artifacts=self.art.store, outbox_store=self.store),
        )  # fmt: skip

    def item(self, content: bytes = b'{"kind":"email"}') -> dict[str, Any]:
        return self.art.seed(self.scope, content)

    def drafted(self, ref: dict[str, Any], *, world: str | None = None, sent: bool = True) -> None:
        """A `create_draft` entry for `ref`: really sent through the outbox, or left queued."""
        entry = {
            **copy.deepcopy(DRAFT),
            "item": ref,
            "world_id": world or self.world,
            "id": "01JB5VQ" + secrets.token_hex(10).upper()[:19],
        }
        entry["idempotency_key"] = f"r_x_1:U1:create_draft:{secrets.token_hex(2)}"
        evidence = copy.deepcopy(DRAFT_EV)
        evidence["reserved_by"]["data"].update(item=ref, outbox_id=entry["id"])
        evidence["authorised_by"]["data"].update(outbox_id=entry["id"])
        noop = types.SimpleNamespace(execute_side_effect=lambda e, g: None)
        outbox = Outbox(self.store, {"gmail": noop}, emit=lambda p: None, clock=lambda: NOW, world_id=entry["world_id"])
        outbox.enqueue(entry, evidence)
        if sent:
            outbox.dispatch_due()
        if sent and (world is None):
            self.run._drafted[(ref["artifact_id"], ref["version"])] = self.art.store.head(self.scope, ref).record[
                "content_sha256"
            ]

    def check(self, ref: dict[str, Any], action: str = "send_email", connector: str = "gmail") -> None:
        Run._draft_first(self.run, connector, action, ref)  # type: ignore[arg-type]


def refused(draftable: Draftable, ref: dict[str, Any]) -> bool:
    try:
        draftable.check(ref)
    except _GateFailed as exc:
        assert str(exc) == NO_DRAFT
        return True
    return False


def test_ADR35_L6_FR_CON_02_lc10_a_send_needs_a_sent_draft_of_the_same_item():
    d = Draftable()
    ref = d.item()
    assert refused(d, ref)  # no draft at all
    d.drafted(ref)
    assert not refused(d, ref)  # the same item
    other_item, other_version = d.item(b'{"kind":"email","n":2}'), {**ref, "version": ref["version"] + 1}
    assert refused(d, other_item) and refused(d, other_version)  # another artifact, another version


def test_ADR35_L6_FR_CON_02_lc10_a_draft_that_was_not_sent_or_is_in_another_world_does_not_count():
    d = Draftable()
    ref = d.item()
    d.drafted(ref, sent=False)
    assert refused(d, ref)
    d2 = Draftable()
    ref2 = d2.item()
    d2.drafted(ref2, world="w_elsewhere")
    assert refused(d2, ref2)


def test_ADR35_L6_FR_CON_02_lc10_a_draft_of_other_content_does_not_count():
    d = Draftable()
    ref = d.item()
    d.drafted(ref)
    d.run._drafted[(ref["artifact_id"], ref["version"])] = "0" * 64  # the content is no longer what the draft carried
    assert refused(d, ref)


def test_ADR35_L6_FR_CON_02_lc10_binds_only_a_live_send_email():
    d = Draftable()
    ref = d.item()
    d.check(ref, action="create_draft")  # a draft needs none
    d.check(ref, action="save_file", connector="google_drive")
    d.run.adapters = {"gmail": types.SimpleNamespace()}  # a fake or mock adapter (every other test rig): unchanged
    d.check(ref)
    d.run.adapters = {}
    d.check(ref)


def test_ADR35_L6_FR_CON_02_lc10_a_store_that_cannot_be_read_refuses():
    d = Draftable()
    ref = d.item()
    d.drafted(ref)
    d.store.all_entries = lambda: (_ for _ in ()).throw(RuntimeError("down"))  # type: ignore[method-assign]
    assert refused(d, ref)


def test_ADR35_L6_FR_CON_02_lc10_through_a_run_a_live_send_with_no_draft_fails_the_unit_before_any_card(
    repo_root, monkeypatch
):
    from _clint2_lib import MOCK_ID, build_run_flow  # noqa: PLC0415

    rf = build_run_flow(repo_root, covered=True)
    spy = Rig().rpc
    rf.app.dependency_overrides[deps.get_connector_adapters] = lambda: {MOCK_ID: ConnectorRpcStub(MOCK_ID, spy)}
    try:
        rf.start()
        rf.approve()
        from _clint2_lib import wait_for  # noqa: PLC0415

        wait_for(lambda: rf.events("world.failed"), what="the unit's failure")
        assert rf.outbox_store.all_entries() == [] and rf.events("approval.requested") == []
        assert rf.events("world.failed")[0]["data"]["reason"]
    finally:
        rf.close()


# ---- abandon-first for person connectors ----------------------------------------------------------------------------


def person_entry(rig: Any, name: str, owner: str, *, world: str) -> str:
    entry, evidence, _ = fixture(
        {"gmail": "gmail_draft_approved_by_the_person", "google_drive": "drive_save_waiting_out_its_undo_window",
         "google_calendar": "calendar_event_without_guests"}[name]
    )  # fmt: skip
    entry["world_id"] = world
    entry["id"] = entry["id"][:-4] + secrets.token_hex(2).upper()  # one entry per call, whatever the fixture
    for key in ("reserved_by", "authorised_by"):
        evidence[key]["data"]["outbox_id"] = entry["id"]
    rig.worlds.worlds[world] = deps.WorldRecord(owner=owner, districts={}, run_id="r_x_1")
    Outbox(rig.store, {name: object()}, emit=lambda p: None, clock=lambda: NOW, world_id=world).enqueue(entry, evidence)
    return entry["id"]


def test_ADR35_L6_FR_CON_02_disconnecting_a_person_connector_abandons_the_owners_unsent_entries_before_the_call(rig):
    ids = [person_entry(rig, n, OWNER, world="w_mine") for n in PERSON_CONNECTORS]
    theirs = person_entry(rig, "gmail", STRANGER, world="w_theirs")
    host = rig.enqueue(user=OWNER)  # the bot's entry is a different connector's: untouched
    rig.set((ok({"revoked_at_provider": True, "parts": []}),))
    assert rig.p.post(DISCONNECT, {"connector": "google_drive"}).status_code == 200
    assert all(rig.transport.at_call[0][i] == "failed" for i in ids)  # before the call went out
    assert rig.store.get(theirs)["state"] == "queued" and rig.store.get(host)["state"] == "queued"


def test_ADR35_L6_FR_CON_02_an_entry_that_may_have_gone_out_is_never_touched_by_a_disconnect(rig):
    (entry_id,) = [person_entry(rig, "gmail", OWNER, world="w_mine")]
    rig.store._retries[entry_id] = {"ambiguous": True}  # a lost answer
    rig.set((ok({"revoked_at_provider": True, "parts": []}),))
    assert rig.p.post(DISCONNECT, {"connector": "gmail"}).status_code == 200
    assert rig.store.get(entry_id)["state"] != "failed"


def test_ADR35_L6_FR_CON_02_an_unreadable_world_never_blocks_a_disconnect_and_only_the_callers_go(
    rig, monkeypatch, caplog
):
    mine = person_entry(rig, "gmail", OWNER, world="w_mine")
    theirs = person_entry(rig, "google_drive", STRANGER, world="w_theirs")
    broken = person_entry(rig, "google_calendar", STRANGER, world="w_broken")
    real = rig.worlds.load_world

    def load(world_id, settle=False):
        if world_id == "w_broken":
            raise RuntimeError("down")
        return real(world_id, settle)

    monkeypatch.setattr(rig.worlds, "load_world", load)
    rig.set((ok({"revoked_at_provider": True, "parts": []}),))
    with caplog.at_level("WARNING"):
        assert rig.p.post(DISCONNECT, {"connector": "gmail"}).status_code == 200
    states = {i: rig.store.get(i)["state"] for i in (mine, theirs, broken)}
    assert (states[mine], states[broken]) == ("failed", "failed") and states[
        theirs
    ] != "failed"  # the caller approved the unreadable one
    assert broken in caplog.text


@pytest.mark.parametrize("kind", ["connection.revoked", "connection.expired"])
def test_ADR35_L6_FR_CON_02_revoked_or_expired_parts_abandon_the_owners_person_entries(rig, kind):
    mine = person_entry(rig, "google_calendar", OWNER, world="w_mine")
    theirs = person_entry(rig, "gmail", STRANGER, world="w_theirs")
    granted = {
        "connector": "gmail",
        "scope_lines": ["x"],
        "parts": [{"type": kind, "connector": "gmail", "user_id": OWNER}],
    }
    rig.set((ok(granted),))
    assert rig.p.post(CALLBACK, rig.callback_body()).status_code == 200
    assert rig.store.get(mine)["state"] == "failed" and rig.store.get(theirs)["state"] == "queued"


def test_ADR35_L6_FR_CON_02_on_connection_event_for_a_person_connector_needs_the_worlds_owner(rig):
    entry_id = person_entry(rig, "gmail", OWNER, world="w_mine")
    sunk = {"type": "connection.revoked", "authz": None, "data": {"connector": "gmail"}, "user_id": OWNER}
    assert meeting_host.on_connection_event(sunk, outbox_store=rig.store) == 0  # no way to know whose: nothing
    owner_of = lambda w: rig.worlds.load_world(w).owner  # noqa: E731
    assert meeting_host.on_connection_event(sunk, outbox_store=rig.store, owner_of=owner_of) == 1
    assert rig.store.get(entry_id)["state"] == "failed"


def test_ADR35_L6_FR_CON_02_the_scheduler_sweep_leaves_a_stub_to_its_run(monkeypatch):
    from tilo_api.outbox_firestore import sweep_due  # noqa: PLC0415

    store = InMemoryOutboxStore()
    rig = Rig(answer("sent"))
    Outbox(store, {"gmail": object()}, emit=lambda p: None, clock=lambda: NOW, world_id=DRAFT["world_id"]).enqueue(
        copy.deepcopy(DRAFT), copy.deepcopy(DRAFT_EV)
    )
    assert sweep_due(store, {"gmail": rig.stub}, lambda: NOW, lambda w: False) == 0
    assert rig.transport.calls == [] and store.get(DRAFT["id"])["state"] == "queued"


# ---- end to end through the real connectors app, Google faked at the Transport ----------------


def through(entry: dict, evidence: dict, document: dict) -> tuple[dict, FakeGoogle, InProcessConnectors5, Outbox, list]:
    google = FakeGoogle()
    connectors = InProcessConnectors5(google)
    raw = raw_of(document)
    stub = ConnectorRpcStub(entry["connector"], connectors.rpc).bound(
        lambda ref: raw, lambda p: None, entry["authz"]["ref"]
    )
    stub.hand_evidence(entry["id"], evidence)
    store, transfers = InMemoryOutboxStore(), []
    outbox = Outbox(
        store, {entry["connector"]: stub}, emit=transfers.append, clock=lambda: NOW, world_id=entry["world_id"]
    )
    outbox.enqueue(copy.deepcopy(entry), copy.deepcopy(evidence))
    outbox.dispatch_due()
    return store.get(entry["id"]), google, connectors, outbox, transfers


def test_ADR35_L6_FR_CON_02_end_to_end_a_gmail_draft_is_made_once_and_the_marker_matches():
    entry = {**DRAFT, "destination": None}
    settled, google, connectors, _, transfers = through(entry, DRAFT_EV, email_doc())
    assert settled["state"] == "sent" and len(transfers) == 1
    assert len(google.drafts) == 1 and connectors.posts[0]["entry"]["state"] == "queued"


def test_ADR35_L6_FR_CON_02_end_to_end_a_drive_save_lands_in_the_tilo_folder():
    entry = {**SAVE, "destination": None}
    settled, google, connectors, _, transfers = through(entry, SAVE_EV, file_doc("notes.txt", b"hello drive"))
    assert settled["state"] == "sent" and len(transfers) == 1
    assert connectors.posts[0]["entry"]["state"] == "scheduled"  # its undo window was spent when it was claimed
    assert len(google.folders) == 1 and len(google.saved) == 1 and b"hello drive" in google.saved[0]


def test_ADR35_L6_FR_CON_02_end_to_end_a_calendar_event_without_guests_is_made_under_the_marker():
    settled, google, _, _, transfers = through(EVENT, EVENT_EV, event_doc())
    assert settled["state"] == "sent" and len(transfers) == 1
    assert list(google.events) == [side_effect_marker(EVENT)]
    assert "attendees" not in google.events[side_effect_marker(EVENT)]
    assert any(url == EVENTS_URL for _, url, _ in google.requests)


def test_ADR35_L6_FR_CON_02_end_to_end_a_calendar_event_with_a_guest_in_it_is_refused_before_google():
    settled, google, _, _, transfers = through(EVENT, EVENT_EV, event_doc(attendees=["guest@example.org"]))
    assert settled["state"] == "failed" and transfers == [] and google.reached() == 0


def test_ADR35_L6_FR_CON_02_end_to_end_a_second_dispatch_after_sent_makes_nothing_more():
    entry = {**DRAFT, "destination": None}
    settled, google, _, outbox, _ = through(entry, DRAFT_EV, email_doc())
    outbox.dispatch_due()
    assert settled["state"] == "sent" and len(google.drafts) == 1


# ---- round 1: a lost answer, the Firestore store, the pins ---------------------------------------------------------


def firestore_store() -> Any:
    from _adr35_l2_fake import OccFirestore  # noqa: PLC0415
    from tilo_api.outbox_firestore import FirestoreOutboxStore  # noqa: PLC0415

    return FirestoreOutboxStore(OccFirestore(), clock=lambda: NOW)


def test_ADR35_L6_FR_CON_02_disconnect_over_the_firestore_store_leaves_a_lost_answer_and_a_live_send(rig):
    fs = firestore_store()
    rig.store = fs
    rig.p.app.dependency_overrides[deps.get_outbox_store] = lambda: fs
    rig.set((ok({"revoked_at_provider": True, "parts": []}),))
    plain = person_entry(rig, "gmail", OWNER, world="w_mine")
    lost = person_entry(rig, "google_drive", OWNER, world="w_mine")
    live = person_entry(rig, "google_calendar", OWNER, world="w_mine")
    fs._claim_for_sending(lost, "h", NOW, 30)
    fs._defer(lost, "h", 1, NOW, 0, True)  # a lost answer: ambiguous, its lease released
    fs._claim_for_sending(live, "h", NOW, 30)  # a send in flight
    assert rig.p.post(DISCONNECT, {"connector": "gmail"}).status_code == 200
    assert fs.get(plain)["state"] == "failed"
    assert fs.get(lost)["state"] != "failed" and fs.get(live)["state"] != "failed"


def run_like(store: Any, stub: ConnectorRpcStub, puts: list) -> Any:
    """What `Run._outbox` and `Run._abandon_unsent` read, over a real store: the real methods, nothing else."""
    import threading  # noqa: PLC0415

    ns = types.SimpleNamespace(
        adapters={DRAFT["connector"]: stub}, seams=types.SimpleNamespace(outbox_store=store),
        world_id=DRAFT["world_id"], run_id=DRAFT["run_id"], paused=lambda: False, _record_transfer=lambda t: None,
        sends={DRAFT["id"]: {"worker": "w", "island": "i", "district": "D1", "cause": "c"}},
        _alerted=set(), _alert_lock=threading.Lock(), _alert_summary="A person must check.",
        put=lambda *a, **k: puts.append(a),
    )  # fmt: skip
    for name in ("_record_alert", "_keeps_ambiguous", "_may_have_sent", "_outbox"):
        setattr(ns, name, lambda *a, _n=name, **k: getattr(Run, _n)(ns, *a, **k))
    return ns


@pytest.mark.parametrize("kind", ["memory", "firestore"])
def test_ADR35_L6_FR_CON_02_a_lost_answer_is_one_post_and_one_alert_and_is_never_failed(kind):
    store = firestore_store() if kind == "firestore" else InMemoryOutboxStore(clock=lambda: NOW)
    rig = Rig(*[TransportError() for _ in range(6)])
    puts: list = []
    run = run_like(store, rig.stub, puts)
    outbox = run._outbox()
    assert outbox._retry.max_delay_s >= 60  # a stub is wired: the 60 s ambiguous delay holds, not "retry at once"
    outbox.enqueue(copy.deepcopy(DRAFT), copy.deepcopy(DRAFT_EV))
    for _ in range(6):  # the run's own dispatch loop (_SEND_RETRY_DELAYS_S)
        outbox.dispatch_due()
    assert len(rig.transport.calls) == 1
    Run._abandon_unsent(run)
    Run._abandon_unsent(run)
    assert [p[0] for p in puts] == ["alert.raised"] and store.get(DRAFT["id"])["state"] != "failed"
    assert Run._keeps_ambiguous(run, DRAFT) and Run._may_have_sent(run, DRAFT["id"])


def test_ADR35_L6_FR_CON_02_a_run_without_a_stub_keeps_the_immediate_retry_policy():
    store = InMemoryOutboxStore()
    run = run_like(store, ConnectorRpcStub("gmail", Rig().rpc), [])
    run.adapters = {"gmail": types.SimpleNamespace()}
    assert Run._outbox(run)._retry.max_delay_s == 0
    assert not Run._keeps_ambiguous(run, DRAFT)


def test_ADR35_L6_FR_CON_02_an_expired_lease_is_not_failed_by_a_give_up_but_alerts_once():
    store = InMemoryOutboxStore(clock=lambda: NOW)
    rig = Rig(answer("sent"))
    puts: list = []
    run = run_like(store, rig.stub, puts)
    run._outbox().enqueue(copy.deepcopy(DRAFT), copy.deepcopy(DRAFT_EV))
    store._claim_for_sending(DRAFT["id"], "dead", NOW, 30)  # the holder died with the lease unreleased
    store._clock = lambda: "2026-10-09T09:45:00.000Z"
    Run._abandon_unsent(run)
    assert store.get(DRAFT["id"])["state"] == "sending" and [p[0] for p in puts] == ["alert.raised"]


def test_ADR35_L6_FR_CON_02_a_demo_schedule_builds_no_live_adapters(monkeypatch):
    from tilo_api import ephemeral, runs, schedules  # noqa: PLC0415

    built = types.SimpleNamespace(adapters={"gmail": object()})
    monkeypatch.setattr(runs, "run_seams", lambda request, mode: dataclasses_replace(built))
    monkeypatch.setattr(ephemeral, "mark_no_person", lambda request: None)
    build = schedules.get_seams_factory(types.SimpleNamespace(), "replay")
    assert build(demo=True).adapters == {} and build().adapters == {"gmail": built.adapters["gmail"]}


def dataclasses_replace(ns: Any) -> Any:
    import dataclasses  # noqa: PLC0415

    @dataclasses.dataclass(frozen=True)
    class S:
        adapters: dict

    return S(adapters=dict(ns.adapters))


def test_ADR35_L6_FR_CON_02_the_post_path_is_pinned_to_the_two_wire_methods():
    """`_post`, the execute path and the `send` route are reached from one method each; nothing else in src posts."""
    tree = ast.parse((SRC / "meeting_host_rpc.py").read_text(encoding="utf-8"))
    by_route: dict[str, list[str]] = {}
    for fn in (f for f in ast.walk(tree) if isinstance(f, ast.FunctionDef)):
        for call in (n for n in ast.walk(fn) if isinstance(n, ast.Call)):
            if isinstance(call.func, ast.Attribute) and call.func.attr == "_post" and call.args:
                first = call.args[0]
                if isinstance(first, ast.Constant):
                    by_route.setdefault(first.value, []).append(fn.name)
    assert by_route["execute"] == ["execute_entry"] and by_route["send"] == ["send_invitation"]
    uses = [
        fn.name
        for fn in ast.walk(tree)
        if isinstance(fn, ast.FunctionDef)
        and any(isinstance(n, ast.Name) and n.id == "EXECUTE_PATH" for n in ast.walk(fn))
    ]
    assert uses == ["execute_entry"]
    for path in SRC.rglob("*.py"):
        if path.name == "meeting_host_rpc.py":
            continue
        text = path.read_text(encoding="utf-8")
        assert "/internal/side-effects/execute" not in text and "EXECUTE_PATH" not in text, path.name
        assert "._post(" not in text and "._call(" not in text, path.name
