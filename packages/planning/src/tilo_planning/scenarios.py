"""Scenario configs (FR-INT-11, PRD 7.1, 4.3, 10.1, 10.4, ADR-0014, BQ-202). A scenario is data:
`config/scenarios/<id>.yaml` names the skills, connectors, seed data, autonomy policy and theme a world starts with,
and this one generic loader reads every such file, so a new scenario needs no code (SN-09: no scenario id in platform
source). Fail closed: any bad id, file, key or reference is a `ScenarioError` before anything is returned. The file is
read with `yaml.safe_load`, validated against `contracts/scenario.schema.json` (the JSON Schema, not a model that
would accept a null the schema refuses), then SN-01 and SN-03 to SN-07 are checked here (`contracts/scenario.rules.md`).
Only the owner creates a policy (PRD 10.1, SN-08), so `policies()` takes the owner from the caller; a T3 action is never
above L1 whatever the file says, and a `grant_budget` entry gets `limits.credits` null so the engine gates it."""

from __future__ import annotations

import csv
import functools
import io
import json
import re
import uuid
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jsonschema
import tilo_policy
import yaml
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012
from tilo_policy.schemas import conforms

REPO_ROOT = Path(__file__).resolve().parents[4]
CONTRACTS = REPO_ROOT / "contracts"
MAX_FILE_BYTES = 2_000_000
MAX_PROBLEMS = 3
SEED_DIR = "seed"  # SN-04: a seed file sits under a directory of this name (not any file in the repo)
_INTERNAL = "internal"  # the reserved connector id of an action that goes through no connector
_ID = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,31}")  # $defs/id of the schema; fullmatch, so no final line break


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


class _PlainLoader(yaml.SafeLoader):
    """SN-02: a scenario is plain data. An anchor or alias (an alias bomb costs seconds) or an explicit tag
    (`!!str`, `!!python/...`) is refused, so only what the schema describes can be written."""

    def compose_node(self, parent: Any, index: Any) -> Any:
        event = self.peek_event()
        if isinstance(event, yaml.AliasEvent) or getattr(event, "anchor", None) or getattr(event, "tag", None):
            raise yaml.MarkedYAMLError(
                problem="anchors, aliases and tags are not allowed", problem_mark=event.start_mark
            )
        return super().compose_node(parent, index)


def _read_yaml(path: Path, what: str, *, plain: bool = False) -> Any:
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            raise ScenarioError(f"{what} is larger than {MAX_FILE_BYTES} bytes")
        text = path.read_text(encoding="utf-8")
        return yaml.load(text, Loader=_PlainLoader) if plain else yaml.safe_load(text)  # noqa: S506 (safe subclass)
    except ScenarioError:
        raise
    except (OSError, yaml.YAMLError, UnicodeError, RecursionError) as error:
        raise ScenarioError(f"{what} cannot be read: {type(error).__name__}") from error


@functools.cache
def _validator() -> jsonschema.protocols.Validator:
    resources = []
    for path in sorted(CONTRACTS.glob("*.schema.json")):  # common.schema.json is what scenario.schema.json refers to
        data = json.loads(path.read_text(encoding="utf-8"))
        resources.append((data["$id"], Resource.from_contents(data, default_specification=DRAFT202012)))
    schema = json.loads((CONTRACTS / "scenario.schema.json").read_text(encoding="utf-8"))
    return jsonschema.Draft202012Validator(schema, registry=Registry().with_resources(resources))


def _schema_problems(data: Any) -> list[str]:
    """SN-02: each way the file fails the schema, naming the key and the offending value (bounded). The pass or fail
    comes from the policy package's validator, where `$` ends the string (a final line break never passes, ECMA
    rules); the stock validator only words the problems and may find none for such a value."""
    if not conforms("scenario.schema.json", data):
        problems = _described_problems(data)
        return problems or ["the file does not fit the schema (a value ends in a line break)"]
    return []


def _described_problems(data: Any) -> list[str]:
    try:
        errors = sorted(_validator().iter_errors(data), key=lambda e: [str(p) for p in e.absolute_path])
    except RecursionError:
        return ["the file is nested too deeply"]
    return [f"{'.'.join(map(str, e.absolute_path)) or 'file'}: {e.message}"[:160] for e in errors[:MAX_PROBLEMS]]


def _connector_ids(repo_root: Path) -> set[str]:
    registry = _read_yaml(repo_root / "config" / "connectors.yaml", "config/connectors.yaml")
    if not isinstance(registry, list) or not all(
        isinstance(c, dict) and isinstance(c.get("id"), str) for c in registry
    ):
        raise ScenarioError("config/connectors.yaml is not a list of connectors")
    return {c["id"] for c in registry}


def _seed_file(entry: str, repo_root: Path) -> Path:
    """SN-04: the schema refuses an absolute, dotted or hidden path. This resolves symlinks, then needs the resolved
    path to be the entry itself (so `seed/x.` or a link elsewhere is refused, with no hidden segment) and an existing
    regular file under a `seed` directory inside the repo root. Nothing is read here."""
    root = repo_root.resolve()
    path = (root / entry).resolve()
    inside = root in path.parents and path.relative_to(root).as_posix() == entry
    parts = entry.split("/")
    if not inside or SEED_DIR not in parts[:-1] or any(p.startswith(".") for p in parts) or not path.is_file():
        raise ScenarioError(f"seed_data {_show(entry)} is not an existing seed file inside the repository")
    return path


def _check_entry(entry: dict[str, Any], index: int, connectors: Collection[str], table: tilo_policy.RiskTable) -> None:
    """SN-06 (level within the tier's max, an unlisted action is T3) and SN-07 (connectors the scenario's own)."""
    where = f"autonomy[{index}]"
    action, level = entry["action_type"], entry["level"]
    tier = table.tier_of(action, [])  # an action the table does not list is T3 (BQ-44)
    if int(level[1]) > int(table.max_level[tier][1]):
        raise ScenarioError(f"{where}: {action} is {tier} and may not be above {table.max_level[tier]}")
    for connector in entry["connectors"]:
        if connector not in connectors and connector != _INTERNAL:
            raise ScenarioError(f"{where}: connector {_show(connector)} is not one of the scenario's own connectors")


def _load_table(repo_root: Path) -> tilo_policy.RiskTable:
    try:
        return tilo_policy.load_risk_table(repo_root / "config" / "autonomy.yaml")
    except tilo_policy.PolicyConfigError as error:
        raise ScenarioError("config/autonomy.yaml is not a valid risk table") from error


def load_scenario(
    scenario_id: str, *, repo_root: Path = REPO_ROOT, skill_ids: Collection[str] | None = None
) -> Scenario:
    if not isinstance(scenario_id, str) or not _ID.fullmatch(scenario_id):
        raise ScenarioError("not a scenario id")  # SN-01: before any path is built
    path = repo_root / "config" / "scenarios" / f"{scenario_id}.yaml"
    scenarios_dir = (repo_root / "config" / "scenarios").resolve()
    if path.resolve().parent != scenarios_dir:  # a link to a file elsewhere is not a scenario
        raise ScenarioError(f"scenario {scenario_id} is not a file of config/scenarios")
    data = _read_yaml(path, f"scenario {scenario_id}", plain=True)
    if problems := _schema_problems(data):
        raise ScenarioError(f"scenario {scenario_id} does not fit scenario.schema.json: " + "; ".join(problems))
    if data["id"] != scenario_id:
        raise ScenarioError(f"scenario file {scenario_id}.yaml must have the id {scenario_id}")
    skills, connectors = data["skills"], data["connectors"]
    if skill_ids is not None and (absent := [s for s in skills if s not in skill_ids]):  # SN-05
        raise ScenarioError(f"scenario {scenario_id}: skills not in the catalog: {absent}")
    registry = _connector_ids(repo_root)  # SN-03: `internal` is never declared there
    if unlisted := [c for c in connectors if c not in registry]:
        raise ScenarioError(f"scenario {scenario_id}: connectors not in config/connectors.yaml: {unlisted}")
    seed_paths = [_seed_file(entry, repo_root) for entry in data["seed_data"]]
    table, autonomy = _load_table(repo_root), data.get("autonomy", [])
    for index, entry in enumerate(autonomy):
        _check_entry(entry, index, connectors, table)
    return Scenario(
        scenario_id, data["title"], tuple(skills), tuple(connectors), tuple(seed_paths), data["theme"], tuple(autonomy)
    )


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
            if root not in resolved.parents:
                problems.append(f"seed file {name} is outside the repository")
                continue
            _parse_seed(_seed_file(resolved.relative_to(root).as_posix(), repo_root))
        except ScenarioError:
            problems.append(f"seed file {name} is missing or not a seed file inside the repository")
        except (OSError, ValueError, UnicodeError, yaml.YAMLError, csv.Error, RecursionError) as error:
            problems.append(f"seed file {name} does not parse: {type(error).__name__}")
    return problems
