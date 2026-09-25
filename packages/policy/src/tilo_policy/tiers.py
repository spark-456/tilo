"""tilo_policy.tiers — risk tiers by action type and context (PRD 10.4, FR-HIL-04, PI-07). Any of
the six modifiers makes an action T3 whatever its base tier; an unlisted action type is T3."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jsonschema
import yaml
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_TABLE = REPO_ROOT / "config" / "autonomy.yaml"  # not in the repo yet (spark-456/tilo#1)
TABLE_SCHEMA = {"$ref": "https://contracts.tilo.example/policy.schema.json#/$defs/risk_tier_table"}


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
        """Anything but an explicit False counts as set (fail closed)."""
        flags = {
            "new_recipients": bool(self.new_recipients),
            "attachments": bool(self.attachments),
            "external_sharing": self.external_share is not False,
            "deletion": self.deletion is not False,
            "money_or_legal": self.money_or_legal is not False,
            "safety_flag": self.safety_flags is not False,
        }
        return {name for name, on in flags.items() if on}


@dataclass(frozen=True)
class Assessment:
    tier: str
    modifiers: tuple[str, ...]


@dataclass(frozen=True)
class RiskTable:
    actions: dict[str, str]
    modifiers: tuple[str, ...]
    max_level: dict[str, str]

    def assess(self, action_type: str, facts: SideEffectFacts) -> Assessment:
        active = facts.active_modifiers()
        if active:  # T3 even if the table somehow lacks the modifier
            return Assessment("T3", tuple(m for m in self.modifiers if m in active))
        tier = self.actions.get(action_type, "T3")
        return Assessment(tier if tier in ("T1", "T2") else "T3", ())


def load_risk_table(path: str | os.PathLike[str] | None = None) -> RiskTable:
    target = Path(path) if path is not None else DEFAULT_TABLE
    try:
        raw = yaml.safe_load(target.read_text(encoding="utf-8"))
        schemas = [
            json.loads((REPO_ROOT / "contracts" / f"{n}.schema.json").read_text("utf-8")) for n in ("common", "policy")
        ]
        registry = Registry().with_resources(
            (s["$id"], Resource.from_contents(s, default_specification=DRAFT202012)) for s in schemas
        )
        jsonschema.Draft202012Validator(TABLE_SCHEMA, registry=registry).validate(raw)
    except (OSError, yaml.YAMLError, jsonschema.ValidationError) as exc:
        raise PolicyConfigError(f"risk table {target}: {exc}") from exc
    modifiers = tuple(m["condition"] for m in raw["modifiers"])
    return RiskTable(actions=dict(raw["actions"]), modifiers=modifiers, max_level=dict(raw["max_level"]))
