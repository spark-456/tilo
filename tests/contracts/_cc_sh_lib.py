"""Shared helpers for ticket CC-SH acceptance tests (test-writer split; PRD 8.1, 8.3, 8.5, 8.6,
13.1, 13.3, 13.5, 15.2; GitHub issues #3, #4, #5, all `spark-456/tilo`).

Not a test module itself (leading underscore keeps pytest from collecting it), same convention
as `_lib.py` and `_events_lib.py`. Builds on `_lib.py` (schema loading, `$ref` resolution,
fixture helpers) rather than duplicating it.

This ticket adds three new contract files that do not exist yet on this branch
(`contracts/agents.schema.json`, `contracts/decision.schema.json`,
`contracts/manifest.schema.json`), a field on an existing one (`question.answered`'s
`data.decision_id`), and two new shipped config files (`config/agents.yaml`,
`config/teams.yaml`, the second an example array of `team_lead.schema.json` entries --
`contracts/team_lead.schema.json` already exists on `feat/P0-03-event-contract`, ticket P4-01).
None of the new schema/config files are created by this test-writer pass (CLAUDE.md: builders
own `contracts/`, test-writer commits tests and fixtures only) -- every test below must fail now
because the file it asserts on is missing, per the test-writer brief ("tests must fail now for
the right reason: missing module or wrong behaviour, not a syntax error").

`contracts/agents.schema.json` and `contracts/decision.schema.json` are deliberately NOT added
to `_lib.py`'s `SCHEMA_NAMES` tuple: that tuple's own docstring scopes it to "the CP0 contract
set ticket P0-02 owns", and reusing it here would also silently pull these two names into every
other test module that parametrizes over `SCHEMA_NAMES` (P0-02's, not this ticket's). Ambiguity
resolved per CLAUDE.md ("apply the PRD's stated default, log it, keep going"): this file defines
its own `CC_SH_SCHEMA_NAMES` and each test file below writes its own fixtures/generated-types/
drift tests mirroring the pattern `test_FR_WLD_03_outbox_contract.py` and
`test_FR_WLD_03_generated_types_cover_events.py` already established for `outbox` and `event`
(also new contracts added after the CP0 set), instead of extending P0-02's tuple. Logged in the
report, not in `docs/open-questions.md` (a production doc this pass does not touch).

Sample builders below (`sample_agents_config`, `sample_decision`, `sample_manifest`) are
schema-plausible instances built from GitHub issues #3, #4 and #5 verbatim, using id shapes and
`$defs` already frozen in `contracts/common.schema.json`, `contracts/providers.schema.json` and
`contracts/event.schema.json` (BQ-01 `authz`; `artifact_ref`; `trace.model_role` /
`trace.profile`'s use of `common.schema.json#/$defs/slug` and
`providers.schema.json#/$defs/profile_id`) so a builder implementing the same conventions is
expected to make them valid without this file changing.
"""

from __future__ import annotations

import pathlib
from typing import Any

from _lib import contracts_dir

# New contract roots this ticket adds -- not in _lib.SCHEMA_NAMES, see module docstring.
CC_SH_SCHEMA_NAMES: tuple[str, ...] = ("agents", "decision", "manifest")

CONFIG_DIR_REL = "config"


def config_dir(repo_root: pathlib.Path) -> pathlib.Path:
    return repo_root / CONFIG_DIR_REL


def agents_yaml_path(repo_root: pathlib.Path) -> pathlib.Path:
    return config_dir(repo_root) / "agents.yaml"


def teams_yaml_path(repo_root: pathlib.Path) -> pathlib.Path:
    return config_dir(repo_root) / "teams.yaml"


def cc_sh_fixtures_dir(repo_root: pathlib.Path, name: str, kind: str) -> pathlib.Path:
    assert kind in ("valid", "invalid")
    return contracts_dir(repo_root) / "fixtures" / name / kind


def list_cc_sh_fixtures(repo_root: pathlib.Path, name: str, kind: str) -> list[pathlib.Path]:
    d = cc_sh_fixtures_dir(repo_root, name, kind)
    return sorted(d.glob("*.json")) if d.is_dir() else []


def sample_agents_config(**overrides: Any) -> dict[str, Any]:
    """Issue #3's proposed `config/agents.yaml` shape, verbatim defaults."""
    base: dict[str, Any] = {
        "limits": {
            "directors_per_world": 1,
            "leads_per_district": 1,
            "max_specialists": 6,
            "max_depth": 3,
        },
        "context": {"compact_at": 0.60, "handoff_at": 0.70},
        "liveness": {"heartbeat_s": 15, "silent_after_s": 90},
        "retries": {"max_attempts": 3},
        "questions": {"hourly_cap_per_person": 6},
    }
    base.update(overrides)
    return base


def sample_authz(**overrides: Any) -> dict[str, Any]:
    base = {"by": "person", "ref": "u_owner", "at": "2026-09-29T09:30:00.000Z"}
    base.update(overrides)
    return base


def sample_decision(**overrides: Any) -> dict[str, Any]:
    """Issue #4's Decision entity (PRD 15.1: "question, answer, answered by, scope, expiry")."""
    base: dict[str, Any] = {
        "id": "01J8Z3K4M5N6P7Q8R9S0T1V2W5",
        "org_id": "org_acme",
        "question": "May Tilo reply to suppliers outside business hours?",
        "domain": "security",
        "answer": "Yes, for suppliers already in the CRM; escalate anyone new.",
        "option_id": "approve",
        "answered_by": sample_authz(),
        "source": {
            "world_id": "w_village_basic",
            "run_id": "r_village_basic_1",
            "card_id": "01J8Z3K4M5N6P7Q8R9S0T1V2W1",
        },
        "scope": {"worlds": "all", "districts": "all"},
        "created_at": "2026-09-29T09:30:00.000Z",
        "expires_at": None,
    }
    base.update(overrides)
    return base


def sample_team_lead(**overrides: Any) -> dict[str, Any]:
    """Matches contracts/team_lead.schema.json (already on this branch, ticket P4-01) --
    the shape config/teams.yaml's entries must take (issue #4 section 3)."""
    base: dict[str, Any] = {
        "id": "tl_security",
        "user": "u_security_lead",
        "domain": "security",
        "assigned_by": {"by": "u_owner", "at": "2026-09-29T09:00:00.000Z"},
    }
    base.update(overrides)
    return base


def sample_manifest(**overrides: Any) -> dict[str, Any]:
    """Issue #5's provenance manifest fields, verbatim."""
    base: dict[str, Any] = {
        "v": "1.0",
        "artifact": {"artifact_id": "art_eval_deck", "version": 2},
        "content_sha256": "a" * 64,
        "parents": [{"artifact_id": "art_eval_deck", "version": 1}],
        "produced_by": {
            "agent_id": "A_writer1",
            "role": "writer",
            "skill": {"id": "deck-writing", "version": "0.1.0"},
            "model_role": "writer",
            "profile": "flash-37",
        },
        "inputs": [{"artifact_id": "art_research_table", "version": 1}],
        "sources": [
            {
                "id": "src1",
                "kind": "web",
                "ref": "https://example.com/quarterly-report",
                "fingerprint": "sha256:" + "b" * 64,
                "fetched_at": "2026-09-29T09:00:00.000Z",
            }
        ],
        "claims": [
            {
                "id": "cl1",
                "location": "slide3/cell:B2",
                "text": "Revenue grew 12% quarter over quarter.",
                "source_ids": ["src1"],
                "verified": True,
            }
        ],
        "events": ["01J8Z3K4M5N6P7Q8R9S0T1V2W6"],
        "authz": sample_authz(),
    }
    base.update(overrides)
    return base
