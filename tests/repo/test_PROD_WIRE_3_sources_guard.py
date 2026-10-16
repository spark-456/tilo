"""PROD-WIRE slice 3 repo guards (ADR-0026 decision 1; PL-01; "no secrets in code"):

- `services/api/src/tilo_api/prod.py` exists and carries no model id and no secret;
- among the `tilo_api` modules a Firestore client is constructed only in `prod.py`: `store_door.client_factory` and the
  people door's default factory delegate to `prod.firestore_client`, so one process holds one client per project and
  every door obeys one guard. (The AST scan finds `firestore.Client(...)`, `<alias>.Client(...)` of
  `google.cloud.firestore[_v1]` and a bare `Client(...)` imported from there.) Ambiguity resolved: the one other
  construction in the package, inside `people_firestore.emulator_people_stores` (the emulator-and-`demo-`-only helper
  that FS-06's own tests pin, with its own guard), is exempt, as the brief's "no deployed door builds one" intends;
- the new tests carry no model id and no secret.

Needs the uv workspace for nothing but the two linting scripts in `scripts/` (stdlib only).
"""

from __future__ import annotations

import ast
import importlib.util
import pathlib
import types

PROD = "services/api/src/tilo_api/prod.py"
PACKAGE = "services/api/src/tilo_api"
# `team_store._build` arrived on the base after PROD-WIRE 3 (another lane's TILO_TEAM_STORE door). It builds its own
# client; delegating it to `prod.firestore_client` is a follow-up in BQ-PW-3, not this slice.
EXEMPT = {("people_firestore.py", "emulator_people_stores"), ("team_store.py", "_build")}
NEW_TESTS = (
    "services/api/tests/_pw3_lib.py",
    "services/api/tests/test_PROD_WIRE_3_one_client_per_project.py",
    "services/api/tests/test_PROD_WIRE_3_doors_share_the_client.py",
    "tests/repo/test_PROD_WIRE_3_api_service_terraform.py",
    "tests/repo/test_PROD_WIRE_3_sources_guard.py",
)


def _script(repo_root: pathlib.Path, name: str) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(f"{name}_under_test", repo_root / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _client_constructions(path: pathlib.Path) -> list[tuple[int, str]]:
    """(line, enclosing function) of every call that builds a Firestore client in one module."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    firestore_names: set[str] = set()  # names bound to the firestore module
    client_names: set[str] = set()  # names bound to the Client class itself
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                bound = alias.asname or alias.name
                if node.module == "google.cloud" and alias.name == "firestore":
                    firestore_names.add(bound)
                elif node.module.startswith("google.cloud.firestore") and alias.name == "Client":
                    client_names.add(bound)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("google.cloud.firestore"):
                    firestore_names.add(alias.asname or alias.name)
    found: list[tuple[int, str]] = []

    def visit(node: ast.AST, function: str) -> None:
        for child in ast.iter_child_nodes(node):
            name = child.name if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef) else function
            if isinstance(child, ast.Call):
                func = child.func
                dotted = (
                    isinstance(func, ast.Attribute)
                    and func.attr == "Client"
                    and ast.unparse(func.value).split(".")[0] in firestore_names | {"google"}
                )
                if dotted or (isinstance(func, ast.Name) and func.id in client_names):
                    found.append((child.lineno, function))
            visit(child, name)

    visit(tree, "<module>")
    return found


def test_PROD_WIRE_3_prod_module_exists_and_builds_the_one_client(repo_root: pathlib.Path) -> None:
    path = repo_root / PROD
    assert path.is_file(), f"{PROD}: the process's one Firestore client lives here"
    assert _client_constructions(path), "prod.py is where the client is built (its default `build_client`)"


def test_PROD_WIRE_3_no_other_tilo_api_module_constructs_a_firestore_client(repo_root: pathlib.Path) -> None:
    offenders = []
    for path in sorted((repo_root / PACKAGE).rglob("*.py")):
        if path.name == "prod.py":
            continue
        for line, function in _client_constructions(path):
            if (path.name, function) not in EXEMPT:
                offenders.append(f"{path.relative_to(repo_root)}:{line} (in {function})")
    assert not offenders, (
        f"a Firestore client is built outside tilo_api/prod.py (delegate to prod.firestore_client): {offenders}"
    )


def test_PROD_WIRE_3_the_scan_sees_the_constructions_it_exempts(repo_root: pathlib.Path) -> None:
    """The guard is not vacuous: it finds the emulator helper's construction (and will find a new one anywhere)."""
    found = _client_constructions(repo_root / PACKAGE / "people_firestore.py")
    assert any(function == "emulator_people_stores" for _, function in found), found


def test_PROD_WIRE_3_no_model_id_and_no_secret_in_prod_or_its_tests(repo_root: pathlib.Path) -> None:
    lint, scan = _script(repo_root, "lint_model_ids"), _script(repo_root, "secret_scan")
    known = lint._configured_model_ids(repo_root)
    for relative in (PROD, *NEW_TESTS):
        path = repo_root / relative
        assert path.is_file(), relative
        text = path.read_text(encoding="utf-8")
        found = set(lint.FAMILY_PATTERN.findall(text)) | {m for m in known if m in text}
        assert not found, f"{relative}: a model id outside config/ and packages/providers/ (PL-01): {sorted(found)}"
        assert scan.scan_file(str(path)) == [], f"{relative}: looks like a secret"
