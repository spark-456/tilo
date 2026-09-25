"""Shared helpers for ticket P0-03 acceptance tests (event contract, PRD 9.3-9.5, 15.2).

Not a test module itself (leading underscore keeps pytest from collecting it), same convention
as `_lib.py`. Builds on `_lib.py` (schema loading, `$ref` resolution, fixture helpers) rather than
duplicating it; `contracts/event.schema.json` and `contracts/outbox.schema.json` are loaded with
`_lib.load_schema(repo_root, "event" | "outbox")` directly, since `find_schema_path` already
covers both the bare-`contracts/` and `contracts/schemas/` layouts P0-02 left open.

Ambiguities this file resolves (CLAUDE.md: "apply the PRD's stated default, log it, keep going";
also reported to the user, not just logged here, since these are new structures the PRD does not
pin down):

- `contracts/events/registry.yaml`'s internal shape (a list under a `types` key, a mapping under
  `types`, or a bare top-level mapping) is not specified anywhere the ticket points to. This file
  accepts all three in `registry_entries()` so the ticket is free to pick any of them without an
  unrelated test failure; only the *content* the ticket's own field list asks for -- `family`,
  `verb`, `priority`, `default_severity`, `side_effect`, `world_effect`, `hud_effect`,
  `story_template`, `trace_row`, `data_schema`, `fixture`, `pillar` -- is asserted, using those
  exact snake_case names (the ticket's prose "story template", "data schema path", "fixture
  path" rendered the repo's existing snake_case convention, e.g. `world_id`, `action_type`).
- Fixture *file names* under `contracts/fixtures/events/valid/` are not specified, unlike the
  `<name>/valid|invalid` fixtures ADR-0002 already fixes for the CP0 set. Tests here index valid
  event fixtures by their own `type` field instead of assuming a file-naming scheme, so the
  ticket is free to name files however it likes.
- `TiloEvent.trace`'s sub-fields (`model_role`, `profile`, `tokens_in`, `tokens_out`, `tool`,
  `latency_ms`, `archive_ref`) are not marked "or null" in PRD 9.3 the way `level`, `district`,
  `item`, `cause` and `authz` are, but most registered types (for example `world.requested`,
  caused by a person, not a model) have no model call to report. The default built here treats
  `trace` itself as a required object (matching every other PRD 9.3 field, and ADR-0002's "every
  object shape is a named $defs entry" plus card.schema.json's precedent of requiring even its
  nullable `gate`/`consent` keys) whose seven sub-fields are each nullable.
- `actor`/`target` are described only as "ids" (PRD 9.3), not tied to one of common.schema.json's
  id kinds. The sample event below uses a plausible agent id and building id; no test in this
  ticket asserts a stricter shape for them, since per-type actor/target rules belong to the
  registry-driven validator (P1), not this generic-shape contract.
- Consent card option ids: ADR-0002/card.rules.md numbers rules CR-01 to CR-12; there is no
  CR-13 yet. `security-reviewer`'s project memory (round 5, contracts-review-patterns.md) asks
  for the same closed-id-plus-fixed-label treatment CR-07 already gives gate cards. This file
  provisionally calls it CR-13 pending the architect's own numbering, and picks the closed set
  `{"connect", "hold"}` (keeping the id `contracts/fixtures/card/valid/consent_drive_folder.json`
  already ships) with fixed labels `Connect` and `Hold` (mirroring the gate's `hold` label
  exactly, for the same "That connection waits" pattern, BQ-15).
"""

from __future__ import annotations

import pathlib
import re
from typing import Any

import yaml
from _lib import contracts_dir, load_json

PRD_PATH_REL = "docs/prd/tilo-prd-v2.md"

_SECTION_HEADER = re.compile(r"^### 9\.5 Event registry\s*$")
_NEXT_HEADER = re.compile(r"^### ")
_BACKTICK = re.compile(r"`([a-z_]+)`")

EVENT_ROOT_FIELDS: tuple[str, ...] = (
    "v",
    "id",
    "seq",
    "ts",
    "world_id",
    "run_id",
    "type",
    "actor",
    "target",
    "level",
    "district",
    "item",
    "severity",
    "credits",
    "summary",
    "cause",
    "vis",
    "authz",
    "data",
    "trace",
)

TRACE_FIELDS: tuple[str, ...] = (
    "model_role",
    "profile",
    "tokens_in",
    "tokens_out",
    "tool",
    "latency_ms",
    "archive_ref",
)

SEVERITIES: tuple[str, ...] = ("info", "fyi", "nudge", "needs_you", "blocked", "gate")

REGISTRY_ENTRY_FIELDS: tuple[str, ...] = (
    "family",
    "verb",
    "priority",
    "default_severity",
    "side_effect",
    "world_effect",
    "hud_effect",
    "story_template",
    "trace_row",
    "data_schema",
    "fixture",
    "pillar",
)

OUTBOX_REQUIRED_FIELDS: tuple[str, ...] = (
    "id",
    "idempotency_key",
    "world_id",
    "run_id",
    "action_type",
    "connector",
    "recipients",
    "attachments",
    "item",
    "destination",
    "modifiers",
    "risk_tier",
    "authz",
    "undo_window_s",
    "scheduled_at",
    "state",
    "created_at",
)

OUTBOX_STATES: tuple[str, ...] = ("queued", "scheduled", "sending", "sent", "cancelled", "failed")


def prd_path(repo_root: pathlib.Path) -> pathlib.Path:
    return repo_root / PRD_PATH_REL


def parse_prd_9_5_types(repo_root: pathlib.Path) -> list[str]:
    """Parse PRD 9.5's "Family | Types | World effect" table into a sorted list of
    "family.verb" strings, e.g. "world.requested" ... "app.refreshed".

    Family cells with a "(+)" suffix (new types) have it stripped; a family cell listing several
    families ("level, district") produces one "family.verb" per family, per verb.
    """
    text = prd_path(repo_root).read_text(encoding="utf-8")
    lines = text.splitlines()
    starts = [i for i, line in enumerate(lines) if _SECTION_HEADER.match(line)]
    if not starts:
        raise AssertionError(f"PRD 9.5: could not find the '### 9.5 Event registry' heading in {prd_path(repo_root)}")
    start = starts[0]
    types: set[str] = set()
    for line in lines[start + 1 :]:
        if _NEXT_HEADER.match(line):
            break
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue
        family_cell, types_cell = cells[0], cells[1]
        if family_cell == "Family" or set(family_cell) == {"-"}:
            continue
        families = [f.replace("(+)", "").strip() for f in family_cell.split(",")]
        verbs = _BACKTICK.findall(types_cell)
        for fam in families:
            for verb in verbs:
                types.add(f"{fam}.{verb}")
    if not types:
        raise AssertionError("PRD 9.5: parsed zero event types out of the table -- parser or table format changed")
    return sorted(types)


def events_dir(repo_root: pathlib.Path) -> pathlib.Path:
    return contracts_dir(repo_root) / "events"


def registry_yaml_path(repo_root: pathlib.Path) -> pathlib.Path:
    return events_dir(repo_root) / "registry.yaml"


def registry_schema_path(repo_root: pathlib.Path) -> pathlib.Path:
    return events_dir(repo_root) / "registry.schema.json"


def data_schema_path(repo_root: pathlib.Path, type_: str) -> pathlib.Path:
    return events_dir(repo_root) / "data" / f"{type_}.schema.json"


def event_fixtures_dir(repo_root: pathlib.Path, kind: str) -> pathlib.Path:
    assert kind in ("valid", "invalid")
    return contracts_dir(repo_root) / "fixtures" / "events" / kind


def list_event_fixtures(repo_root: pathlib.Path, kind: str) -> list[pathlib.Path]:
    d = event_fixtures_dir(repo_root, kind)
    if not d.is_dir():
        return []
    return sorted(d.glob("*.json"))


def valid_event_fixtures_by_type(repo_root: pathlib.Path) -> dict[str, list[pathlib.Path]]:
    """Index contracts/fixtures/events/valid/*.json by each fixture's own `type` field,
    rather than assuming a file-naming convention (see module docstring)."""
    out: dict[str, list[pathlib.Path]] = {}
    for path in list_event_fixtures(repo_root, "valid"):
        try:
            instance = load_json(path)
        except (OSError, ValueError):
            continue
        type_ = instance.get("type") if isinstance(instance, dict) else None
        if isinstance(type_, str):
            out.setdefault(type_, []).append(path)
    return out


def load_registry_raw(repo_root: pathlib.Path) -> Any:
    path = registry_yaml_path(repo_root)
    if not path.is_file():
        return None
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def registry_entries(registry: Any) -> dict[str, dict[str, Any]]:
    """Normalise registry.yaml's top-level shape into {type: attrs}. Accepts a `types` list of
    dicts each carrying `type`, a `types` mapping of type -> attrs, or a bare top-level mapping
    of type -> attrs (see module docstring)."""
    if registry is None:
        return {}
    container = registry.get("types", registry) if isinstance(registry, dict) else registry
    out: dict[str, dict[str, Any]] = {}
    if isinstance(container, list):
        for entry in container:
            if isinstance(entry, dict) and isinstance(entry.get("type"), str):
                out[entry["type"]] = entry
    elif isinstance(container, dict):
        for key, val in container.items():
            if isinstance(val, dict):
                out[val.get("type", key)] = val
    return out


def sample_event(type_: str, **overrides: Any) -> dict[str, Any]:
    """A minimal, schema-plausible TiloEvent v1 instance per PRD 9.3 (see module docstring for
    the ambiguities this default resolves)."""
    base: dict[str, Any] = {
        "v": "1.0",
        "id": "01J8Z3K4M5N6P7Q8R9S0T1V2W3",
        "seq": 1,
        "ts": "2026-09-29T09:30:00.000Z",
        "world_id": "w_01",
        "run_id": "r_01J8Z3K4M5",
        "type": type_,
        "actor": "A_dir1",
        "target": "B0001",
        "level": None,
        "district": None,
        "item": None,
        "severity": "info",
        "credits": 0,
        "summary": "Something happened.",
        "cause": None,
        "vis": "all",
        "authz": None,
        "data": {},
        "trace": {field: None for field in TRACE_FIELDS},
    }
    base.update(overrides)
    return base


def sample_authz(**overrides: Any) -> dict[str, Any]:
    base = {"by": "person", "ref": "u_owner", "at": "2026-09-29T09:30:00.000Z"}
    base.update(overrides)
    return base


def sample_outbox_entry(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "01J8Z3K4M5N6P7Q8R9S0T1V2W4",
        "idempotency_key": "run-r_01J8Z3K4M5-step-1",
        "world_id": "w_01",
        "run_id": "r_01J8Z3K4M5",
        "action_type": "send_email",
        "connector": "gmail",
        "recipients": ["riya@example.com"],
        "attachments": [],
        "item": {"artifact_id": "art_reply_draft", "version": 1},
        "destination": "thread-supplier-1",
        "modifiers": [],
        "risk_tier": "T2",
        "authz": sample_authz(),
        "undo_window_s": 60,
        "scheduled_at": "2026-09-29T09:31:00.000Z",
        "state": "scheduled",
        "created_at": "2026-09-29T09:30:00.000Z",
    }
    base.update(overrides)
    return base
