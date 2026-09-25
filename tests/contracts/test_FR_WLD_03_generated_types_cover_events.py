"""FR-WLD-03 (PRD 9.8 acceptance test: "Coverage test at 100% of registered types") plus ticket
P0-03 section 7: "extend the generator so Python and TypeScript get the event, per-type data
payloads (TS: a discriminated union on `type`), registry constants and the outbox type; keep
`just contracts-check` failing on drift."

Mirrors `test_FR_WLD_02_generated_types_exist.py` and `test_FR_WLD_02_contracts_check_drift.py`
(P0-02) rather than duplicating their machinery: the drift-on-a-temp-copy helpers are imported
from that module (both live in `tests/contracts/`, which is on `sys.path` per `conftest.py`'s
docstring), so a schema drift here is caught by the exact same mechanism P0-02 already proved
works, without re-implementing the subprocess/tmp_path plumbing.

The 100%-coverage check is the cheapest one available without assuming datamodel-code-generator's
or json-schema-to-typescript's exact output shape: every PRD 9.5 "family.verb" string must appear
as a quoted literal somewhere in the generated TypeScript, since a discriminated union on `type`
needs each member's literal string type at least once.
"""

from __future__ import annotations

import json
import re

import pytest
from _events_lib import parse_prd_9_5_types
from test_FR_WLD_02_contracts_check_drift import _copy_runnable_repo, _run_contracts_check

CONTRACTS_PY_SRC = "packages/contracts-py/src"
CONTRACTS_TS_SRC = "packages/contracts-ts/src"


def _pascal(name: str) -> str:
    return "".join(part[:1].upper() + part[1:] for part in name.split("_") if part)


def test_FR_WLD_03_generated_python_type_exists_for_event(repo_root):
    src = repo_root / CONTRACTS_PY_SRC
    assert src.is_dir(), f"FR-WLD-03: {CONTRACTS_PY_SRC}/ must exist (ticket P0-02 already requires this)"
    pattern = re.compile(r"\bclass\s+Event\b")
    hit = any(pattern.search(p.read_text(encoding="utf-8", errors="ignore")) for p in src.rglob("*.py"))
    assert hit, (
        f"FR-WLD-03: no generated Python class 'Event' found under {CONTRACTS_PY_SRC}/ for contracts/event.schema.json"
    )


def test_FR_WLD_03_generated_typescript_type_exists_for_event(repo_root):
    src = repo_root / CONTRACTS_TS_SRC
    assert src.is_dir(), f"FR-WLD-03: {CONTRACTS_TS_SRC}/ must exist (ticket P0-02 already requires this)"
    pattern = re.compile(r"\b(?:interface|type)\s+Event\b")
    ts_files = list(src.rglob("*.ts")) + list(src.rglob("*.d.ts"))
    hit = any(pattern.search(p.read_text(encoding="utf-8", errors="ignore")) for p in ts_files)
    assert hit, f"FR-WLD-03: no generated TypeScript interface/type 'Event' found under {CONTRACTS_TS_SRC}/"


def test_FR_WLD_03_generated_python_type_exists_for_outbox(repo_root):
    src = repo_root / CONTRACTS_PY_SRC
    assert src.is_dir(), f"FR-WLD-03: {CONTRACTS_PY_SRC}/ must exist"
    pattern = re.compile(r"\bclass\s+Outbox\b")
    hit = any(pattern.search(p.read_text(encoding="utf-8", errors="ignore")) for p in src.rglob("*.py"))
    assert hit, (
        f"FR-WLD-03: no generated Python class 'Outbox' found under {CONTRACTS_PY_SRC}/ "
        "for contracts/outbox.schema.json"
    )


def test_FR_WLD_03_generated_typescript_type_exists_for_outbox(repo_root):
    src = repo_root / CONTRACTS_TS_SRC
    assert src.is_dir(), f"FR-WLD-03: {CONTRACTS_TS_SRC}/ must exist"
    pattern = re.compile(r"\b(?:interface|type)\s+Outbox\b")
    ts_files = list(src.rglob("*.ts")) + list(src.rglob("*.d.ts"))
    hit = any(pattern.search(p.read_text(encoding="utf-8", errors="ignore")) for p in ts_files)
    assert hit, f"FR-WLD-03: no generated TypeScript interface/type 'Outbox' found under {CONTRACTS_TS_SRC}/"


def test_FR_WLD_03_typescript_discriminated_union_covers_every_registered_type(repo_root):
    src = repo_root / CONTRACTS_TS_SRC
    assert src.is_dir(), f"FR-WLD-03: {CONTRACTS_TS_SRC}/ must exist"
    ts_files = list(src.rglob("*.ts")) + list(src.rglob("*.d.ts"))
    text = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in ts_files)
    missing = [t for t in parse_prd_9_5_types(repo_root) if f'"{t}"' not in text]
    assert not missing, (
        f"FR-WLD-03: {len(missing)}/70 registered types have no quoted literal in the generated TypeScript "
        f"(needed for a discriminated union on `type`): {missing[:10]}"
    )


@pytest.mark.slow
def test_FR_WLD_03_contracts_check_fails_on_event_data_schema_drift(repo_root, tmp_path):
    """The generator must pick up contracts/events/data/*.schema.json too, not just the
    top-level contracts/*.schema.json glob P0-02's codegen already covers (ADR-0002
    consequence: 'P0-03 adds event.schema.json and the event registry under the same
    conventions; the generator picks up any new contracts/*.schema.json automatically' --
    that sentence does not cover the nested events/data/ tree, which is this ticket's own
    section 7 extension)."""
    building_completed = repo_root / "contracts/events/data/building.completed.schema.json"
    assert building_completed.is_file(), (
        "FR-WLD-03: contracts/events/data/building.completed.schema.json must exist first"
    )

    work_dir = tmp_path / "events-drift"
    _copy_runnable_repo(repo_root, work_dir)

    rel = building_completed.relative_to(repo_root)
    mutated_path = work_dir / rel
    schema = json.loads(mutated_path.read_text(encoding="utf-8"))
    schema.setdefault("$defs", {})["drift_marker_field_not_in_generated_output"] = {"type": "string"}
    mutated_path.write_text(json.dumps(schema, indent=2), encoding="utf-8")

    result = _run_contracts_check(work_dir, repo_root / ".venv")
    assert result.returncode != 0, (
        "FR-WLD-03: `just contracts-check` must fail when a contracts/events/data/*.schema.json changes "
        f"without regeneration.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
