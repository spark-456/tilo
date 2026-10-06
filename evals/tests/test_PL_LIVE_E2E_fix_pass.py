"""PL-LIVE-E2E (issue #340), the review fix pass on PR #358: a provider's rejected request, the Director's output cap,
what the report says is faked, the replay miss naming its stage, the gate reading both environments, and an attempt that
raised after it was sent still being counted. PRD 6.6 EFF-01, 9.4 HR-1, 16.1 rule 4.

Everything runs on the fake provider of `_live_e2e_lib`; the live switch is only ever set inside a test's own patched
environment, and no paid or network call is made. Fake secrets are assembled at runtime.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
import yaml
from _live_e2e_lib import (
    COMMITTED_RECORDINGS,
    PROJECT,
    REAL_MODELS,
    STOP_RE,
    CaseFakeModel,
    FakeWorld,
    bank_case,
    env,
    fake_secret,
    live_e2e,
    live_run,
    network_guard,  # noqa: F401  (autouse fixture)
    recording_files,
    replay_run,
    request_kind,
    run_direct,
    world_for,
    write_bank,
    write_prices,
)
from tilo_providers.config import load_providers_config
from tilo_providers.errors import ProviderError, RequestError, SafetyError, map_http_status
from tilo_providers.interfaces import GenerateRequest, GenerateResponse, ModelProvider
from tilo_providers.safety import FakeSafetyProvider

CRED_PATH = "/home/someone/keys/robot-account-credentials.json"
ADC_PATH = "C:/Users/someone/AppData/Roaming/gcloud/application_default_credentials.json"
SERVER_WORDS = "the thinking level is not supported for this model"
CLASSES = {400: "rejected", 401: "auth", 403: "permission", 404: "location", 429: "quota", 500: "unknown"}


class _RedactedAPIError(Exception):
    """Named like the Google adapter's stand-in for the SDK error (the classifier reads the class name and `code`)."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


def _server_text() -> str:
    """What a careless server message could echo: padding, then the project id (whole, bare, across the 200-character
    cut), a project path, two credential files, a token, a bearer header and an email address."""
    return (
        f"{SERVER_WORDS} " + "pad " * 45 + f"project {PROJECT} at projects/{PROJECT}/locations/global "
        f"adc {ADC_PATH} key {CRED_PATH} token {fake_secret('access_token')} "
        f"Authorization: {fake_secret('bearer')} contact {fake_secret('email')}"
    )


def _provider_error(status: int) -> ProviderError:
    error = map_http_status(status, _server_text())
    error.__cause__ = _RedactedAPIError(status, _server_text())
    return error


def _leaks(blob: str) -> list[str]:
    needles = {
        "project id": PROJECT,
        "project id prefix": PROJECT[:9],
        "ADC path": "application_default_credentials",
        "credentials file": "robot-account-credentials",
        "access token": "FakeTokenAbc123",
        "bearer": "fakeBearerValue",
        "email": fake_secret("email"),
    }
    return [name for name, needle in needles.items() if needle in blob]


EXTRA_ENV = {"GOOGLE_APPLICATION_CREDENTIALS": CRED_PATH}


@pytest.mark.parametrize("status", sorted(CLASSES))
def test_PL_LIVE_E2E_28_a_provider_status_prints_its_class_and_leaks_nothing(status: int, tmp_path: Path) -> None:
    world = world_for(fail_roles={"director": _provider_error(status)})
    report_path = tmp_path / "report.json"
    result, _, recordings = live_run(
        tmp_path, world=world, record=True, extra_env=EXTRA_ENV, extra_args=("--report-json", str(report_path))
    )
    folder = tmp_path / "direct"
    folder.mkdir()
    report, _ = run_direct(folder, world=world_for(fail_roles={"director": _provider_error(status)}))
    blob = "\n".join(
        (result.everything, report_path.read_text(encoding="utf-8"), json.dumps(report.events, default=str))
        + tuple(p.read_text(encoding="utf-8") for p in recording_files(recordings))
    )
    assert _leaks(blob) == [], f"HTTP {status} leaked into the output, the events or a recording"
    assert result.code == 1
    outcome = result.outcome()
    assert outcome and outcome["outcome"] != "completed"
    stop = STOP_RE.match(result.err_lines()[-1])
    assert stop and "\n" not in stop["message"]
    if status == 400:  # a rejected request: the outcome says so and gives the scrubbed reason, one line, at most 200
        assert outcome["outcome"] == "rejected" and "rejected" in live_e2e().OUTCOME_CLASSES
        assert stop["outcome"] == "rejected" and report.outcome_class == "rejected"
        reason = stop["message"].split(": ", 1)[1]
        assert reason.startswith(SERVER_WORDS[:30]) and len(reason) <= 200
        assert report.reason and report.reason.startswith("the provider rejected a request of the director role")
    else:  # any other status: the code only, none of the server's own words
        assert outcome["outcome"] != "rejected" and SERVER_WORDS not in blob
        assert f"provider call failed (director role): {CLASSES[status]}" in stop["message"]


def test_PL_LIVE_E2E_28_a_rejected_reason_is_scrubbed_before_it_is_capped(tmp_path: Path) -> None:
    text = "x" * 170 + f" project {PROJECT} done"  # the project id straddles character 200 of the reason
    error = map_http_status(400, text)
    error.__cause__ = _RedactedAPIError(400, text)
    report, _ = run_direct(tmp_path, world=world_for(fail_roles={"director": error}))
    assert report.outcome_class == "rejected" and report.reason
    assert PROJECT not in report.reason and PROJECT[:8] not in report.reason and "\n" not in report.reason
    assert len(report.reason.split(": ", 1)[1]) <= 200


def test_PL_LIVE_E2E_28_a_narrator_that_is_rejected_leaves_no_story_but_does_not_end_the_run(tmp_path: Path) -> None:
    error = map_http_status(400, _server_text())
    error.__cause__ = _RedactedAPIError(400, _server_text())
    path = tmp_path / "report.json"
    result, _, _ = live_run(
        tmp_path,
        world=world_for(fail_roles={"narrator": error}),
        extra_env=EXTRA_ENV,
        extra_args=("--report-json", str(path)),
    )
    assert result.code == 0, result.err
    assert result.outcome()["outcome"] == "completed"  # type: ignore[index]
    assert re.search(r"^story: none \(the Narrator call failed: rejected", result.out, re.M)
    assert _leaks(result.everything + path.read_text(encoding="utf-8")) == []
    assert json.loads(path.read_text(encoding="utf-8"))["story_lines"] == []


@dataclass
class _RequestLog(FakeWorld):
    requests: list[tuple[str, str, int | None]] = field(default_factory=list)

    def factory(self, role: str, profile_id: str) -> ModelProvider:
        self.built.append((role, profile_id))
        return _LoggingModel(self, role, profile_id)


class _LoggingModel(CaseFakeModel):
    def generate(self, request: GenerateRequest) -> GenerateResponse:
        assert isinstance(self._world, _RequestLog)
        self._world.requests.append((self._role, request_kind(request), request.max_output_tokens))
        return super().generate(request)


def test_PL_LIVE_E2E_29_director_requests_carry_the_roles_output_cap_or_a_floor_never_the_routers_1024(
    tmp_path: Path,
) -> None:
    module = live_e2e()
    config = load_providers_config(REAL_MODELS, write_prices(tmp_path))
    expected = config.roles["director"].max_output_tokens or module._DIRECTOR_OUT
    world = _RequestLog(script=bank_case("B-007").director)
    report, _ = run_direct(tmp_path, world=world)
    assert report.outcome_class == "completed", report.reason
    director = {kind: cap for role, kind, cap in world.requests if role == "director"}
    assert set(director) >= {"brief", "approaches", "plan"}
    assert all(cap == expected for role, _, cap in world.requests if role == "director")
    assert expected > 1024  # thinking tokens count against the cap: 1024 can cut a plan short
    assert all(cap is not None for _, _, cap in world.requests)  # no request goes out without a cap


def test_PL_LIVE_E2E_29_a_roles_configured_cap_is_the_one_sent_and_the_one_estimated(tmp_path: Path) -> None:
    module = live_e2e()
    raw = yaml.safe_load(REAL_MODELS.read_text(encoding="utf-8"))
    raw["roles"]["director"]["max_output_tokens"] = 2000
    models = tmp_path / "models.yaml"
    models.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    prices = write_prices(tmp_path)
    world = _RequestLog(script=bank_case("B-007").director)
    with env(LIVE="1", GOOGLE_CLOUD_PROJECT=PROJECT):
        report = module.run_live_e2e(
            "B-007", mode="live", models_path=models, prices_path=prices, recordings_dir=tmp_path / "rec",
            live_provider_factory=world.factory, safety=FakeSafetyProvider(),
        )  # fmt: skip
    assert report.outcome_class == "completed", report.reason
    assert {cap for role, _, cap in world.requests if role == "director"} == {2000}
    default = module.run_live_e2e("B-007", mode="dry-run", prices_path=prices)
    assert report.estimate.credits_high < default.estimate.credits_high  # the estimate follows the cap that is sent


def test_PL_LIVE_E2E_30_the_report_says_what_is_faked_where_planning_credits_come_from_and_the_claim_scope(
    tmp_path: Path,
) -> None:
    result, _, _ = live_run(tmp_path)
    assert result.code == 0, result.err
    out = result.out
    assert "faked: safety screen" in out and "faked: connectors and recipient: recording mocks" in out
    assert "faked: Verifier verdict: recorded in the unit's summary, not acted on" in out
    assert "planning credits come from this meter" in out and "#327" in out
    assert "claim scope: structural pass rate (GEN-11), not output quality" in out
    assert "SYNTHETIC" not in out and "recordings:" not in out  # a live run has no recordings line


def test_PL_LIVE_E2E_30_a_replay_of_the_synthetic_fixture_says_it_is_not_a_real_model_run(tmp_path: Path) -> None:
    assert (COMMITTED_RECORDINGS / "B-007" / "SYNTHETIC").is_file()  # the committed fixture is marked
    result, _ = replay_run(tmp_path, COMMITTED_RECORDINGS / "B-007")
    assert result.code == 0, result.err
    assert "recordings: SYNTHETIC fixture written by a fake provider; this replay is not a real model run" in result.out
    assert "faked: safety screen" in result.out and "claim scope: structural pass rate" in result.out


def test_PL_LIVE_E2E_30_a_replay_names_the_recordings_origin_from_who_wrote_them(tmp_path: Path) -> None:
    recorded, _, _ = live_run(tmp_path, record=True)
    recordings = tmp_path / "recordings-out"
    assert recorded.code == 0 and (recordings / "SYNTHETIC").is_file()  # a fake provider wrote them
    folder = tmp_path / "replay"
    folder.mkdir()
    marked, _ = replay_run(folder, recordings)
    assert "recordings: SYNTHETIC" in marked.out
    (recordings / "SYNTHETIC").unlink()
    unmarked, _ = replay_run(folder, recordings)
    assert unmarked.code == 0, unmarked.err
    assert "recordings: not marked synthetic" in unmarked.out and "SYNTHETIC" not in unmarked.out
    data = tmp_path / "replay.json"
    replay_run(folder, recordings, extra_args=("--report-json", str(data)))
    assert json.loads(data.read_text(encoding="utf-8"))["recordings"] == "unmarked"


def test_PL_LIVE_E2E_31_a_replay_miss_names_the_stage_the_role_and_the_key(tmp_path: Path) -> None:
    recorded, _, _ = live_run(tmp_path, record=True)
    assert recorded.code == 0, recorded.err
    recordings = tmp_path / "recordings-out"
    folder = tmp_path / "changed"
    folder.mkdir()
    bank = write_bank(folder, "B-007", brief="A different request: summarise our returns policy in a note.")
    result, _ = replay_run(folder, recordings, bank=bank)
    match = STOP_RE.match(result.err_lines()[0])
    assert match and match["outcome"] == "replay_miss"
    assert "stage intake (role director)" in match["message"], match["message"]
    assert re.search(r"with key [0-9a-f]{16}", match["message"])
    assert "a prompt, brief or config changed" in match["message"]
    victim = next(p for p in recording_files(recordings) if p.parent.name == "writer")
    victim.unlink()
    second = tmp_path / "missing"
    second.mkdir()
    result, _ = replay_run(second, recordings)
    match = STOP_RE.match(result.err_lines()[0])
    assert match and "stage run (role writer)" in match["message"] and victim.stem in match["message"]


GATE_ENV = {"LIVE": "1", "GOOGLE_CLOUD_PROJECT": PROJECT}
MARKERS = [("CI", "true", "ci_refused"), ("GITHUB_ACTIONS", "true", "ci_refused")]
MARKERS += [("K_SERVICE", "", "deployed_refused"), ("CLOUD_RUN_JOB", "", "deployed_refused")]


def _live_with(tmp_path: Path, environ: dict[str, str]) -> Any:
    world = world_for()
    module = live_e2e()
    with pytest.raises(module.LiveE2ERefused) as info:
        module.run_live_e2e(
            "B-007", mode="live", environ=environ, prices_path=write_prices(tmp_path),
            recordings_dir=tmp_path / "rec", live_provider_factory=world.factory, safety=FakeSafetyProvider(),
        )  # fmt: skip
    assert world.built == [] and world.calls == [] and not (tmp_path / "rec").exists()
    return info.value.code


@pytest.mark.parametrize(("marker", "value", "code"), MARKERS)
def test_PL_LIVE_E2E_32_a_ci_or_cloud_run_marker_in_the_process_environment_refuses_a_callers_clean_environ(
    marker: str, value: str, code: str, tmp_path: Path
) -> None:
    with env(**{marker: value}):  # os.environ has the marker; the caller's own environ is clean
        assert _live_with(tmp_path, dict(GATE_ENV)) == code


@pytest.mark.parametrize(("marker", "value", "code"), MARKERS)
def test_PL_LIVE_E2E_32_a_ci_or_cloud_run_marker_in_the_callers_environ_refuses_with_a_clean_process(
    marker: str, value: str, code: str, tmp_path: Path
) -> None:
    with env():  # os.environ is clean; the caller's environ has the marker
        assert _live_with(tmp_path, {**GATE_ENV, marker: value}) == code


def test_PL_LIVE_E2E_32_replay_and_dry_run_still_run_with_the_markers_set(tmp_path: Path) -> None:
    module = live_e2e()
    with env(CI="true", K_SERVICE="svc", CLOUD_RUN_JOB="job", GITHUB_ACTIONS="true"):
        dry = module.run_live_e2e("B-007", mode="dry-run", prices_path=write_prices(tmp_path))
        result, _ = replay_run(tmp_path, COMMITTED_RECORDINGS / "B-007")
    assert dry.outcome_class is None and result.code == 0, result.err


def test_PL_LIVE_E2E_33_an_attempt_that_raised_after_it_was_sent_is_still_counted(tmp_path: Path) -> None:
    blocked, _ = run_direct(tmp_path, world=world_for(fail_roles={"writer": SafetyError("blocked by safety filter")}))
    writer = [r for r in blocked.rows if r.role == "writer"]
    assert writer and all(r.calls >= 1 and r.credits > 0 and r.tokens_out > 0 for r in writer)
    assert blocked.total_credits == pytest.approx(sum(r.credits for r in blocked.rows))
    folder = tmp_path / "rejected"
    folder.mkdir()
    refused, _ = run_direct(folder, world=world_for(fail_roles={"writer": RequestError("never generated")}))
    assert not [r for r in refused.rows if r.role == "writer"]  # a refused request is never billed
