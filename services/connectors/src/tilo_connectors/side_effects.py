"""tilo_connectors.side_effects — SEC-03 registry and static scanner (tests/API.md)."""

from __future__ import annotations

import ast
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

SIDE_EFFECT_METHOD_NAMES: frozenset[str] = frozenset({"send_reply"})  # callable only from outbox.py


@dataclass(frozen=True)
class Violation:
    path: Path
    lineno: int
    method_name: str


def _direct_call_args(node: ast.AST) -> Iterable[ast.expr]:  # a call's own args, not nested in a literal
    if isinstance(node, ast.Call):
        yield from node.args
        yield from (kw.value for kw in node.keywords)


def scan_for_side_effect_calls(paths: Iterable[Path], *, allowed_path: Path) -> list[Violation]:
    allowed = allowed_path.resolve()  # every reference to a SIDE_EFFECT_METHOD_NAMES name outside it
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
            name: str | None = getattr(node, "attr", None) or getattr(node, "id", None)
            if isinstance(node, (ast.Attribute, ast.Name)) and name in SIDE_EFFECT_METHOD_NAMES:
                violations.append(Violation(path=resolved, lineno=node.lineno, method_name=name))
                continue
            for arg in _direct_call_args(node):
                if isinstance(arg, ast.Constant) and arg.value in SIDE_EFFECT_METHOD_NAMES:
                    violations.append(Violation(path=resolved, lineno=arg.lineno, method_name=arg.value))
    return violations
