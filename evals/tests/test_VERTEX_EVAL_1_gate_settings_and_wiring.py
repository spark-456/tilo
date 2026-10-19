"""VERTEX-EVAL-1 (PR 1b, evals half; design 3.1-3.3, 4; ADR-0033; PRD 6.4 PL-01/PL-04, 6.6 EFF-01/EFF-07, 19.3):
the live gate, the cap range, the settings file and its schema, the config and price checks, the rubric files, and
the wiring (git-ignored outputs, the justfile recipe).

Criteria covered (test numbers are the design's section 5 list):
  16 live is refused before any file is read; 17 refused in CI, when deployed, with an API key, or without a project;
  18 --fake is refused with the live switch; 19 a cap outside (0, 19] is refused; 20 the settings schema refuses
  unknown keys and bad values; 21 live is refused without the eval role or its price, printing the needed lines;
  rubrics (PL-04) with the service's placeholders, fenced, and no model id (PL-01); 39 default outputs git-ignored.
Ambiguities resolved (design silent): refusal text is `REFUSED <code>: ...` on stderr as `generate` prints it; the
settings file is selected with `--settings` (as `generate`); `--dry-run` works without the live switch (design 3.2:
"--fake and --dry-run work with no network/ADC").
"""

from __future__ import annotations

import json
import math
import re
import subprocess
from pathlib import Path

import jsonschema
import pytest
import yaml
from _vertex_eval_lib import (
    GROUNDED_FILE,
    LIVE_ENV,
    PAIR_PLACEHOLDERS,
    PAIRWISE_FILE,
    PROJECT,
    PROMPTS,
    REAL_SETTINGS,
    REAL_SETTINGS_SCHEMA,
    REPO_ROOT,
    SETTINGS,
    Boom,
    assert_refused,
    fences,
    ids_of,
    invoke,
    live_models,
    live_run_argv,
    network_guard,  # noqa: F401  (autouse fixture)
    pair_row,
    rubric,
    run_argv,
    write_models,
    write_pairs,
    write_prices,
    write_settings,
    write_yaml,
)

HARD_MAX = 19


def _pairs(tmp_path: Path) -> Path:
    return write_pairs(tmp_path, [pair_row(i) for i in ids_of(2)])


def test_VERTEX_EVAL_1_command_is_registered() -> None:
    """The subcommands exist: `vertex-eval run --help` and `vertex-eval export --help` print the pinned flags."""
    for sub, flag in (("run", "--pairs"), ("export", "--candidate")):
        result = invoke(["vertex-eval", sub, "--help"])
        assert result.code == 0, result.err
        assert flag in result.out, result.out


# --- 16, 17: the gate, first of all ----------------------------------------------------------------------------------


def test_VERTEX_EVAL_1_live_refused_before_any_read(tmp_path: Path) -> None:
    """Pairs, settings, models and prices are all missing and the code is still `live_not_enabled`: the switch is
    looked at before any file, config or Google import (design 3.3)."""
    argv = [
        "vertex-eval", "run", "--pairs", str(tmp_path / "missing-pairs.yaml"),
        "--settings", str(tmp_path / "missing-settings.yaml"),
        "--models-file", str(tmp_path / "missing-models.yaml"),
        "--prices-file", str(tmp_path / "missing-prices.yaml"),
        "--report-md", str(tmp_path / "report.md"),
    ]  # fmt: skip
    for environ in ({}, {"GOOGLE_CLOUD_PROJECT": PROJECT}, {"LIVE": "0", "GOOGLE_CLOUD_PROJECT": PROJECT}):
        result = invoke(argv, environ=environ, provider=Boom())
        assert_refused(result, "live_not_enabled")
        assert not (tmp_path / "report.md").exists()


@pytest.mark.parametrize("value", ["", "0", "true", "yes", "TRUE", "01", " 1", "1 ", "2"])
def test_VERTEX_EVAL_1_live_needs_exactly_1(value: str, tmp_path: Path) -> None:
    result = invoke(live_run_argv(tmp_path, _pairs(tmp_path)), environ={"LIVE": value, "GOOGLE_CLOUD_PROJECT": PROJECT})
    assert_refused(result, "live_not_enabled")


@pytest.mark.parametrize(
    ("marker", "code"),
    [
        ("CI", "ci_refused"),
        ("GITHUB_ACTIONS", "ci_refused"),
        ("K_SERVICE", "deployed_refused"),
        ("CLOUD_RUN_JOB", "deployed_refused"),
        ("GOOGLE_API_KEY", "api_key_present"),
        ("GEMINI_API_KEY", "api_key_present"),
    ],
)
@pytest.mark.parametrize("where", ["environ", "process"])
def test_VERTEX_EVAL_1_live_refused_in_ci_deployed_or_with_api_key(
    marker: str, code: str, where: str, tmp_path: Path
) -> None:
    argv = live_run_argv(tmp_path, _pairs(tmp_path))
    value = "x" if marker.endswith("KEY") else "true"
    provider = Boom()
    if where == "environ":
        result = invoke(argv, environ={**LIVE_ENV, marker: value}, provider=provider)
    else:  # the real process environment: a marker there is never hidden by the caller's own mapping
        result = invoke(argv, environ=LIVE_ENV, process_env={marker: value}, provider=provider)
    assert_refused(result, code)
    assert not (tmp_path / "report.md").exists()


def test_VERTEX_EVAL_1_live_refused_in_deployed_marker_present_but_empty(tmp_path: Path) -> None:
    """Presence, not truthiness: Cloud Run can set a variable to an empty string."""
    for marker in ("K_SERVICE", "CLOUD_RUN_JOB"):
        result = invoke(live_run_argv(tmp_path, _pairs(tmp_path)), environ={**LIVE_ENV, marker: ""}, provider=Boom())
        assert_refused(result, "deployed_refused")


def test_VERTEX_EVAL_1_live_refused_without_project(tmp_path: Path) -> None:
    result = invoke(live_run_argv(tmp_path, _pairs(tmp_path)), environ={"LIVE": "1"}, provider=Boom())
    assert_refused(result, "missing_project")


# --- 18: --fake and the live switch ----------------------------------------------------------------------------------


def test_VERTEX_EVAL_1_fake_refused_with_live_switch(tmp_path: Path) -> None:
    result = invoke(run_argv(tmp_path, _pairs(tmp_path)), environ=LIVE_ENV, provider=Boom())
    assert_refused(result)
    assert "LIVE" in result.err, result.err
    assert not (tmp_path / "report.md").exists()


def test_VERTEX_EVAL_1_fake_and_dry_run_need_no_live_switch(tmp_path: Path) -> None:
    pairs = _pairs(tmp_path)
    fake = invoke(run_argv(tmp_path, pairs, report=tmp_path / "fake.md"), provider=None)
    assert fake.code == 0, fake.err
    dry = invoke(run_argv(tmp_path, pairs, mode="--dry-run"), provider=Boom())
    assert dry.code == 0, dry.err


# --- 19: the cap ----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("cap", ["19.01", "0", "-1", "-0.5", "nan", "inf", "-inf", "20", "1000000"])
@pytest.mark.parametrize("mode", ["fake", "live"])
def test_VERTEX_EVAL_1_cap_out_of_range_refused(cap: str, mode: str, tmp_path: Path) -> None:
    pairs = _pairs(tmp_path)
    if mode == "fake":
        result = invoke(run_argv(tmp_path, pairs, extra=("--max-credits", cap)), provider=Boom())
    else:
        result = invoke(live_run_argv(tmp_path, pairs, extra=("--max-credits", cap)), environ=LIVE_ENV, provider=Boom())
    assert_refused(result)
    assert "cap_out_of_range" in result.err or "max-credits" in result.err, result.err
    assert not (tmp_path / "report.md").exists()


def test_VERTEX_EVAL_1_cap_checked_before_files_in_live_mode(tmp_path: Path) -> None:
    """With the live switch right, a bad cap is refused ahead of the (missing) settings and pairs files."""
    argv = ["vertex-eval", "run", "--pairs", str(tmp_path / "nope.yaml"), "--max-credits", "19.5"]
    argv += ["--settings", str(tmp_path / "nope-settings.yaml")]
    assert_refused(invoke(argv, environ=LIVE_ENV, provider=Boom()), "cap_out_of_range")


@pytest.mark.parametrize("cap", [19, 19.0, 0.5, 18])
def test_VERTEX_EVAL_1_cap_inside_range_is_accepted(cap: float, tmp_path: Path) -> None:
    result = invoke(run_argv(tmp_path, _pairs(tmp_path), mode="--dry-run", cap=cap), provider=Boom())
    assert result.code == 0, result.err
    assert math.isclose(float(re.search(r"cap=(\d+\.\d+)", result.out)[1]), float(cap), abs_tol=1e-4), result.out  # type: ignore[index]


@pytest.mark.parametrize("settings_cap", [19.01, 25, 100])
def test_VERTEX_EVAL_1_settings_cap_above_hard_max_refused(settings_cap: float, tmp_path: Path) -> None:
    """HARD_MAX_CREDITS = 19 is a code constant: the settings file cannot raise it."""
    settings = write_settings(tmp_path, max_credits=settings_cap)
    result = invoke(run_argv(tmp_path, _pairs(tmp_path), settings=settings), provider=Boom())
    assert_refused(result, "cap_out_of_range")


# --- 20: the settings file and its schema ---------------------------------------------------------------------------


def _schema() -> jsonschema.Draft202012Validator:
    assert REAL_SETTINGS_SCHEMA.is_file(), "evals/vertex_eval.schema.json does not exist"
    return jsonschema.Draft202012Validator(json.loads(REAL_SETTINGS_SCHEMA.read_text(encoding="utf-8")))


def test_VERTEX_EVAL_1_settings_file_holds_the_designs_values_and_validates() -> None:
    assert REAL_SETTINGS.is_file(), "evals/vertex_eval.yaml does not exist"
    data = yaml.safe_load(REAL_SETTINGS.read_text(encoding="utf-8"))
    _schema().validate(data)
    assert data["max_credits"] == 18 and data["max_credits"] <= HARD_MAX  # under 20 credits a run, always
    assert data["max_cases"] == 20
    assert data["assumed_output_tokens"] == 512 and data["overhead_tokens"] == 400
    assert data["field_chars"] == {"prompt": 1500, "context": 3000, "response": 2500}
    assert data["metrics"] == SETTINGS["metrics"]


def test_VERTEX_EVAL_1_settings_schema_refuses_unknown_keys_and_bad_values() -> None:
    validator = _schema()
    good = yaml.safe_load(REAL_SETTINGS.read_text(encoding="utf-8"))
    assert not list(validator.iter_errors(good))

    def broken(mutate) -> dict:  # noqa: ANN001
        data = json.loads(json.dumps(good))
        mutate(data)
        return data

    cases = {
        "unknown top-level key": lambda d: d.update(surprise=1),
        "unknown field_chars key": lambda d: d["field_chars"].update(extra=10),
        "unknown metrics key": lambda d: d["metrics"].update(extra={}),
        "unknown metric key": lambda d: d["metrics"]["pairwise"].update(extra="x"),
        "max_credits zero": lambda d: d.update(max_credits=0),
        "max_credits negative": lambda d: d.update(max_credits=-3),
        "max_credits text": lambda d: d.update(max_credits="18"),
        "max_credits bool": lambda d: d.update(max_credits=True),
        "max_cases zero": lambda d: d.update(max_cases=0),
        "max_cases fraction": lambda d: d.update(max_cases=2.5),
        "assumed_output_tokens zero": lambda d: d.update(assumed_output_tokens=0),
        "overhead_tokens negative": lambda d: d.update(overhead_tokens=-1),
        "field_chars zero": lambda d: d["field_chars"].update(prompt=0),
        "field_chars text": lambda d: d["field_chars"].update(context="3000"),
        "field_chars missing key": lambda d: d["field_chars"].pop("response"),
        "metric id not a slug": lambda d: d["metrics"]["pairwise"].update(id="Plan Pairwise"),
        "template with a path": lambda d: d["metrics"]["groundedness"].update(template="../secrets.md"),
    }
    for required in good:
        cases[f"missing {required}"] = lambda d, key=required: d.pop(key)
    for label, mutate in cases.items():
        assert list(validator.iter_errors(broken(mutate))), f"the schema accepted: {label}"


def test_VERTEX_EVAL_1_cli_refuses_a_bad_settings_file(tmp_path: Path) -> None:
    pairs = _pairs(tmp_path)
    bad = {**SETTINGS, "surprise": True}
    for name, data in (("unknown", bad), ("zero", {**SETTINGS, "max_cases": 0}), ("list", ["not", "a", "mapping"])):
        path = write_yaml(tmp_path / f"{name}.yaml", data)
        result = invoke(run_argv(tmp_path, pairs, settings=path), provider=Boom())
        assert_refused(result)
    missing = invoke(run_argv(tmp_path, pairs, settings=tmp_path / "nope.yaml"), provider=Boom())
    assert_refused(missing)
    assert not (tmp_path / "report.md").exists()


# --- 21: the eval role and its price --------------------------------------------------------------------------------


def test_VERTEX_EVAL_1_live_refused_without_eval_role_or_price(tmp_path: Path) -> None:
    pairs = _pairs(tmp_path)
    prices = write_prices(tmp_path, profile="judge-live")
    no_role = write_models(tmp_path, provider="vertex_eval", profile="judge-live", role=False, name="norole.yaml")
    cases = {  # label: (models file, prices file, does the refusal print the lines the user adds)
        "no eval_judge role": (no_role, prices, True),
        "no price row": (live_models(tmp_path), write_prices(tmp_path, profile="judge-live", with_profile=False), True),
        "prices unset": (live_models(tmp_path), write_prices(tmp_path, profile="judge-live", status="unset"), True),
        "models file missing": (tmp_path / "nope-models.yaml", prices, False),
        "prices file missing": (live_models(tmp_path), tmp_path / "nope-prices.yaml", False),
    }
    for label, (models, price_file, prints_lines) in cases.items():
        argv = run_argv(tmp_path, pairs, mode="", models=models, prices=price_file)
        result = invoke(argv, environ=LIVE_ENV, provider=Boom())
        assert_refused(result, "config_invalid")
        if prints_lines:  # the refusal prints what the user adds, together (design 3.1)
            assert "eval_judge" in result.err and "vertex-eval" in result.err, (label, result.err)
        assert not (tmp_path / "report.md").exists(), label


def test_VERTEX_EVAL_1_no_model_id_appears_in_a_refusal(tmp_path: Path) -> None:
    models = write_models(tmp_path, provider="vertex_eval", profile="judge-live", role=False)
    prices = write_prices(tmp_path, profile="judge-live")
    result = invoke(run_argv(tmp_path, _pairs(tmp_path), mode="", models=models, prices=prices), environ=LIVE_ENV)
    assert_refused(result, "config_invalid")
    assert "zz-judge-model-under-test" not in result.everything
    assert PROJECT not in result.everything


# --- the rubrics (PL-04) and PL-01 ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "placeholders"),
    [(PAIRWISE_FILE, PAIR_PLACEHOLDERS), (GROUNDED_FILE, ("prompt", "context", "response"))],
)
def test_VERTEX_EVAL_1_rubric_has_service_placeholders_once_each_inside_fences(
    name: str, placeholders: tuple[str, ...]
) -> None:
    path = PROMPTS / name
    assert path.is_file(), f"prompts/eval_judge/{name} does not exist"
    text = rubric(name)
    assert "\r" not in text and text.endswith("\n")
    blocks = re.findall(r"<<<([A-Z_]+)\n(.*?)\n\1>>>", text, flags=re.DOTALL)
    assert len(blocks) == len(placeholders), (blocks, placeholders)
    for placeholder in PAIR_PLACEHOLDERS:
        token = "{" + placeholder + "}"
        if placeholder in placeholders:
            assert text.count(token) == 1, f"{token} must appear exactly once in {name}"
            assert sum(token in body for _, body in blocks) == 1, f"{token} must sit inside its own fence"
        else:
            assert token not in text
    assert any(marker == "RESPONSE" and "{response}" in body for marker, body in blocks)
    assert text.count("<<<RESPONSE") == 1 and text.count("RESPONSE>>>") == 1
    assert len(set(fences(text))) == len(placeholders)


def test_VERTEX_EVAL_1_rubric_text_names_the_task() -> None:
    pairwise, grounded = rubric(PAIRWISE_FILE), rubric(GROUNDED_FILE)
    assert re.search(r"(?i)\bdata\b[^.\n]*\bnot instructions\b|never follow", pairwise), "no injection warning"
    assert re.search(r"(?i)\bdata\b[^.\n]*\bnot instructions\b|never follow", grounded), "no injection warning"
    assert re.search(r"(?i)\bpair|better|prefer", pairwise)
    assert re.search(r"(?i)support", grounded) and re.search(r"\b0\b", grounded) and re.search(r"\b1\b", grounded)
    # a planning decision is not a factual claim (design 1.3 (b))
    assert re.search(r"(?i)planning decision|decision", grounded)


def test_VERTEX_EVAL_1_no_model_id_in_evals_prompts_or_settings() -> None:
    """PL-01: ids live in config/ and packages/providers only; rubrics, settings, schema and the source hold none."""
    ids: set[str] = set()
    for path in (REPO_ROOT / "config").glob("models*.yaml"):
        for profile in (yaml.safe_load(path.read_text(encoding="utf-8")).get("profiles") or {}).values():
            ids.add(str(profile["model"]))
    pattern = re.compile("|".join(re.escape(i) for i in sorted(ids, key=len, reverse=True)))
    family = re.compile(r"\b(?:gemini|gemma|gpt|claude|llama|mistral|nemotron)-[\w.-]+", re.IGNORECASE)
    source = REPO_ROOT / "evals" / "src" / "tilo_evals" / "vertex_eval.py"
    assert source.is_file(), "evals/src/tilo_evals/vertex_eval.py does not exist"
    files = [source, REAL_SETTINGS, REAL_SETTINGS_SCHEMA, *sorted(PROMPTS.glob("*"))]
    for path in files:
        assert path.is_file(), path
        text = path.read_text(encoding="utf-8")
        assert not pattern.search(text), f"{path}: a model id from config/models*.yaml"
        assert not family.search(text), f"{path}: a model id"


def test_VERTEX_EVAL_1_new_module_is_not_read_by_the_metrics_or_results_code() -> None:
    """EV rows stay apart (design 3.4 / ADR-0033): nothing that computes EV rows or results.md knows this module."""
    src = REPO_ROOT / "evals" / "src" / "tilo_evals"
    assert (src / "vertex_eval.py").is_file()
    for name in ("metrics.py", "metrics_report.py", "results.py", "runner.py", "bank_report.py"):
        assert "vertex_eval" not in (src / name).read_text(encoding="utf-8"), name


# --- 39: wiring ------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["evals/vertex-eval/pairs.local.yaml", "evals/vertex-eval/report.local.md"])
def test_VERTEX_EVAL_1_default_outputs_are_git_ignored(path: str) -> None:
    done = subprocess.run(
        ["git", "check-ignore", "-q", path], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, f"{path} is not git-ignored"


def test_VERTEX_EVAL_1_justfile_has_the_recipe_and_never_the_live_switch() -> None:
    text = (REPO_ROOT / "justfile").read_text(encoding="utf-8")
    assert re.search(r"^vertex-eval \*args:\s*\n\s+uv run python -m tilo_evals vertex-eval \{\{args\}\}", text, re.M)
    assert "LIVE" + "=1" not in text.split("vertex-eval *args:")[1].split("\n\n")[0]


def test_VERTEX_EVAL_1_evals_claude_md_documents_the_command() -> None:
    text = (REPO_ROOT / "evals" / "CLAUDE.md").read_text(encoding="utf-8")
    assert "vertex-eval" in text and "export" in text
    assert "run" in text.split("vertex-eval", 1)[1]
