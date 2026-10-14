"""Offline candidate checks; #415 activation holds are documented, never mocked away."""

from pathlib import Path

import pytest
from _gapi_lib import enqueue
from test_FR_CON_12_mcp_allowlist import FakeArtifacts, FakeTransport, _case
from tilo_connectors.errors import MissingGrant
from tilo_connectors.mcp import (
    McpAdapter,
    McpClient,
    McpConfigError,
    McpSideEffectRefused,
    load_allowlist,
)
from tilo_connectors.outbox import Outbox
from tilo_connectors.store import InMemoryOutboxStore

FIXTURE = Path(__file__).parent / "fixtures" / "lovable-mcp.yaml"


def test_FR_CON_18_candidate_loads_with_shipped_policy_and_reservations():
    allowlist = load_allowlist(FIXTURE)
    assert allowlist.ids() == ("lovable_mcp",)
    (tool,) = allowlist.tools("lovable_mcp")
    assert (tool.name, tool.action_type, tool.risk_tier, tool.side_effect) == (
        "build_handoff",
        "build_handoff",
        "T3",
        True,
    )


def test_FR_CON_18_fake_handoff_requires_person_outbox_and_preserves_arguments(tmp_path):
    log = []
    client = McpClient(load_allowlist(FIXTURE), lambda server: FakeTransport(server, log))
    artifacts = FakeArtifacts()
    adapter = McpAdapter(client, "lovable_mcp", artifacts)
    outbox = Outbox(
        InMemoryOutboxStore(),
        {"lovable_mcp": adapter},
        emit=lambda event: None,
        clock=lambda: "2026-09-29T09:32:10.000Z",
    )
    case = _case(artifacts, "build_handoff", "T3")
    case["entry"]["connector"] = "lovable_mcp"
    arguments = {"prompt": "Build exactly this: ₹ & <untrusted>", "granted_data": []}
    artifacts.put_mcp_call("art_mcp_1", arguments)
    assert case["entry"]["authz"]["by"] == "person"
    with pytest.raises(MissingGrant):
        adapter.execute_side_effect(case["entry"], object())
    with pytest.raises(McpSideEffectRefused):
        client.connect("lovable_mcp").call_read("build_handoff", arguments)
    assert not [row for row in log if row[0] == "call_tool"]
    enqueue(outbox, case)
    assert [entry["state"] for entry in outbox.dispatch_due()] == ["sent"]
    outbox.dispatch_due()
    calls = [row for row in log if row[0] == "call_tool"]
    assert len(calls) == 1
    assert calls[0][1:4] == ("lovable_mcp", "build_handoff", arguments)


def test_FR_CON_12_candidate_rejects_private_literal_endpoint(tmp_path):
    path = tmp_path / "mcp.yaml"
    path.write_text(FIXTURE.read_text().replace("lovable.example", "127.0.0.1"), encoding="utf-8")
    with pytest.raises(McpConfigError, match="public host"):
        load_allowlist(path)
