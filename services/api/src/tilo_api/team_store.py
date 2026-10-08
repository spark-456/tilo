"""The team's stored settings (FR-TEAM-02, FR-TEAM-04, FR-ACC-01; issues #621, #629).

One team per install: the roles map (person id -> Park role, BQ-DSN-01), personal spend limits, the five switches,
each tool's access level, which person each of the team's worlds belongs to, and pending invites. Every write is a
compare-and-set on `version`: a route reads, applies a `team_rules` change to that snapshot, and writes only if no one
wrote in between; otherwise it reads again and re-checks the change on the fresh state (two Owners demoting each other
from one stale snapshot leave exactly one). In memory by name or in dev mode by default (seeded with the dev owner);
Firestore only for `TILO_TEAM_STORE=firestore` plus `TILO_FIRESTORE_PROJECT`, one document in a transaction. Anything
else is 503 `not_configured`: no team, so no route and no engine check reads one (BQ-TEAMRT-2).
"""

from __future__ import annotations

import dataclasses
import functools
import logging
import os
import re
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from fastapi import HTTPException

from tilo_api.team_rules import MUST_ASK_KEYS, ROLES, RoleChangeRefused, change_role, load_switches

logger = logging.getLogger("tilo_api.team_store")
LEVELS = ("off", "read", "draft", "act")
_PROJECT = re.compile(r"[a-z][a-z0-9-]{4,28}[a-z0-9]")


def _switch_defaults() -> dict[str, bool]:
    return {key: s.default for key, s in load_switches().items()}


@dataclass(frozen=True)
class TeamState:
    roles: dict[str, str] = field(default_factory=dict)  # person id -> one of team_rules.ROLES
    limits: dict[str, int] = field(default_factory=dict)  # person id -> personal limit, INR minor units
    switches: dict[str, bool] = field(default_factory=_switch_defaults)
    tools: dict[str, str] = field(default_factory=dict)  # connector id -> one of LEVELS; unset = "act" (as before)
    worlds: dict[str, str] = field(default_factory=dict)  # the team's world id -> the person it belongs to
    invites: dict[str, dict[str, str]] = field(default_factory=dict)  # invite id -> {email, role}; nothing is sent
    version: int = 0

    def with_roles(self, roles: Mapping[str, str]) -> TeamState:
        return dataclasses.replace(self, roles=dict(roles))


def effective_switches(state: TeamState) -> dict[str, bool]:
    """The switches as they apply: a Must-ask rule reads as on whatever was stored (PRD 8.3)."""
    stored = {key: state.switches.get(key, default) for key, default in _switch_defaults().items()}
    return {key: value is True or key in MUST_ASK_KEYS for key, value in stored.items()}


def apply_role_change(state: TeamState, *, actor: str, target: str, role: str) -> TeamState:
    """`team_rules.change_role` on this snapshot; never leaves the team without an Owner."""
    roles = change_role(state.roles, actor, target, role)
    if "Owner" not in roles.values():
        raise RoleChangeRefused("last_owner")
    return state.with_roles(roles)


class TeamRepository(Protocol):
    def read(self) -> TeamState: ...

    def compare_and_set(self, expected_version: int, new: TeamState) -> bool:
        """Stores `new` with version `expected_version + 1` only if the stored version is still `expected_version`."""
        ...


class InMemoryTeamStore:
    def __init__(self, state: TeamState | None = None) -> None:
        self._state, self._lock = state if state is not None else TeamState(), threading.Lock()

    def read(self) -> TeamState:
        with self._lock:
            return self._state

    def compare_and_set(self, expected_version: int, new: TeamState) -> bool:
        with self._lock:
            if self._state.version != expected_version:
                return False
            self._state = dataclasses.replace(new, version=expected_version + 1)
            return True


def _to_doc(state: TeamState) -> dict[str, Any]:
    return dataclasses.asdict(state)


def _from_doc(doc: Mapping[str, Any] | None) -> TeamState:
    """A stored document, checked field by field; anything malformed raises (the caller refuses, never guesses)."""
    if doc is None:
        return TeamState()
    roles, limits, switches, tools = doc["roles"], doc["limits"], doc["switches"], doc["tools"]
    worlds, invites, version = doc["worlds"], doc["invites"], doc["version"]
    ok = (
        all(isinstance(p, str) and r in ROLES for p, r in roles.items())
        and all(isinstance(p, str) and type(v) is int and v >= 0 for p, v in limits.items())
        and all(isinstance(k, str) and type(v) is bool for k, v in switches.items())
        and all(isinstance(k, str) and v in LEVELS for k, v in tools.items())
        and all(isinstance(w, str) and isinstance(p, str) for w, p in worlds.items())
        and all(isinstance(i, dict) and set(i) == {"email", "role"} for i in invites.values())
        and type(version) is int
    )
    if not ok:
        raise ValueError("malformed team document")
    return TeamState(dict(roles), dict(limits), dict(switches), dict(tools), dict(worlds), dict(invites), version)


class FirestoreTeamStore:
    """`orgs/{org}/team/settings`: one document; the compare-and-set is a transaction on its `version`."""

    def __init__(self, client: Any, org_id: str = "org_tilo") -> None:
        self._client, self._ref = client, client.collection(f"orgs/{org_id}/team").document("settings")

    def read(self) -> TeamState:
        snap = self._ref.get()
        return _from_doc(snap.to_dict() if snap.exists else None)

    def compare_and_set(self, expected_version: int, new: TeamState) -> bool:
        from google.cloud import firestore

        @firestore.transactional
        def work(tx: Any) -> bool:
            snap = self._ref.get(transaction=tx)
            if _from_doc(snap.to_dict() if snap.exists else None).version != expected_version:
                return False
            tx.set(self._ref, _to_doc(dataclasses.replace(new, version=expected_version + 1)))
            return True

        return bool(work(self._client.transaction()))


def _dev_seed() -> TeamState | None:
    from tilo_api import dev  # late: dev imports the run machinery, which imports this module

    return TeamState(roles={dev.DEV_OWNER: "Owner"}) if dev.dev_enabled() else None


@functools.cache
def _open(kind: str, project: str) -> TeamRepository:
    if kind == "memory":
        return InMemoryTeamStore(_dev_seed())
    if kind == "firestore" and _PROJECT.fullmatch(project):
        from google.cloud import firestore

        return FirestoreTeamStore(firestore.Client(project=project))
    raise LookupError("team store not configured")


def get_team_store() -> TeamRepository:
    """Memory by name, or in dev mode by default (never deployed or live); Firestore only by explicit config; else
    503 `not_configured`. A success is cached per config, a refusal never is."""
    from tilo_api import dev

    kind = os.environ.get("TILO_TEAM_STORE") or ""
    if not kind and dev.dev_enabled():
        try:
            dev.refuse_if_unsafe()
            kind = "memory"
        except dev.DevModeRefused:
            pass
    try:
        return _open(kind, os.environ.get("TILO_FIRESTORE_PROJECT") or "")
    except LookupError as exc:  # not configured: the usual case until a team store is set up, so no log line
        raise HTTPException(status_code=503, detail="not_configured") from exc
    except Exception as exc:  # unconfigured, or a client that cannot be built: closed, never the text
        logger.warning("team store unavailable (%s)", type(exc).__name__)
        raise HTTPException(status_code=503, detail="not_configured") from exc


get_team_store.cache_clear = _open.cache_clear  # type: ignore[attr-defined]


def team_reader(overrides: Mapping[Callable[..., Any], Callable[..., Any]]) -> Callable[[], TeamState | None]:
    """For the engine: the team's state as the app is wired (overrides included). No team store configured means no
    team settings, so nothing changes from before; a configured store that fails to READ raises (callers fail
    closed)."""
    try:
        store = overrides.get(get_team_store, get_team_store)()
    except HTTPException:
        return lambda: None
    return store.read
