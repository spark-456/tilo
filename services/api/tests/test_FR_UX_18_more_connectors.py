"""FR-UX-18 setup catalogue: no invented OAuth connection or token exposure."""

import pytest
from fastapi import Response
from tilo_api import deps
from tilo_api.connectors_list import connectors_route
from tilo_connectors.mcp import McpClient, McpServerNotAllowed, load_allowlist

IDS = ("slack", "notion", "github", "xero", "hubspot", "stripe", "microsoft365", "jira", "bamboohr")


@pytest.mark.parametrize("connector", IDS)
def test_FR_UX_18_declared_oauth_card_is_unconnected_until_workspace_setup(connector):
    registry = deps.get_connector_registry()
    declared = registry.get(connector)
    assert declared["auth"] == "oauth2"
    assert declared["actions"][0]["risk_tier"] == "T3"
    assert declared["actions"][0]["gate_type"] == "approval"
    response = connectors_route(
        Response(), deps.Principal(user_id="u_owner", role="owner", world_id=None, channel="web"), registry, None
    )
    row = next(r for r in response["connectors"] if r["id"] == connector)
    assert row["state"] == "available" and row["state_known"] is False
    assert row["scopes"] == []
    assert not set(row).intersection({"token", "password", "client_secret"})
    attempted = []
    client = McpClient(load_allowlist(), lambda server: attempted.append(server))
    with pytest.raises(McpServerNotAllowed):
        client.connect(connector)
    assert attempted == []
