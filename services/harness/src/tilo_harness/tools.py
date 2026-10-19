"""Tools a unit's model may ask for (LW-07; PRD 8.2 `tools_allowed`, SEC-05, 16.3 item 1).

A `Tool` is a named, schema-checked capability behind one interface: `web_search` and `fetch_url` first (real
providers plug in later, LW-05 and LW-08); a tool that acts in the world (`side_effect`) never runs from here, it goes
to the outbox gate (`ToolUnitRunner`'s `effect_gate`). Nothing here touches the network: the two registered tools are
FAKES that return the same canned text for the same arguments, so dev and CI never leave the machine (EFF-01).

Also here: the small interfaces the runner needs (`ToolArchive`: the run's raw archive; `ToolCache`: one run's result
cache keyed by tool + arguments) with in-memory versions, and the record of one call (`ToolCallRecord`) that becomes
one Trace row (`tool`, `latency_ms`, `archive_ref`) once the contract has an event type for it.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol, runtime_checkable

from tilo_providers.media import MediaPart

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

Outcome = Literal["ok", "cached", "dropped", "refused", "error", "queued"]


@dataclass(frozen=True)
class ToolResult:
    content: str  # what the tool returned; for an external-content tool this is UNTRUSTED text
    credits: float = 0.0  # what this call cost
    parts: tuple[MediaPart, ...] = ()  # native files; screened before a model sees them


@runtime_checkable
class Tool(Protocol):
    name: str
    description: str
    input_schema: Mapping[str, Any]  # JSON Schema of the arguments
    tier: str  # risk tier of the action: T1 for a read
    external_content: bool  # the result is text from outside Tilo (SEC-05: reading it removes side-effect tools)
    side_effect: bool  # acts in the world: only ever through the outbox and the policy engine, never from `run`

    def run(self, args: Mapping[str, Any]) -> ToolResult: ...


class ToolRegistry:
    """The tools that exist, by name. A unit sees only the part its skill, its role and SEC-05 allow."""

    def __init__(self, tools: Iterable[Tool] = ()) -> None:
        self._tools: dict[str, Tool] = {}
        for tool in tools:
            if tool.name in self._tools:
                raise ValueError(f"duplicate tool name {tool.name!r}")
            self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> frozenset[str]:
        return frozenset(self._tools)

    def __bool__(self) -> bool:
        return bool(self._tools)

    @staticmethod
    def is_side_effect(tool: Tool) -> bool:
        """The one place that decides it: a tool that declares a side effect, or any tool above T1 (a read)."""
        return bool(tool.side_effect) or tool.tier != "T1"

    @staticmethod
    def is_private(tool: Tool) -> bool:
        """WT-04 (ADR-0048): does its result hold the person's own private data (mail, calendar, Drive)? A unit that
        called one, and any unit whose input rests on that unit's output, can no longer send anything out by the web."""
        return bool(getattr(tool, "reads_private", False))

    @staticmethod
    def is_egress(tool: Tool) -> bool:
        """WT-04: does the tool's call carry text to a server outside Tilo (a fetched address)? A search query goes
        only to the search provider and is not egress."""
        return bool(getattr(tool, "web_egress", False))

    @classmethod
    def is_external(cls, tool: Tool) -> bool:
        """Does reading its result make the unit an outside-content reader (SEC-05)? Every read tool does, whatever
        it declares (files, mail and pages are all untrusted); a side-effect tool says for itself."""
        return bool(tool.external_content) or not cls.is_side_effect(tool)


def args_hash(tool: str, args: Mapping[str, Any]) -> str:
    """The cache key and the trace id of a call: sha256 of the tool name and its canonical JSON arguments."""
    canonical = json.dumps({"tool": tool, "args": args}, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def archive_id(payload: Mapping[str, Any]) -> str:
    """A deterministic ULID-shaped id for an archived record (`provenance_ids` are ULIDs, PRD 13.3)."""
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    number = int.from_bytes(hashlib.sha256(raw.encode("utf-8")).digest()[:16], "big")
    chars = [_CROCKFORD[(number >> (5 * i)) & 31] for i in range(25, -1, -1)]
    chars[0] = _CROCKFORD[(number >> 125) & 7]  # a ULID's first character is 0-7
    return "".join(chars)


class ToolArchive(Protocol):
    def record(self, payload: Mapping[str, Any]) -> str:
        """Appends one `tool_call` record to the run's raw archive and returns its id (a ULID)."""
        ...


class MemoryToolArchive:
    """An in-memory stand-in for the run's raw archive (tests, dev)."""

    def __init__(self) -> None:
        self.records: dict[str, Mapping[str, Any]] = {}

    def record(self, payload: Mapping[str, Any]) -> str:
        ref = archive_id(payload)
        self.records[ref] = dict(payload)
        return ref


@dataclass(frozen=True)
class CachedCall:
    """What a repeated call is served from: the screened, neutralised text (None if dropped) and its archive id."""

    text: str | None
    outcome: Outcome
    archive_ref: str | None
    parts: tuple[MediaPart, ...] = ()


class ToolCache(Protocol):
    def get(self, key: str) -> CachedCall | None: ...

    def put(self, key: str, value: CachedCall) -> None: ...


class MemoryToolCache:
    """One run's tool-result cache. Scope it to one run: it is never shared between worlds."""

    def __init__(self) -> None:
        self._entries: dict[str, CachedCall] = {}

    def get(self, key: str) -> CachedCall | None:
        return self._entries.get(key)

    def put(self, key: str, value: CachedCall) -> None:
        self._entries[key] = value


@dataclass(frozen=True)
class ToolCallRecord:
    """One call, one Trace row: `tool`, `latency_ms` and `archive_ref` are the Trace columns (PRD 9.3 `trace`)."""

    unit_id: str
    step: int
    tool: str
    args_hash: str
    outcome: Outcome
    credits: float
    latency_ms: int
    archive_ref: str | None
    external_content: bool = False
    note: str = ""


class FakeWebSearch:
    """FAKE `web_search` (LW-05 plugs the real provider in): deterministic canned results, no network."""

    name = "web_search"
    description = "Search the web and return a short list of results (title, address, snippet)."
    input_schema: Mapping[str, Any] = {
        "type": "object",
        "properties": {"query": {"type": "string", "minLength": 1, "maxLength": 300}},
        "required": ["query"],
        "additionalProperties": False,
    }
    tier = "T1"
    external_content = True
    side_effect = False

    def __init__(self, credits: float = 0.0) -> None:
        self._credits = credits
        self.calls: list[Mapping[str, Any]] = []

    def run(self, args: Mapping[str, Any]) -> ToolResult:
        self.calls.append(dict(args))
        query = str(args["query"])
        slug = hashlib.sha256(query.encode("utf-8")).hexdigest()[:8]
        lines = [
            f"{n}. Result {n} for '{query}' - https://example.test/{slug}/{n} - canned snippet {n}" for n in (1, 2, 3)
        ]
        return ToolResult("\n".join(lines), self._credits)


class FakeFetchUrl:
    """FAKE `fetch_url` (LW-08 plugs the real fetch in): a canned page for the address, no network."""

    name = "fetch_url"
    web_egress = True  # WT-04: the address a model chooses can carry text out
    description = "Fetch one web page and return its readable text."
    input_schema: Mapping[str, Any] = {
        "type": "object",
        "properties": {"url": {"type": "string", "minLength": 1, "maxLength": 500}},
        "required": ["url"],
        "additionalProperties": False,
    }
    tier = "T1"
    external_content = True
    side_effect = False

    def __init__(self, credits: float = 0.0) -> None:
        self._credits = credits
        self.calls: list[Mapping[str, Any]] = []

    def run(self, args: Mapping[str, Any]) -> ToolResult:
        self.calls.append(dict(args))
        url = str(args["url"])
        slug = hashlib.sha256(url.encode("utf-8")).hexdigest()[:8]
        return ToolResult(f"Canned page {slug} for {url}. It has three paragraphs of plain text.", self._credits)


def fake_tool_registry(*, credits: float = 0.0) -> ToolRegistry:
    """The registry dev and CI use until the real search and fetch land."""
    return ToolRegistry([FakeWebSearch(credits), FakeFetchUrl(credits)])


def trace_fields(record: ToolCallRecord) -> dict[str, Any]:
    """The one mapping from a call record to the envelope `trace` columns (PRD 9.3). The `tool.called` event that
    carries it comes with the contract change (ADR-0029 amendment); nothing else may build these fields."""
    return {
        "model_role": None,
        "profile": None,
        "tokens_in": None,
        "tokens_out": None,
        "tool": record.tool,
        "latency_ms": record.latency_ms,
        "archive_ref": record.archive_ref,
    }
