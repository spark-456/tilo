"""PRD 20.3 stack (Python 3.12 with uv; TypeScript with pnpm) and the ticket's
root-level scaffold deliverables: pyproject.toml, pnpm workspace, pre-commit
config, secret scanner, .env.example, .editorconfig, README skeleton.
"""

from __future__ import annotations

import json
import pathlib
import tomllib

import yaml


def test_PRD_20_3_python_version_pinned_to_3_12(repo_root: pathlib.Path) -> None:
    version_file = repo_root / ".python-version"
    assert version_file.is_file(), ".python-version must exist at the repo root"
    assert version_file.read_text(encoding="utf-8").strip() == "3.12"


def test_PRD_20_3_root_pyproject_requires_python_3_12(repo_root: pathlib.Path) -> None:
    pyproject = repo_root / "pyproject.toml"
    assert pyproject.is_file(), "root pyproject.toml must exist (uv workspace root)"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    requires_python = data.get("project", {}).get("requires-python", "")
    assert "3.12" in requires_python, f"requires-python must pin 3.12.*, got {requires_python!r}"


def test_PRD_20_3_root_pyproject_has_dev_dependency_group(repo_root: pathlib.Path) -> None:
    pyproject = repo_root / "pyproject.toml"
    assert pyproject.is_file(), "root pyproject.toml must exist (uv workspace root)"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    dep_groups = data.get("dependency-groups", {})
    dev_group = dep_groups.get("dev", [])
    dev_group_text = " ".join(d for d in dev_group if isinstance(d, str)).lower()

    for pkg in ["pytest", "hypothesis", "ruff", "mypy", "pre-commit", "pyyaml", "httpx"]:
        assert pkg in dev_group_text, f"pyproject.toml dev dependency-group must include {pkg}"


def test_PRD_20_3_uv_lock_committed(repo_root: pathlib.Path) -> None:
    assert (repo_root / "uv.lock").is_file(), "uv.lock must be committed at the repo root"


def test_PRD_20_3_root_pyproject_workspace_members(repo_root: pathlib.Path) -> None:
    pyproject = repo_root / "pyproject.toml"
    assert pyproject.is_file(), "root pyproject.toml must exist (uv workspace root)"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    members = data.get("tool", {}).get("uv", {}).get("workspace", {}).get("members", [])
    members_text = " ".join(members)
    assert "services/api" in members_text, "uv workspace must include services/api (has code now)"
    assert "packages/providers" in members_text, "uv workspace must include packages/providers (has code now)"


def test_PRD_20_3_pnpm_workspace_yaml_exists(repo_root: pathlib.Path) -> None:
    pnpm_workspace = repo_root / "pnpm-workspace.yaml"
    assert pnpm_workspace.is_file(), "pnpm-workspace.yaml must exist at the repo root"
    data = yaml.safe_load(pnpm_workspace.read_text(encoding="utf-8"))
    packages = data.get("packages", [])
    assert any("apps/*" == p for p in packages), "pnpm-workspace.yaml must list apps/*"
    assert any("packages/*-ts" == p for p in packages), "pnpm-workspace.yaml must list packages/*-ts"


def test_PRD_20_3_root_package_json_pins_pnpm_and_node(repo_root: pathlib.Path) -> None:
    package_json = repo_root / "package.json"
    assert package_json.is_file(), "root package.json must exist"
    data = json.loads(package_json.read_text(encoding="utf-8"))

    package_manager = data.get("packageManager", "")
    assert package_manager.startswith("pnpm@"), "package.json packageManager must pin a pnpm version via corepack"
    major_version = int(package_manager.split("@")[1].split(".")[0])
    assert major_version >= 10, f"packageManager must pin pnpm 10.x or later, got {package_manager!r}"

    node_engine = data.get("engines", {}).get("node", "")
    assert ">=22" in node_engine, f"package.json engines.node must require >=22, got {node_engine!r}"


def test_PRD_20_3_pnpm_lock_committed(repo_root: pathlib.Path) -> None:
    assert (repo_root / "pnpm-lock.yaml").is_file(), "pnpm-lock.yaml must be committed at the repo root"


def test_PRD_20_3_biome_configured(repo_root: pathlib.Path) -> None:
    has_biome_config = (repo_root / "biome.json").is_file() or (repo_root / "biome.jsonc").is_file()
    assert has_biome_config, "a biome.json(c) must exist to configure Biome for TS/JSON lint and format"


def test_PRD_20_3_tsconfig_base_is_strict(repo_root: pathlib.Path) -> None:
    tsconfig = repo_root / "tsconfig.base.json"
    assert tsconfig.is_file(), "tsconfig.base.json must exist at the repo root"
    # tsconfig.json permits comments; strip // line comments before parsing.
    lines = [ln for ln in tsconfig.read_text(encoding="utf-8").splitlines() if not ln.strip().startswith("//")]
    data = json.loads("\n".join(lines))
    assert data.get("compilerOptions", {}).get("strict") is True, "tsconfig.base.json must set compilerOptions.strict"


def test_PRD_20_3_pre_commit_config_has_required_hooks(repo_root: pathlib.Path) -> None:
    pre_commit_config = repo_root / ".pre-commit-config.yaml"
    assert pre_commit_config.is_file(), ".pre-commit-config.yaml must exist"
    data = yaml.safe_load(pre_commit_config.read_text(encoding="utf-8"))
    repos = data.get("repos", [])

    all_hook_ids: set[str] = set()
    for repo in repos:
        for hook in repo.get("hooks", []):
            all_hook_ids.add(hook.get("id", ""))

    required_hooks = {
        "check-yaml",
        "check-json",
        "check-toml",
        "end-of-file-fixer",
        "trailing-whitespace",
        "mixed-line-ending",
        "detect-private-key",
        "check-added-large-files",
        "ruff",
    }
    missing = required_hooks - all_hook_ids
    assert not missing, f".pre-commit-config.yaml is missing hooks: {missing}"


def test_PRD_20_3_secret_scan_script_exists(repo_root: pathlib.Path) -> None:
    script = repo_root / "scripts" / "secret_scan.py"
    assert script.is_file(), "scripts/secret_scan.py must exist for the local pre-commit secret-scan hook"
    text = script.read_text(encoding="utf-8")
    assert "from .claude" not in text and "import .claude" not in text.replace(" ", ""), (
        "scripts/secret_scan.py must not import from .claude"
    )


def test_PRD_20_3_env_example_has_placeholders_only(repo_root: pathlib.Path) -> None:
    env_example = repo_root / ".env.example"
    assert env_example.is_file(), ".env.example must exist at the repo root"
    text = env_example.read_text(encoding="utf-8")
    assert "LIVE=0" in text
    assert "GOOGLE_CLOUD_PROJECT=tilo-dev" in text
    assert "REGION=asia-southeast1" in text


def test_PRD_20_3_editorconfig_exists(repo_root: pathlib.Path) -> None:
    assert (repo_root / ".editorconfig").is_file(), ".editorconfig must exist at the repo root"


def test_PRD_20_5_readme_skeleton_has_required_sections(repo_root: pathlib.Path) -> None:
    readme = repo_root / "README.md"
    assert readme.is_file(), "README.md must exist at the repo root"
    text = readme.read_text(encoding="utf-8").lower()
    for section in [
        "try it",
        "architecture",
        "genai map",
        "eval result",
        "security note",
        "honest note",
        "how to run",
    ]:
        assert section in text, f"README.md must have a '{section}' section (PRD 20.5)"
