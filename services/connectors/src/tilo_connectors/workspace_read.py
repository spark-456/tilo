"""tilo_connectors.workspace_read: `POST /internal/workspace/read` (ADR-0048 decisions 3 and 9, WT-02, WT-03, WT-06).

One read of the person's own Gmail, primary Google Calendar or Google Drive for an agent's tool call, answered with the
contract's closed `read_answer`. The route is host_routes' `serve` (HB-01 caller, 64 KiB body cap, request and answer
validated); this module is the work. Each tool uses exactly the scope its capability declares in config/connectors.yaml
(the broker's `required_scopes`) and never asks for another. Order: the window of `read_events` is checked first
(`invalid_request`, nothing else touched), then the grant (no grant: `not_connected`; the scope absent:
`missing_scope`; no readable `connected_at`: `expired`, fail closed), then one Google call with no retry and no wait.
Nothing here is a side effect, nothing is logged but an exception type, and no token, query, id or text is in an error.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import Any

from .adapters import CalendarAdapter, DriveAdapter, GmailAdapter, InMemoryPicks
from .adapters._transport import AdapterError, FileTooLarge, NotPicked, ProviderUnavailable, RateLimited
from .adapters.calendar import window
from .adapters.drive import UnsupportedType
from .tokens import ConnectionExpired, InsufficientScope, NotConnected, TokenError

_log = logging.getLogger(__name__)
TOOLS = {  # the five read tools, each named after the connector action it runs (config/connectors.yaml)
    "search_email": "gmail",
    "read_email": "gmail",
    "read_events": "google_calendar",
    "list_files": "google_drive",
    "read_file": "google_drive",
}


class _NoArtifacts:  # a read saves nothing
    def get(self, artifact_id: str, version: int) -> Mapping[str, Any]:
        raise AdapterError("a read has no artifacts")


def invalid_window(body: Mapping[str, Any]) -> bool:
    """WT-02: a `read_events` window that does not end after it starts, or spans over 31 days (or has no offset)."""
    if body["tool"] != "read_events":
        return False
    try:
        window(body["args"]["start"], body["args"]["end"])
    except ValueError:
        return True
    return False


def read(
    body: Mapping[str, Any],
    *,
    declaration: Mapping[str, Any],
    broker: Any,
    transport: Any,
    clock: Callable[[], str],
    emit: Callable[[dict[str, Any]], None],
    parts: Any,
) -> dict[str, Any]:
    """The `read_answer` for one request. The caller has captured `parts` (`emit` feeds them) and checked the window."""
    user, tool, args = body["user_id"], body["tool"], body["args"]
    connector = TOOLS[tool]
    scopes = declaration["scopes"][next(a["capability"] for a in declaration["actions"] if a["id"] == tool)]

    def answer(outcome: str, result: dict[str, Any] | None = None, stamp: str | None = None) -> dict[str, Any]:
        return {"tool": tool, "outcome": outcome, "connected_at": stamp, "result": result, "parts": list(parts.items)}

    try:
        state, granted, _ = broker.connection_view(user, connector)
        if state is None:
            return answer("not_connected")
        if state != "connected":
            return answer("expired")
        if not set(scopes) <= set(granted):
            return answer("missing_scope")
        stamp = broker.connected_at(user, connector)
        if stamp is None:  # no consent time to stamp the read with: no read
            return answer("expired")
        common: dict[str, Any] = {
            "declaration": declaration, "broker": broker, "transport": transport, "clock": clock, "emit": emit,
        }  # fmt: skip
        wide = {
            **common,
            "artifacts": _NoArtifacts(),
            "owner_of": str,
            "sleep": lambda seconds: None,
            "max_attempts": 1,
        }
        found = _run(tool, args, user, common, wide)
    except NotConnected:
        return answer("not_connected")
    except InsufficientScope:
        return answer("missing_scope")
    except ConnectionExpired:
        return answer("expired")  # the broker emitted connection.expired into `parts`
    except FileTooLarge:
        return answer("too_large")
    except UnsupportedType:
        return answer("unsupported_type")
    except NotPicked:
        return answer("not_found")  # for Drive the same answer for a file that is missing and one not picked
    except (RateLimited, ProviderUnavailable, TokenError) as exc:  # includes a refresh that did not get through
        _log.warning("a workspace read was unavailable (%s)", type(exc).__name__)
        return answer("unavailable")
    except AdapterError as exc:
        if exc.status == 404:
            return answer("not_found")
        _log.warning("a workspace read failed (%s)", type(exc).__name__)
        return answer("unavailable")
    except Exception as exc:  # noqa: BLE001 - the type only: a message could echo mail or a file name
        _log.error("a workspace read broke (%s)", type(exc).__name__)
        return answer("unavailable")
    return answer("ok", found, stamp)


def _run(tool: str, args: Mapping[str, Any], user: str, common: dict[str, Any], wide: dict[str, Any]) -> dict[str, Any]:
    if tool == "search_email":
        return GmailAdapter(**wide).search_messages(user, args["query"], max_results=args.get("max_results", 10))
    if tool == "read_email":
        return GmailAdapter(**wide).read_message(user, args["message_id"])
    if tool == "read_events":
        calendar = CalendarAdapter(**common)
        return calendar.list_window(user, args["start"], args["end"], args.get("max_results", 50))
    if tool == "list_files":
        drive = DriveAdapter(picks=InMemoryPicks(), **wide)
        return drive.search_files(user, args.get("query"), max_results=args.get("max_results", 10))
    return DriveAdapter(picks=InMemoryPicks(), **wide).read_text(user, args["file_id"])
