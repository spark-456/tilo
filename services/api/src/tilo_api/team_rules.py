"""FR-TEAM-02 and FR-TEAM-04: team roles, personal limits and the five stop-and-ask switches.

Pure, deterministic rules (no model, no clock, no I/O beyond `config/team_rules.yaml`); no route calls them yet, so
the web Team page shows the same rules on fixture data. A change returns the new state plus an audit record: no
registered event type fits a switch change (`policy.changed` is a covering policy's), see BQ-TEAMACC-1."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import yaml

_CONFIG = Path(__file__).resolve().parents[4] / "config" / "team_rules.yaml"
ROLES = ("Owner", "Approver", "Member", "Viewer")  # the Park labels (BQ-DSN-01)


class RoleChangeRefused(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class MustAskLocked(Exception):
    """A PRD Must-ask rule can't be switched off."""


def change_role(roles: Mapping[str, str], actor: str, target: str, new_role: str) -> dict[str, str]:
    """A new person -> role map with `target` set to `new_role`. Nobody changes their own role, and only an Owner
    changes roles (BQ-TEAMACC-2: PRD 10.1 gives the Approver no admin rights)."""
    if new_role not in ROLES or actor not in roles or target not in roles or roles[target] not in ROLES:
        raise RoleChangeRefused("unknown")
    if actor == target:
        raise RoleChangeRefused("own_role")
    if roles[actor] != "Owner":
        raise RoleChangeRefused("not_allowed")
    return {**roles, target: new_role}


def _minor(value: object, name: str) -> int | None:
    if value is None:
        return None
    if type(value) is not int:
        raise TypeError(f"{name} must be an integer (minor units)")
    if value < 0:
        raise ValueError(f"{name} must not be negative")
    return value


def effective_user_cap(
    *, role_limit_minor: int | None, personal_limit_minor: int | None, lifetime_cap_minor: int
) -> int:
    """The per-user cap: the smallest of the role limit, the personal limit and the SEC-16 lifetime cap (None = no
    limit of that kind). A team limit can lower a person's cap, never lift the lifetime cap."""
    limits = [_minor(role_limit_minor, "role_limit_minor"), _minor(personal_limit_minor, "personal_limit_minor")]
    cap = _minor(lifetime_cap_minor, "lifetime_cap_minor")
    if cap is None:
        raise TypeError("lifetime_cap_minor is required")
    return min([cap, *[x for x in limits if x is not None]])


@dataclass(frozen=True)
class Switch:
    key: str
    default: bool
    must_ask: bool


MUST_ASK_KEYS = frozenset({"spend", "share", "undo"})  # pinned in code: a config edit can't unlock one (PRD 8.3)
TOOL_SWITCHES = frozenset({"tools"})  # changing one needs the `change_tool_access` capability (config capabilities)


@dataclass(frozen=True)
class Capability:
    key: str
    label: str
    roles: tuple[str, ...]


def load_capabilities(path: str | Path | None = None) -> dict[str, Capability]:
    """The 8 capabilities of the role matrix (FR-TEAM-05), in the page's row order."""
    doc = yaml.safe_load(Path(path if path is not None else _CONFIG).read_text(encoding="utf-8"))
    rows = doc.get("capabilities") if isinstance(doc, dict) else None
    if not isinstance(rows, list):
        raise ValueError("team_rules.yaml: capabilities must be a list")
    out: dict[str, Capability] = {}
    for r in rows:
        c = Capability(str(r["key"]), str(r["label"]), tuple(r["roles"]))
        if c.key in out or not set(c.roles) <= set(ROLES):
            raise ValueError("team_rules.yaml: bad capability")
        out[c.key] = c
    return out


def role_can(role: str, capability: str) -> bool:
    """Whether `role` holds `capability`; an unknown capability is a KeyError, an unknown role holds nothing."""
    return role in load_capabilities()[capability].roles


def load_switches(path: str | Path | None = None) -> dict[str, Switch]:
    doc = yaml.safe_load(Path(path if path is not None else _CONFIG).read_text(encoding="utf-8"))
    rows = doc["switches"] if isinstance(doc, dict) else None
    if not isinstance(rows, list):
        raise ValueError("team_rules.yaml: switches must be a list")
    out: dict[str, Switch] = {}
    for r in rows:
        s = Switch(str(r["key"]), r["default"], r["must_ask"] or str(r["key"]) in MUST_ASK_KEYS)
        if type(s.default) is not bool or type(s.must_ask) is not bool or s.key in out:
            raise ValueError("team_rules.yaml: bad switch")
        if s.must_ask and not s.default:
            raise ValueError("team_rules.yaml: a Must-ask rule must default on")
        out[s.key] = s
    return out


def set_switch(
    state: Mapping[str, bool], key: str, value: bool, *, actor: str, actor_role: str, at: str
) -> tuple[dict[str, bool], dict[str, object]]:
    """The new switch state and the audit record of this change. A Must-ask switch can't go off; an unknown key is a
    KeyError, a non-bool a TypeError."""
    switch = load_switches()[key]
    if actor_role not in ("Owner", "Approver") or (
        key in TOOL_SWITCHES and not role_can(actor_role, "change_tool_access")
    ):
        raise PermissionError(key)
    if type(value) is not bool:
        raise TypeError("a switch is on or off")
    if switch.must_ask and not value:
        raise MustAskLocked(key)
    record: dict[str, object] = {
        "kind": "team_rule_changed",
        "key": key,
        "from": state[key],
        "to": value,
        "by": actor,
        "at": at,
    }
    return {**state, key: value}, record
