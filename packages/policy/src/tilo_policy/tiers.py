"""tilo_policy.tiers — risk tiers by action type and context (PRD 10.4, FR-HIL-04, PI-07). Any of
the six modifiers makes an action T3 whatever its base tier; an unlisted action type, or facts of
the wrong type, are T3."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .schemas import CONTRACTS, conforms

TABLE_REF = "policy.schema.json#/$defs/risk_tier_table"
DEFAULT_TABLE = CONTRACTS.parent / "config" / "autonomy.yaml"  # not in the repo yet (spark-456/tilo#1)


class PolicyConfigError(Exception):
    """The risk table file is missing or fails its schema (fail closed, never a partial table)."""


@dataclass(frozen=True)
class SideEffectFacts:
    recipients: tuple[str, ...] = ()
    known_recipients: tuple[str, ...] = ()
    attachments: tuple[Any, ...] = ()
    external_share: bool = False
    deletion: bool = False
    money_or_legal: bool = False
    safety_flags: bool = False

    @property
    def new_recipients(self) -> tuple[str, ...]:
        return tuple(r for r in self.recipients if r not in self.known_recipients)

    def active_modifiers(self) -> set[str]:
        """Raises ValueError on a field of the wrong type (so None is never "no attachments")."""
        lists = (self.recipients, self.known_recipients, self.attachments)
        flags = (self.external_share, self.deletion, self.money_or_legal, self.safety_flags)
        addresses = [*self.recipients, *self.known_recipients]
        if not all(isinstance(v, tuple | list) for v in lists) or not all(isinstance(f, bool) for f in flags):
            raise ValueError("malformed side-effect facts")
        if not all(isinstance(a, str) for a in addresses):
            raise ValueError("malformed recipient")
        names = ("new_recipients", "attachments", "external_sharing", "deletion", "money_or_legal", "safety_flag")
        values = (self.new_recipients, self.attachments, *flags)
        return {name for name, on in zip(names, values, strict=True) if on}


@dataclass(frozen=True)
class Assessment:
    tier: str
    modifiers: tuple[str, ...]


@dataclass(frozen=True)
class RiskTable:
    actions: dict[str, str]
    modifiers: tuple[str, ...]
    max_level: dict[str, str]

    def __post_init__(self) -> None:
        """A hand-built table must meet the same contract as a loaded one."""
        raw = {
            "actions": self.actions,
            "modifiers": [{"condition": m, "raises_to": "T3"} for m in self.modifiers],
            "max_level": self.max_level,
        }
        if not isinstance(self.modifiers, tuple) or not conforms(TABLE_REF, raw):
            raise PolicyConfigError(f"risk table fails contracts/{TABLE_REF}")

    def assess(self, action_type: str, facts: SideEffectFacts) -> Assessment:
        try:
            active = facts.active_modifiers()
        except Exception:
            return Assessment("T3", ())
        if active:  # T3 even if the table somehow lacks the modifier
            return Assessment("T3", tuple(m for m in self.modifiers if m in active))
        tier = self.actions.get(action_type, "T3")
        return Assessment(tier if tier in ("T1", "T2") else "T3", ())


def load_risk_table(path: str | os.PathLike[str] | None = None) -> RiskTable:
    target = Path(path) if path is not None else DEFAULT_TABLE
    try:
        raw = yaml.safe_load(target.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise PolicyConfigError(f"risk table {target}: {exc}") from exc
    if not conforms(TABLE_REF, raw):
        raise PolicyConfigError(f"risk table {target} fails contracts/{TABLE_REF}")
    modifiers = tuple(m["condition"] for m in raw["modifiers"])
    return RiskTable(actions=dict(raw["actions"]), modifiers=modifiers, max_level=dict(raw["max_level"]))
