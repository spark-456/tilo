"""Shared helpers for ticket CC-SE acceptance tests (test-writer split; PRD 14.1, 14.2, 14.4, 14.5,
6.6, 17.3, 2.4; GitHub issues #7-#12, all `spark-456/tilo`).

Not a test module itself (leading underscore keeps pytest from collecting it), same convention as
`_lib.py`, `_events_lib.py` and `_cc_sh_lib.py`. Builds on `_lib.py` (schema loading, `$ref`
resolution, fixture helpers) rather than duplicating it.

This ticket adds five new contract files that do not exist yet on this branch
(`contracts/metering.schema.json`, `contracts/evals.schema.json`, `contracts/attention.schema.json`,
`contracts/pilot.schema.json`, `contracts/meter.schema.json`), a minor-version bump to an existing
one (`contracts/events/data/budget.requested.schema.json` 1.0.0 -> 1.1.0), and two new shipped
config files (`config/metering.yaml`, `config/evals.yaml`). None of these are created by this
test-writer pass (CLAUDE.md: builders own `contracts/` and `config/`; test-writer commits tests and
fixtures only) -- every test below must fail now because the file or field it asserts on is missing
or not yet at the new version, per the test-writer brief ("tests must fail now for the right
reason: missing module or wrong behaviour, not a syntax error").

Sample builders below are schema-plausible instances built from GitHub issues #7-#11 verbatim
(`sample_metering_config` mirrors `packages/metering/tests/data/metering.stub.yaml` and
`packages/metering/src/tilo_metering/config.py`'s `MeteringConfig`, already merged on this branch
per ticket P8-01a; `sample_evals_config` mirrors `evals/src/tilo_evals/config.py`'s `EvalsConfig`,
already merged per ticket P8-06a), using id shapes and `$defs` already frozen in
`contracts/common.schema.json` and `contracts/event.schema.json` (BQ-01 `authz`; `credits`;
`credit_range`; `unit_id`) so a builder implementing the same conventions is expected to make them
valid without this file changing.

Ambiguities this file resolves (CLAUDE.md: "apply the PRD's stated default, log it, keep going"):

- Issue #9's `budget.requested` 1.1.0 change makes `remaining_units` and `estimate` required,
  though it offers "If you prefer, make the two new fields optional" as an alternative. The
  issue's own "Proposed shape" (the stated default) requires both, and PRD 14.1's acceptance test
  ("The request card shows remaining plan and a new estimate") implies both are always present
  when the event fires, so this file's `sample_budget_requested_data_v1_1` and the tests built on
  it require both fields. Logged in the report, not `docs/open-questions.md` (a production doc this
  pass does not touch).
- `contracts/pilot.schema.json`'s root shape is not specified by issue #11 beyond its five `$defs`.
  Mirrors `common.schema.json`'s own documented convention (ADR-0002 decision 3: "Its root is a
  sampler with one optional property per definition... nothing sends a `Common` document") since
  no single "pilot" document is ever sent either -- each record (`consent`, `tag`, `diary_entry`,
  `survey_response`) is written on its own.
- `pilot.tag.ref` is described only as "Card id, artifact id or run id" is not stated; issue #11
  says a `tag` "tags a run id or card id". This file's sample treats `ref` as either a `run_id` or
  a `ulid` (card ids are ULIDs elsewhere in the repo, e.g. `sample_decision`'s `card_id` in
  `_cc_sh_lib.py`), and tests assert only that both shapes are accepted, not that a third shape is
  rejected (issue #11 does not rule one out).
- `attention.ref` (issue #10: "Card id, artifact id or null for intake") is modelled the same way:
  tests assert a ULID and `null` both validate, without asserting an artifact id's shape, which the
  issue does not pin down beyond "artifact id".
"""

from __future__ import annotations

import pathlib
from typing import Any

from _lib import contracts_dir

# New contract roots this ticket adds -- not in _lib.SCHEMA_NAMES, see module docstring.
CC_SE_SCHEMA_NAMES: tuple[str, ...] = ("metering", "evals", "attention", "pilot", "meter")

CONFIG_DIR_REL = "config"


def config_dir(repo_root: pathlib.Path) -> pathlib.Path:
    return repo_root / CONFIG_DIR_REL


def metering_yaml_path(repo_root: pathlib.Path) -> pathlib.Path:
    return config_dir(repo_root) / "metering.yaml"


def evals_yaml_path(repo_root: pathlib.Path) -> pathlib.Path:
    return config_dir(repo_root) / "evals.yaml"


def cc_se_fixtures_dir(repo_root: pathlib.Path, name: str, kind: str) -> pathlib.Path:
    assert kind in ("valid", "invalid")
    return contracts_dir(repo_root) / "fixtures" / name / kind


def list_cc_se_fixtures(repo_root: pathlib.Path, name: str, kind: str) -> list[pathlib.Path]:
    d = cc_se_fixtures_dir(repo_root, name, kind)
    return sorted(d.glob("*.json")) if d.is_dir() else []


# ---------------------------------------------------------------------------
# config/metering.yaml (issue #7, FR-MTR-02, -03, -04, -08)
# ---------------------------------------------------------------------------


def sample_metering_config(**overrides: Any) -> dict[str, Any]:
    """Issue #7's proposed `config/metering.yaml` shape with the PRD 14.1/17.3 demo defaults,
    matching `packages/metering/tests/data/metering.stub.yaml` (already merged, ticket P8-01a) and
    BQ-42's decision (`org_day_credits: null`, no separate per-org cap)."""
    base: dict[str, Any] = {
        "treasury": {"reserve_margin": 0.15, "request_at": 0.80},
        "caps": {"run_credits": 300, "user_day_credits": 1500, "org_day_credits": None},
        "spend": {"daily_usd_soft": 15, "daily_usd_hard": 25},
        "reconciliation": {"tolerance": 0.10, "billing_services": []},
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# config/evals.yaml (issue #8, EFF-06, EFF-07)
# ---------------------------------------------------------------------------

# PRD 19.2's eval set table: group -> case count, summing to 170.
PRD_19_2_GROUPS: dict[str, int] = {
    "E-PLAN": 10,
    "E-RES": 10,
    "E-DOC": 6,
    "E-MAIL": 50,
    "E-CHN": 30,
    "E-ROUTE": 20,
    "E-HAND": 20,
    "E-RED": 14,
}


def sample_evals_config(**overrides: Any) -> dict[str, Any]:
    """Issue #8's proposed `config/evals.yaml` shape; credit caps are BQ-43's decided placeholders
    (full 2,000, smoke 200, gate 1,000 credits), `deploy_gate_repeats` is PRD 19.2's "three times",
    `cost_regression_threshold` is EFF-06's 20%, and `groups` is PRD 19.2's case-count table."""
    base: dict[str, Any] = {
        "credit_cap": {"full": 2000, "smoke": 200, "gate": 1000},
        "deploy_gate_repeats": 3,
        "cost_regression_threshold": 0.20,
        "groups": dict(PRD_19_2_GROUPS),
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# contracts/events/data/budget.requested.schema.json 1.1.0 (issue #9, FR-MTR-03)
# ---------------------------------------------------------------------------


def sample_budget_requested_data_v1_1(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "requested": 20,
        "spent": 32,
        "cap": 40,
        "remaining_units": [
            {"unit_id": "U0012", "title": "Draft supplier reply"},
            {"unit_id": "U0013", "title": "Chart Q3 spend"},
        ],
        "estimate": {"min": 55, "max": 68},
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# contracts/attention.schema.json (issue #10, FR-MTR-05)
# ---------------------------------------------------------------------------

ATTENTION_KINDS: tuple[str, ...] = ("intake", "question", "card", "take_over", "review")


def sample_attention_span(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "01J8Z3K4M5N6P7Q8R9S0T1V2W7",
        "world_id": "w_village_basic",
        "run_id": "r_village_basic_1",
        "user": "u_owner",
        "kind": "question",
        "started_at": "2026-09-29T09:30:00.000Z",
        "ended_at": "2026-09-29T09:31:40.000Z",
        "ref": "01J8Z3K4M5N6P7Q8R9S0T1V2W1",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# contracts/pilot.schema.json (issue #11, FR-MTR-09, PRD 2.4, 16.5)
# ---------------------------------------------------------------------------


def sample_pilot_tester_id() -> str:
    return "t_r7k2m9pz"


def sample_pilot_consent(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "tester_id": sample_pilot_tester_id(),
        "study": "EV-G3",
        "consented_at": "2026-10-10T09:00:00.000Z",
        "keep_data": False,
        "delete_after": "2026-11-11",
    }
    base.update(overrides)
    return base


def sample_pilot_tag(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "tester_id": sample_pilot_tester_id(),
        "kind": "run",
        "ref": "r_village_basic_1",
    }
    base.update(overrides)
    return base


def sample_pilot_diary_entry(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "tester_id": sample_pilot_tester_id(),
        "date": "2026-10-10",
        "day": 1,
        "minutes_saved_self": 25,
        "trust": 4,
        "reinvested": "Used the time to call a supplier back.",
        "submitted_at": "2026-10-10T18:00:00.000Z",
    }
    base.update(overrides)
    return base


def sample_pilot_survey_response(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "tester_id": sample_pilot_tester_id(),
        "submitted_at": "2026-10-12T09:00:00.000Z",
        "trust": 5,
        "reinvested_share": 0.5,
        "reinvested_how": "Spent it on customer calls instead of drafting replies.",
        "quote": "It felt like having a second pair of hands.",
        "quote_consent": True,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# contracts/meter.schema.json (issue #12, FR-MTR-07)
# ---------------------------------------------------------------------------


def sample_meter_state(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "run_id": "r_village_basic_1",
        "last_seq": 105,
        "credits_used": 32,
        "credits_saved": 4.5,
        "time_saved": {
            "minutes": 12.5,
            "low": 8.0,
            "high": 18.0,
            "steering_measured": True,
            "method_url": "https://tilo.example/docs/time-saved-method",
        },
        "budget": {"cap": 40, "spent": 32, "reserved": 6.9},
    }
    base.update(overrides)
    return base
