"""The only formulas a deliverable may carry: row arithmetic over the numeric columns of one table.

A writer states a computed column as `{"column": "Revenue", "expr": "[Units] * [Unit price]"}`. The grammar is numbers,
`[Column name]`, `+ - * /`, unary minus and parentheses; nothing else parses (no names, functions, cell addresses,
exponent or text). Code evaluates it for every row, so every format shows the same numbers, and the Excel renderer
writes the same expression as a real cell formula built from column letters it chose itself: model text never reaches
a formula cell. Deterministic, no model call.
"""

import re
from collections.abc import Callable, Mapping
from typing import Any

MAX_EXPR_CHARS = 200
MAX_DEPTH = 20
_TOKEN = re.compile(r"\s*(?:(\d+(?:\.\d+)?)|\[([^\[\]\n]{1,100})\]|([-+*/()]))")

Node = tuple[Any, ...]  # ("num", x) | ("col", name) | ("neg", node) | (op, left, right)


def parse(expr: str) -> Node:
    """The expression as a tree, or ValueError."""
    if not isinstance(expr, str) or not expr.strip() or len(expr) > MAX_EXPR_CHARS:
        raise ValueError("a formula is 1 to 200 characters")
    tokens: list[tuple[str, str]] = []
    pos = 0
    while pos < len(expr):
        if not expr[pos:].strip():
            break
        found = _TOKEN.match(expr, pos)
        if found is None:
            raise ValueError("a formula uses numbers, [Column] names, + - * / and brackets only")
        pos = found.end()
        number, column, symbol = found.groups()
        tokens.append(("num", number) if number else ("col", column) if column else ("sym", symbol))
    at = 0

    def peek() -> tuple[str, str] | None:
        return tokens[at] if at < len(tokens) else None

    def take() -> tuple[str, str]:
        nonlocal at
        token = peek()
        if token is None:
            raise ValueError("the formula ends too early")
        at += 1
        return token

    def expression(depth: int) -> Node:
        if depth > MAX_DEPTH:
            raise ValueError("the formula nests too deeply")
        node = term(depth)
        while (t := peek()) is not None and t in (("sym", "+"), ("sym", "-")):
            take()
            node = (t[1], node, term(depth))
        return node

    def term(depth: int) -> Node:
        node = factor(depth)
        while (t := peek()) is not None and t in (("sym", "*"), ("sym", "/")):
            take()
            node = (t[1], node, factor(depth))
        return node

    def factor(depth: int) -> Node:
        kind, value = take()
        if kind == "num":
            return ("num", float(value) if "." in value else int(value))
        if kind == "col":
            return ("col", value)
        if value == "-":
            return ("neg", factor(depth + 1))
        if value == "(":
            node = expression(depth + 1)
            if take() != ("sym", ")"):
                raise ValueError("a bracket is not closed")
            return node
        raise ValueError("the formula is not arithmetic")

    tree = expression(0)
    if at != len(tokens):
        raise ValueError("the formula has extra text")
    return tree


def columns_used(node: Node) -> list[str]:
    if node[0] == "col":
        return [node[1]]
    if node[0] == "num":
        return []
    return [name for child in node[1:] for name in columns_used(child)]


def evaluate(node: Node, value_of: Callable[[str], int | float]) -> int | float:
    kind = node[0]
    if kind == "num":
        return node[1]
    if kind == "col":
        return value_of(node[1])
    if kind == "neg":
        return -evaluate(node[1], value_of)
    left, right = evaluate(node[1], value_of), evaluate(node[2], value_of)
    if kind == "+":
        return left + right
    if kind == "-":
        return left - right
    if kind == "*":
        return left * right
    if right == 0:
        raise ValueError("a formula divides by zero")
    return left / right


_PRECEDENCE = {"+": 1, "-": 1, "*": 2, "/": 2}


def to_excel(node: Node, cell_of: Mapping[str, str]) -> str:
    """The Excel formula text (with no leading =) for one row; `cell_of` maps a column name to this row's cell."""
    kind = node[0]
    if kind == "num":
        return repr(node[1])
    if kind == "col":
        return cell_of[node[1]]
    if kind == "neg":
        inner = to_excel(node[1], cell_of)
        return f"-({inner})" if node[1][0] in _PRECEDENCE else f"-{inner}"
    prec = _PRECEDENCE[kind]
    left, right = to_excel(node[1], cell_of), to_excel(node[2], cell_of)
    if node[1][0] in _PRECEDENCE and _PRECEDENCE[node[1][0]] < prec:
        left = f"({left})"
    if node[2][0] in _PRECEDENCE and (
        _PRECEDENCE[node[2][0]] < prec or (_PRECEDENCE[node[2][0]] == prec and kind in "-/")
    ):
        right = f"({right})"
    return f"{left}{kind}{right}"
