"""tilo_connectors.mcp — MCP client with an allowlist and per-tool risk tiers (FR-CON-12, PRD 12.2).

`config/mcp.yaml` is the only source of which servers may connect and which of their tools exist.
`McpClient.connect` refuses an unlisted server before the transport factory runs, so no connection
is attempted. A server's own tool list is untrusted: unlisted tools are dropped and refused.
Each listed tool names its action type and risk tier; the tier must equal the policy table's
(config/autonomy.yaml, an unlisted action type is T3), never a model's or a server's claim.
A tool is either a T1 read or a T3 side effect: an MCP call's free-form arguments decide its audience,
which the policy engine cannot assess, so a person approves every one (OB-04). It runs only as an
outbox entry through `McpAdapter.execute_side_effect` (SEC-03), at most once per key (OB-03);
`McpSession.call_read` refuses it. Reads are T1 and their results are marked untrusted.
The transport is injected: tests use a fake, nothing here opens a socket.
"""

from __future__ import annotations

import ipaddress
import itertools
import os
import re
import threading
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import tilo_policy
import yaml

from .adapters import side_effect_marker
from .errors import MissingGrant, PossiblySent, SideEffectRefused
from .outbox import Grant
from .registry import (
    RESERVED_ACTION_TYPES,
    RESERVED_CONNECTOR_ID,
    ConnectorConfigError,
    load_registry,
    load_strict_yaml,
)

_CONFIG_DIR = Path(__file__).resolve().parents[4] / "config"
DEFAULT_CONFIG = _CONFIG_DIR / "mcp.yaml"
_SERVER_ID = re.compile(r"[a-z][a-z0-9_]{1,31}")
_ACTION_TYPE = re.compile(r"[a-z][a-z0-9_]{1,47}")
_TOOL_NAME = re.compile(r"[A-Za-z0-9_.-]{1,64}")
# ASCII only, no userinfo, query or fragment; the host is checked again by _public_host.
_ENDPOINT = re.compile(r"https://([A-Za-z0-9.-]{1,253})(?::([0-9]{1,5}))?(/[A-Za-z0-9._~/-]*)?", re.ASCII)
_LABEL = re.compile(r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?", re.ASCII)
_INTERNAL_SUFFIXES = ("localhost", "internal", "local")  # localhost, metadata.google.internal, mDNS names
_TIERS = ("T1", "T3")
_MAX_ADVERTISED = 256  # a server's tool list is read up to this many entries
_MAX_SHOWN = 64  # characters of a server or tool name echoed in an error


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


def _shown(value: object) -> str:
    return repr(value[:_MAX_SHOWN]) if isinstance(value, str) else type(value).__name__


class McpAllowlist:
    """Read-only; built by `load_allowlist`."""

    def __init__(self, servers: Mapping[str, McpServer], tools: Mapping[str, tuple[McpTool, ...]]) -> None:
        self._servers, self._tools = dict(servers), dict(tools)

    def ids(self) -> tuple[str, ...]:
        return tuple(self._servers)

    def __contains__(self, server_id: object) -> bool:
        return isinstance(server_id, str) and server_id in self._servers

    def server(self, server_id: str) -> McpServer:
        if server_id not in self:
            raise McpServerNotAllowed(f"MCP server {_shown(server_id)} is not in the allowlist")
        return self._servers[server_id]

    def tools(self, server_id: str) -> tuple[McpTool, ...]:
        self.server(server_id)
        return self._tools[server_id]

    def tool(self, server_id: str, name: str) -> McpTool:
        for tool in self.tools(server_id):
            if tool.name == name:
                return tool
        raise McpToolNotAllowed(f"tool {_shown(name)} is not listed for MCP server {_shown(server_id)}")


def _check(ok: bool, where: str, problem: str) -> None:
    if not ok:
        raise McpConfigError(f"{where}: {problem}")


def _public_endpoint(endpoint: Any) -> bool:
    """https to a public host: no loopback, private, link-local or metadata address, a port from 1 to 65535."""
    match = _ENDPOINT.fullmatch(endpoint) if isinstance(endpoint, str) and endpoint.isascii() else None
    if match is None:
        return False
    host, port = match.group(1).lower(), match.group(2)
    if port is not None and not 0 < int(port) <= 65535:
        return False
    try:
        return ipaddress.ip_address(host).is_global
    except ValueError:
        pass
    labels = host.split(".")
    return (
        len(labels) > 1
        and all(_LABEL.fullmatch(label) for label in labels)
        and labels[-1][0].isalpha()  # never a numeric host some resolvers read as an address (2130706433, 0x7f.1)
        and labels[-1] not in _INTERNAL_SUFFIXES
    )


def _tool(server_id: str, raw: Any, table: tilo_policy.RiskTable) -> McpTool:
    where = f"mcp server {server_id!r} tool"
    _check(isinstance(raw, dict) and set(raw) == {"name", "action_type", "risk_tier", "side_effect"}, where, "bad keys")
    name, action, tier, effect = raw["name"], raw["action_type"], raw["risk_tier"], raw["side_effect"]
    _check(isinstance(name, str) and _TOOL_NAME.fullmatch(name) is not None, where, "bad name")
    where = f"{where} {name!r}"
    _check(isinstance(action, str) and _ACTION_TYPE.fullmatch(action) is not None, where, "bad action_type")
    _check(action not in RESERVED_ACTION_TYPES, where, "action_type is reserved and is not a connector action")
    _check(tier in _TIERS and isinstance(effect, bool), where, "risk_tier must be T1 or T3; side_effect a boolean")
    _check(tier == table.tier_of(action, ()), where, "risk_tier must equal the policy table's (unlisted is T3)")
    _check(effect == (tier == "T3"), where, "a read must be T1 and a side effect T3 (a person approves it)")
    return McpTool(server_id, name, action, tier, effect)


def _server(raw: Any, table: tilo_policy.RiskTable, reserved: frozenset[str]) -> tuple[McpServer, tuple[McpTool, ...]]:
    _check(isinstance(raw, dict) and set(raw) == {"id", "name", "endpoint", "tools"}, "mcp server", "bad keys")
    sid, name, endpoint, tools = raw["id"], raw["name"], raw["endpoint"], raw["tools"]
    _check(isinstance(sid, str) and _SERVER_ID.fullmatch(sid) is not None, "mcp server", "bad id")
    where = f"mcp server {sid!r}"
    _check(sid != RESERVED_CONNECTOR_ID and sid not in reserved, where, "id is taken by a connector")
    _check(isinstance(name, str) and 0 < len(name) <= 60, where, "bad name")
    _check(_public_endpoint(endpoint), where, "endpoint must be https to a public host, with no query")
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
        raw = load_strict_yaml(Path(path).read_text(encoding="utf-8"))
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
        """The server's tools that config lists, in config order, with config's tier (never the server's).
        Only the first _MAX_ADVERTISED entries of the server's list are read; malformed ones are skipped."""
        listed = self._transport.list_tools()
        advertised: set[str] = set()
        for entry in itertools.islice(listed if isinstance(listed, list | tuple) else (), _MAX_ADVERTISED):
            name = entry.get("name") if isinstance(entry, Mapping) else None
            if isinstance(name, str):
                advertised.add(name)
        return [t for t in self._allowlist.tools(self.server_id) if t.name in advertised]

    def call_read(self, name: str, arguments: Mapping[str, Any]) -> McpResult:
        tool = self._allowlist.tool(self.server_id, name)  # unlisted: refused before the transport
        if tool.side_effect or tool.risk_tier != "T1":
            raise McpSideEffectRefused(f"tool {_shown(name)} runs only as an outbox entry (SEC-03)")
        return McpResult(self.server_id, name, self._transport.call_tool(name, dict(arguments)))

    def call_for_outbox(
        self, tool: McpTool, arguments: Mapping[str, Any], *, grant: Grant, idempotency_key: str, marker: str
    ) -> McpResult:
        """Only with the grant `Outbox.dispatch_due()` minted for this send. The server gets `marker`, never the key."""
        if not isinstance(grant, Grant):
            raise MissingGrant("grant not minted by Outbox.dispatch_due() for this exact send")
        grant.verify(idempotency_key)
        if self._allowlist.tool(self.server_id, tool.name) != tool or not tool.side_effect:
            raise SideEffectRefused("not a listed side-effect tool of this server")
        data = self._transport.call_tool(tool.name, dict(arguments), idempotency_key=marker)
        return McpResult(self.server_id, tool.name, data)

    def close(self) -> None:
        self._transport.close()


class McpClient:
    def __init__(self, allowlist: McpAllowlist, transport_factory: Callable[[McpServer], McpTransport]) -> None:
        self._allowlist, self._factory = allowlist, transport_factory

    @property
    def allowlist(self) -> McpAllowlist:
        return self._allowlist

    def connect(self, server_id: str) -> McpSession:
        server = self._allowlist.server(server_id)  # raises before the factory is reached
        return McpSession(self._allowlist, server_id, self._factory(server))


class InMemoryMcpCallLedger:
    """Which side-effect markers have been started or finished. One per process, shared by every adapter of a
    server; it moves into the durable outbox store with it (BQ-CON12-2)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state: dict[str, str] = {}

    def begin(self, marker: str) -> str | None:
        """Atomically: None and records "started" if the marker is new, else its earlier state."""
        with self._lock:
            earlier = self._state.get(marker)
            if earlier is None:
                self._state[marker] = "started"
            return earlier

    def finish(self, marker: str) -> None:
        with self._lock:
            self._state[marker] = "done"


_LEDGERS: dict[str, InMemoryMcpCallLedger] = {}  # server id -> the ledger every default adapter of it shares
_LEDGERS_LOCK = threading.Lock()


def _shared_ledger(server_id: str) -> InMemoryMcpCallLedger:
    """Two outboxes over one store each build an adapter; their ledger must be the same one (probe P1c)."""
    with _LEDGERS_LOCK:
        return _LEDGERS.setdefault(server_id, InMemoryMcpCallLedger())


class McpAdapter:
    """Outbox connector for one allowlisted server: its side-effect tools, only with the outbox's grant."""

    def __init__(
        self, client: McpClient, server_id: str, artifacts: Any, *, ledger: InMemoryMcpCallLedger | None = None
    ) -> None:
        client.allowlist.server(server_id)
        self._client, self._server_id, self._artifacts = client, server_id, artifacts
        self._ledger = ledger if ledger is not None else _shared_ledger(server_id)

    def _tool_for(self, entry: Mapping[str, Any]) -> McpTool:
        if entry.get("connector") != self._server_id:
            raise SideEffectRefused("the entry is for another connector")
        for tool in self._client.allowlist.tools(self._server_id):
            if (
                tool.side_effect
                and tool.action_type == entry.get("action_type")
                and tool.risk_tier == entry.get("risk_tier")
            ):
                return tool
        raise SideEffectRefused("no listed MCP tool matches this action type and tier")

    def _arguments(self, entry: Mapping[str, Any]) -> dict[str, Any]:
        # An MCP call reaches only whom its arguments name; recipients, a destination or attachments on the entry
        # would be assessed by the policy engine but never honoured, so such an entry is refused (OB-05).
        if entry.get("recipients") or entry.get("destination") is not None or entry.get("attachments"):
            raise SideEffectRefused("an MCP call cannot honour recipients, a destination or attachments")
        if (ref := entry.get("item")) is None:
            return {}
        try:
            item = self._artifacts.get(str(ref["artifact_id"]), int(ref["version"]))
        except (KeyError, TypeError, ValueError):
            raise SideEffectRefused("the artifact cannot be found") from None
        arguments = item.get("arguments") if isinstance(item, Mapping) else None
        if not isinstance(item, Mapping) or item.get("kind") != "mcp_call" or not isinstance(arguments, dict):
            raise SideEffectRefused("the artifact is not an MCP call")
        return arguments

    def execute_side_effect(self, entry: Mapping[str, Any], grant: Grant) -> dict[str, Any]:
        if not isinstance(grant, Grant) or grant.world_id != entry.get("world_id"):
            raise MissingGrant("grant not minted by Outbox.dispatch_due() for this exact send")
        grant.verify(entry["idempotency_key"])
        tool, arguments = self._tool_for(entry), self._arguments(entry)
        marker = side_effect_marker(entry)
        session = self._client.connect(self._server_id)  # a failure here sent nothing: the outbox retries
        try:
            earlier = self._ledger.begin(marker)  # recorded before the call: a retry never reaches call_tool
            if earlier == "done":
                return {"server": self._server_id, "tool": tool.name}
            if earlier is not None:
                raise PossiblySent("an earlier attempt may have acted; a person checks the server")
            try:
                session.call_for_outbox(
                    tool, arguments, grant=grant, idempotency_key=entry["idempotency_key"], marker=marker
                )
            except (MissingGrant, SideEffectRefused):  # refused before the transport: nothing was sent
                raise
            except Exception as exc:  # MCP has no way to ask whether it acted: never retried, a person checks
                raise PossiblySent("the MCP call may have acted before it failed") from exc
            self._ledger.finish(marker)
        finally:
            session.close()
        # The server's reply is untrusted data: nothing of it is recorded or emitted, only which tool ran.
        return {"server": self._server_id, "tool": tool.name}
