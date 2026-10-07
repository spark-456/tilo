"""CL-LIVE-1: the real Google connectors for a local live run, READ-ONLY by construction (API_CL_LIVE_1.md).

`real_adapters` builds the Gmail, Drive and Calendar adapters on an injected broker and transport and wraps each in
a surface of reads only. The one write door of every adapter refuses until CL-LIVE-2, before the broker, the transport
or the grant is touched. It refuses to build at all unless the user's live switch is on, outside CI and Cloud Run, in
a live (not replay) run with real providers, on a live transport, with every scope inside the pinned minimum and a
token in hand. Nothing falls back to a mock. Messages are fixed text: no token, config value or mail text.
No logging; what the adapters read is returned to the caller and written nowhere here.
"""

from __future__ import annotations

import functools
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from os import environ as process_environ
from typing import Any

from ._time import format_ts
from .adapters import CalendarAdapter, DriveAdapter, GmailAdapter, InMemoryPicks, SideEffectRefused, Transport
from .adapters._google import has_token
from .recording import RecordingTransport, ReplayTransport
from .registry import ConnectorRegistry
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
_REFUSALS = {
    "live_not_enabled": "real connectors need the live switch LIVE=1 set by the user",
    "ci_refused": "real connectors are never used in CI",
    "deployed_refused": "real connectors are never used on Cloud Run",
    "not_live_mode": "real connectors need a live run",
    "fake_providers": "real connectors cannot be combined with fake providers",
    "replay_transport": "real connectors need a live transport, not a recorded one",
    "scope_widened": "a connector declares a scope wider than the read-only minimum",
    "no_token": "a Google connector has no usable token; connect it again",
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

    def __init__(self, connector_id: str, inner: Any = None) -> None:
        self.id, self._inner = connector_id, inner

    @property
    def sent(self) -> tuple[()]:
        return ()

    def execute_side_effect(self, entry: Any, grant: Any) -> dict[str, Any]:
        raise RealWritesDisabled


class _NoArtifacts:  # nothing is saved, so nothing is looked up
    def get(self, artifact_id: str, version: int) -> Mapping[str, Any]:
        raise SideEffectRefused(_WRITES_OFF)


def _delegate(adapter_class: type, name: str) -> Callable[..., Any]:
    @functools.wraps(getattr(adapter_class, name))
    def call(self: _ReadOnly, *args: Any, **kwargs: Any) -> Any:
        return getattr(self._inner, name)(*args, **kwargs)

    return call


def _read_only(connector_id: str, inner: Any) -> _ReadOnly:
    """A wrapper with exactly the pinned reads: no watch, no send, nothing reaches the inner write door."""
    cls = type(
        f"ReadOnly_{connector_id}", (_ReadOnly,), {n: _delegate(type(inner), n) for n in READ_METHODS[connector_id]}
    )
    return cls(connector_id, inner)  # type: ignore[no-any-return]


def real_connector_plan(registry: ConnectorRegistry) -> list[dict[str, Any]]:
    return [{"connector": c, "scopes": s, "mode": "read_only"} for c, s in REAL_SCOPES.items() if c in registry]


def _refuse_unless_allowed(
    registry: ConnectorRegistry, transport: Transport, environ: Mapping[str, str], mode: str, providers_fake: bool
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
) -> dict[str, Any]:
    """One adapter per connector in `registry`, the same shape as `dev_run.mock_adapters()`; reads only."""
    _refuse_unless_allowed(registry, transport, process_environ if environ is None else environ, mode, providers_fake)
    plan = real_connector_plan(registry)
    for row in plan:  # fail closed: a token for the first pinned scope of each, no Google request
        if not has_token(broker, user_id, row["connector"], row["scopes"][0]):
            raise RealConnectorsRefused("no_token")
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
        declaration["scopes"] = {c: s for c, s in declaration["scopes"].items() if c != "send"}
        extra: dict[str, Any] = {"declaration": declaration, **common}
        if connector_id != "google_calendar":
            extra |= {"artifacts": _NoArtifacts(), "owner_of": str, "sleep": sleep or time.sleep}
        if connector_id == "google_drive":
            extra["picks"] = picks if picks is not None else InMemoryPicks()
        out[connector_id] = _read_only(connector_id, _ADAPTERS[connector_id](**extra))
    return out
