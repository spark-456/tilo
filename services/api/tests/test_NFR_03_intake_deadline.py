"""NFR-03 / NFR-22 / FR-INT-03 (live defect 15 Oct 2026, tilo-api-00062): a Gemini 503 made POST /intake take
122.6 s and answer 201 after the web had given up at 120 s, so the person saw a failure while the plan existed
unseen. The Director's brief now has an overall deadline from `config/intake.yaml`, inside the web's wait: a 503 on
the primary falls back at once on the cascade with the time left, and when the time is gone the answer is a plain 503
`intake_deadline` with nothing stored, never a late 201. Fakes only, no network, no paid call."""

from __future__ import annotations

import re
import time
from pathlib import Path

import pytest
from _clint1_lib import APPROACHES_REPLY, RoleScriptedProvider, brief_reply
from tilo_providers.errors import RetryableError

# models.yaml: director = flash-38, falling back to flash-37.
PRIMARY, FALLBACK = "flash-38", "flash-37"


class _Timed(RoleScriptedProvider):
    """Waits `delay`, then raises `error` or answers like the scripted Director."""

    def __init__(self, delay: float, error: Exception | None = None) -> None:
        super().__init__(brief_reply([]), APPROACHES_REPLY)
        self.delay, self.error = delay, error

    def generate(self, request):
        time.sleep(self.delay)
        if self.error is not None:
            raise self.error
        return super().generate(request)


def _router(repo_root: Path, **providers: _Timed):
    from tilo_providers.config import load_providers_config  # noqa: PLC0415
    from tilo_providers.router import Router  # noqa: PLC0415

    config = load_providers_config(repo_root / "config" / "models.yaml", repo_root / "config" / "prices.yaml")
    return Router(config, provider_for_profile=lambda profile_id: providers[profile_id.replace("-", "_")])


def _deadline(monkeypatch, seconds: float, share: float = 0.5) -> None:
    from tilo_api import intake  # noqa: PLC0415
    from tilo_api.intake_deadline import IntakeDeadline  # noqa: PLC0415

    monkeypatch.setattr(intake, "load_intake_deadline", lambda: IntakeDeadline(seconds, share))


def test_NFR_03_a_503_on_the_primary_falls_back_and_the_plan_is_answered_in_time(clear_flow, repo_root, monkeypatch):
    _deadline(monkeypatch, 5.0)
    clear_flow.router = _router(repo_root, flash_38=_Timed(0.05, RetryableError("503 (fake)")), flash_37=_Timed(0.2))
    start = time.monotonic()

    response = clear_flow.intake()

    assert response.status_code == 201, response.text
    assert response.json()["task_id"]
    assert time.monotonic() - start < 4.0


def test_NFR_22_when_the_deadline_passes_the_answer_is_a_plain_503_and_nothing_is_stored(
    clear_flow, repo_root, monkeypatch
):
    _deadline(monkeypatch, 0.8)
    clear_flow.router = _router(repo_root, flash_38=_Timed(30.0), flash_37=_Timed(30.0))
    start = time.monotonic()

    response = clear_flow.intake()

    assert response.status_code == 503, response.text
    assert response.json()["detail"]["code"] == "intake_deadline"
    assert "replay_only" not in response.json()
    assert time.monotonic() - start < 4.0, "the answer comes at the deadline, not when the model finally replies"
    assert clear_flow.store.tasks == {} and clear_flow.store.worlds == {}


def test_NFR_22_a_503_then_a_slow_fallback_is_the_deadline_answer_not_a_model_outage(
    clear_flow, repo_root, monkeypatch
):
    """The incident's shape: the primary says 503, the fallback is then too slow."""
    _deadline(monkeypatch, 0.8)
    clear_flow.router = _router(repo_root, flash_38=_Timed(0.05, RetryableError("503 (fake)")), flash_37=_Timed(30.0))

    response = clear_flow.intake()

    assert response.status_code == 503, response.text
    assert response.json()["detail"]["code"] == "intake_deadline"
    assert "replay_only" not in response.json()


def test_FR_INT_06_NFR_03_approaches_deadline_stores_no_proposal(clear_flow, repo_root, monkeypatch):
    from tilo_api import tasks  # noqa: PLC0415
    from tilo_api.intake_deadline import IntakeDeadline  # noqa: PLC0415

    intake = clear_flow.new_task()
    task_id, world_id = intake["task_id"], intake["world_id"]
    before = list(clear_flow.events(world_id))
    monkeypatch.setattr(tasks, "load_intake_deadline", lambda: IntakeDeadline(0.2, 0.5), raising=False)
    clear_flow.router = _router(repo_root, flash_38=_Timed(0.6), flash_37=_Timed(0.6))
    start = time.monotonic()

    response = clear_flow.approaches(task_id)

    assert response.status_code == 503, response.text
    assert response.json()["detail"]["code"] == "intake_deadline"
    assert time.monotonic() - start < 1.0
    time.sleep(0.7)  # abandoned fake calls must not publish a late proposal
    assert clear_flow.events(world_id) == before
    assert clear_flow.store.tasks[task_id].approaches is None


def test_NFR_03_the_shipped_deadline_is_inside_the_webs_wait(repo_root):
    """The server must answer (201 or a refusal) before the web gives up, with room for sign-in checks and storage."""
    from tilo_api.intake_deadline import load_intake_deadline  # noqa: PLC0415

    shipped = load_intake_deadline()
    web = (repo_root / "apps" / "web" / "src" / "api" / "http.ts").read_text(encoding="utf-8")
    web_ms = int(re.search(r"export const INTAKE_TIMEOUT_MS = ([\d_]+);", web).group(1).replace("_", ""))

    assert 30 <= shipped.seconds <= 90
    assert shipped.seconds * 1000 + 10_000 <= web_ms


@pytest.mark.parametrize(
    "text",
    [
        "version: 1\ndeadline_seconds: 0\nfirst_attempt_share: 0.5\n",
        "version: 1\ndeadline_seconds: 60\nfirst_attempt_share: 1\n",
        "version: 1\n",
    ],
    ids=["zero_seconds", "share_not_below_one", "missing_keys"],
)
def test_NFR_03_a_bad_deadline_file_fails_loudly(tmp_path, text):
    from tilo_api.intake_deadline import IntakeDeadlineConfigError, load_intake_deadline  # noqa: PLC0415

    path = tmp_path / "intake.yaml"
    path.write_text(text, encoding="utf-8")

    with pytest.raises(IntakeDeadlineConfigError):
        load_intake_deadline(path)
