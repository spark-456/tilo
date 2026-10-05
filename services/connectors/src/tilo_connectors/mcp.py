"""tilo_connectors.mcp — MCP client with an allowlist and per-tool risk tiers (FR-CON-12, PRD 12.2).

`config/mcp.yaml` is the only source of which servers may connect and which of their tools exist.
`McpClient.connect` refuses an unlisted server before the transport factory runs, so no connection
is attempted. A server's own tool list is untrusted: unlisted tools are dropped and refused.
Each listed tool names its action type and risk tier; the tier must equal the policy table's
(config/autonomy.yaml, an unlisted action type is T3), never a model's or a server's claim.
A tool with a side effect runs only as an outbox entry through `McpAdapter.execute_side_effect`
(SEC-03, T3 is always a person); `McpSession.call_read` refuses it. Reads are T1 and their results
are marked untrusted. The transport is injected: tests use a fake, nothing here opens a socket.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import tilo_policy
import yaml

from .errors import MissingGrant, SideEffectRefused
from .outbox import Grant
from .registry import RESERVED_CONNECTOR_ID, ConnectorConfigError, _NoAliasLoader, load_registry

_CONFIG_DIR = Path(__file__).resolve().parents[4] / "config"
DEFAULT_CONFIG = _CONFIG_DIR / "mcp.yaml"
_SERVER_ID = re.compile(r"[a-z][a-z0-9_]{1,31}")
_ACTION_TYPE = re.compile(r"[a-z][a-z0-9_]{1,47}")
_TOOL_NAME = re.compile(r"[A-Za-z0-9_.-]{1,64}")
_ENDPOINT = re.compile(r"https://[A-Za-z0-9.-]+(:[0-9]{1,5})?(/[^\s#@]*)?")
_TIERS = ("T1", "T2", "T3")


class McpConfigError(ValueError):
    """The MCP config is unreadable or breaks a rule; nothing is partially listed."""


class McpServerNotAllowed(Exception):
    """The server is not in config/mcp.yaml. Raised before any connection attempt."""


class McpToolNotAllowed(Exception):
    """The tool is not listed for that server."""


class McpSideEffectRefused(Exception):
    """A tool that is gated or has a side effect cannot run outside the outbox."""


@dataclass(frozen=True)
class McpServer:
    id: str
    name: str
    endpoint: str


@dataclass(frozen=True)
class McpTool:
    server_id: str
    name: str
    action_type: str
    risk_tier: str
    side_effect: bool


@dataclass(frozen=True)
class McpResult:
    server_id: str
    tool: str
    data: Any
    untrusted: bool = True  # a server's reply is data, never instructions


class McpTransport(Protocol):
    def list_tools(self) -> list[Mapping[str, Any]]: ...

    def call_tool(self, name: str, arguments: Mapping[str, Any], *, idempotency_key: str | None = None) -> Any: ...

    def close(self) -> None: ...


class McpAllowlist:
    """Read-only; built by `load_allowlist`."""

    def __init__(self, servers: Mapping[str, McpServer], tools: Mapping[str, tuple[McpTool, ...]]) -> None:
        self._servers, self._tools = dict(servers), dict(tools)

    def ids(self) -> tuple[str, ...]:
        return tuple(self._servers)

    def __contains__(self, server_id: object) -> bool:
        return server_id in self._servers

    def server(self, server_id: str) -> McpServer:
        if server_id not in self._servers:
            raise McpServerNotAllowed(f"MCP server {server_id!r} is not in the allowlist")
        return self._servers[server_id]

    def tools(self, server_id: str) -> tuple[McpTool, ...]:
        self.server(server_id)
        return self._tools[server_id]

    def tool(self, server_id: str, name: str) -> McpTool:
        for tool in self.tools(server_id):
            if tool.name == name:
                return tool
        raise McpToolNotAllowed(f"tool {name!r} is not listed for MCP server {server_id!r}")


def _check(ok: bool, where: str, problem: str) -> None:
    if not ok:
        raise McpConfigError(f"{where}: {problem}")


def _tool(server_id: str, raw: Any, table: tilo_policy.RiskTable) -> McpTool:
    where = f"mcp server {server_id!r} tool"
    _check(isinstance(raw, dict) and set(raw) == {"name", "action_type", "risk_tier", "side_effect"}, where, "bad keys")
    name, action, tier, effect = raw["name"], raw["action_type"], raw["risk_tier"], raw["side_effect"]
    _check(isinstance(name, str) and _TOOL_NAME.fullmatch(name) is not None, where, "bad name")
    where = f"{where} {name!r}"
    _check(isinstance(action, str) and _ACTION_TYPE.fullmatch(action) is not None, where, "bad action_type")
    _check(tier in _TIERS and isinstance(effect, bool), where, "risk_tier must be T1, T2 or T3; side_effect a boolean")
    _check(tier == table.tier_of(action, ()), where, "risk_tier must equal the policy table's (unlisted is T3)")
    _check(effect or tier == "T1", where, "a tool with no side effect is a read and must be T1")
    return McpTool(server_id, name, action, tier, effect)


def _server(raw: Any, table: tilo_policy.RiskTable, reserved: frozenset[str]) -> tuple[McpServer, tuple[McpTool, ...]]:
    _check(isinstance(raw, dict) and set(raw) == {"id", "name", "endpoint", "tools"}, "mcp server", "bad keys")
    sid, name, endpoint, tools = raw["id"], raw["name"], raw["endpoint"], raw["tools"]
    _check(isinstance(sid, str) and _SERVER_ID.fullmatch(sid) is not None, "mcp server", "bad id")
    where = f"mcp server {sid!r}"
    _check(sid != RESERVED_CONNECTOR_ID and sid not in reserved, where, "id is taken by a connector")
    _check(isinstance(name, str) and 0 < len(name) <= 60, where, "bad name")
    _check(isinstance(endpoint, str) and _ENDPOINT.fullmatch(endpoint) is not None, where, "endpoint must be https")
    _check(isinstance(tools, list), where, "tools must be a list")
    listed = tuple(_tool(sid, t, table) for t in tools)
    _check(len({t.name for t in listed}) == len(listed), where, "a tool is listed twice")
    _check(len({t.action_type for t in listed}) == len(listed), where, "an action type is listed twice")
    return McpServer(sid, name, endpoint), listed


def load_allowlist(
    path: str | os.PathLike[str] = DEFAULT_CONFIG,
    *,
    risk_table: tilo_policy.RiskTable | None = None,
    reserved_ids: Iterable[str] | None = None,
) -> McpAllowlist:
    table = risk_table if risk_table is not None else tilo_policy.load_risk_table()
    if reserved_ids is None:
        try:
            reserved_ids = load_registry(_CONFIG_DIR / "connectors.yaml").ids()
        except ConnectorConfigError as exc:
            raise McpConfigError(f"connectors config unreadable: {exc}") from exc
    try:
        raw = yaml.load(Path(path).read_text(encoding="utf-8"), Loader=_NoAliasLoader)  # noqa: S506
    except (OSError, UnicodeDecodeError, yaml.YAMLError, RecursionError, ValueError) as exc:
        raise McpConfigError(f"{path}: not a readable UTF-8 YAML file: {exc}") from exc
    _check(
        isinstance(raw, dict) and set(raw) == {"servers"} and isinstance(raw["servers"], list), str(path), "bad shape"
    )
    servers: dict[str, McpServer] = {}
    tools: dict[str, tuple[McpTool, ...]] = {}
    for entry in raw["servers"]:
        server, listed = _server(entry, table, frozenset(reserved_ids))
        _check(server.id not in servers, f"mcp server {server.id!r}", "declared more than once")
        servers[server.id], tools[server.id] = server, listed
    return McpAllowlist(servers, tools)


class McpSession:
    def __init__(self, allowlist: McpAllowlist, server_id: str, transport: McpTransport) -> None:
        self.server_id, self._allowlist, self._transport = server_id, allowlist, transport

    def tools(self) -> list[McpTool]:
        """The server's tools that config lists, in config order, with config's tier (never the server's)."""
        advertised = {t.get("name") for t in self._transport.list_tools() if isinstance(t, Mapping)}
        return [t for t in self._allowlist.tools(self.server_id) if t.name in advertised]

    def call_read(self, name: str, arguments: Mapping[str, Any]) -> McpResult:
        tool = self._allowlist.tool(self.server_id, name)  # unlisted: refused before the transport
        if tool.side_effect or tool.risk_tier != "T1":
            raise McpSideEffectRefused(f"tool {name!r} runs only as an outbox entry (SEC-03)")
        return McpResult(self.server_id, name, self._transport.call_tool(name, dict(arguments)))

    def _call_for_outbox(self, tool: McpTool, arguments: Mapping[str, Any], idempotency_key: str) -> McpResult:
        data = self._transport.call_tool(tool.name, dict(arguments), idempotency_key=idempotency_key)
        return McpResult(self.server_id, tool.name, data)

    def close(self) -> None:
        self._transport.close()


class McpClient:
    def __init__(self, allowlist: McpAllowlist, transport_factory: Callable[[McpServer], McpTransport]) -> None:
        self._allowlist, self._factory = allowlist, transport_factory

    def connect(self, server_id: str) -> McpSession:
        server = self._allowlist.server(server_id)  # raises before the factory is reached
        return McpSession(self._allowlist, server_id, self._factory(server))


class McpAdapter:
    """Outbox connector for one allowlisted server: its side-effect tools, only with the outbox's grant."""

    def __init__(self, client: McpClient, server_id: str, artifacts: Any) -> None:
        client._allowlist.server(server_id)
        self._client, self._server_id, self._artifacts = client, server_id, artifacts

    def _tool_for(self, entry: Mapping[str, Any]) -> McpTool:
        for tool in self._client._allowlist.tools(self._server_id):
            if (
                tool.side_effect
                and tool.action_type == entry.get("action_type")
                and tool.risk_tier == entry.get("risk_tier")
            ):
                return tool
        raise SideEffectRefused("no listed MCP tool matches this action type and tier")

    def execute_side_effect(self, entry: Mapping[str, Any], grant: Grant) -> dict[str, Any]:
        if not isinstance(grant, Grant) or grant.world_id != entry.get("world_id"):
            raise MissingGrant("grant not minted by Outbox.dispatch_due() for this exact send")
        grant.verify(entry["idempotency_key"])
        tool = self._tool_for(entry)
        arguments: Mapping[str, Any] = {}
        if (ref := entry.get("item")) is not None:
            try:
                item = self._artifacts.get(str(ref["artifact_id"]), int(ref["version"]))
            except (KeyError, TypeError, ValueError):
                raise SideEffectRefused("the artifact cannot be found") from None
            arguments = item.get("arguments")  # type: ignore[assignment]
            if item.get("kind") != "mcp_call" or not isinstance(arguments, dict):
                raise SideEffectRefused("the artifact is not an MCP call")
        session = self._client.connect(self._server_id)
        try:
            result = session._call_for_outbox(tool, arguments, entry["idempotency_key"])
        finally:
            session.close()
        return {"server": result.server_id, "tool": result.tool}
