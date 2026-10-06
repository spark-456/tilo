"""FR-CON-12 hardening (issue #415, from the #403 security review): adapters of one server share a default
ledger, a wrong-tier side-effect tool never loads, and config/mcp.yaml names its preconditions. No network.
"""

from __future__ import annotations

import pathlib

import pytest
from _connectors_lib import ManualClock
from _gapi_lib import enqueue
from test_FR_CON_12_mcp_allowlist import CONFIG, TABLE, FakeArtifacts, FakeTransport, _case, _write
from tilo_connectors.errors import SideEffectRefused
from tilo_connectors.mcp import McpAdapter, McpClient, McpConfigError, load_allowlist
from tilo_connectors.outbox import Outbox
from tilo_connectors.store import InMemoryOutboxStore

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
START = "2026-09-29T09:32:10.000Z"


def test_FR_CON_12_two_outboxes_over_one_store_call_the_server_once(tmp_path):
    """Probe P1c: instance A is mid-call when its lease lapses; instance B (a fresh adapter) must not call again."""
    clock, store, artifacts, log = ManualClock(START), InMemoryOutboxStore(), FakeArtifacts(), []
    allowlist = load_allowlist(_write(tmp_path), risk_table=TABLE, reserved_ids=())

    def outbox(transport_cls):
        client = McpClient(allowlist, lambda server: transport_cls(server, log))
        return Outbox(store, {"notes_hub": McpAdapter(client, "notes_hub", artifacts)}, lambda part: None, clock)

    class Rival(FakeTransport):
        def call_tool(self, name, arguments, *, idempotency_key=None):
            super().call_tool(name, arguments, idempotency_key=idempotency_key)
            clock.advance(31)  # the lease lapses while this call is still running
            outbox(FakeTransport).dispatch_due()
            return {"ok": True}

    case = _case(artifacts, "share_file", "T3")
    first = outbox(Rival)
    enqueue(first, case)
    first.dispatch_due()

    assert len([e for e in log if e[0] == "call_tool"]) == 1


def test_FR_CON_12_adapters_of_different_servers_do_not_share_a_ledger(tmp_path):
    other = "  - {id: other_hub, name: Other hub, endpoint: 'https://mcp.other.example/v1', tools: []}\n"
    allowlist = load_allowlist(_write(tmp_path, CONFIG + other), risk_table=TABLE, reserved_ids=())
    client = McpClient(allowlist, lambda server: FakeTransport(server, []))
    a, b = McpAdapter(client, "notes_hub", FakeArtifacts()), McpAdapter(client, "other_hub", FakeArtifacts())

    assert a._ledger is not b._ledger
    assert a._ledger is McpAdapter(client, "notes_hub", FakeArtifacts())._ledger


@pytest.mark.parametrize("tier", ["T1", "T2"])
def test_FR_CON_12_publish_post_declared_below_t3_is_refused_by_the_loader(tmp_path, tier):
    """publish_post is not in the policy table, so it is T3; a config that says T1 or T2 for it never loads."""
    line = "action_type: publish_post, risk_tier: T3, side_effect: true"
    assert line in CONFIG
    for effect in ("true", "false"):
        text = CONFIG.replace(line, f"action_type: publish_post, risk_tier: {tier}, side_effect: {effect}")
        with pytest.raises(McpConfigError, match="risk_tier"):
            load_allowlist(_write(tmp_path, text), risk_table=TABLE, reserved_ids=())


@pytest.mark.parametrize("tier", ["T1", "T2"])
def test_FR_CON_12_an_entry_for_publish_post_at_a_lower_tier_matches_no_tool(tmp_path, tier):
    client = McpClient(load_allowlist(_write(tmp_path), risk_table=TABLE, reserved_ids=()), lambda server: None)
    adapter = McpAdapter(client, "notes_hub", FakeArtifacts())

    with pytest.raises(SideEffectRefused):
        adapter._tool_for({"connector": "notes_hub", "action_type": "publish_post", "risk_tier": tier})


def test_FR_CON_12_the_config_header_names_the_preconditions_before_a_server_is_listed():
    head = (REPO_ROOT / "config" / "mcp.yaml").read_text(encoding="utf-8").split("servers:")[0].lower()
    for word in ("arguments", "ledger", "egress", "resolved"):
        assert word in head and "precondition" in head
