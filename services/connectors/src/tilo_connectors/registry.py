"""tilo_connectors.registry — connectors declared in config, loaded once, read-only (FR-CON-01).

`load_registry(path)` reads a top-level YAML list of `contracts/connector.schema.json` entries
(PRD 12.1), validates all of them and returns a `ConnectorRegistry`, or raises
`ConnectorConfigError` naming the entry; nothing is partially registered. The registry has no
mutators and hands out copies. Island state comes only from recorded `connection.*` events (PRD 9.5,
HR-1). This module declares and lists connectors; it never sends anything (SEC-03).
"""

from __future__ import annotations

import copy
import os
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import yaml

from ._schema import connector_validator

_MAX_MESSAGE = 500

# ADR-0002 decision 14: `internal` names actions that go through no connector, and `grant_budget` is
# such an action (a budget grant needs a person). No declared connector may take either.
RESERVED_CONNECTOR_ID = "internal"
RESERVED_ACTION_TYPES = frozenset({"grant_budget"})

# PRD 9.5 effects of connection events, in the layout contract's island `state` vocabulary.
_EVENT_STATE = {
    "connection.requested": "requested",
    "connection.consented": "requested",
    "connection.established": "connected",
    "connection.rate_limited": "connected",
    "connection.expiring": "connected",
    "connection.expired": "failed",
    "connection.revoked": "locked",
}
_NO_CONNECTION = "locked"  # no event yet: the island is under cloud cover
_API_LINK = {"conn": "api", "bridge": "road"}  # every connector in this release is an API connector


class ConnectorConfigError(ValueError):
    """The connectors config is unreadable, not a list, or an entry breaks connector.schema.json."""

    def __init__(self, message: str) -> None:
        text = message if len(message) <= _MAX_MESSAGE else message[: _MAX_MESSAGE - 15] + " ...[truncated]"
        super().__init__(text)


class _NoAliasLoader(yaml.SafeLoader):  # no aliases: a few hundred bytes of chained ones expand without bound
    def compose_node(self, parent: Any, index: Any) -> Any:
        if self.check_event(yaml.AliasEvent):
            raise yaml.YAMLError("YAML aliases are not allowed")
        return super().compose_node(parent, index)


def _read_entries(path: str | os.PathLike[str]) -> list[Any]:
    try:
        raw = yaml.load(Path(path).read_text(encoding="utf-8"), Loader=_NoAliasLoader)  # noqa: S506
    except (OSError, UnicodeDecodeError, yaml.YAMLError, RecursionError, ValueError) as exc:
        raise ConnectorConfigError(f"{path}: not a readable UTF-8 YAML file: {exc}") from exc
    if raw is None:
        return []  # an empty file is an empty registry
    if not isinstance(raw, list):
        raise ConnectorConfigError(f"{path}: must be a list of connector entries, got {type(raw).__name__}")
    return raw


def _validated(entries: list[Any]) -> dict[str, dict[str, Any]]:
    validator = connector_validator()
    declared: dict[str, dict[str, Any]] = {}
    for index, entry in enumerate(entries):
        label = entry["id"] if isinstance(entry, dict) and isinstance(entry.get("id"), str) else f"#{index}"
        problems = [
            f"{'/'.join(str(p) for p in err.absolute_path) or '(entry)'}: {err.message}"
            for err in sorted(validator.iter_errors(entry), key=lambda e: [str(p) for p in e.absolute_path])
        ]
        if problems:
            raise ConnectorConfigError(f"connector {label!r}: {'; '.join(problems)}")
        # The schema patterns end in `$`, which also matches before a final newline: refuse it here.
        if any(i != i.strip() for i in [entry["id"], *(a["id"] for a in entry["actions"])]):
            raise ConnectorConfigError(f"connector {label!r}: an id or action id has surrounding whitespace")
        if entry["id"] == RESERVED_CONNECTOR_ID:
            raise ConnectorConfigError(f"connector {entry['id']!r}: id is reserved for actions with no connector")
        for action in entry["actions"]:
            if action["id"] in RESERVED_ACTION_TYPES:
                raise ConnectorConfigError(
                    f"connector {label!r}: action {action['id']!r} is reserved and is not a connector action"
                )
        if entry["id"] in declared:
            raise ConnectorConfigError(f"connector {entry['id']!r}: declared more than once")
        declared[entry["id"]] = copy.deepcopy(entry)
    return declared


class ConnectorRegistry:
    """Read-only: built once by `load_registry`; every getter returns a copy."""

    def __init__(self, declared: Mapping[str, dict[str, Any]]) -> None:
        self._declared = dict(declared)  # insertion order is declaration order

    def ids(self) -> tuple[str, ...]:
        return tuple(self._declared)

    def get(self, connector_id: str) -> dict[str, Any]:
        return copy.deepcopy(self._declared[connector_id])  # KeyError for an unknown id

    def __contains__(self, connector_id: object) -> bool:
        return connector_id in self._declared

    def __len__(self) -> int:
        return len(self._declared)

    def island_link(self, connector_id: str) -> dict[str, str]:
        if connector_id not in self._declared:
            raise KeyError(connector_id)
        return dict(_API_LINK)

    def list_for_world(self, events: Iterable[Mapping[str, Any]] = ()) -> list[dict[str, Any]]:
        """One island per connector, in declaration order. State: the last recorded connection.* event."""
        state: dict[str, str] = {}
        for event in events:
            new = _EVENT_STATE.get(event.get("type", ""))
            connector = (event.get("data") or {}).get("connector")
            if new is not None and connector in self._declared:
                state[connector] = new
        return [
            {
                "id": cid,
                "name": decl["name"],
                "icon": decl["icon"],
                "scopes": copy.deepcopy(decl["scopes"]),
                "state": state.get(cid, _NO_CONNECTION),
            }
            for cid, decl in self._declared.items()
        ]


def load_registry(path: str | os.PathLike[str]) -> ConnectorRegistry:
    return ConnectorRegistry(_validated(_read_entries(path)))
