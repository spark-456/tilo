"""CL-LIVE-1: the real Google connectors for a local live run, READ-ONLY by construction (API_CL_LIVE_1.md).

`real_adapters` builds the Gmail, Drive and Calendar adapters on an injected broker and transport and wraps each in
a surface of reads only. The one write door of every adapter refuses, before the broker, the transport or the grant is
touched, unless the caller passes `allow_writes` (CL-LIVE-2, API_CL_LIVE_2.md): then the Gmail draft and Drive save
doors (and Gmail send with `allow_send`) open only for an entry whose exact payload a person approved at a terminal.
It refuses to build at all unless the user's live switch is on, outside CI and Cloud Run, in a live (not replay) run
with real providers, on a live transport, with every scope inside the pinned minimum and a token in hand. Nothing
falls back to a mock. Messages are fixed text: no token, config value or mail text. No logging; what the
adapters read is returned to the caller and written nowhere here.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime
from os import environ as process_environ
from typing import Any

from ._time import format_ts
from .adapters import CalendarAdapter, DriveAdapter, GmailAdapter, InMemoryPicks, SideEffectRefused, Transport
from .adapters._google import GoogleAdapter, has_token
from .real_writes import SEND_SCOPE, WriteFlags, WriteGate, write_plan
from .recording import RecordingTransport, ReplayTransport
from .registry import ConnectorRegistry
from .side_effects import SIDE_EFFECT_METHOD_NAMES
from .tokens import TokenBroker

_AUTH = "https://www.googleapis.com/auth/"
REAL_SCOPES: Mapping[str, tuple[str, ...]] = {  # the minimum config/connectors.yaml already declares; never widened
    "gmail": (_AUTH + "gmail.readonly", _AUTH + "gmail.compose"),
    "google_drive": (_AUTH + "drive.file",),
    "google_calendar": (_AUTH + "calendar.readonly",),
}
READ_METHODS: Mapping[str, frozenset[str]] = {  # the public methods of the Google adapters, besides the write door
    "gmail": frozenset(
        {"list_threads", "search_threads", "get_thread", "get_message", "list_labels", "recent_inbox", "list_history"}
    ),
    "google_drive": frozenset({"get_metadata", "list_folder", "download"}),
    "google_calendar": frozenset({"list_events"}),
}
_ADAPTERS: Mapping[str, type] = {
    "gmail": GmailAdapter,
    "google_drive": DriveAdapter,
    "google_calendar": CalendarAdapter,
}
_WRITES_OFF = "writes are not enabled until CL-LIVE-2"
_DOOR = next(n for n in sorted(SIDE_EFFECT_METHOD_NAMES) if n.startswith("execute"))  # the one write door (SEC-03)
_REFUSALS = {
    "live_not_enabled": "real connectors need the live switch LIVE=1 set by the user",
    "ci_refused": "real connectors are never used in CI",
    "deployed_refused": "real connectors are never used on Cloud Run",
    "not_live_mode": "real connectors need a live run",
    "fake_providers": "real connectors cannot be combined with fake providers",
    "replay_transport": "real connectors need a live transport, not a recorded one",
    "scope_widened": "a connector declares a scope wider than the read-only minimum",
    "no_token": "a Google connector has no usable token; connect it again",
    "send_needs_writes": "sending needs writes to be enabled too",
}


class RealConnectorsRefused(Exception):
    """The real connectors were not built; `.code` says why and the text is fixed."""

    def __init__(self, code: str) -> None:
        super().__init__(_REFUSALS[code])
        self.code = code


class RealWritesDisabled(SideEffectRefused):
    """Final for the outbox: the entry fails and nothing is sent."""

    def __init__(self) -> None:
        super().__init__(_WRITES_OFF)


class _ReadOnly:
    """Common part of every adapter returned: an id, an empty `sent` and the refusing write door."""

    real_read_only = True  # the mark `is_real_read_only` looks for; the run never trusts a factory's say-so

    def __init__(self, connector_id: str) -> None:
        self.id = connector_id

    @property
    def sent(self) -> tuple[str, ...]:
        return ()

    def execute_side_effect(self, entry: Any, grant: Any) -> dict[str, Any]:
        raise RealWritesDisabled


class _NoArtifacts:  # nothing is saved, so nothing is looked up
    def get(self, artifact_id: str, version: int) -> Mapping[str, Any]:
        raise SideEffectRefused(_WRITES_OFF)


def _delegate(inner: Any, name: str) -> Callable[..., Any]:
    read = getattr(inner, name)  # held only in this closure: no attribute of the wrapper leads to the adapter

    def call(self: _ReadOnly, *args: Any, **kwargs: Any) -> Any:
        return read(*args, **kwargs)

    call.__name__, call.__doc__ = name, read.__doc__
    return call


def _read_only(connector_id: str, inner: Any) -> _ReadOnly:
    """A wrapper with exactly the pinned reads: no watch, no send, nothing reaches the inner write door."""
    methods = {n: _delegate(inner, n) for n in READ_METHODS[connector_id]}
    return type(f"ReadOnly_{connector_id}", (_ReadOnly,), methods)(connector_id)  # type: ignore[no-any-return]


class _Served:
    """The one item the write door is serving right now: the content the person approved, nothing else."""

    def __init__(self) -> None:
        self._ref: tuple[Any, Any] | None = None
        self._item: Mapping[str, Any] = {}

    @contextmanager
    def serving(self, ref: Mapping[str, Any], item: Mapping[str, Any]) -> Iterator[None]:
        self._ref, self._item = (ref["artifact_id"], ref["version"]), item
        try:
            yield
        finally:
            self._ref, self._item = None, {}

    def get(self, artifact_id: str, version: int) -> Mapping[str, Any]:
        if self._ref != (artifact_id, version):
            raise SideEffectRefused(_WRITES_OFF)
        return deepcopy(self._item)


def _gated(connector_id: str, inner: Any, source: _Served, gate: WriteGate) -> _ReadOnly:
    """Reads as in `_read_only`; the write door opens only for a payload `gate` holds a typed approval for. The inner
    adapter is held in closures only, and is handed the very content that was approved."""
    door = getattr(inner, _DOOR)

    class Gated(_ReadOnly):
        real_read_only = False
        real_write_gated = True
        _write_gate = gate

        @property
        def sent(self) -> tuple[str, ...]:  # the actions that went out, no content
            return tuple(a for a in gate.executed if a.startswith(connector_id + "."))

        def execute_side_effect(self, entry: Any, grant: Any) -> dict[str, Any]:
            GoogleAdapter._check_grant(entry, grant)  # first: a call with no real grant must not spend an approval
            with gate.lock:  # one write at a time: an approved entry makes at most one request
                auth = gate.authorise(entry, connector_id)
                if auth.done is not None:
                    return auth.done
                with source.serving(auth.entry["item"], auth.content):
                    result: dict[str, Any] = door(auth.entry, grant)
                gate.complete(entry, connector_id, result)
                return result

    for name in READ_METHODS[connector_id]:
        setattr(Gated, name, _delegate(inner, name))
    return Gated(connector_id)


def is_real_write_gated(adapters: object) -> bool:
    """True only for a dict whose Gmail and Drive are gated wrappers made here and whose Calendar is read-only."""
    return isinstance(adapters, dict) and all(
        getattr(adapters.get(c), "id", None) == c
        and getattr(adapters.get(c), "real_write_gated" if c != "google_calendar" else "real_read_only", False) is True
        for c in REAL_SCOPES
    )


def write_gate_of(adapters: object) -> WriteGate | None:
    gate = getattr(adapters.get("gmail"), "_write_gate", None) if isinstance(adapters, dict) else None
    return gate if isinstance(gate, WriteGate) else None


def real_write_plan(
    registry: ConnectorRegistry, flags: WriteFlags
) -> tuple[list[dict[str, Any]], list[tuple[str, str]]]:
    return write_plan(real_connector_plan(registry), flags)


def is_real_read_only(adapters: object) -> bool:
    """True only for a dict whose Google ids are read-only wrappers made here (the run checks a factory's result)."""
    return isinstance(adapters, dict) and all(
        getattr(adapters.get(c), "real_read_only", False) is True and getattr(adapters.get(c), "id", None) == c
        for c in REAL_SCOPES
    )


def real_connector_plan(registry: ConnectorRegistry) -> list[dict[str, Any]]:
    return [{"connector": c, "scopes": s, "mode": "read_only"} for c, s in REAL_SCOPES.items() if c in registry]


def _refuse_unless_allowed(  # noqa: PLR0913
    registry: ConnectorRegistry,
    transport: Transport,
    environ: Mapping[str, str],
    mode: str,
    providers_fake: bool,
    allow_send: bool = False,
) -> None:
    if environ.get("LIVE") != "1":
        raise RealConnectorsRefused("live_not_enabled")
    if any(m.get("CI") or m.get("GITHUB_ACTIONS") for m in (environ, process_environ)):
        raise RealConnectorsRefused("ci_refused")
    if any(k in m for m in (environ, process_environ) for k in ("K_SERVICE", "CLOUD_RUN_JOB")):
        raise RealConnectorsRefused("deployed_refused")
    if mode != "live":
        raise RealConnectorsRefused("not_live_mode")
    if providers_fake:
        raise RealConnectorsRefused("fake_providers")
    if isinstance(transport, ReplayTransport | RecordingTransport):
        raise RealConnectorsRefused("replay_transport")
    for connector_id in (c for c in REAL_SCOPES if c in registry):
        for capability, scopes in registry.get(connector_id)["scopes"].items():
            if capability == "send" and allow_send and connector_id == "gmail" and tuple(scopes) != (SEND_SCOPE,):
                raise RealConnectorsRefused("scope_widened")  # the one send scope, nothing wider
            if capability != "send" and not set(scopes) <= set(REAL_SCOPES[connector_id]):
                raise RealConnectorsRefused("scope_widened")


def real_adapters(  # noqa: PLR0913
    broker: TokenBroker,
    registry: ConnectorRegistry,
    transport: Transport,
    *,
    user_id: str,
    environ: Mapping[str, str] | None = None,
    mode: str = "live",
    providers_fake: bool = False,
    picks: InMemoryPicks | None = None,
    clock: Callable[[], str] | None = None,
    emit: Callable[[dict[str, Any]], None] | None = None,
    sleep: Callable[[float], None] | None = None,
    allow_writes: bool = False,  # CL-LIVE-2: Gmail drafts and Drive saves, each only after a typed terminal approval
    allow_send: bool = False,  # CL-LIVE-2: also Gmail send (needs allow_writes), the same gate
) -> dict[str, Any]:
    """One adapter per connector in `registry`, the same shape as `dev_run.mock_adapters()`; reads only, unless
    `allow_writes`. Then Gmail and Drive are gated wrappers (`write_gate_of` gives the gate the run binds and the
    terminal person approves with), and the Google tokens for the write scopes must exist too."""
    _refuse_unless_allowed(
        registry, transport, process_environ if environ is None else environ, mode, providers_fake, allow_send
    )
    if allow_send and not allow_writes:
        raise RealConnectorsRefused("send_needs_writes")
    flags = WriteFlags(allow_writes, allow_send)
    plan = real_connector_plan(registry)
    wanted = [(row["connector"], row["scopes"][0]) for row in plan]
    if allow_writes:
        wanted += [("gmail", REAL_SCOPES["gmail"][1])] + ([("gmail", SEND_SCOPE)] if allow_send else [])
    for connector_id, scope in wanted:  # fail closed: a token for each scope the run may use, no Google request
        if connector_id in registry and not has_token(broker, user_id, connector_id, scope):
            raise RealConnectorsRefused("no_token")
    gate, source = WriteGate(flags), _Served()
    common: dict[str, Any] = {
        "broker": broker,
        "transport": transport,
        "clock": clock or (lambda: format_ts(datetime.now(UTC))),
        "emit": emit or (lambda _event: None),
    }
    out: dict[str, Any] = {}
    for connector_id in registry.ids():
        if connector_id not in REAL_SCOPES:
            out[connector_id] = _ReadOnly(connector_id)  # a refusing stub: the map keeps the mock map's shape
            continue
        declaration = registry.get(connector_id)
        keep_send = allow_send and connector_id == "gmail"
        declaration["scopes"] = {c: s for c, s in declaration["scopes"].items() if c != "send" or keep_send}
        extra: dict[str, Any] = {"declaration": declaration, **common}
        gated = allow_writes and connector_id in ("gmail", "google_drive")
        if connector_id != "google_calendar":
            extra |= {"artifacts": source if gated else _NoArtifacts(), "sleep": sleep or time.sleep,
                      "owner_of": (lambda _world: user_id) if gated else str}  # fmt: skip
        if connector_id == "google_drive":
            extra["picks"] = picks if picks is not None else InMemoryPicks()
        inner = _ADAPTERS[connector_id](**extra)
        out[connector_id] = _gated(connector_id, inner, source, gate) if gated else _read_only(connector_id, inner)
    return out
