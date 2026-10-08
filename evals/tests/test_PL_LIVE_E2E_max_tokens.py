"""PL-LIVE-E2E (issue #340) follow-up: the first LIVE run of bank case B-007 failed at intake with
"stage=intake role=director ... tokens_out=4096 ...; outcome=refused; check=terminal_honest findings=1;
STOP refused: The Director could not draft a brief.; provider call failed (director role): unknown".

Cause (read from the code, not assumed): `config/models.yaml` gives the Director `thinking: high` and no
`max_output_tokens`; `live_e2e._output_cap` therefore sends the Director's own 4096-token floor (`_DIRECTOR_OUT`);
thinking tokens use the whole cap, Gemini stops with MAX_TOKENS and no text, `google_adapter` has no branch for that
finish reason, the empty reply fails schema validation twice, the Router gives up with no adapter error behind it and
`vertex_smoke.classify` has nothing to name: "unknown". The adapter and config halves are pinned in
`packages/providers/tests/test_PL_02_max_tokens_finish.py`; this file pins what `just live-e2e` shows and costs.

Criteria:
  (1) a Director whose reply was cut off at its output cap ends the run honestly and the STOP line names the
      condition ("provider call failed (director role): truncated"), never "unknown"; no same-profile retry;
  (2) the cost estimate counts the Director's configured `max_output_tokens`, and the run sends that cap;
  (3) `terminal_honest` on a run refused at intake. VERDICT, from `bank_checks.terminal_honest` and PRD 9.4 / 19.3:
      the one finding is NOT a false positive and NOT an honesty defect. B-007 expects `completed`; a run refused at
      intake did not complete, which is exactly what the check reports ("outcome 'refused', expected 'completed'").
      The refusal itself is honest (a reason is shown, no `world.completed`, no `artifact.delivered`, no events): HR-1.
      A case that EXPECTS a refusal and is refused at intake has no `terminal_honest` finding. The tests pin both.

Everything runs on the fake provider of `_live_e2e_lib`; no paid or network call is made and the live switch is only
set inside a test's own patched environment. The truncation error is built through the API pinned in the providers
test: `OutputTruncatedError(message, *, output_tokens=None, thinking_tokens=None)`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from _live_e2e_lib import (
    BANK,
    REAL_MODELS,
    REAL_PRICES,
    STOP_RE,
    CaseFakeModel,
    FakeWorld,
    bank_case,
    env,
    event_types,
    live_e2e,
    live_run,
    network_guard,  # noqa: F401  (autouse fixture)
    run_direct,
    world_for,
    write_prices,
)
from tilo_evals.bank_checks import terminal_honest
from tilo_evals.bank_run import Observation
from tilo_providers.config import load_providers_config
from tilo_providers.errors import ProviderError
from tilo_providers.interfaces import GenerateRequest, GenerateResponse

REPO = Path(__file__).resolve().parents[2]
DIRECTOR_FLOOR = 4096  # live_e2e._DIRECTOR_OUT, the cap the incident's Director call carried
STOP_TEXT = "The Director could not draft a brief."  # services/api intake.py: the 502 detail, said on purpose


def _truncated() -> Exception:
    from tilo_providers.errors import OutputTruncatedError  # noqa: PLC0415

    return OutputTruncatedError("PL-02: output cap reached", output_tokens=0, thinking_tokens=DIRECTOR_FLOOR)


# ---------------------------------------------------------------------------------------------------------------
# (1) a cut-off Director is named, not "unknown"
# ---------------------------------------------------------------------------------------------------------------


def test_PL_LIVE_E2E_35_a_director_cut_off_at_its_cap_stops_the_run_naming_truncated_not_unknown(
    tmp_path: Path,
) -> None:
    world = world_for(fail_roles={"director": _truncated()})
    result, _, _ = live_run(tmp_path, world=world)
    assert result.code == 1
    stop = STOP_RE.match(result.err_lines()[-1])
    assert stop, result.err_lines()
    assert stop["outcome"] == "refused" and STOP_TEXT in stop["message"]
    assert "provider call failed (director role): truncated" in stop["message"]
    assert "unknown" not in stop["message"]
    outcome = result.outcome()
    assert outcome and outcome["outcome"] == "refused"
    director_profiles = [call.profile_id for call in world.calls if call.role == "director"]
    assert director_profiles, "the Director was never called"
    assert len(director_profiles) == len(set(director_profiles)), "a truncated reply is never retried on its profile"


def test_PL_LIVE_E2E_35_the_report_of_a_cut_off_director_carries_the_named_reason(tmp_path: Path) -> None:
    report, _ = run_direct(tmp_path, world=world_for(fail_roles={"director": _truncated()}))
    assert report.outcome_class == "refused"
    assert report.reason and STOP_TEXT in report.reason
    assert "provider call failed (director role): truncated" in report.reason


# ---------------------------------------------------------------------------------------------------------------
# (3) terminal_honest on a run refused at intake
# ---------------------------------------------------------------------------------------------------------------


def test_PL_LIVE_E2E_35_a_run_refused_at_intake_is_honest_and_its_only_finding_is_the_missed_expected_outcome(
    tmp_path: Path,
) -> None:
    report, _ = run_direct(tmp_path, world=world_for(fail_roles={"director": ProviderError("synthetic outage")}))
    assert report.expected == "completed" and report.outcome_class == "refused"
    types = event_types(report.events)
    assert "world.completed" not in types and "artifact.delivered" not in types and "world.failed" not in types  # HR-1
    assert report.reason and report.reason.strip(), "a refusal always tells the person why"
    assert [(f.check, f.hard) for f in report.findings] == [("terminal_honest", True)]
    assert report.findings[0].detail.startswith("outcome 'refused', expected 'completed'")
    assert "terminal_honest" in report.checks_run  # the check ran; it was not skipped as for a stopped_at_cap run


def test_PL_LIVE_E2E_35_terminal_honest_passes_a_refusal_the_case_expects_and_flags_one_it_does_not() -> None:
    refusal = Observation(case=bank_case("B-009"), outcome="refused", reason=STOP_TEXT)
    assert terminal_honest(refusal) == []  # expected refused, refused with a reason, nothing completed
    missed = Observation(case=bank_case("B-007"), outcome="refused", reason=STOP_TEXT)
    found = terminal_honest(missed)
    assert [f.check for f in found] == ["terminal_honest"] and len(found) == 1
    assert found[0].detail.startswith("outcome 'refused', expected 'completed'")
    silent = Observation(case=bank_case("B-009"), outcome="refused", reason="  ")
    assert [f.detail for f in terminal_honest(silent)] == ["refused with no reason shown to the person"]


def test_PL_LIVE_E2E_35_a_case_that_expects_a_refusal_at_intake_has_no_terminal_honest_finding(tmp_path: Path) -> None:
    report, _ = run_direct(tmp_path, case="B-009")
    assert report.outcome_class == "refused" == report.expected
    assert "terminal_honest" in report.checks_run
    assert [f for f in report.findings if f.check == "terminal_honest"] == []


# ---------------------------------------------------------------------------------------------------------------
# (2) the estimate and the run use the configured Director cap
# ---------------------------------------------------------------------------------------------------------------


def _models_file(tmp_path: Path, name: str, director_cap: int | None) -> Path:
    raw = yaml.safe_load(REAL_MODELS.read_text(encoding="utf-8"))
    if director_cap is None:
        raw["roles"]["director"].pop("max_output_tokens", None)
    else:
        raw["roles"]["director"]["max_output_tokens"] = director_cap
    path = tmp_path / name
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return path


def _credits_high(tmp_path: Path, models: Path) -> float:
    """The dry-run estimate of B-007 on `models`, at a flat US$1 per million tokens (no call, nothing written)."""
    with env():
        report = live_e2e().run_live_e2e(
            "B-007", mode="dry-run", bank_dir=BANK, models_path=models, prices_path=write_prices(tmp_path)
        )
    return float(report.estimate.credits_high)


def test_PL_LIVE_E2E_35_the_estimate_grows_linearly_with_the_directors_configured_cap(tmp_path: Path) -> None:
    # guard (passes before the fix): `_output_cap` already prefers the role's `max_output_tokens` to the 4096 floor
    low, mid, high = (
        _credits_high(tmp_path, _models_file(tmp_path, f"m{cap}.yaml", cap))
        for cap in (2048, 4096, 6144)  # COST-AUDIT: under the Director's p90 (8192), where the cap still sets the count
    )
    assert low < mid < high
    assert (mid - low) == pytest.approx(high - mid, rel=1e-6)


def test_PL_LIVE_E2E_35_the_shipped_config_gives_the_director_a_cap_and_the_estimate_counts_it(tmp_path: Path) -> None:
    cap = load_providers_config(REAL_MODELS, REAL_PRICES).roles["director"].max_output_tokens
    assert cap is not None and cap > DIRECTOR_FLOOR, f"config/models.yaml director max_output_tokens is {cap}"
    shipped = _credits_high(tmp_path, REAL_MODELS)
    at_floor = _credits_high(tmp_path, _models_file(tmp_path, "floor.yaml", DIRECTOR_FLOOR))
    per_token = (
        _credits_high(tmp_path, _models_file(tmp_path, "twice.yaml", 2 * DIRECTOR_FLOOR)) - at_floor
    ) / DIRECTOR_FLOOR
    p90 = json.loads((REPO / "evals" / "live_usage_p90.json").read_text(encoding="utf-8"))["output_tokens_p90"][
        "director"
    ]
    # COST-AUDIT: the estimate counts min(cap, p90); the old whole-cap figure stays reachable as the hard bound
    assert shipped - at_floor == pytest.approx(per_token * (min(cap, p90) - DIRECTOR_FLOOR), rel=1e-6)
    assert shipped > at_floor, "the estimate before a live run must show what the new cap can cost"


class _RecordingModel(CaseFakeModel):
    def generate(self, request: GenerateRequest) -> GenerateResponse:
        self._world.requested.append((self._role, request.max_output_tokens))  # type: ignore[attr-defined]
        return super().generate(request)


class _RecordingWorld(FakeWorld):
    def factory(self, role: str, profile_id: str) -> Any:
        self.built.append((role, profile_id))
        return _RecordingModel(self, role, profile_id)


def test_PL_LIVE_E2E_35_every_director_request_of_a_live_run_carries_the_configured_cap(tmp_path: Path) -> None:
    cap = load_providers_config(REAL_MODELS, REAL_PRICES).roles["director"].max_output_tokens
    assert cap is not None, "config/models.yaml gives the Director no max_output_tokens"
    world = _RecordingWorld(script=bank_case("B-007").director)
    world.requested = []  # type: ignore[attr-defined]
    result, _, _ = live_run(tmp_path, world=world)
    assert result.code == 0, result.err
    sent = [n for role, n in world.requested if role == "director"]  # type: ignore[attr-defined]
    assert len(sent) >= 3  # brief, approaches, plan
    assert set(sent) == {cap}, f"the Director's calls went out with {sorted(set(map(str, sent)))}, config says {cap}"
