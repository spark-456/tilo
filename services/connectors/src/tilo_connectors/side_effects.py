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


def _callee_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def scan_for_side_effect_calls(paths: Iterable[Path], *, allowed_path: Path) -> list[Violation]:
    """AST-parses each file in `paths` (skipping any that fail to parse), recording a Violation
    for every call to a name in SIDE_EFFECT_METHOD_NAMES outside `allowed_path`."""
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
            if not isinstance(node, ast.Call):
                continue
            name = _callee_name(node.func)
            if name is None or name not in SIDE_EFFECT_METHOD_NAMES:
                continue
            violations.append(Violation(path=resolved, lineno=node.lineno, method_name=name))
    return violations
