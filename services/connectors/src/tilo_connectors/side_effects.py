"""tilo_connectors.side_effects — the SEC-03 registry and static scanner: connector side-effect
methods are callable only from the outbox module. No opinion about tests/ or git; the caller
decides which paths to scan."""

from __future__ import annotations

import ast
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

# Method names callable only from the outbox (SEC-03); a new adapter side-effect method is added here.
SIDE_EFFECT_METHOD_NAMES: frozenset[str] = frozenset({"send_reply"})


@dataclass(frozen=True)
class Violation:
    path: Path
    lineno: int
    method_name: str


def _direct_call_args(node: ast.AST) -> Iterable[ast.expr]:
    """Every argument expression passed straight to a call (not nested in a literal), so
    `getattr(x, "send_reply")` and `operator.methodcaller("send_reply")` are seen but
    `frozenset({"send_reply"})` (the name nested inside a set literal) is not."""
    if isinstance(node, ast.Call):
        yield from node.args
        yield from (kw.value for kw in node.keywords)


def scan_for_side_effect_calls(paths: Iterable[Path], *, allowed_path: Path) -> list[Violation]:
    """AST-parses each file in `paths` (skipping any that fail to parse), recording a Violation
    for every reference to a name in SIDE_EFFECT_METHOD_NAMES outside `allowed_path`: a direct
    call, an attribute access (an alias, functools.partial, `.__call__`, however nested — a
    reference is a reference whether or not it is immediately called), or the name as a string
    constant passed straight to a call (getattr, operator.methodcaller)."""
    allowed = allowed_path.resolve()
    violations: list[Violation] = []
    for path in paths:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError, ValueError, UnicodeDecodeError):
            continue
        resolved = path.resolve()
        if resolved == allowed:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in SIDE_EFFECT_METHOD_NAMES:
                violations.append(Violation(path=resolved, lineno=node.lineno, method_name=node.attr))
                continue
            if isinstance(node, ast.Name) and node.id in SIDE_EFFECT_METHOD_NAMES:
                violations.append(Violation(path=resolved, lineno=node.lineno, method_name=node.id))
                continue
            for arg in _direct_call_args(node):
                if (
                    isinstance(arg, ast.Constant)
                    and isinstance(arg.value, str)
                    and arg.value in SIDE_EFFECT_METHOD_NAMES
                ):
                    violations.append(Violation(path=resolved, lineno=arg.lineno, method_name=arg.value))
    return violations
