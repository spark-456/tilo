"""PL-LIVE-E2E (issue #340): what `just live-e2e` reports, the events it emits, and where model ids may appear.

PRD 6.4 PL-01 ("Lint fails on any model id outside config/ and packages/providers"), 9.4 HR-1 / 9.5 (every event type
registered, with a fixture), 14.1 (credits), 16.1 rule 4 (no secrets in logs or reports), EFF-01, GEN-a (issue #272).

Criteria covered:
  (1) the report gives, per stage and role, calls, tokens, credits and latency; the outcome class; the event count;
      the GEN-a structural checks applied to the live run; total and cap; in text and as JSON (`--report-json`);
  (2) every event the run emits is a registered type with a fixture and validates against its schema;
  (3) model ids appear only through configuration: not in the new code, not in the committed fixture, not in the
      report (it names profiles); the report never carries a provider's own error text (it can echo a credential).
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

import pytest
import yaml
from _live_e2e_lib import (
    ESTIMATE_RE,
    REAL_MODELS,
    REPO_ROOT,
    SECRET_RE,
    fake_secret,
    live_e2e,
    live_run,
    network_guard,  # noqa: F401  (autouse fixture)
    run_direct,
    world_for,
)
from tilo_evals.bank_checks import CHECKS
from tilo_harness.validator import repo_validator
from tilo_providers.errors import ProviderError

REGISTRY = yaml.safe_load((REPO_ROOT / "contracts" / "events" / "registry.yaml").read_text(encoding="utf-8"))["types"]
FAMILY = re.compile(r"\b(?:gemini|gemma|gpt|claude|llama|mistral|nemotron)-[A-Za-z0-9][A-Za-z0-9_.\-]*")


def test_PL_LIVE_E2E_24_the_text_report_lists_the_estimate_rows_outcome_events_checks_and_total(
    tmp_path: Path,
) -> None:
    result, world, _ = live_run(tmp_path)
    assert result.code == 0, result.err
    lines = result.out_lines()
    assert ESTIMATE_RE.match(lines[0])  # the estimate comes first
    mode = result.mode()
    assert mode and mode["mode"] == "live" and mode["case"] == "B-007"
    rows = result.rows()
    assert {(m["stage"], m["role"]) for m in rows} >= {
        ("intake", "director"),
        ("run", "writer"),
        ("narrate", "narrator"),
    }
    assert sum(int(m["calls"]) for m in rows) == len(world.calls)
    outcome = result.outcome()
    assert outcome and outcome["outcome"] == "completed" and int(outcome["events"]) > 0
    # the GEN-a structural checks, one line each, none with a finding on a good run
    checks = result.checks()
    assert set(checks) >= {fn.__name__ for fn in CHECKS}
    assert all(n == 0 for name, n in checks.items() if name != "delivers_something")
    total = result.total()
    assert total is not None
    assert float(total["credits"]) == pytest.approx(sum(float(m["credits"]) for m in rows), abs=1e-3)


def test_PL_LIVE_E2E_24_the_json_report_has_the_same_facts_and_a_stable_shape(tmp_path: Path) -> None:
    path = tmp_path / "report.json"
    result, world, _ = live_run(tmp_path, extra_args=("--report-json", str(path)))
    assert result.code == 0, result.err
    data = json.loads(path.read_text(encoding="utf-8"))
    assert {
        "case_id", "mode", "outcome_class", "reason", "cap_credits", "total_credits", "event_count", "event_types",
        "rows", "checks", "questions", "answered", "estimate", "story_lines", "side_effects",
    } <= set(data)  # fmt: skip
    assert data["case_id"] == "B-007" and data["mode"] == "live" and data["outcome_class"] == "completed"
    assert data["outcome_class"] in live_e2e().OUTCOME_CLASSES
    assert data["cap_credits"] == 40.0 and data["side_effects"] == "mock_only"
    assert data["event_count"] == len(data["event_types"]) > 0
    assert set(data["checks"]) >= {fn.__name__ for fn in CHECKS}
    assert all(data["checks"][name] == [] for name in data["checks"] if name != "delivers_something")
    assert 0 < data["estimate"]["credits_low"] <= data["estimate"]["credits_high"]
    keys = {"stage", "role", "profile", "calls", "tokens_in", "tokens_out", "credits", "latency_ms"}
    assert data["rows"] and all(set(row) == keys for row in data["rows"])
    assert math.isclose(data["total_credits"], sum(row["credits"] for row in data["rows"]), abs_tol=1e-3)
    assert sum(row["calls"] for row in data["rows"]) == len(world.calls)
    assert data["total_credits"] <= data["cap_credits"]


@pytest.mark.parametrize("case_id", ["B-007", "B-016", "B-005"])
def test_PL_LIVE_E2E_25_every_event_the_run_emits_is_registered_fixtured_and_valid(
    case_id: str, tmp_path: Path
) -> None:
    report, _ = run_direct(tmp_path, case=case_id)
    assert report.events, "the run emitted no event"
    validator = repo_validator()
    for event in report.events:
        assert event["type"] in REGISTRY, f"unregistered event type {event['type']!r} (EV-01)"
        fixture = REPO_ROOT / "contracts" / REGISTRY[event["type"]]["fixture"]
        assert fixture.is_file(), f"{event['type']} has no fixture"
        assert validator.problems(event) == [], (event["type"], validator.problems(event)[:2])


def test_PL_LIVE_E2E_26_model_ids_appear_only_through_config_not_in_the_new_code_fixtures_or_report(
    tmp_path: Path,
) -> None:
    configured = {p["model"] for p in yaml.safe_load(REAL_MODELS.read_text(encoding="utf-8"))["profiles"].values()}
    configured = {m for m in configured if not m.startswith("fake-")}
    assert configured, "config/models.yaml names no model"
    new_code = [
        *sorted((REPO_ROOT / "evals" / "src" / "tilo_evals").glob("*.py")),
        *sorted((REPO_ROOT / "evals" / "scripts").glob("*.py")),
        *sorted(  # adhoc/: `just live-run` recordings of the user's own topics, git-ignored and never committed
            p for p in (REPO_ROOT / "evals" / "bank" / "live").rglob("*.json") if "adhoc" not in p.parent.parts
        ),
    ]
    assert any(path.name == "live_e2e.py" for path in new_code), "tilo_evals/live_e2e.py or the script does not exist"
    for path in new_code:
        text = path.read_text(encoding="utf-8")
        assert not FAMILY.search(text), f"{path} names a model id (PL-01)"
        assert not [m for m in configured if m in text], f"{path} names a configured model id (PL-01)"
    report_path = tmp_path / "report.json"
    result, _, _ = live_run(tmp_path, extra_args=("--report-json", str(report_path)))
    blob = result.everything + report_path.read_text(encoding="utf-8")
    assert not FAMILY.search(blob) and not [m for m in configured if m in blob]  # profiles are named, models never


def test_PL_LIVE_E2E_27_a_providers_own_error_text_never_reaches_the_report_or_the_logs(tmp_path: Path) -> None:
    secret = fake_secret("access_token")
    world = world_for(fail_roles={"director": ProviderError(f"permission denied for {secret} {fake_secret('bearer')}")})
    report_path = tmp_path / "report.json"
    result, _, _ = live_run(tmp_path, world=world, extra_args=("--report-json", str(report_path)))
    assert result.code == 1  # the run failed honestly: nothing was done
    blob = result.everything + report_path.read_text(encoding="utf-8")
    assert secret not in blob and "fakeBearerValue" not in blob and not SECRET_RE.search(blob)
    outcome = result.outcome()
    assert outcome and outcome["outcome"] != "completed"
    assert json.loads(report_path.read_text(encoding="utf-8"))["outcome_class"] != "completed"
