"""FR-CON-12 security review round 1 (PR #403): the MCP adapter runs a key at most once (OB-03) and
acts only on what the policy engine assessed (OB-04/OB-05); the loader and the session refuse what
the review probed. Nothing opens a socket: every transport is a fake.
"""

from __future__ import annotations

import re

import pytest
import tilo_policy
from _gapi_lib import enqueue
from test_FR_CON_12_mcp_allowlist import CONFIG, MCP_SRC, TABLE, FakeArtifacts, FakeTransport, _case, _write
from tilo_connectors.adapters import side_effect_marker
from tilo_connectors.errors import MissingGrant
from tilo_connectors.mcp import McpAdapter, McpClient, McpConfigError, McpServerNotAllowed, load_allowlist
from tilo_connectors.outbox import Outbox
from tilo_connectors.side_effects import scan_for_side_effect_calls
from tilo_connectors.store import InMemoryOutboxStore


class ActsThenRaises(FakeTransport):
    def call_tool(self, name, arguments, *, idempotency_key=None):
        super().call_tool(name, arguments, idempotency_key=idempotency_key)
        raise TimeoutError("the reply was lost after the server acted")


class Rewrites:
    """An outbox connector that edits the claimed entry, then hands it on with the live grant: it stands
    in for an entry whose fields the adapter must honour or refuse."""

    def __init__(self, adapter: McpAdapter, **fields) -> None:
        self.adapter, self.fields = adapter, fields

    def execute_side_effect(self, entry, grant):
        return self.adapter.execute_side_effect({**entry, **self.fields}, grant)


def _env(tmp_path, transport=FakeTransport, artifacts=None, wrap=None):
    log: list = []
    allowlist = load_allowlist(_write(tmp_path), risk_table=TABLE, reserved_ids=())
    client = McpClient(allowlist, lambda server: transport(server, log))
    artifacts = artifacts if artifacts is not None else FakeArtifacts()
    adapter = McpAdapter(client, "notes_hub", artifacts)
    store, alerts = InMemoryOutboxStore(), []
    connector = wrap(adapter) if wrap else adapter
    outbox = Outbox(store, {"notes_hub": connector}, lambda part: None, lambda: "2026-09-29T09:32:10.000Z",
                    alert=alerts.append)  # fmt: skip
    return log, artifacts, store, outbox, alerts


def _calls(log):
    return [e for e in log if e[0] == "call_tool"]


# -- BLOCKING 1: OB-03, at most once ---------------------------------------------------------------


def test_FR_CON_12_a_call_that_acts_then_raises_runs_once_over_four_dispatches(tmp_path):
    log, artifacts, store, outbox, alerts = _env(tmp_path, transport=ActsThenRaises)
    case = _case(artifacts, "share_file", "T3")
    enqueue(outbox, case)
    for _ in range(4):
        outbox.dispatch_due()
    assert len(_calls(log)) == 1, "a possibly-sent MCP call is never repeated"
    assert store.get(case["entry"]["id"])["state"] == "failed"
    assert [a["data"]["alert_id"] for a in alerts] == [case["entry"]["id"]], "a person is told"


def test_FR_CON_12_the_server_gets_a_hashed_marker_never_the_raw_key(tmp_path):
    log, artifacts, _, outbox, _ = _env(tmp_path)
    case = _case(artifacts, "share_file", "T3")
    enqueue(outbox, case)
    outbox.dispatch_due()
    ((_, _, _, _, sent_key),) = _calls(log)
    entry = case["entry"]
    assert sent_key == side_effect_marker(entry)
    assert entry["idempotency_key"] not in sent_key and entry["run_id"] not in sent_key


# -- BLOCKING 2: OB-04/OB-05, the adapter acts only on what was assessed ---------------------------


def test_FR_CON_12_the_loader_refuses_a_side_effect_tool_below_t3(tmp_path):
    text = CONFIG.replace(
        "{name: post_update, action_type: publish_post, risk_tier: T3",
        "{name: post_update, action_type: post_status_update, risk_tier: T2",
    )
    assert text != CONFIG
    with pytest.raises(McpConfigError):  # T2 equals the table, but an MCP side effect always waits for a person
        load_allowlist(_write(tmp_path, text), risk_table=TABLE, reserved_ids=())


@pytest.mark.parametrize(
    "fields",
    [
        {"recipients": ["stranger@elsewhere.example"]},
        {"destination": "team-channel"},
        {"attachments": [{"artifact_id": "art_secret", "version": 1}]},
    ],
)
def test_FR_CON_12_an_entry_with_recipients_destination_or_attachments_is_refused(tmp_path, fields):
    log, artifacts, store, outbox, _ = _env(tmp_path, wrap=lambda a: Rewrites(a, **fields))
    case = _case(artifacts, "share_file", "T3")
    enqueue(outbox, case)
    outbox.dispatch_due()
    assert _calls(log) == [], "the adapter cannot honour these fields, so it never calls"
    assert store.get(case["entry"]["id"])["state"] == "failed"


# -- follow-ups fixed in the same pass --------------------------------------------------------------


def test_FR_CON_12_the_session_side_effect_call_needs_a_live_grant(tmp_path):
    log: list = []
    allowlist = load_allowlist(_write(tmp_path), risk_table=TABLE, reserved_ids=())
    session = McpClient(allowlist, lambda server: FakeTransport(server, log)).connect("notes_hub")
    tool = allowlist.tool("notes_hub", "share_page")
    with pytest.raises(MissingGrant):
        session.call_for_outbox(tool, {"page": "p1"}, grant=object(), idempotency_key="k1", marker="m" * 32)
    assert _calls(log) == []


def test_FR_CON_12_the_mcp_module_never_calls_a_side_effect_method_or_reaches_into_privates(outbox_module_path):
    assert scan_for_side_effect_calls([MCP_SRC], allowed_path=outbox_module_path) == []
    source = MCP_SRC.read_text(encoding="utf-8")
    assert not re.search(r"\b(client|session|self\._client)\._[a-z]", source), "no cross-class private access"


@pytest.mark.parametrize(
    "text",
    [
        # a duplicate key: the visible `side_effect: true` would load as false
        CONFIG.replace("risk_tier: T1, side_effect: false}", "risk_tier: T1, side_effect: true, side_effect: false}"),
        CONFIG.replace("    name: Notes hub\n", "    name: Notes hub\n    name: Notes hub two\n"),
        "servers:\n  - <<: {id: notes_hub, name: Notes hub}\n"
        "    endpoint: https://mcp.notes.example/v1\n    tools: []\n",
    ],
)
def test_FR_CON_12_duplicate_and_merge_yaml_keys_are_refused(tmp_path, text):
    assert text != CONFIG
    with pytest.raises(McpConfigError):
        load_allowlist(_write(tmp_path, text), risk_table=TABLE, reserved_ids=())


def test_FR_CON_12_a_reserved_action_type_is_refused(tmp_path):
    table = tilo_policy.RiskTable(actions={**TABLE.actions, "grant_budget": "T1"}, modifiers=TABLE.modifiers,
                                  max_level=TABLE.max_level)  # fmt: skip
    text = CONFIG.replace("action_type: read_notes", "action_type: grant_budget")
    with pytest.raises(McpConfigError):
        load_allowlist(_write(tmp_path, text), risk_table=table, reserved_ids=())


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://mcp.example/v1?token=abc",
        "https://mcp.example/v1?",
        "https://127.0.0.1/v1",
        "https://127.8.9.1/v1",
        "https://localhost/v1",
        "https://api.localhost/v1",
        "https://10.0.0.5/v1",
        "https://172.16.3.4/v1",
        "https://192.168.1.1/v1",
        "https://169.254.169.254/computeMetadata/v1",
        "https://metadata.google.internal/v1",
        "https://2130706433/v1",
        "https://0x7f.0.0.1/v1",
        "https://mcp.example:99999/v1",
        "https://mcp.example:0/v1",
        "https://mcp.example/v1/café",
        "https://mcp.exämple/v1",
        "https://[::1]/v1",
    ],
)
def test_FR_CON_12_endpoint_refuses_queries_internal_hosts_bad_ports_and_non_ascii(tmp_path, endpoint):
    text = CONFIG.replace("https://mcp.notes.example/v1", endpoint)
    with pytest.raises(McpConfigError):
        load_allowlist(_write(tmp_path, text), risk_table=TABLE, reserved_ids=())


@pytest.mark.parametrize("endpoint", ["https://mcp.notes.example/v1", "https://Mcp.Example:8443/v1/tools_x"])
def test_FR_CON_12_endpoint_still_accepts_a_public_https_host(tmp_path, endpoint):
    text = CONFIG.replace("https://mcp.notes.example/v1", endpoint)
    assert load_allowlist(_write(tmp_path, text), risk_table=TABLE, reserved_ids=()).ids() == ("notes_hub",)


def test_FR_CON_12_an_entry_for_another_connector_is_refused(tmp_path):
    log, artifacts, store, outbox, _ = _env(tmp_path, wrap=lambda a: Rewrites(a, connector="other_hub"))
    case = _case(artifacts, "share_file", "T3")
    enqueue(outbox, case)
    outbox.dispatch_due()
    assert _calls(log) == [] and store.get(case["entry"]["id"])["state"] == "failed"


class OddTools(FakeTransport):
    def list_tools(self):
        junk = [{"name": ["unhashable"]}, "not a mapping", None, {"name": 5}, {"name": "share_page"}]
        return junk + [{"name": "filler"}] * 300 + [{"name": "get_notes"}]  # past the cap: never read


def test_FR_CON_12_tools_caps_the_server_list_and_skips_malformed_entries(tmp_path):
    allowlist = load_allowlist(_write(tmp_path), risk_table=TABLE, reserved_ids=())
    session = McpClient(allowlist, lambda server: OddTools(server, [])).connect("notes_hub")
    assert [t.name for t in session.tools()] == ["share_page"]


class ReturnsNone(FakeArtifacts):
    def get(self, artifact_id, version):
        return None


class ReturnsList(FakeArtifacts):
    def get(self, artifact_id, version):
        return ["kind", "mcp_call"]


@pytest.mark.parametrize("artifacts", [ReturnsNone(), ReturnsList()])
def test_FR_CON_12_an_artifact_port_returning_a_non_dict_fails_the_entry(tmp_path, artifacts):
    log, _, store, outbox, _ = _env(tmp_path, artifacts=artifacts)
    case = _case(artifacts, "share_file", "T3")
    enqueue(outbox, case)
    outbox.dispatch_due()
    assert _calls(log) == [] and store.get(case["entry"]["id"])["state"] == "failed"


def test_FR_CON_12_error_messages_cap_the_echoed_server_and_tool_names(tmp_path):
    allowlist = load_allowlist(_write(tmp_path), risk_table=TABLE, reserved_ids=())
    for call in (lambda: allowlist.server("s" * 5000), lambda: allowlist.tool("notes_hub", "t" * 5000)):
        with pytest.raises(Exception) as caught:
            call()
        assert len(str(caught.value)) < 200
    with pytest.raises(McpServerNotAllowed):
        allowlist.server("evil")
