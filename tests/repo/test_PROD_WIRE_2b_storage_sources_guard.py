"""PROD-WIRE 2b repo guards (CLAUDE.md hard rules; ADR-0023 / ADR-0026 pattern): the new durable-store source carries no
model id (PL-01), no secret and no credential handling (ADC only), builds no client and imports the storage library
only lazily; `google-cloud-storage` is declared for the api image (P0-07a: `uv sync --package tilo-api` installs only
what the service declares). Needs the uv workspace (it reads `scripts/`); run with `uv run pytest tests/repo`.
"""

from __future__ import annotations

import ast
import importlib.util
import pathlib
import re
import tomllib
import types

SRC = "services/api/src/tilo_api/run_stores.py"
NEW_TESTS = (
    "services/api/tests/_prod_wire_2b_lib.py",
    "services/api/tests/test_PROD_WIRE_2b_archive_store.py",
    "services/api/tests/test_PROD_WIRE_2b_blob_backend.py",
    "services/api/tests/test_PROD_WIRE_2b_doors_and_seams.py",
    "services/api/tests/test_PROD_WIRE_2b_meta_backend.py",
    "tests/repo/test_PROD_WIRE_2b_storage_sources_guard.py",
)


def _script(repo_root: pathlib.Path, name: str) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(f"{name}_under_test", repo_root / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_PROD_WIRE_2b_the_new_sources_exist_and_have_no_model_id_and_no_secret(repo_root: pathlib.Path) -> None:
    lint, scan = _script(repo_root, "lint_model_ids"), _script(repo_root, "secret_scan")
    known = lint._configured_model_ids(repo_root)
    for relative in (SRC, *NEW_TESTS):
        path = repo_root / relative
        assert path.is_file(), relative
        text = path.read_text(encoding="utf-8")
        found = set(lint.FAMILY_PATTERN.findall(text)) | {m for m in known if m in text}
        assert not found, f"{relative}: a model id outside config/ and packages/providers/ (PL-01): {sorted(found)}"
        assert scan.scan_file(str(path)) == [], f"{relative}: looks like a secret"


def test_PROD_WIRE_2b_the_source_uses_adc_only_and_names_the_explicit_switches(repo_root: pathlib.Path) -> None:
    source = (repo_root / SRC).read_text(encoding="utf-8")
    for forbidden in (
        "from_service_account",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "credentials=",
        "service_account",
        "private_key",
    ):
        assert forbidden not in source, (
            f"{forbidden}: the doors use the runtime identity's application default credentials"
        )
    for name in (
        "TILO_ARTIFACTS_STORE",
        "TILO_ARTIFACTS_BUCKET",
        "TILO_ARCHIVE_STORE",
        "TILO_ARCHIVE_BUCKET",
        "K_SERVICE",
    ):
        assert name in source, name
    assert not re.search(r"[\w.+-]+@[\w-]+\.iam\.gserviceaccount\.com", source)


def test_PROD_WIRE_2b_the_source_imports_google_cloud_storage_only_inside_its_factory(repo_root: pathlib.Path) -> None:
    tree = ast.parse((repo_root / SRC).read_text(encoding="utf-8"))
    for node in tree.body:
        names = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [f"{node.module}.{alias.name}" for alias in node.names]
        assert not [n for n in names if n.startswith("google.cloud.storage")], (
            f"line {node.lineno}: import google-cloud-storage inside its default factory, not at module level"
        )


def test_PROD_WIRE_2b_the_api_declares_google_cloud_storage(repo_root: pathlib.Path) -> None:
    project = tomllib.loads((repo_root / "services/api/pyproject.toml").read_text(encoding="utf-8"))
    declared = [re.match(r"[A-Za-z0-9_.-]+", dep).group(0).lower() for dep in project["project"]["dependencies"]]  # type: ignore[union-attr]
    assert "google-cloud-storage" in declared, "the api image installs only what tilo-api declares (P0-07a)"
