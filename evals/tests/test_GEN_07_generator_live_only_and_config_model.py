"""GEN-07 (issue #272 (b); PRD 6.6 EFF-01, 6.4 PL-01, PL-04): `uv run python -m tilo_evals generate --n N` is
user-run only, takes its model from configuration, keeps its prompt in prompts/generator/, and is given the
domain x shape matrix, never bank case text.

Criteria covered:
  (1) refuses unless LIVE is exactly "1", and refuses when CI, K_SERVICE or CLOUD_RUN_JOB is set even with LIVE=1;
      a refusal is exit code 2, says why on stderr, and happens before any provider is built or any file written;
  (2) the model is the `generator` role of config/models.yaml, called through the provider layer (the fake provider
      is built for that role and that role's profile, and answers the call); no model id appears under evals/ (PL-01);
  (3) the prompt lives in prompts/generator/ and is what the model receives; it carries the domain and shape matrix
      and none of the bank's case text (the generator invents; code never copies a case).
Ambiguity resolved: `--dry-run` is tested only with LIVE=1 set (whether a dry run needs the switch is not pinned).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import jsonschema
import pytest
import yaml
from _generator_lib import (
    ESTIMATE_RE,
    GENERATOR_ROLE,
    LIVE_ENV,
    REAL_SETTINGS,
    REAL_SETTINGS_SCHEMA,
    REPO_ROOT,
    RecordingSafety,
    cli_args,
    env,
    gen_world,
    generated_files,
    invoke_generate,
    live_generate,
    network_guard,  # noqa: F401  (autouse fixture)
    tree,
)
from tilo_evals.bank import load_bank

BANK = REPO_ROOT / "evals" / "bank"
MODELS = REPO_ROOT / "config" / "models.yaml"
PROMPTS = REPO_ROOT / "prompts" / "generator"


def _assert_refused(result, world, tmp_path: Path, *, mention: str) -> None:
    assert result.code == 2, (result.code, result.err)
    assert mention in result.err, result.err
    assert world.built == [] and world.calls == []  # no provider was built, none was called
    assert not (tmp_path / "generated").exists()  # nothing written


def test_GEN_07_generator_live_only_and_config_model(tmp_path: Path) -> None:
    """The headline: no LIVE, no run; with LIVE=1 the `generator` role of config/models.yaml writes the briefs."""
    world = gen_world(briefs=[])
    with env():  # a clean environment: no live switch
        refused = invoke_generate(cli_args(tmp_path, n=2), world=world)
    _assert_refused(refused, world, tmp_path, mention="LIVE")

    roles = yaml.safe_load(MODELS.read_text(encoding="utf-8"))["roles"]
    assert GENERATOR_ROLE in roles, "config/models.yaml has no `generator` role"
    result, world = live_generate(tmp_path, n=2)
    assert result.code in (0, 1, 3), result.err
    profiles = {roles[GENERATOR_ROLE]["primary"], roles[GENERATOR_ROLE].get("fallback")}
    built = [profile for role, profile in world.built if role == GENERATOR_ROLE]
    assert built and set(built) <= profiles, (built, profiles)
    assert len(world.calls_of(GENERATOR_ROLE)) >= 1


@pytest.mark.parametrize("value", [None, "", "0", "true", "yes", "TRUE", "01", " 1", "1 ", "2"])
def test_GEN_07_refuses_unless_live_is_exactly_1(value: str | None, tmp_path: Path) -> None:
    world = gen_world()
    environ = {"GOOGLE_CLOUD_PROJECT": "demo-project"} | ({} if value is None else {"LIVE": value})
    with env():
        result = invoke_generate(cli_args(tmp_path), world=world, environ=environ)
    _assert_refused(result, world, tmp_path, mention="LIVE")


@pytest.mark.parametrize("marker", ["CI", "K_SERVICE", "CLOUD_RUN_JOB"])
@pytest.mark.parametrize("where", ["environ", "process"])
def test_GEN_07_refuses_in_ci_or_deployed_even_with_live_set(marker: str, where: str, tmp_path: Path) -> None:
    world = gen_world()
    value = "true" if marker == "CI" else "tilo-api"
    if where == "environ":  # the mapping the caller gives, with a clean process environment
        with env():
            result = invoke_generate(cli_args(tmp_path), world=world, environ={**LIVE_ENV, marker: value})
    else:  # the real process environment: a marker there is never hidden by the caller's own mapping
        with env(**LIVE_ENV, **{marker: value}):
            result = invoke_generate(cli_args(tmp_path), world=world, environ=dict(LIVE_ENV))
    _assert_refused(result, world, tmp_path, mention=marker)


def test_GEN_07_refuses_a_run_with_no_briefs_asked_for(tmp_path: Path) -> None:
    for n in (0, -1):
        world = gen_world()
        with env(**LIVE_ENV):
            result = invoke_generate(cli_args(tmp_path, n=n), world=world)
        assert result.code == 2, (n, result.out, result.err)
        assert world.calls == []


def test_GEN_07_the_real_command_line_refuses_without_live(tmp_path: Path) -> None:
    """`python -m tilo_evals generate --n 1` in a real subprocess with no live switch: refused, nothing written."""
    import os  # noqa: PLC0415
    import subprocess  # noqa: PLC0415
    import sys  # noqa: PLC0415

    clean = {k: v for k, v in os.environ.items() if k not in {*LIVE_ENV, "CI", "K_SERVICE", "CLOUD_RUN_JOB"}}
    clean["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        [sys.executable, "-m", "tilo_evals", "generate", "--n", "1", "--out-dir", str(tmp_path / "generated")],
        cwd=REPO_ROOT,
        env=clean,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 2, (proc.returncode, proc.stdout, proc.stderr)
    assert "LIVE" in proc.stderr
    assert not (tmp_path / "generated").exists()


def test_GEN_07_a_dry_run_builds_no_provider_and_prints_the_estimate_first(tmp_path: Path) -> None:
    world = gen_world()
    with env(**LIVE_ENV):
        result = invoke_generate(cli_args(tmp_path, dry_run=True), world=world)
    assert result.code == 0, result.err
    assert ESTIMATE_RE.match(result.out_lines()[0]), result.out
    assert world.built == [] and world.calls == []


def test_GEN_07_the_model_is_configuration_only_no_model_id_under_evals() -> None:
    """PL-01: no model id in evals/ (source, settings, schema, prompts/generator). Ids come from config/models*.yaml."""
    ids: set[str] = set()
    for path in (REPO_ROOT / "config").glob("models*.yaml"):
        for profile in (yaml.safe_load(path.read_text(encoding="utf-8")).get("profiles") or {}).values():
            ids.add(str(profile["model"]))
    assert ids, "no model ids found in config/models*.yaml"
    pattern = re.compile("|".join(re.escape(i) for i in sorted(ids, key=len, reverse=True)))
    family = re.compile(r"\b(?:gemini|gemma|gpt|claude|llama|mistral|nemotron)-[\w.-]+", re.IGNORECASE)
    generator_py = REPO_ROOT / "evals" / "src" / "tilo_evals" / "generator.py"
    assert generator_py.is_file(), "evals/src/tilo_evals/generator.py does not exist"
    roots = [REPO_ROOT / "evals" / "src", PROMPTS]
    files = [p for root in roots if root.exists() for p in root.rglob("*") if p.is_file()]
    files += [p for p in (REAL_SETTINGS, REAL_SETTINGS_SCHEMA) if p.exists()]
    assert generator_py in files
    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        assert not pattern.search(text) and not family.search(text), f"a model id appears in {path}"


def test_GEN_07_the_prompt_lives_in_prompts_generator_and_is_what_the_model_receives(tmp_path: Path) -> None:
    templates = sorted(PROMPTS.glob("*.md"))
    assert templates, "prompts/generator/ holds no template (PL-04)"
    world = gen_world()
    result, world = live_generate(tmp_path, world=world, n=2)
    assert result.code in (0, 1, 3), result.err
    asked = [req for role, req in world.requests if role == GENERATOR_ROLE]
    assert asked, "the generator role was never called"
    sent = "\n".join(f"{req.system or ''}\n{req.prompt}" for req in asked)
    lines = [
        ln.strip()
        for t in templates
        for ln in t.read_text(encoding="utf-8").splitlines()
        if len(ln.strip()) >= 30 and "$" not in ln and not ln.lstrip().startswith(("#", "<!--"))
    ]
    assert lines, "the generator templates hold no plain line to look for"
    assert any(" ".join(ln.split()) in " ".join(sent.split()) for ln in lines), "no template text reached the model"


def test_GEN_07_the_model_is_given_the_matrix_and_never_a_bank_case(tmp_path: Path) -> None:
    schema = json.loads((REPO_ROOT / "evals" / "bank.schema.json").read_text(encoding="utf-8"))
    domains = schema["properties"]["domain"]["enum"]
    shapes = schema["properties"]["shapes"]["items"]["enum"]
    result, world = live_generate(tmp_path, n=3, bank=BANK)
    assert result.code in (0, 1, 3), result.err
    asked = [req for role, req in world.requests if role == GENERATOR_ROLE]
    assert asked
    sent = "\n".join(f"{req.system or ''}\n{req.prompt}" for req in asked)
    missing = [name for name in (*domains, *shapes) if name not in sent]
    assert not missing, f"the matrix is not in the prompt: {missing}"

    flat = " ".join(sent.lower().split())
    words_of = lambda text: re.findall(r"[a-z0-9']+", text.lower())  # noqa: E731
    for case in load_bank(BANK):
        assert case.title.lower() not in flat, f"{case.id}'s title was sent to the generator"
        words = words_of(case.brief)
        for i in range(len(words) - 5):
            assert " ".join(words[i : i + 6]) not in " ".join(words_of(sent)), f"text of {case.id} was sent"


def test_GEN_07_the_screen_sees_every_brief_the_model_wrote(tmp_path: Path) -> None:
    screen = RecordingSafety()
    world = gen_world()
    result, world = live_generate(tmp_path, world=world, safety=screen, n=3)
    assert result.code in (0, 1, 3), result.err
    wrote = {b["brief"] for b in world.briefs}
    assert wrote <= set(screen.checked), "a generated brief was not screened"


def test_GEN_07_the_generator_settings_have_a_home_and_a_schema_and_say_inr_150() -> None:
    """No contract change: the cap lives in an evals-local file with its own schema (contracts/evals.schema.json
    forbids extra keys), not in config/evals.yaml. The user approved INR 150 per run (issue #272, decision 3)."""
    assert REAL_SETTINGS.is_file(), "evals/generator.yaml is missing"
    assert REAL_SETTINGS_SCHEMA.is_file(), "evals/generator.schema.json is missing"
    settings = yaml.safe_load(REAL_SETTINGS.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(json.loads(REAL_SETTINGS_SCHEMA.read_text(encoding="utf-8"))).validate(settings)
    assert settings["max_inr"] == 150
    assert settings["inr_per_usd"] > 0  # the repo has no INR rate yet: the settings file carries the one in use
    evals_yaml = yaml.safe_load((REPO_ROOT / "config" / "evals.yaml").read_text(encoding="utf-8"))
    assert "generator" not in evals_yaml and "max_inr" not in evals_yaml


def test_GEN_07_the_real_cap_is_150_inr_in_credits(tmp_path: Path) -> None:
    """The dry run's cap is `max_inr / inr_per_usd / credit_usd` from the real settings and the prices file."""
    settings = yaml.safe_load(REAL_SETTINGS.read_text(encoding="utf-8"))
    argv = cli_args(tmp_path, dry_run=True)
    at = argv.index("--settings")
    del argv[at : at + 2]  # no --settings: the real evals/generator.yaml is used
    with env(**LIVE_ENV):
        result = invoke_generate(argv, world=gen_world())
    assert result.code == 0, result.err
    match = ESTIMATE_RE.match(result.out_lines()[0])
    assert match, result.out
    assert float(match["cap"]) == pytest.approx(150 / settings["inr_per_usd"] / 0.005, abs=1e-3)


def test_GEN_07_a_refused_run_changes_nothing_in_the_bank(tmp_path: Path) -> None:
    before = tree(BANK)
    with env():
        invoke_generate(cli_args(tmp_path, bank=BANK), world=gen_world())
    assert tree(BANK) == before
    assert generated_files(tmp_path / "generated") == []
