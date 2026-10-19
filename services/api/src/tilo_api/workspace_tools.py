"""The agents' read tools for the person's own Gmail, Google Calendar and Google Drive (ADR-0048, WT-01 to WT-05).

Five `Tool`s named after the connector actions they run (`search_email`, `read_email`, `read_events`, `list_files`,
`read_file`), each with the contract's `<tool>_args` as its input schema, T1, `external_content` and no side effect,
so the tool loop's own path applies unchanged: the arguments are checked against the schema, the result is neutralised,
screened by the SafetyProvider (a flagged or unreadable verdict drops it) and written to the raw archive. A tool that is
`reads_private` makes its unit private (WT-04): it loses `fetch_url`, and so does a unit that rests on its output.

WT-01: a tool is built only for a live run (a demo is replay), and every call re-checks the world: the user to read for
is the world record's owner, never a model, argument or request; a world with a team share in force reads nothing.
WT-05: one `data.transfer` (direction `in`) per `ok` read, written once the tool loop has archived the call, with fixed
text only: no query, id, subject, sender, file name or title is ever in it. A refused or failed read writes none.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
from collections import defaultdict
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from tilo_harness.tools import ToolCallRecord, ToolResult, args_hash
from tilo_people.directory import Directory
from tilo_people.world_share import in_force
from tilo_providers.media import MediaPart

from tilo_api import deps, events
from tilo_api.meeting_host_rpc import MeetingHostRpc

logger = logging.getLogger("tilo_api.workspace_tools")
_SCHEMA = Path(__file__).resolve().parents[4] / "contracts" / "meeting_host_rpc.schema.json"
MAX_WINDOW = timedelta(days=31)
_CHAIN_MAX = 25  # person records read to judge one share
CONNECTOR_OF = {
    "search_email": "gmail", "read_email": "gmail", "read_events": "google_calendar",
    "list_files": "google_drive", "read_file": "google_drive",
}  # fmt: skip
READS_OF = {  # a brief source {kind: connector, ref} gives a unit its connector's reads
    "gmail": ("search_email", "read_email"), "google_calendar": ("read_events",),
    "google_drive": ("list_files", "read_file"),
}  # fmt: skip
DESCRIPTIONS = {
    "search_email": "Search the person's own Gmail (Gmail search words): at most 10 message summaries, newest first.",
    "read_email": "Read one of the person's Gmail messages by the id search_email gave: headers and plain text.",
    "read_events": "List the events on the person's own Google Calendar between two dates and times (at most 31 days).",
    "list_files": "List the Google Drive files the person gave Tilo (picked files and files Tilo saved), newest first.",
    "read_file": "Read one Drive file by the id list_files gave: a Google Doc, Sheet or Slides file, text file or PDF.",
}  # fmt: skip
LABELS = {  # WT-05: a fixed item label per tool
    "search_email": "Mail search", "read_email": "1 email", "read_events": "Calendar events",
    "list_files": "Drive file list", "read_file": "1 Drive file",
}  # fmt: skip
SUMMARIES = {  # WT-05: a fixed summary per connector
    "gmail": "An agent read from Gmail.", "google_calendar": "An agent read from Google Calendar.",
    "google_drive": "An agent read from Google Drive.",
}  # fmt: skip
_WHERE = {"gmail": ("Gmail", "Read mail"), "google_calendar": ("Google Calendar", "Read calendar"),
          "google_drive": ("Google Drive", "Read Drive")}  # fmt: skip
SHARED = (
    "Nothing was read: the person's own mail, calendar and files are read only in their own worlds, never in a world "
    "shared with a team."
)
WINDOW = "Nothing was read: the dates must be a window that ends after it starts and spans at most 31 days."
UNAVAILABLE = "Nothing was read: Google did not answer now. Try again later."
NOT_READABLE = "That PDF could not be read as a document."
_FIXED = {
    "not_found": "Nothing was found with that id, or it is not one the person gave Tilo.",
    "too_large": "That PDF is over 4 MiB, so it was not read.",
    "unsupported_type": "That file type cannot be read. Only Google Docs, Sheets, Slides, text files and PDFs can be.",
    "unavailable": UNAVAILABLE,
}  # fmt: skip


def note(connector: str, outcome: str) -> str:
    """The fixed plain line a refused or failed read gives the unit (WT-03): no text of the person's or Google's."""
    name, toggle = _WHERE[connector]
    if outcome == "not_connected":
        return f"{name} is not connected. The person can connect it under Connectors: {toggle}."
    if outcome == "missing_scope":
        return f"{name} is connected without permission to read. The person can allow it under Connectors: {toggle}."
    if outcome == "expired":
        return f"The {name} connection has expired. The person must connect it again under Connectors."
    return _FIXED.get(outcome, UNAVAILABLE)


def window_ok(start: str, end: str) -> bool:
    """WT-02: an RFC 3339 window with offsets, ending after it starts, of at most 31 days."""
    try:
        first, last = datetime.fromisoformat(start), datetime.fromisoformat(end)
        first.astimezone(UTC), last.astimezone(UTC)  # OverflowError for year 9999 with an offset, as connectors refuses
        return (
            first.utcoffset() is not None and last.utcoffset() is not None and timedelta(0) < last - first <= MAX_WINDOW
        )
    except (TypeError, ValueError, OverflowError):
        return False


def _chain(persons: Any, owner: str, teams: set[Any]) -> list[Any] | None:
    """The owner's person record and, transitively, those of whoever assigned them to one of `teams` (the only records
    PE-31's membership check reads), at most `_CHAIN_MAX` of them; None when more are needed."""
    todo, seen, found = [owner], set[str](), []
    while todo:
        uid = todo.pop()
        if uid in seen:
            continue
        if len(seen) >= _CHAIN_MAX:
            return None
        seen.add(uid)
        stored = persons.get(deps.ORG_ID, uid)
        if stored is None:
            continue
        found.append(stored.record)
        for m in stored.record.get("memberships") or []:
            if isinstance(m, Mapping) and m.get("team") in teams and isinstance(m.get("assigned_by"), Mapping):
                todo.append(str(m["assigned_by"].get("by")))
    return found


def team_share_in_force(
    world_id: str,
    owner: str,
    *,
    stores: Callable[[], Any] | None = None,
    clock: Callable[[], str] = events.now,
    configured: Callable[[], bool] = lambda: bool(os.environ.get("TILO_PEOPLE_STORE")),
) -> bool:
    """ADR-0040: is a team share of this world in force now? True also when that cannot be told (fail closed), except
    that with no people store configured at all no share can exist, so none is in force."""
    try:
        people = (stores or deps.get_people_stores)()
        shares = people.world_shares.list(deps.ORG_ID, "world_id", world_id)
        if not shares:
            return False
        teams = {s.record.get("team") for s in shares}
        records = _chain(people.persons, owner, teams)  # the owner and who assigned them to those teams, not the org
        if records is None:
            return True  # a chain longer than the bound: cannot be told, so shared
        return any(in_force(s.record, owner, Directory.of(records), clock()) for s in shares)
    except HTTPException:
        return configured()
    except Exception as exc:  # noqa: BLE001 - the type only
        logger.warning("a team share could not be checked (%s)", type(exc).__name__)
        return True


class WorkspaceAccess:
    """What a live run needs to read the person's own account: the connectors client and the team-share check."""

    def __init__(
        self, rpc: Callable[[], MeetingHostRpc], shared: Callable[[str, str], bool] = team_share_in_force
    ) -> None:
        self._rpc, self.shared = rpc, shared

    def client(self) -> MeetingHostRpc | None:
        try:
            return self._rpc()
        except Exception:  # noqa: BLE001 - not configured, or backing off after a failed build
            return None


def _schema(tool: str) -> Mapping[str, Any]:
    return dict(json.loads(_SCHEMA.read_text(encoding="utf-8"))["$defs"][f"{tool}_args"])


class WorkspaceReadTool:
    tier, external_content, side_effect = "T1", True, False
    reads_private = True  # WT-04

    def __init__(self, name: str, unit: WorkspaceUnit) -> None:
        self.name, self.description, self._unit = name, DESCRIPTIONS[name], unit
        self.input_schema = _schema(name)

    def run(self, args: Mapping[str, Any]) -> ToolResult:
        return self._unit.read(self.name, dict(args))


class WorkspaceUnit:
    """The read tools of one unit of one run, and the events they owe (WT-05): built per unit like the web tools."""

    def __init__(
        self,
        run: Any,
        access: WorkspaceAccess,
        unit: Mapping[str, Any],
        agent: str,
        building: str,
        refs: Mapping[str, str] | None = None,
    ) -> None:
        self.run, self.access, self.unit, self.agent, self.building = run, access, unit, agent, building
        self._refs = refs if refs is not None else {}  # the tool loop's call id -> the archive record's `<run>/<seq>`
        self._pending: dict[str, list[tuple[str, str, str, int]]] = defaultdict(list)

    def tools(self, names: tuple[str, ...] = tuple(CONNECTOR_OF)) -> list[WorkspaceReadTool]:
        return [WorkspaceReadTool(name, self) for name in names]

    def owner(self) -> str | None:
        """WT-01, at every call: the world record's owner, and only while no team share of the world is in force."""
        world = self.run.store.load_world(self.run.world_id)
        owner = getattr(world, "owner", None)
        if not isinstance(owner, str) or self.access.shared(self.run.world_id, owner):
            return None
        return owner

    def read(self, tool: str, args: dict[str, Any]) -> ToolResult:
        connector = CONNECTOR_OF[tool]
        if (owner := self.owner()) is None:
            return ToolResult(SHARED)
        if tool == "read_events" and not window_ok(args["start"], args["end"]):  # WT-02, before the call
            return ToolResult(WINDOW)
        client = self.access.client()
        if client is None:
            return ToolResult(UNAVAILABLE)
        started = time.monotonic()
        try:
            answer = client.read(owner, tool, args)
        except Exception as exc:  # noqa: BLE001 - HostRpcError: a fixed kind, never a body
            logger.warning("a workspace read failed (%s)", type(exc).__name__)
            return ToolResult(UNAVAILABLE)
        self._deliver(answer.parts, owner)
        if answer.outcome != "ok" or answer.result is None or answer.connected_at is None:
            return ToolResult(note(connector, answer.outcome))
        result = answer.result.model_dump(mode="json")
        latency = max(0, int((time.monotonic() - started) * 1000))
        self._pending[args_hash(tool, args)].append((tool, owner, answer.connected_at, latency))  # it happened (WT-05)
        parts: tuple[MediaPart, ...] = ()
        if tool == "read_file" and result["pdf_b64"] is not None:
            try:
                parts = (MediaPart(mime_type="application/pdf", data=base64.b64decode(result.pop("pdf_b64"))),)
            except Exception as exc:  # noqa: BLE001 - encrypted, too many pages, not a PDF
                logger.warning("a Drive PDF was not readable (%s)", type(exc).__name__)
                return ToolResult(NOT_READABLE)
            result["pdf"] = "attached as a document"
        return ToolResult(json.dumps(result, ensure_ascii=False, separators=(",", ":")), parts=parts)

    def _deliver(self, parts: list[Any], user_id: str) -> None:
        """Connection parts of this call (connection.expired, .rate_limited) reach the run like the host's do."""
        sink = getattr(self.run, "_part_sink", None)
        for part in parts:
            if sink is not None and getattr(part, "user_id", None) == user_id:
                try:
                    sink({"type": part.type, "authz": None, "data": {"connector": part.connector}, "user_id": user_id})
                except Exception as exc:  # noqa: BLE001 - a sink error never fails the read
                    logger.warning("a connection part was not handled (%s)", type(exc).__name__)

    def on_call(self, record: ToolCallRecord) -> None:
        """WT-05: the tool loop has archived the call; write the read's one `data.transfer`. Never raises."""
        pending = self._pending.get(record.args_hash)
        if not pending:
            return
        tool, owner, connected_at, latency = pending.pop(0)
        trace = dict.fromkeys(("model_role", "profile", "tokens_in", "tokens_out"))
        trace |= {"tool": tool, "latency_ms": latency, "archive_ref": self._refs.get(record.archive_ref or "")}
        data = {"connector": CONNECTOR_OF[tool], "action_type": tool, "direction": "in", "artifact": None,
                "outbox_id": None, "risk_tier": "T1"}  # fmt: skip
        try:
            self.run.put(
                "data.transfer", self.agent, self.building, SUMMARIES[CONNECTOR_OF[tool]], data,
                district=self.unit["district"], item={"kind": "scroll", "artifact_id": None, "label": LABELS[tool]},
                authz={"by": "person", "ref": owner, "at": connected_at}, trace=trace, check_pause=False,
            )  # fmt: skip
        except Exception as exc:  # noqa: BLE001 - the archive still holds the call
            logger.warning("a workspace read was not recorded (%s)", type(exc).__name__)
