"""ADR-0042 T4 (BQ-M2-4, BQ-M2-5, BQ-M2-12): the Live voice meter's deploy settings are documented, match the code that
reads them, and stay out of Terraform (tilo-api has `ignore_env`, the service module declares no env, and the FR-AGT-14e
guard keeps `api` out of `extra_invokers`). Static only: no terraform, no gcloud, no network."""

from __future__ import annotations

import pathlib

API_SETTINGS = ("TILO_VOICE_METER", "TILO_VOICE_METER_AUDIENCE", "TILO_VOICE_METER_CALLER")
BOT_SETTING = "TILO_API_URL"
DOCS = ("docs/deploy-dev.md", "meet-bot/docs/CLOUD_RUN.md")
SECTION = "### The meeting bot's Live voice meter"


def _read(repo_root: pathlib.Path, relative: str) -> str:
    return (repo_root / relative).read_text(encoding="utf-8")


def _runbook(repo_root: pathlib.Path) -> str:
    text = _read(repo_root, "docs/deploy-dev.md")
    start = text.index(SECTION)
    return text[start : text.index("\n### ", start + 4)]


def test_BQ_M2_4_T4_the_four_settings_are_read_by_the_code_and_named_in_every_doc(repo_root: pathlib.Path) -> None:
    api = _read(repo_root, "services/api/src/tilo_api/meeting_voice_meter.py") + _read(
        repo_root, "services/api/src/tilo_api/meeting_voice_claims.py"
    )
    bot = _read(repo_root, "meet-bot/bot/voice_meter.py")
    for name in API_SETTINGS:
        assert f'"{name}"' in api, f"{name} is not read by tilo-api"
    assert f'"{BOT_SETTING}"' in bot
    for relative in DOCS:
        text = _read(repo_root, relative)
        for name in (*API_SETTINGS, BOT_SETTING):
            assert name in text, f"{relative} must name {name}"
    assert "TILO_VOICE_METER_CALLER" in _read(repo_root, "infra/ACCESS.md")


def test_BQ_M2_4_T4_the_settings_are_gcloud_env_never_terraform(repo_root: pathlib.Path) -> None:
    for path in (repo_root / "infra").rglob("*.tf"):
        text = path.read_text(encoding="utf-8")
        for name in (*API_SETTINGS, BOT_SETTING, "meeting-voice"):
            assert name not in text, (
                f"{path.relative_to(repo_root).as_posix()} names {name}: the settings are set by hand"
            )


def test_BQ_M2_4_T4_the_caller_account_names_match_terraform(repo_root: pathlib.Path) -> None:
    main = _read(repo_root, "infra/envs/dev/main.tf")
    assert '"meet-bot" = {' in main  # the module names the account `tilo-<key>`: tilo-meet-bot
    assert 'account_id   = "tilo-schedule-scheduler"' in main and 'account_id   = "tilo-tasks-invoker"' in main
    runbook = _runbook(repo_root)
    for account in ("tilo-meet-bot", "tilo-schedule-scheduler", "tilo-tasks-invoker"):
        assert account in runbook, account
    assert "TILO_VOICE_METER_CALLER=$BotSa" in _read(repo_root, "meet-bot/docs/CLOUD_RUN.md")


def test_BQ_M2_4_T4_the_runbook_has_the_checks_the_rollback_and_the_unchanged_list(repo_root: pathlib.Path) -> None:
    runbook = _runbook(repo_root)
    for word in ("Check A", "Check B", "Check C", "`404`", "`401`", "`503`", "`409`", "**Rollback**"):
        assert word in runbook, word
    assert "--remove-env-vars=TILO_VOICE_METER" in runbook
    for phrase in ("no Terraform change", "allUsers", "one instance", "no Firestore or ledger", "BQ-M2-12"):
        assert phrase in runbook, phrase
    steps = [line for line in runbook.splitlines() if line[:3] in {f"{n}. " for n in range(1, 10)}]
    assert len(steps) == 8, "the user's ordered steps are numbered 1 to 8"
    # the meter routes never read LIVE: the API's own switch (the user's, for live Home tasks) is irrelevant to them
    assert "never read `LIVE`" in runbook and "not matter to them" in runbook
    assert "on `tilo-meet-bot`" in runbook and "BQ-M2-13" in runbook


def test_BQ_M2_4_T4_the_voice_meter_settings_are_on_the_env_drift_allowlist(repo_root: pathlib.Path) -> None:
    rollout = _read(repo_root, "docs/routines-rollout.md")
    optional = next(line for line in rollout.splitlines() if line.startswith("$Optional"))
    for name in API_SETTINGS:
        assert f'"{name}"' in optional, name


def test_BQ_M2_4_T4_the_refusal_memory_finding_is_an_open_question_row(repo_root: pathlib.Path) -> None:
    # Rows are appended at the END of the file (BQ row order), so a later row may follow this one: it is found by id.
    rows = [line for line in _read(repo_root, "docs/open-questions.md").splitlines() if line.startswith("| BQ-M2-12 |")]
    assert len(rows) == 1, "exactly one BQ-M2-12 row"
    last = rows[0]
    for word in ("FallbackTTS", "NotConfigured", "out/.tts_state.json", "packages/providers", "NOT done"):
        assert word in last, word
