"""PL-LIVE-E2E (issue #340): the live gate of `just live-e2e`. PRD 6.6 EFF-01 ("no paid model calls unless the live
switch is on", CI and dev never live), PRD 6.5 / PL-02 (Gemini on Vertex through Application Default Credentials).

Where the code lives: the evals lane owns the bank runner, so the command is `tilo_evals.live_e2e` (module `main`,
`run_live_e2e`, `LiveE2ERefused`) with a thin script `evals/scripts/live_e2e.py` and the justfile recipe `live-e2e`.
Every model call still goes through `packages/providers` (the Router and its record-and-replay provider); the module
names no model and builds no Google client of its own.

Criteria covered:
  (1) refuses unless the live switch is exactly "1", and looks at nothing else first;
  (2) refuses in CI and on Cloud Run, even with the switch on;
  (3) ADC only: GOOGLE_API_KEY / GEMINI_API_KEY refused by name, never by value; the project must be set;
  (4) `--replay` and `--dry-run` never need the switch, never build a live provider (zero paid calls), and run in CI;
      `--replay` with the switch on is refused (it must never go live);
  (5) the command exists: script, `--help`, justfile recipe.

Ambiguity resolved (PRD 6.6 EFF-01 default): CI is "any non-empty CI or GITHUB_ACTIONS"; Cloud Run is the *presence*
of K_SERVICE or CLOUD_RUN_JOB (even empty), the rule the dev API and the bank runner already use.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from _live_e2e_lib import (
    PROJECT,
    REFUSED_RE,
    REPO_ROOT,
    SCRIPT,
    SpyEnviron,
    cli_args,
    env,
    fake_secret,
    invoke_main,
    live_e2e,
    network_guard,  # noqa: F401  (autouse fixture)
    replay_run,
    world_for,
    write_prices,
)


@pytest.mark.parametrize("live", [None, "", "0", "true", "yes", "01", " 1", "1 "])
def test_PL_LIVE_E2E_01_run_refuses_unless_live_is_exactly_1_and_looks_at_nothing_else_first(
    live: str | None, tmp_path: Path
) -> None:
    values = {"GOOGLE_CLOUD_PROJECT": PROJECT, "CI": "true"}
    if live is not None:
        values["LIVE"] = live
    spy = SpyEnviron(values)
    module = live_e2e()
    world = world_for()
    with env(), pytest.raises(module.LiveE2ERefused) as info:
        module.run_live_e2e(
            case_id="B-007",
            mode="live",
            environ=spy,
            bank_dir=tmp_path / "does-not-exist",  # the gate comes before even reading the bank or config
            prices_path=tmp_path / "does-not-exist.yaml",
            recordings_dir=tmp_path / "recordings-out",
            live_provider_factory=world.factory,
        )
    assert info.value.code == "live_not_enabled"
    assert spy.touched <= {"LIVE"}, f"looked at {sorted(spy.touched)} before the gate"
    assert world.built == [] and world.calls == []
    assert not (tmp_path / "recordings-out").exists()


@pytest.mark.parametrize("live", [None, "0", "true"])
def test_PL_LIVE_E2E_01_main_prints_one_refusal_line_and_exits_2(live: str | None, tmp_path: Path) -> None:
    values = {"GOOGLE_CLOUD_PROJECT": PROJECT}
    if live is not None:
        values["LIVE"] = live
    world = world_for()
    with env():
        result = invoke_main(cli_args(tmp_path), environ=SpyEnviron(values), world=world)
    assert result.code == 2
    assert result.out == ""
    lines = result.err_lines()
    assert len(lines) == 1
    match = REFUSED_RE.match(lines[0])
    assert match and match["code"] == "live_not_enabled"
    assert "LIVE" in match["message"]  # tells the user which switch to set
    assert world.built == [] and world.calls == []


@pytest.mark.parametrize(
    "extra,code",
    [
        ({"CI": "true"}, "ci_refused"),
        ({"GITHUB_ACTIONS": "true"}, "ci_refused"),
        ({"K_SERVICE": "tilo-api"}, "deployed_refused"),
        ({"K_SERVICE": ""}, "deployed_refused"),  # presence, not truthiness: Cloud Run can set an empty string
        ({"CLOUD_RUN_JOB": "nightly"}, "deployed_refused"),
    ],
)
def test_PL_LIVE_E2E_02_refuses_in_ci_and_on_cloud_run_even_with_the_switch_on(
    extra: dict[str, str], code: str, tmp_path: Path
) -> None:
    world = world_for()
    environ = {"LIVE": "1", "GOOGLE_CLOUD_PROJECT": PROJECT, **extra}
    with env():
        result = invoke_main(cli_args(tmp_path), environ=environ, world=world)
    assert result.code == 2
    assert result.out == ""
    lines = result.err_lines()
    assert len(lines) == 1
    match = REFUSED_RE.match(lines[0])
    assert match and match["code"] == code
    assert world.built == [] and world.calls == []
    assert not (tmp_path / "recordings-out").exists()


@pytest.mark.parametrize("name", ["GOOGLE_API_KEY", "GEMINI_API_KEY"])
def test_PL_LIVE_E2E_03_an_api_key_is_refused_by_name_never_by_value(name: str, tmp_path: Path) -> None:
    key_value = fake_secret("api_key")
    world = world_for()
    environ = {"LIVE": "1", "GOOGLE_CLOUD_PROJECT": PROJECT, name: key_value}
    with env():
        result = invoke_main(cli_args(tmp_path), environ=environ, world=world)
    assert result.code == 2
    lines = result.err_lines()
    assert len(lines) == 1
    match = REFUSED_RE.match(lines[0])
    assert match and match["code"] == "api_key_present" and name in match["message"]
    assert key_value not in result.everything
    assert world.built == [] and world.calls == []


def test_PL_LIVE_E2E_03_missing_project_is_refused_naming_the_variable(tmp_path: Path) -> None:
    world = world_for()
    with env():
        result = invoke_main(cli_args(tmp_path), environ={"LIVE": "1"}, world=world)
    assert result.code == 2
    lines = result.err_lines()
    assert len(lines) == 1
    match = REFUSED_RE.match(lines[0])
    assert match and match["code"] == "missing_project" and "GOOGLE_CLOUD_PROJECT" in match["message"]
    assert world.built == [] and world.calls == []


@pytest.mark.parametrize("mode", ["replay", "dry-run"])
@pytest.mark.parametrize("ci", [False, True])
def test_PL_LIVE_E2E_04_replay_and_dry_run_need_no_switch_and_make_zero_paid_calls(
    mode: str, ci: bool, tmp_path: Path
) -> None:
    extra_env = {"CI": "true"} if ci else {}
    if mode == "dry-run":
        world = world_for()
        with env(**extra_env):
            result = invoke_main(cli_args(tmp_path, mode="dry-run"), world=world)
        assert result.code == 0, result.err
    else:  # an empty recordings dir: the run replay-misses, which is not a refusal
        empty = tmp_path / "empty-recordings"
        empty.mkdir()
        result, world = replay_run(tmp_path, empty, extra_env=extra_env)
        assert result.code != 2, result.err
    assert not any(REFUSED_RE.match(line) for line in result.err_lines()), result.err
    assert world.built == [] and world.calls == []  # a live provider was never even constructed


def test_PL_LIVE_E2E_04_replay_with_the_switch_on_is_refused_because_it_must_never_go_live(tmp_path: Path) -> None:
    world = world_for()
    with env():
        result = invoke_main(
            cli_args(tmp_path, mode="replay"), environ={"LIVE": "1", "GOOGLE_CLOUD_PROJECT": PROJECT}, world=world
        )
    assert result.code == 2
    lines = result.err_lines()
    assert len(lines) == 1
    match = REFUSED_RE.match(lines[0])
    assert match and match["code"] == "replay_with_live"
    assert world.built == [] and world.calls == []


def test_PL_LIVE_E2E_05_script_refuses_without_the_switch_in_a_real_process(tmp_path: Path) -> None:
    child_env = {k: v for k, v in os.environ.items() if k not in {"LIVE", "TILO_RECORD", "GOOGLE_API_KEY"}}
    child_env["GOOGLE_CLOUD_PROJECT"] = PROJECT
    done = subprocess.run(
        [sys.executable, str(SCRIPT)], capture_output=True, text=True, env=child_env, cwd=tmp_path, timeout=120
    )
    assert done.returncode == 2, (done.stdout, done.stderr)
    assert "Traceback" not in done.stderr
    lines = [line for line in done.stderr.splitlines() if line.strip()]
    assert len(lines) == 1 and REFUSED_RE.match(lines[0])
    assert "live_not_enabled" in lines[0]


def test_PL_LIVE_E2E_05_script_help_lists_the_flags() -> None:
    child_env = {k: v for k, v in os.environ.items() if k not in {"LIVE", "TILO_RECORD"}}
    done = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"], capture_output=True, text=True, env=child_env, timeout=120
    )
    assert done.returncode == 0, done.stderr
    for flag in ("--case", "--max-credits", "--replay", "--dry-run", "--report-json"):
        assert flag in done.stdout


def test_PL_LIVE_E2E_05_justfile_has_the_live_e2e_recipe_that_runs_the_script() -> None:
    justfile = (REPO_ROOT / "justfile").read_text(encoding="utf-8")
    assert "live-e2e *args:" in justfile
    recipe = justfile.split("live-e2e *args:", 1)[1].split("\n\n", 1)[0]
    assert "evals/scripts/live_e2e.py" in recipe and "{{args}}" in recipe
    assert "LIVE=1" not in recipe  # the user sets the switch; the recipe never does (CLAUDE.md hard rules)


def test_PL_LIVE_E2E_05_prices_must_be_set_before_any_live_call(tmp_path: Path) -> None:
    world = world_for()
    prices = write_prices(tmp_path, status="unset")
    values = {"LIVE": "1", "GOOGLE_CLOUD_PROJECT": PROJECT}
    with env(**values):
        result = invoke_main(cli_args(tmp_path, prices=prices), world=world)
    assert result.code == 2
    lines = result.err_lines()
    assert lines and REFUSED_RE.match(lines[0])
    assert REFUSED_RE.match(lines[0])["code"] == "prices_unset"  # type: ignore[index]
    assert world.calls == []
