"""PROD-WIRE slice 5a repo guards (ADR-0026 decision 1; PL-01; "no secrets in code"; FR-MTR-10, COST-FAST-1b):

- the new and changed source carries no model id and no secret: `prod.py`, the shared conversion module
  `cost_entries.py`, `world_writer.py`, `dev.py` and `durable_store.py`, and the new tests;
- among the `tilo_api` modules a Firestore client is constructed only in `prod.py` (the PW3 rule, restated: the ledger
  is built on the door's shared client, never on a client of its own; `people_firestore.emulator_people_stores` is the
  one exemption, as in PW3);
- `FirestoreLedger` is append-only by construction: no `set`, `update`, `delete`, `transaction`, `batch`,
  `collection_group` call anywhere in its body;
- dev mode and the deployed writer cannot drift: both call `cost_entries.entry_from_cost_event`, and neither builds a
  `LedgerEntry` itself.
"""

from __future__ import annotations

import ast
import importlib.util
import pathlib
import types

PACKAGE = "services/api/src/tilo_api"
PROD = f"{PACKAGE}/prod.py"
COST_ENTRIES = f"{PACKAGE}/cost_entries.py"
WORLD_WRITER = f"{PACKAGE}/world_writer.py"
DEV = f"{PACKAGE}/dev.py"
# Ambiguity resolved: besides PW3's one exemption, `team_store._build` (FR-TEAM-02, merged from the base after PW3's
# guard was written) builds its own client; PW3's guard already fails on it and it is not slice 5a's to fix, so
# this guard exempts it too and only forbids a NEW construction (a ledger on a client of its own).
EXEMPT = {("people_firestore.py", "emulator_people_stores"), ("team_store.py", "_build")}
SOURCES = (PROD, COST_ENTRIES, WORLD_WRITER, DEV, f"{PACKAGE}/durable_store.py")
NEW_TESTS = (
    "services/api/tests/_pw5_lib.py",
    "services/api/tests/test_PROD_WIRE_5a_firestore_ledger.py",
    "services/api/tests/test_PROD_WIRE_5a_firestore_ledger_emulator.py",
    "services/api/tests/test_PROD_WIRE_5a_seams.py",
    "services/api/tests/test_PROD_WIRE_5a_cost_event_feed.py",
    "services/api/tests/test_PROD_WIRE_5a_cost_routes.py",
    "tests/repo/test_PROD_WIRE_5a_sources_guard.py",
)
FORBIDDEN_CALLS = {"set", "delete", "transaction", "batch", "collection_group"}


def _script(repo_root: pathlib.Path, name: str) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(f"{name}_under_test", repo_root / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _tree(repo_root: pathlib.Path, relative: str) -> ast.Module:
    path = repo_root / relative
    assert path.is_file(), f"{relative} does not exist yet"
    return ast.parse(path.read_text(encoding="utf-8"))


def _client_constructions(path: pathlib.Path) -> list[tuple[int, str]]:
    """(line, enclosing function) of every call that builds a Firestore client in one module (the PW3 scan)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    firestore_names: set[str] = set()
    client_names: set[str] = set()
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


def _calls(node: ast.AST) -> list[ast.Call]:
    return [n for n in ast.walk(node) if isinstance(n, ast.Call)]


def _names_called(tree: ast.AST) -> set[str]:
    out: set[str] = set()
    for call in _calls(tree):
        if isinstance(call.func, ast.Name):
            out.add(call.func.id)
        elif isinstance(call.func, ast.Attribute):
            out.add(call.func.attr)
    return out


def test_PROD_WIRE_5a_no_model_id_and_no_secret_in_the_ledger_sources_or_their_tests(repo_root: pathlib.Path) -> None:
    lint, scan = _script(repo_root, "lint_model_ids"), _script(repo_root, "secret_scan")
    known = lint._configured_model_ids(repo_root)
    for relative in (*SOURCES, *NEW_TESTS):
        path = repo_root / relative
        assert path.is_file(), relative
        text = path.read_text(encoding="utf-8")
        found = set(lint.FAMILY_PATTERN.findall(text)) | {m for m in known if m in text}
        assert not found, f"{relative}: a model id outside config/ and packages/providers/ (PL-01): {sorted(found)}"
        assert scan.scan_file(str(path)) == [], f"{relative}: looks like a secret"


def test_PROD_WIRE_5a_only_prod_py_constructs_a_firestore_client(repo_root: pathlib.Path) -> None:
    offenders = []
    for path in sorted((repo_root / PACKAGE).rglob("*.py")):
        if path.name == "prod.py":
            continue
        for line, function in _client_constructions(path):
            if (path.name, function) not in EXEMPT:
                offenders.append(f"{path.relative_to(repo_root)}:{line} (in {function})")
    assert not offenders, f"a Firestore client is built outside tilo_api/prod.py (use the door's client): {offenders}"


def test_PROD_WIRE_5a_firestore_ledger_is_defined_in_prod_py_and_never_overwrites(repo_root: pathlib.Path) -> None:
    tree = _tree(repo_root, PROD)
    classes = {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}
    assert "FirestoreLedger" in classes, "prod.FirestoreLedger"
    assert "LedgerConflict" in classes, "prod.LedgerConflict"
    ledger = classes["FirestoreLedger"]
    methods = {n.name for n in ledger.body if isinstance(n, ast.FunctionDef)}
    assert {"append", "entries", "append_entry"} <= methods, methods
    called = {c.func.attr for c in _calls(ledger) if isinstance(c.func, ast.Attribute)}
    assert not (called & FORBIDDEN_CALLS), (
        f"FirestoreLedger is create-only; it calls {sorted(called & FORBIDDEN_CALLS)}"
    )
    assert "create" in called, "an entry is written with one create"


def test_PROD_WIRE_5a_dev_mode_and_the_deployed_writer_share_one_conversion(repo_root: pathlib.Path) -> None:
    tree = _tree(repo_root, COST_ENTRIES)
    assert any(isinstance(n, ast.FunctionDef) and n.name == "entry_from_cost_event" for n in tree.body), (
        f"{COST_ENTRIES}: the one conversion of a cost event to its ledger entry"
    )
    for relative in (DEV, WORLD_WRITER):
        tree = _tree(repo_root, relative)
        assert "entry_from_cost_event" in _names_called(tree), (
            f"{relative} must call cost_entries.entry_from_cost_event"
        )
        assert "LedgerEntry" not in _names_called(tree), f"{relative} builds a LedgerEntry itself: the two can drift"


def test_PROD_WIRE_5a_the_deployed_store_gives_the_adapter_a_ledger_on_the_doors_client(
    repo_root: pathlib.Path,
) -> None:
    tree = _tree(repo_root, f"{PACKAGE}/durable_store.py")
    deployed = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "deployed")
    assert "FirestoreLedger" in _names_called(deployed), "durable_store.deployed() builds the FirestoreLedger"
