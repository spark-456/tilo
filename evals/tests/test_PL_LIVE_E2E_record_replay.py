"""PL-LIVE-E2E (issue #340): record once, replay free. PRD 6.6 EFF-01 ("record and replay": dev and CI make no paid
call), 16.1 rule 4 (secrets never enter prompts, logs, traces, the raw archive or analytics) with the ticket's rule
that no email address or phone number is kept either, 9.4 HR-1 (a replay is never passed off as a live result).

Where recordings live: `evals/bank/live/<case id>/model-recordings/<role>/<key>.json`, the provider layer's own
layout (`tilo_providers.replay.RecordReplayProvider`, key = `recording_key(role, profile, request)`), beside the case
files. The folder is NOT called `recordings/`: the repo's .gitignore ignores that name.

Criteria covered:
  (1) with TILO_RECORD=1 every model reply is saved, redacted: no secret, token, email address or phone number
      survives on disk or in any output; without TILO_RECORD nothing is written;
  (2) a recorded run replays free and identically: same outcome, same rows, same credits, zero live calls, and with
      no live switch, in CI too; the replay says it is a replay;
  (3) replay is keyed on the whole request: a changed brief, or a missing recording, is a clear replay miss (outcome
      `replay_miss`, exit 1, the role and the key named), never a silent pass and never a completion;
  (4) two recorded runs of one case write the same keys (prompts carry no timestamp, random id or counter), which is
      what makes replay possible at all;
  (5) the committed fixture of one bank case replays offline: `just live-e2e --case B-007 --replay` in CI.

Ambiguity resolved (PRD 6.6, 16.1): a reply is redacted BEFORE the run uses it, in live mode as well as in the
file, so a run that echoes an email into the next prompt records and replays the same prompts (otherwise the replay
would miss). The committed fixture is regenerated, when a prompt changes on purpose, by
`uv run python evals/tests/regen_live_e2e_fixture.py` (it records the fake run through the real code).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml
from _live_e2e_lib import (
    COMMITTED_RECORDINGS,
    EMAIL_RE,
    PHONE_RE,
    REAL_MODELS,
    REAL_PRICES,
    SECRET_RE,
    STOP_RE,
    all_text,
    env,
    fake_secret,
    invoke_main,
    leak_text,
    live_e2e,
    live_run,
    network_guard,  # noqa: F401  (autouse fixture)
    recording_files,
    replay_run,
    world_for,
    write_bank,
)

KEY_RE = re.compile(r"^[0-9a-f]{16}$")


def _record(tmp_path: Path, *, leak: bool = False, sub: str = "rec"):  # noqa: ANN202
    folder = tmp_path / sub
    folder.mkdir()
    world = world_for(leak=leak_text() if leak else "")
    result, world, recordings = live_run(folder, world=world, record=True)
    return folder, result, world, recordings


def test_PL_LIVE_E2E_18_recording_saves_every_reply_redacted_beside_the_case(tmp_path: Path) -> None:
    _, result, world, recordings = _record(tmp_path, leak=True)
    assert result.code == 0, result.err
    files = recording_files(recordings)
    roles = {path.parent.name for path in files}
    assert {"director", "lead_review", "writer", "verifier", "narrator"} <= roles  # COST-AUDIT: the review role, roles
    assert len(files) >= 7 and len(files) <= len(world.calls)
    for path in files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["role"] == path.parent.name and payload["key"] == path.stem and KEY_RE.match(path.stem)
        assert isinstance(payload["response"]["text"], str) and payload["response"]["text"]
        assert payload["response"]["usage"]["input_tokens"] == 1000  # the cost is replayable from the recording
        assert b"\r" not in path.read_bytes()  # LF even on Windows (.gitattributes): write bytes, not text mode
    text = all_text(files)
    for kind in ("email", "phone", "access_token", "bearer"):
        assert fake_secret(kind) not in text, kind
    assert not EMAIL_RE.search(text) and not PHONE_RE.search(text) and not SECRET_RE.search(text)
    assert "7946 0958" not in text and "FakeTokenAbc123" not in text


def test_PL_LIVE_E2E_18_no_output_of_the_run_carries_a_secret_or_personal_detail(tmp_path: Path) -> None:
    report_json = tmp_path / "report.json"
    result, _, _ = live_run(
        tmp_path, world=world_for(leak=leak_text()), record=True, extra_args=("--report-json", str(report_json))
    )
    assert result.code == 0, result.err
    report = json.loads(report_json.read_text(encoding="utf-8"))
    assert report["outcome_class"] == "completed" and report["rows"]
    for blob in (result.everything, report_json.read_text(encoding="utf-8")):
        assert not EMAIL_RE.search(blob) and not PHONE_RE.search(blob) and not SECRET_RE.search(blob)
        assert "FakeTokenAbc123" not in blob and "fakeBearerValue" not in blob


def test_PL_LIVE_E2E_18_without_the_record_flag_nothing_is_written(tmp_path: Path) -> None:
    result, world, recordings = live_run(tmp_path, record=False)
    assert result.code == 0, result.err
    assert world.calls
    assert not recordings.exists() or recording_files(recordings) == []


def test_PL_LIVE_E2E_19_a_recorded_run_replays_free_and_identically_even_with_a_leaky_model(tmp_path: Path) -> None:
    folder, live, world, recordings = _record(tmp_path, leak=True)
    assert live.code == 0, live.err
    replay_folder = tmp_path / "replay"
    replay_folder.mkdir()
    replayed, replay_world = replay_run(replay_folder, recordings, extra_env={"CI": "true"})  # CI: replay still runs
    assert replayed.code == 0, replayed.err
    assert replay_world.built == [] and replay_world.calls == []  # zero live calls, not even a provider built
    assert replayed.outcome()["outcome"] == live.outcome()["outcome"] == "completed"  # type: ignore[index]
    assert replayed.outcome()["events"] == live.outcome()["events"]  # type: ignore[index]

    def stable(rows):  # noqa: ANN001, ANN202  (latency differs by nature: a replay is instant)
        return [(m["stage"], m["role"], m["profile"], m["calls"], m["tin"], m["tout"], m["credits"]) for m in rows]

    assert stable(replayed.rows()) == stable(live.rows())
    assert replayed.total()["credits"] == live.total()["credits"]  # type: ignore[index]
    assert replayed.mode()["mode"] == "replay" and live.mode()["mode"] == "live"  # type: ignore[index]
    assert world.calls  # and the live run really did call the model


def test_PL_LIVE_E2E_20_a_changed_brief_is_a_clear_replay_miss_never_a_silent_pass(tmp_path: Path) -> None:
    folder, live, _, recordings = _record(tmp_path)
    assert live.code == 0, live.err
    changed_bank = write_bank(folder, "B-007", brief="A different request: summarise our returns policy in a note.")
    replay_folder = tmp_path / "replay"
    replay_folder.mkdir()
    result, world = replay_run(replay_folder, recordings, bank=changed_bank)
    assert result.code == 1
    assert result.outcome()["outcome"] == "replay_miss"  # type: ignore[index]
    assert "replay_miss" in live_e2e().OUTCOME_CLASSES
    lines = result.err_lines()
    assert len(lines) == 1
    match = STOP_RE.match(lines[0])
    assert match and match["outcome"] == "replay_miss"
    assert "director" in match["message"] and re.search(r"\b[0-9a-f]{16}\b", match["message"])  # the role and the key
    assert world.built == [] and world.calls == []
    assert "world.completed" not in result.out


def test_PL_LIVE_E2E_20_a_missing_run_stage_recording_is_a_replay_miss_too(tmp_path: Path) -> None:
    folder, live, _, recordings = _record(tmp_path)
    assert live.code == 0, live.err
    victim = next(path for path in recording_files(recordings) if path.parent.name == "writer")
    victim.unlink()
    replay_folder = tmp_path / "replay"
    replay_folder.mkdir()
    result, world = replay_run(replay_folder, recordings)
    assert result.code == 1
    assert result.outcome()["outcome"] == "replay_miss"  # type: ignore[index]
    match = STOP_RE.match(result.err_lines()[0])
    assert match and "writer" in match["message"] and victim.stem in match["message"]
    assert world.calls == []


def test_PL_LIVE_E2E_21_two_recorded_runs_of_one_case_write_the_same_keys(tmp_path: Path) -> None:
    _, first, _, rec_a = _record(tmp_path, sub="one")
    _, second, _, rec_b = _record(tmp_path, sub="two")
    assert first.code == 0 and second.code == 0
    names_a = {(p.parent.name, p.name) for p in recording_files(rec_a)}
    names_b = {(p.parent.name, p.name) for p in recording_files(rec_b)}
    assert names_a and names_a == names_b, "a prompt carries something that changes between runs (time, id, counter)"


def test_PL_LIVE_E2E_22_default_recordings_live_beside_the_case_and_not_under_a_gitignored_name() -> None:
    module = live_e2e()
    folder = Path(module.default_recordings_dir("B-007"))
    assert folder == COMMITTED_RECORDINGS / "B-007"
    assert "recordings" not in folder.parts  # .gitignore ignores `recordings/`
    assert (folder.parent.parent / "B-007.yaml").is_file()


def test_PL_LIVE_E2E_22_the_committed_fixture_of_one_case_replays_offline_in_ci() -> None:
    # `just live-e2e --case B-007 --replay` with no other flag: default bank, default prices, default recordings.
    with env(CI="true"):
        result = invoke_main(["--case", "B-007", "--replay"], safety=False)
    assert result.code == 0, (result.out, result.err)
    assert result.outcome()["outcome"] == "completed"  # type: ignore[index]
    assert result.mode()["mode"] == "replay"  # type: ignore[index]
    checks = result.checks()  # the GEN-a checks, one line each; `delivers_something` is reported, not gated
    assert checks and all(count == 0 for name, count in checks.items() if name != "delivers_something")
    total = result.total()
    assert total is not None and 0 < float(total["credits"]) <= 40.0
    assert REAL_PRICES.is_file()  # credits come from config/prices.yaml, the file the user set


def test_PL_LIVE_E2E_23_every_committed_recording_is_well_formed_redacted_and_named_by_config() -> None:
    files = sorted(COMMITTED_RECORDINGS.glob("*/model-recordings/*/*.json"))
    assert files, "no committed recording under evals/bank/live"
    models = yaml.safe_load(REAL_MODELS.read_text(encoding="utf-8"))
    for path in files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert path.parent.name == payload["role"] and path.stem == payload["key"] and KEY_RE.match(path.stem)
        assert payload["role"] in models["roles"] and payload["profile"] in models["profiles"]
        assert payload["response"]["profile_id"] == payload["profile"]
        usage = payload["response"]["usage"]
        assert usage["input_tokens"] > 0 and usage["output_tokens"] > 0
        text = path.read_text(encoding="utf-8")
        assert not EMAIL_RE.search(text) and not PHONE_RE.search(text) and not SECRET_RE.search(text), path
        assert "\r" not in text  # LF only (.gitattributes)
    covered = {path.parent.parent.parent.name for path in files}
    assert "B-007" in covered
    cases = {p.stem for p in COMMITTED_RECORDINGS.parent.glob("B-*.yaml")}
    assert covered <= cases  # a recording sits beside a case that exists
