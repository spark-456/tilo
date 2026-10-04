"""Scenario configs (FR-INT-11, PRD 7.1, 4.3, 10.1, 10.4, BQ-202). A scenario is data: `config/scenarios/<id>.yaml`
names the skills, connectors, seed data, autonomy policy and theme a world starts with, and this one generic loader
reads every such file, so a new scenario needs no code (no scenario id appears in platform source). Fail closed: any
bad id, file, key or reference is a `ScenarioError` before anything is returned; the file is data, never code
(`yaml.safe_load`). Only the owner creates a policy (PRD 10.1), so `policies()` takes the owner from the caller, and a
T3 action is never above L1 whatever the file says. The shape is checked here until `contracts/scenario.schema.json`
exists (needs contract change, BQ-202)."""

from __future__ import annotations

import csv
import io
import json
import re
import uuid
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tilo_policy
import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]
MAX_FILE_BYTES = 2_000_000
_ID = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,31}")
_SKILL = re.compile(r"[a-z][a-z0-9]*([_-][a-z0-9]+)*")  # common.schema.json skill_id
_SLUG = re.compile(r"[a-z][a-z0-9_]{0,63}")
_CONNECTOR = re.compile(r"[a-z][a-z0-9_]{1,31}")
_ACTION = re.compile(r"[a-z][a-z0-9_]{1,47}")
_LEVEL = re.compile(r"L[0-3]")
_KEYS = {"id", "title", "skills", "connectors", "seed_data", "theme", "autonomy"}
_ENTRY_KEYS = {"action_type", "level", "connectors", "per_day", "undo_window_s"}
_INTERNAL = "internal"  # the reserved connector id of an action that goes through no connector


class ScenarioError(Exception):
    """A scenario id, file or reference is unusable; the message names the offender, never a file's contents."""


@dataclass(frozen=True)
class Scenario:
    id: str
    title: str
    skills: Sequence[str]
    connectors: Sequence[str]
    seed_data: Sequence[Path]  # absolute, existing files inside the repo root
    theme: str
    autonomy: Sequence[dict[str, Any]]

    def policies(self, *, owner: str, at: str) -> list[dict[str, Any]]:
        """One `policy.schema.json` record per autonomy entry, created by the owner at `at`."""
        records = []
        for entry in self.autonomy:
            level = entry["level"]
            records.append(
                {
                    "id": f"pol_{uuid.uuid4().hex[:24]}",
                    "owner": owner,
                    "action_type": entry["action_type"],
                    "scope": {
                        "connectors": list(entry["connectors"]),
                        "recipients": [],
                        "domains": [],
                        "districts": [],
                    },
                    "limits": {"per_day": entry.get("per_day"), "credits": None},
                    "conditions": {"no_attachments": True, "no_new_recipients": True, "no_safety_flags": True},
                    "level": level,
                    "undo_window_s": entry.get("undo_window_s", 60),
                    "expiry": None,
                    "notify_channel": "web",
                    "team_lead_domains": [],
                    "created_by": {"by": owner, "at": at},
                    "changed_by": None,
                    "history": [{"by": owner, "at": at, "change": f"created from scenario {self.id}", "level": level}],
                }
            )
        return records


def _show(value: Any) -> str:
    return repr(value)[:80]  # a file's content never floods a message


def _read_yaml(path: Path, what: str) -> Any:
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            raise ScenarioError(f"{what} is larger than {MAX_FILE_BYTES} bytes")
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except ScenarioError:
        raise
    except (OSError, yaml.YAMLError, UnicodeError, RecursionError) as error:
        raise ScenarioError(f"{what} cannot be read: {type(error).__name__}") from error


def _connector_ids(repo_root: Path) -> set[str]:
    registry = _read_yaml(repo_root / "config" / "connectors.yaml", "config/connectors.yaml")
    if not isinstance(registry, list) or not all(
        isinstance(c, dict) and isinstance(c.get("id"), str) for c in registry
    ):
        raise ScenarioError("config/connectors.yaml is not a list of connectors")
    return {c["id"] for c in registry}


def _seed_path(entry: Any, repo_root: Path) -> Path:
    where = f"seed_data entry {_show(entry)}"
    if not isinstance(entry, str) or not entry.strip() or "\x00" in entry:
        raise ScenarioError(f"{where} must be a repo-relative path")
    parts = re.split(r"[\\/]", entry)
    if entry[0] in "/\\" or ":" in entry or ".." in parts:
        raise ScenarioError(f"{where} must stay inside the repository (no absolute path, no '..')")
    root = repo_root.resolve()
    path = (root / entry).resolve()
    if root not in path.parents:
        raise ScenarioError(f"{where} leaves the repository")
    if not path.is_file():
        raise ScenarioError(f"{where} does not exist")
    return path


def _check_entry(entry: Any, index: int, connectors: Collection[str], table: tilo_policy.RiskTable) -> None:
    where = f"autonomy[{index}]"
    if not isinstance(entry, dict) or not {"action_type", "level", "connectors"} <= set(entry) <= _ENTRY_KEYS:
        raise ScenarioError(f"{where} must have action_type, level, connectors and at most per_day, undo_window_s")
    action, level, own = entry["action_type"], entry["level"], entry["connectors"]
    if not isinstance(action, str) or not _ACTION.fullmatch(action):
        raise ScenarioError(f"{where}.action_type is not an action type")
    if not isinstance(level, str) or not _LEVEL.fullmatch(level):
        raise ScenarioError(f"{where}.level must be L0, L1, L2 or L3")
    tier = table.tier_of(action, [])  # an action the table does not list is T3 (BQ-44)
    if int(level[1]) > int(table.max_level[tier][1]):
        raise ScenarioError(f"{where}: {action} is {tier} and may not be above {table.max_level[tier]}")
    per_day = entry.get("per_day")
    if level in ("L2", "L3") and (not isinstance(per_day, int) or isinstance(per_day, bool) or per_day < 1):
        raise ScenarioError(f"{where}: {level} needs a per_day limit of at least 1")
    if "per_day" in entry and per_day is not None and (not isinstance(per_day, int) or isinstance(per_day, bool)):
        raise ScenarioError(f"{where}.per_day must be a whole number")
    undo = entry.get("undo_window_s", 60)
    if not isinstance(undo, int) or isinstance(undo, bool) or not 0 <= undo <= 3600:
        raise ScenarioError(f"{where}.undo_window_s must be 0 to 3600")
    if not isinstance(own, list) or not own or len(set(map(str, own))) != len(own):
        raise ScenarioError(f"{where}.connectors must be a non-empty list without repeats")
    for connector in own:
        if not isinstance(connector, str) or not (connector in connectors or connector == _INTERNAL):
            raise ScenarioError(f"{where}: connector {_show(connector)} is not one of the scenario's own connectors")


def _load_table(repo_root: Path) -> tilo_policy.RiskTable:
    try:
        return tilo_policy.load_risk_table(repo_root / "config" / "autonomy.yaml")
    except tilo_policy.PolicyConfigError as error:
        raise ScenarioError("config/autonomy.yaml is not a valid risk table") from error


def _text_list(value: Any, name: str, pattern: re.Pattern[str]) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(v, str) and pattern.fullmatch(v) for v in value):
        raise ScenarioError(f"{name} must be a list of valid ids")
    if len(set(value)) != len(value):
        raise ScenarioError(f"{name} has a repeated id")
    return value


def load_scenario(
    scenario_id: str, *, repo_root: Path = REPO_ROOT, skill_ids: Collection[str] | None = None
) -> Scenario:
    if not isinstance(scenario_id, str) or not _ID.fullmatch(scenario_id):
        raise ScenarioError("not a scenario id")  # before any path is built
    path = repo_root / "config" / "scenarios" / f"{scenario_id}.yaml"
    data = _read_yaml(path, f"scenario {scenario_id}")
    if not isinstance(data, dict):
        raise ScenarioError(f"scenario {scenario_id} must be a mapping")
    unknown, missing = sorted(map(str, set(data) - _KEYS)), sorted(_KEYS - {"autonomy"} - set(data))
    if unknown or missing:
        raise ScenarioError(f"scenario {scenario_id}: unknown keys {unknown}, missing keys {missing}")
    if data["id"] != scenario_id:
        raise ScenarioError(f"scenario file {scenario_id}.yaml must have the id {scenario_id}")
    title, theme = data["title"], data["theme"]
    if not isinstance(title, str) or not title.strip() or len(title) > 120:
        raise ScenarioError(f"scenario {scenario_id}: title must be text of 1 to 120 characters")
    if not isinstance(theme, str) or not _SLUG.fullmatch(theme):
        raise ScenarioError(f"scenario {scenario_id}: theme must be a lower-case slug")
    skills = _text_list(data["skills"], "skills (skill ids)", _SKILL)
    if not skills or any(len(s) > 64 for s in skills):
        raise ScenarioError(f"scenario {scenario_id}: skills must name 1 or more skill ids")
    if skill_ids is not None and (absent := [s for s in skills if s not in skill_ids]):
        raise ScenarioError(f"scenario {scenario_id}: skills not in the catalog: {absent}")
    connectors = _text_list(data["connectors"], "connectors", _CONNECTOR)
    registry = _connector_ids(repo_root)
    if unlisted := [c for c in connectors if c not in registry]:
        raise ScenarioError(f"scenario {scenario_id}: connectors not in config/connectors.yaml: {unlisted}")
    seeds = data["seed_data"]
    if not isinstance(seeds, list):
        raise ScenarioError(f"scenario {scenario_id}: seed_data must be a list of paths")
    seed_paths = [_seed_path(entry, repo_root) for entry in seeds]
    autonomy = data.get("autonomy") or []
    if not isinstance(autonomy, list):
        raise ScenarioError(f"scenario {scenario_id}: autonomy must be a list")
    table = _load_table(repo_root)
    for index, entry in enumerate(autonomy):
        _check_entry(entry, index, connectors, table)
    return Scenario(scenario_id, title, tuple(skills), tuple(connectors), tuple(seed_paths), theme, tuple(autonomy))


def _parse_seed(path: Path) -> None:
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("larger than the limit")
    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    if suffix in (".yaml", ".yml"):
        yaml.safe_load(text)
    elif suffix == ".json":
        json.loads(text)
    elif suffix == ".csv":
        list(csv.reader(io.StringIO(text), strict=True))
    else:
        raise ValueError(f"unsupported seed file type {suffix or '(none)'}")


def smoke_test(scenario: Scenario, *, repo_root: Path = REPO_ROOT) -> list[str]:
    """Problems found when every reference is resolved again against `repo_root` as it is now; [] passes."""
    problems: list[str] = []
    try:
        known = _connector_ids(repo_root)
        table = _load_table(repo_root)
    except ScenarioError as error:
        return [str(error)]
    problems += [f"connector {c} is not in config/connectors.yaml" for c in scenario.connectors if c not in known]
    for index, entry in enumerate(scenario.autonomy):
        try:
            _check_entry(entry, index, scenario.connectors, table)
        except ScenarioError as error:
            problems.append(str(error))
    root = repo_root.resolve()
    for seed in scenario.seed_data:
        name = Path(seed).name
        try:
            resolved = Path(seed).resolve()
            if root not in resolved.parents or not resolved.is_file():
                problems.append(f"seed file {name} is missing or outside the repository")
            else:
                _parse_seed(resolved)
        except (OSError, ValueError, UnicodeError, yaml.YAMLError, csv.Error, RecursionError) as error:
            problems.append(f"seed file {name} does not parse: {type(error).__name__}")
    return problems
