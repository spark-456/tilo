"""PL-LIVE-E2E (issue #340): `just live-e2e` runs a held-out bank case through the real pipeline.

PRD 6.4 PL-01..PL-03 (every call through the provider layer, by role), 6.6 EFF-01, 9.4 HR-1 (no completion without
its event), and the GEN-a bank (issue #272: `tilo_evals.bank`, `bank_checks`). With a fake provider scripted from the
case (the Director's brief, approaches and plan come from the case's own `director` data, exactly what the GEN-a bank
scripts) the run goes: intake -> questions (answers scripted from the case) -> approaches -> approve -> plan -> run
(leads, specialists and writers, the Verifier) -> narrator -> delivery, or an honest stop. It uses the same code
paths the real system uses: no code names a scenario or a case id.

Criteria covered:
  (1) the whole flow on one case, in order, ending in `world.completed` with its delivered artifact;
  (2) per stage and role calls: Director at intake, approaches and plan; Lead, writers and the Verifier in the run
      (a Lead call per milestone, fewer than one per unit); the Narrator once per world (PRD 8.1);
  (3) the questions are the Director's own and are answered from the case's `answers`;
  (4) every outcome class a case can expect (completed, held_at_gate, needs_answers, refused) ends the same way and
      passes the GEN-a hard checks; the checks have teeth (a run that misses its expected outcome is a finding);
  (5) a failed unit is a failed run: no `world.completed`, no `artifact.delivered` (HR-1);
  (6) a case renamed to a fresh id behaves identically (no special-casing by id);
  (7) models are configuration: every call names the profile `config/models.yaml` gives that role.

Ambiguity resolved (PRD 8.1, 9.4): the Narrator reply is plain text, one call for the whole run, and every Story line
carries the ids of the events it narrates (HR-1). A unit that fails is reported as `refused` or `failed`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from _live_e2e_lib import (
    REAL_MODELS,
    REAL_PRICES,
    FakeWorld,
    bank_case,
    event_types,
    is_subsequence,
    live_e2e,
    live_run,
    network_guard,  # noqa: F401  (autouse fixture)
    run_direct,
    world_for,
    write_bank,
)
from tilo_evals.bank_checks import CHECKS
from tilo_providers.config import load_providers_config
from tilo_providers.errors import ProviderError

FLOW = [
    "world.requested",
    "plan.approaches_proposed",
    "budget.granted",
    "world.started",
    "agent.spawned",
    "agent.assigned",
    "agent.working",
    "artifact.created",
    "approval.requested",
    "approval.resolved",
    "data.transfer",
    "artifact.delivered",
    "world.completed",
]


def _rows(report: Any) -> dict[tuple[str, str], Any]:
    return {(row.stage, row.role): row for row in report.rows}


def test_PL_LIVE_E2E_10_one_case_goes_through_the_whole_flow_and_completes_with_its_delivery(tmp_path: Path) -> None:
    report, world = run_direct(tmp_path)
    assert report.case_id == "B-007" and report.mode == "live"
    assert report.outcome_class == "completed", report.reason
    types = event_types(report.events)
    assert is_subsequence(FLOW, types), types
    assert types[-1] == "world.completed"
    done = next(e for e in report.events if e["type"] == "world.completed")
    assert done["data"]["deliverable_count"] == types.count("artifact.delivered") >= 1
    assert report.event_count == len(report.events) > 0
    assert [f for f in report.findings if f.hard] == []  # the GEN-a hard checks hold on the live run
    assert world.calls, "the run made no model call"
    # A live model run never reaches a real connector: the delivery and the gated send go to recording mocks only
    # (CLAUDE.md: no real email or message without the user's say-so).
    assert report.side_effects == "mock_only"


def test_PL_LIVE_E2E_10_events_are_the_pipelines_own_not_the_runners(tmp_path: Path) -> None:
    # HR-1: the report counts events the pipeline wrote; seq strictly increases and ids are unique.
    report, _ = run_direct(tmp_path)
    seqs = [e["seq"] for e in report.events]
    assert seqs == sorted(set(seqs)) and seqs[0] >= 1
    ids = [e["id"] for e in report.events]
    assert len(ids) == len(set(ids))


def test_PL_LIVE_E2E_11_calls_per_stage_and_role_cover_director_lead_writer_verifier_and_narrator(
    tmp_path: Path,
) -> None:
    module = live_e2e()
    report, world = run_direct(tmp_path)
    rows = _rows(report)
    assert {stage for stage, _ in rows} <= set(module.STAGES)
    plan_roles = {unit["role"] for unit in bank_case("B-007").director["plan"]["units"]}
    assert plan_roles == {"writer", "verifier"}
    for stage in ("intake", "approaches", "plan"):
        assert (stage, "director") in rows, sorted(rows)
        assert rows[(stage, "director")].calls == 1  # a valid reply costs one call, no repeats
    for role in plan_roles | {"lead"}:
        assert ("run", role) in rows, sorted(rows)
    assert ("narrate", "narrator") in rows
    assert rows[("narrate", "narrator")].calls == 1  # one Narrator call per world (PRD 8.1)
    units = len(bank_case("B-007").director["plan"]["units"])
    assert 1 <= rows[("run", "lead")].calls < units  # supervisors review at milestones, not every step (PRD 8.1)
    assert rows[("run", "verifier")].calls >= 1
    # every call the model saw is in exactly one row, with the fake's own token counts
    assert sum(row.calls for row in report.rows) == len(world.calls)
    for row in report.rows:
        assert row.tokens_in == row.calls * 1000 and row.tokens_out == row.calls * 500
        assert row.credits > 0 and row.latency_ms >= 5 * row.calls


def test_PL_LIVE_E2E_11_story_lines_each_cite_the_events_they_narrate(tmp_path: Path) -> None:
    report, _ = run_direct(tmp_path)  # HR-1: every Story line is caused by a recorded event
    assert report.story_lines
    known = {e["id"] for e in report.events}
    for line in report.story_lines:
        assert line.text.strip()
        assert line.event_ids and set(line.event_ids) <= known


def test_PL_LIVE_E2E_12_questions_are_the_directors_own_and_answered_from_the_case(tmp_path: Path) -> None:
    case = bank_case("B-016")
    report, world = run_direct(tmp_path, case="B-016")
    assert report.outcome_class == "completed", report.reason
    asked = case.director["brief"]["ambiguous_fields"]
    assert report.questions == len(asked) == 2
    assert report.answered == case.answers  # {"deliverables": "...", "audience": None}: skipped stays skipped
    types = event_types(report.events)
    assert "plan.questions_asked" in types
    assert types.index("plan.questions_asked") < types.index("plan.approaches_proposed")
    kinds = [call.kind for call in world.calls if call.kind in ("brief", "approaches", "plan")]
    assert kinds == ["brief", "approaches", "plan"]  # the answers came from the case, not from a model


@pytest.mark.parametrize("case_id", ["B-007", "B-005", "B-006", "B-009", "B-016"])
def test_PL_LIVE_E2E_13_every_expected_outcome_ends_the_way_the_case_says_and_passes_the_hard_checks(
    case_id: str, tmp_path: Path
) -> None:
    case = bank_case(case_id)
    report, world = run_direct(tmp_path, case=case_id)
    assert report.outcome_class == case.outcome, report.reason  # completed | held_at_gate | needs_answers | refused
    assert {fn.__name__ for fn in CHECKS} <= set(report.checks_run)
    assert [(f.check, f.detail) for f in report.findings if f.hard] == []
    if case.outcome == "held_at_gate":  # held: a person has not said yes, so nothing was sent
        assert "world.completed" not in event_types(report.events)
    if case.outcome == "needs_answers":  # stops after the questions: no approaches, no plan, no run
        assert {call.kind for call in world.calls} <= {"brief", "text"}
        assert world.roles_called() <= {"director", "narrator"}
    if case.outcome == "refused":
        assert report.reason and report.reason.strip()
    folder = tmp_path / "cli"
    folder.mkdir()
    result, _, _ = live_run(folder, case=case_id)  # the command's exit code agrees: 0 when the case ends as expected
    assert result.code == 0, result.err
    outcome = result.outcome()
    assert outcome and outcome["outcome"] == case.outcome


def test_PL_LIVE_E2E_14_the_structural_checks_have_teeth_on_a_live_run(tmp_path: Path) -> None:
    # B-007 expects `completed`. A Director that never gives a plan cannot complete it: the run stops honestly,
    # and the GEN-a `terminal_honest` check reports the mismatch as a hard finding; the command exits 1.
    script = {**bank_case("B-007").director, "plan": None}
    world = FakeWorld(script=script)
    report, _ = run_direct(tmp_path, world=world)
    assert report.outcome_class != "completed"
    assert "world.completed" not in event_types(report.events)
    assert "terminal_honest" in {f.check for f in report.findings if f.hard}
    folder = tmp_path / "cli"
    folder.mkdir()
    result, _, _ = live_run(folder, world=FakeWorld(script=script))
    assert result.code == 1


def test_PL_LIVE_E2E_15_a_failed_unit_is_a_failed_run_with_no_completion_and_no_delivery(tmp_path: Path) -> None:
    world = world_for(fail_roles={"writer": ProviderError("synthetic outage")})
    report, _ = run_direct(tmp_path, world=world)
    assert report.outcome_class in {"refused", "failed"}
    types = event_types(report.events)
    assert "world.completed" not in types and "artifact.delivered" not in types  # HR-1
    assert report.reason and report.reason.strip()
    folder = tmp_path / "cli"
    folder.mkdir()
    result, _, _ = live_run(folder, world=world_for(fail_roles={"writer": ProviderError("synthetic outage")}))
    assert result.code == 1
    outcome = result.outcome()
    assert outcome and outcome["outcome"] in {"refused", "failed"}


def test_PL_LIVE_E2E_16_a_renamed_case_behaves_exactly_like_the_original(tmp_path: Path) -> None:
    first, second = tmp_path / "a", tmp_path / "b"
    first.mkdir()
    second.mkdir()
    original, _ = run_direct(first)
    renamed_bank = write_bank(second, "B-007", new_id="B-901")
    renamed, _ = run_direct(second, case="B-901", bank=renamed_bank, world=world_for("B-007"))
    assert renamed.case_id == "B-901"
    assert renamed.outcome_class == original.outcome_class == "completed"
    assert event_types(renamed.events) == event_types(original.events)
    assert [(r.stage, r.role, r.calls) for r in renamed.rows] == [(r.stage, r.role, r.calls) for r in original.rows]


def test_PL_LIVE_E2E_17_every_call_goes_through_the_router_by_role_to_the_profile_the_config_names(
    tmp_path: Path,
) -> None:
    config = load_providers_config(REAL_MODELS, REAL_PRICES)  # config/models.yaml, the file the real run uses
    report, world = run_direct(tmp_path)
    assert report.outcome_class == "completed", report.reason
    assert world.calls
    for call in world.calls:
        assert call.role in config.roles
        assert call.profile_id == config.roles[call.role].primary, call  # nothing fell back, nothing named a model
    assert {profile for _, profile in world.built} <= set(config.profiles)
    assert all(row.profile in config.profiles for row in report.rows)
