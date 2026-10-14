"""Skill registry (FR-AGT-03, PRD 8.2): skills/<domain>/<skill-id>/{skill.yaml,SKILL.md}.

Each skill.yaml is checked against contracts/skill.schema.json, its folder names must equal its
`domain` and `id`, and its inputs/outputs must be valid 2020-12 schemas; an invalid folder is
listed in `problems` and never loaded. The planner sees `catalog()` (id and description only);
a run calls `pin()` once at start and loads every skill through `load_pinned()`, which re-reads
the files and refuses them unless they still hash to the pinned sha256."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any

import jsonschema
import yaml
from tilo_providers.diagnostics import log_caught

from tilo_harness.validator import repo_validator

# id -> (version, sha256 of skill.yaml bytes + SKILL.md bytes), frozen at run start.
Pins = Mapping[str, tuple[str, str]]

_MAX_FILE_BYTES = 256 * 1024


class SkillError(Exception):
    """A skill is unknown, invalid, unreadable or no longer matches its pin."""


@dataclass(frozen=True)
class LoadedSkill:
    id: str
    version: str
    body: str
    sha256: str
    tool_access: Mapping[str, Any] = field(default_factory=dict)  # FR-ACC-02: connector id -> level, as declared
    tools_allowed: tuple[str, ...] = ()  # the tools the skill may use (LW-07); a unit gets these intersect its role's


def _read_capped(path: Path) -> bytes:
    if path.stat().st_size > _MAX_FILE_BYTES:
        raise SkillError(f"{path.name} is larger than {_MAX_FILE_BYTES} bytes")
    return path.read_bytes()


def _read_skill(folder: Path) -> tuple[dict[str, Any], LoadedSkill]:
    """Any read or parse failure (even ValueError or RecursionError from hostile YAML) is a SkillError."""
    try:
        return _parse_skill(folder)
    except SkillError:
        raise
    except Exception as error:
        log_caught(error, __name__, locals())
        raise SkillError(f"{folder.name}: cannot read skill ({type(error).__name__})") from error


def _parse_skill(folder: Path) -> tuple[dict[str, Any], LoadedSkill]:
    raw_yaml = _read_capped(folder / "skill.yaml")
    raw_md = _read_capped(folder / "SKILL.md")
    data = yaml.safe_load(raw_yaml.decode("utf-8"))
    body = raw_md.decode("utf-8")
    problems = repo_validator().contract_problems("skill", data)
    if problems:
        raise SkillError(f"{folder.name}: " + "; ".join(problems))
    if data["id"] != folder.name or data["domain"] != folder.parent.name:
        raise SkillError(f"{folder.name}: skill.yaml id/domain must match skills/<domain>/<skill-id>/")
    for name in ("inputs", "outputs"):
        try:
            jsonschema.Draft202012Validator.check_schema(data[name])
        except jsonschema.SchemaError as error:
            raise SkillError(f"{folder.name}: {name} is not a valid JSON Schema") from error
    sha256 = hashlib.sha256(raw_yaml + raw_md).hexdigest()
    return data, LoadedSkill(
        id=data["id"],
        version=data["version"],
        body=body,
        sha256=sha256,
        tool_access=data.get("tool_access") or {},
        tools_allowed=tuple(data["tools_allowed"]),
    )


class SkillRegistry:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.problems: dict[str, str] = {}  # "<domain>/<folder>" -> why it was not loaded
        self._folders: dict[str, Path] = {}
        self._descriptions: dict[str, str] = {}
        for yaml_path in sorted(self.root.glob("*/*/skill.yaml")):
            folder = yaml_path.parent
            name = f"{folder.parent.name}/{folder.name}"
            try:
                data, _ = _read_skill(folder)
            except SkillError as error:
                self.problems[name] = str(error)
                continue
            if data["id"] in self._folders:
                self.problems[name] = f"{data['id']}: duplicate skill id"
                continue
            self._folders[data["id"]] = folder
            self._descriptions[data["id"]] = data["description"]

    def catalog(self) -> list[tuple[str, str]]:
        """What the planner sees (PRD 8.2 Selection): (id, one-line description) per skill."""
        return sorted(self._descriptions.items())

    def folder(self, skill_id: str) -> Path | None:
        """The skill's folder, `<root>/<domain>/<skill-id>`, or None if it is not in the registry (FR-AGT-15)."""
        return self._folders.get(skill_id)

    def load(self, skill_id: str) -> LoadedSkill:
        folder = self._folders.get(skill_id)
        if folder is None:
            raise SkillError(f"{skill_id!r} is not in the skill registry")
        return _read_skill(folder)[1]

    def pin(self, skill_ids: Iterable[str]) -> Pins:
        """Snapshots id -> (version, sha256) for a run; raises SkillError for an unknown id."""
        pins: dict[str, tuple[str, str]] = {}
        for skill_id in skill_ids:
            loaded = self.load(skill_id)
            pins[skill_id] = (loaded.version, loaded.sha256)
        return MappingProxyType(pins)

    def load_pinned(self, skill_id: str, pins: Pins) -> LoadedSkill:
        """Loads a skill only if its files still match the pin; never returns unpinned content."""
        if skill_id not in pins:
            raise SkillError(f"{skill_id!r} was not pinned for this run")
        loaded = self.load(skill_id)
        if (loaded.version, loaded.sha256) != pins[skill_id]:
            raise SkillError(f"{skill_id!r} changed on disk since it was pinned")
        return loaded
