"""Where the team's rules meet the engine (FR-ACC-01/02, FR-TEAM-02, FR-TEAM-04; issue #621).

* `tool_check`: `permits(effective_level(team_level, skill_level), tier, read_only)`, with `read_only` from the
  connector tables only (`config/connectors.yaml`, `config/mcp.yaml`), never from a tool call or model output. It runs
  BEFORE the policy engine and can only refuse: "allow" means "go on to the engine as before", never "approved".
* `user_cap_minor`: the SEC-16 lifetime cap lowered by the person's role limit and personal limit (a MIN).
* `weekend_hold`: the `weekend` switch on the scheduled-run path.

No team store wired (`state is None`) changes nothing. Deterministic; no model, no clock of its own.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from tilo_policy import Level, effective_level, permits
from tilo_policy.access_levels import Outcome, parse_level

from tilo_api.team_rules import effective_user_cap, load_role_limits
from tilo_api.team_store import TeamState, effective_switches

logger = logging.getLogger("tilo_api.team_access")
_READ_CAPABILITIES = frozenset({"read", "search", "list"})


def read_only(connector: str, action: str, *, registry: Any, mcp: Any = None) -> bool:
    """True only for an action the tables declare a plain read: a connector action of a read capability, T1, ungated
    and reversible; or an allowlisted MCP tool with `side_effect: false` at T1. Anything unknown is not a read."""
    if connector in registry:
        declared = next((a for a in registry.get(connector)["actions"] if a.get("id") == action), None)
        return declared is not None and (
            declared.get("capability") in _READ_CAPABILITIES
            and declared.get("risk_tier") == "T1"
            and declared.get("gate_type") == "none"
            and declared.get("irreversible") is False
        )
    if mcp is not None and connector in mcp:
        tool = next((t for t in mcp.tools(connector) if t.name == action), None)
        return tool is not None and tool.side_effect is False and tool.risk_tier == "T1"
    return False


def skill_level(skills: Any, skill_ids: Iterable[str], connector: str) -> Level | None:
    """FR-ACC-02: the lowest `tool_access[connector]` the unit's skills declare, or None (the team's level applies).
    It can only lower. A value that is not one of the four levels (or a map that is not a map) counts as off, never
    act. An unknown or unreadable skill is skipped, never trusted to lower or raise, with an ids-only log line."""
    found: list[Level] = []
    for skill_id in skill_ids:
        try:
            declared = skills.load(skill_id).tool_access
        except Exception as exc:
            logger.warning("skill %s tool_access not read (%s)", skill_id, type(exc).__name__)
            continue
        if declared is None or declared == {}:  # a skill without tool_access changes nothing
            continue
        if not isinstance(declared, dict):
            found.append(Level.OFF)
            continue
        if connector in declared:
            try:
                found.append(parse_level(declared[connector]))
            except ValueError:
                found.append(Level.OFF)
    return min(found) if found else None


def tool_check(
    state: TeamState | None,
    connector: str,
    action: str,
    tier: str,
    *,
    registry: Any,
    mcp: Any = None,
    skill_level: Level | None = None,
) -> Outcome:
    """Whether the team's level for `connector` (lowered by a skill's) lets an action of `tier` through to the
    engine. An unset declared tool is Act (as before); an undeclared tool or a stored level that is not one of the
    four blocks."""
    if state is None:
        return "allow"
    if connector not in registry and (mcp is None or connector not in mcp):
        return "block"  # a tool the tables do not declare has no level, so it is never Act
    try:
        level = effective_level(parse_level(state.tools.get(connector, "act")), skill_level)
    except (TypeError, ValueError):
        return "block"
    return permits(level, tier, read_only=read_only(connector, action, registry=registry, mcp=mcp))


def user_cap_minor(state: TeamState | None, uid: str, lifetime_cap_minor: int) -> int:
    """The SEC-16 cap for `uid`: never above the lifetime cap; a team member's role and personal limits lower it."""
    role = state.roles.get(uid) if state is not None else None
    if state is None or role is None:
        return lifetime_cap_minor
    return effective_user_cap(
        role_limit_minor=load_role_limits()[role],
        personal_limit_minor=state.limits.get(uid),
        lifetime_cap_minor=lifetime_cap_minor,
    )


def weekend_hold(state: TeamState | None, now: datetime, tz: str) -> bool:
    """The `weekend` switch is on and it is Saturday or Sunday where the schedule runs: hold until Monday."""
    if state is None or not effective_switches(state)["weekend"]:
        return False
    return now.astimezone(ZoneInfo(tz)).weekday() >= 5
