"""PROD-WIRE slice 1a, ADR-0026 decision 4: every event goes through `EventWriter.append`. No code in
services/api/src writes to `store.events` (extend, append, setdefault, item assignment, `del`) except the writer
adapter (`tilo_api/world_writer.py`) and dev mode's `DevEventWriter` (`tilo_api/dev.py`). Reads (`.get`, iteration)
stay free. Today `tasks._append` and `ScheduleStarter._create_world` write around the writer, so this fails.

The scan follows `store.events` / `self.store.events` / `self._store.events` through subscripts and calls; it does not
follow an alias (`w = store.events`), so the self-tests below pin what it does see.
"""

from __future__ import annotations

import ast
import pathlib

API_SRC = "services/api/src/tilo_api"
ALLOWED = {("world_writer.py", ""), ("dev.py", "DevEventWriter")}  # (file, qualname prefix; "" is the whole file)
MUTATORS = {"append", "extend", "insert", "setdefault", "update", "pop", "popitem", "clear", "remove", "sort"}
STORE_NAMES = {"store", "_store"}


def _is_store_events(node: ast.AST) -> bool:
    if not (isinstance(node, ast.Attribute) and node.attr == "events"):
        return False
    base = node.value
    return (base.id if isinstance(base, ast.Name) else getattr(base, "attr", None)) in STORE_NAMES


def _rooted_in_store_events(node: ast.AST) -> bool:
    while not _is_store_events(node):
        if isinstance(node, ast.Subscript | ast.Attribute):
            node = node.value
        elif isinstance(node, ast.Call):
            node = node.func
        else:
            return False
    return True


class _Scan(ast.NodeVisitor):
    def __init__(self) -> None:
        self.stack: list[str] = []
        self.hits: list[tuple[str, int]] = []

    def _scope(self, node: ast.AST) -> None:
        self.stack.append(node.name)  # type: ignore[attr-defined]
        self.generic_visit(node)
        self.stack.pop()

    visit_ClassDef = visit_FunctionDef = visit_AsyncFunctionDef = _scope

    def _hit(self, node: ast.AST) -> None:
        self.hits.append((".".join(self.stack), node.lineno))  # type: ignore[attr-defined]

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in MUTATORS and _rooted_in_store_events(func.value):
            self._hit(node)
        self.generic_visit(node)

    def _targets(self, targets: list[ast.expr], node: ast.AST) -> None:
        for target in targets:
            if isinstance(target, ast.Tuple | ast.List):
                self._targets(list(target.elts), node)
            elif _is_store_events(target) or _rooted_in_store_events(target):
                self._hit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        self._targets(node.targets, node)
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self._targets([node.target], node)
        self.generic_visit(node)

    def visit_Delete(self, node: ast.Delete) -> None:
        self._targets(node.targets, node)
        self.generic_visit(node)


def _writes(source: str) -> list[tuple[str, int]]:
    scan = _Scan()
    scan.visit(ast.parse(source))
    return sorted(set(scan.hits))


def test_PROD_WIRE_1a_the_scan_sees_each_kind_of_write_and_no_read() -> None:
    writes = """
def f(store, self):
    store.events.setdefault(w, []).extend(x)
    self.store.events[w].append(x)
    self._store.events[w] = []
    store.events[w] += [x]
    del store.events[w]
    store.events = {}
"""
    reads = """
def g(store, w, people):
    first = [e for e in store.events.get(w, []) if e]
    count = len(store.events[w])
    people.events = []
    for e in store.events.values():
        pass
"""
    assert [line for _, line in _writes(writes)] == [3, 4, 5, 6, 7, 8]
    assert _writes(reads) == []


def test_PROD_WIRE_1a_nothing_in_tilo_api_writes_store_events_outside_the_writer_adapter(
    repo_root: pathlib.Path,
) -> None:
    offenders = []
    for path in sorted((repo_root / API_SRC).glob("*.py")):
        for qualname, line in _writes(path.read_text(encoding="utf-8")):
            if not any(path.name == f and qualname.startswith(q) for f, q in ALLOWED):
                offenders.append(f"{path.name}:{line} in {qualname or '<module>'}")
    assert not offenders, "a write to store.events around EventWriter.append (ADR-0026 decision 4): " + "; ".join(
        offenders
    )
