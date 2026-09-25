"""PL-01 (PRD 6.4): "Business code never names a model" -- "Lint fails on any
model id outside config/ and packages/providers."

Ticket P0-04 section 4: `scripts/lint_model_ids.py`, stdlib only,
cross-platform, scans tracked files (`git ls-files`) for every `model:`
value in config/models.yaml plus generic patterns for common model families
(gemini-, gemma-, gpt-, claude-, llama-, mistral-, nemotron-); docs (*.md)
and design/source are excluded.

Exercised against throwaway git repos under `tmp_path`, never against this
worktree's own history, so these tests neither depend on nor mutate this
repo's git state. The one exception, `test_PL_01_lint_passes_on_this_repos_
current_tree`, runs the real script against the real repo read-only (no
`git add`/commit), to satisfy the ticket's "and passes on the current tree".
"""

from __future__ import annotations

import subprocess
import sys

import pytest

LINT_SCRIPT_RELATIVE = "scripts/lint_model_ids.py"


@pytest.fixture()
def lint_script(repo_root):
    return repo_root / LINT_SCRIPT_RELATIVE


def _init_git_repo(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)


def _write(tmp_path, relative, content):
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _git_add_all(tmp_path):
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)


def _run_lint(lint_script, cwd):
    return subprocess.run(
        [sys.executable, str(lint_script)],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def test_PL_01_lint_fails_on_model_id_outside_config_and_providers(tmp_path, lint_script):
    _init_git_repo(tmp_path)
    _write(tmp_path, "config/models.yaml", "profiles:\n  large: { provider: fake, model: fake-large-1 }\n")
    _write(
        tmp_path,
        "services/api/src/tilo_api/planner.py",
        'MODEL = "gpt-4o"  # PL-01 violation: a model id outside config/ and packages/providers\n',
    )
    _git_add_all(tmp_path)

    result = _run_lint(lint_script, tmp_path)

    combined = result.stdout + result.stderr
    assert result.returncode != 0, f"PL-01: lint must fail on a model id outside config/, stdout/stderr={combined!r}"
    assert "gpt-4o" in combined, f"PL-01: lint output must name the offending model id, got: {combined!r}"
    assert "planner.py" in combined, f"PL-01: lint output must name the offending file, got: {combined!r}"


def test_PL_01_lint_ignores_model_ids_inside_config_and_providers(tmp_path, lint_script):
    _init_git_repo(tmp_path)
    _write(tmp_path, "config/models.yaml", "profiles:\n  large: { provider: fake, model: gemini-3.8-flash }\n")
    _write(
        tmp_path,
        "packages/providers/src/tilo_providers/adapters/google.py",
        'DEFAULT_MODEL = "gemini-3.8-flash"  # allowed: inside packages/providers\n',
    )
    _write(tmp_path, "services/api/src/tilo_api/planner.py", "ROLE = 'director'  # no model id here\n")
    _git_add_all(tmp_path)

    result = _run_lint(lint_script, tmp_path)

    combined = result.stdout + result.stderr
    assert result.returncode == 0, (
        f"PL-01: lint must pass when every model id sits inside config/ or packages/providers, got: {combined!r}"
    )


def test_PL_01_lint_flags_generic_model_family_pattern_even_if_not_in_config(tmp_path, lint_script):
    """Ticket section 4: generic family patterns (gemini-, gemma-, gpt-,
    claude-, llama-, mistral-, nemotron-) are checked even when the id never
    appears in config/models.yaml."""
    _init_git_repo(tmp_path)
    _write(tmp_path, "config/models.yaml", "profiles:\n  large: { provider: fake, model: fake-large-1 }\n")
    _write(
        tmp_path,
        "services/harness/src/tilo_harness/router.py",
        'FALLBACK = "claude-sonnet-4-5"  # never configured, but still a model id\n',
    )
    _git_add_all(tmp_path)

    result = _run_lint(lint_script, tmp_path)

    combined = result.stdout + result.stderr
    assert result.returncode != 0, f"PL-01: lint must flag a generic model-family pattern, got: {combined!r}"
    assert "claude-sonnet-4-5" in combined


def test_PL_01_lint_ignores_docs_and_design_source(tmp_path, lint_script):
    # Ticket section 4: "Docs (*.md) and design/source are excluded."
    _init_git_repo(tmp_path)
    _write(tmp_path, "config/models.yaml", "profiles:\n  large: { provider: fake, model: fake-large-1 }\n")
    _write(tmp_path, "docs/adr/0099-example.md", "We considered gpt-4o and gemini-3.8-flash.\n")
    _write(tmp_path, "design/source/notes.md", "Prototype used claude-sonnet-4-5.\n")
    _git_add_all(tmp_path)

    result = _run_lint(lint_script, tmp_path)

    combined = result.stdout + result.stderr
    assert result.returncode == 0, f"PL-01: docs/*.md and design/source must be excluded, got: {combined!r}"


def test_PL_01_lint_only_scans_tracked_files(tmp_path, lint_script):
    """`git ls-files` -- an untracked file with a model id must not fail the
    lint (mirrors, e.g., a .gitignore'd scratch file)."""
    _init_git_repo(tmp_path)
    _write(tmp_path, "config/models.yaml", "profiles:\n  large: { provider: fake, model: fake-large-1 }\n")
    tracked = _write(tmp_path, "services/api/src/tilo_api/ok.py", "ROLE = 'director'\n")
    subprocess.run(["git", "add", str(tracked.relative_to(tmp_path)), "config/models.yaml"], cwd=tmp_path, check=True)
    _write(tmp_path, "services/api/src/tilo_api/untracked_scratch.py", 'MODEL = "gpt-4o"\n')

    result = _run_lint(lint_script, tmp_path)

    combined = result.stdout + result.stderr
    assert result.returncode == 0, f"PL-01: an untracked file must not fail the lint, got: {combined!r}"


@pytest.mark.slow
def test_PL_01_lint_passes_on_this_repos_current_tree(repo_root, lint_script):
    result = _run_lint(lint_script, repo_root)

    combined = result.stdout + result.stderr
    assert result.returncode == 0, f"PL-01: the lint must pass on the current tree, got: {combined!r}"
