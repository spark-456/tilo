"""tilo_policy.access_levels — Off / Read / Draft / Act per tool (FR-ACC-01, BQ-DSN-04).

A level is a ceiling on the risk tier a tool may be used for. It only ever narrows: `permits` never authorises an
action, it says whether the level lets the action reach the policy engine at all. `Act` is up to the engine's own
ceiling (T2 within policy bounds), and a T3 action still needs a person and never auto-executes. A skill's level
(FR-ACC-02) can only restrict: `effective_level` is the lower of the two. Pure and deterministic; no model."""

from __future__ import annotations

from enum import IntEnum
from typing import Literal

Outcome = Literal["allow", "block", "needs_person"]
_TIERS = ("T0", "T1", "T2", "T3")  # T0: a read with no side effect (the risk table lists T1..T3 only)


class Level(IntEnum):
    OFF = 0
    READ = 1
    DRAFT = 2
    ACT = 3


def parse_level(value: str) -> Level:
    """`"off" | "read" | "draft" | "act"` (exact, lower case); anything else is a ValueError."""
    if not isinstance(value, str) or value not in ("off", "read", "draft", "act"):
        raise ValueError("unknown access level")
    return Level[value.upper()]


def effective_level(team: Level, skill: Level | None = None) -> Level:
    """min(team_level, skill_level): a skill can restrict a tool, never elevate it. No skill level means the team's."""
    return team if skill is None else Level(min(team, skill))


def permits(level: Level, tier: str, *, read_only: bool = False) -> Outcome:
    """Whether `level` lets an action of `tier` through. `read_only` marks a read (T0 whatever its table tier).
    An unknown tier or level blocks (fail closed)."""
    if tier not in _TIERS or not isinstance(level, Level):
        return "block"
    if level is Level.OFF:
        return "block"
    if tier == "T0" or (read_only and tier in ("T1", "T2")):  # a "read" raised to T3 by a modifier is no plain read
        return "allow"
    if level is Level.READ:
        return "block"
    if level is Level.DRAFT:
        return "allow" if tier == "T1" else "block"
    return "needs_person" if tier == "T3" else "allow"
