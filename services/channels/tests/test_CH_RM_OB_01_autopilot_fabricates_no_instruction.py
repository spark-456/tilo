"""CH-RM, OB-01 provenance (ADR-0019, BQ-CHRM-2): tilo-channels never writes an instruction. An inbound mail is
recorded at most as a `channel.message_in` and never opens a send, and the Autopilot takes its `instruction_id` from
its caller (the owner's `world.requested`, written by tilo-api from a signed-in control). No source module names
`world.requested`, so none can build one.

The check reads each module's syntax tree, not its text: it folds string constants (concatenation, f-strings, `join`,
module-level names) and looks at every imported or referenced name, so `"world." + "requested"` or an imported
`WORLD_REQUESTED` is found too. It cannot see a value defined in another package under an unrelated name; the writer
(tilo-api, ADR-0013) is the other half of that guarantee.
"""

from __future__ import annotations

import ast
import pathlib
import re

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "tilo_channels"
_NAME = re.compile(r"world[._-]?requested", re.IGNORECASE)


def _fold(node: ast.AST, env: dict[str, str]) -> str | None:
    """The string an expression of constants evaluates to, or None when it is not a plain string."""
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else None
    if isinstance(node, ast.Name):
        return env.get(node.id)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _fold(node.left, env), _fold(node.right, env)
        return left + right if left is not None and right is not None else None
    if isinstance(node, ast.JoinedStr):
        parts = [_fold(v.value if isinstance(v, ast.FormattedValue) else v, env) for v in node.values]
        return "".join(parts) if all(p is not None for p in parts) else None  # type: ignore[arg-type]
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "join":
        sep = _fold(node.func.value, env)
        items = node.args[0] if len(node.args) == 1 else None
        if sep is not None and isinstance(items, (ast.List, ast.Tuple)):
            folded = [_fold(e, env) for e in items.elts]
            return sep.join(folded) if all(f is not None for f in folded) else None  # type: ignore[arg-type]
    return None


def instruction_event_mentions(source: str) -> list[str]:
    """Every place the source names the `world.requested` event type, however it is spelled or assembled."""
    tree = ast.parse(source)
    env: dict[str, str] = {}
    for stmt in tree.body:  # module-level `NAME = "..."`, resolved in order
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
            value = _fold(stmt.value, env)
            if value is not None:
                env[stmt.targets[0].id] = value
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Constant, ast.BinOp, ast.JoinedStr, ast.Call)):
            value = _fold(node, env)
            if value is not None and _NAME.search(value):
                found.append(f"string at line {node.lineno}")
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if _NAME.search(alias.name) or (alias.asname and _NAME.search(alias.asname)):
                    found.append(f"import {alias.name} at line {node.lineno}")
        elif isinstance(node, ast.Name) and _NAME.search(node.id):
            found.append(f"name {node.id} at line {node.lineno}")
        elif isinstance(node, ast.Attribute) and _NAME.search(node.attr):
            found.append(f"attribute {node.attr} at line {node.lineno}")
    return found


def test_CH_RM_OB_01_the_source_directory_is_found_and_has_modules():
    assert len(sorted(SRC.glob("*.py"))) >= 10  # a guard that fails open on an empty glob proves nothing


def test_CH_RM_OB_01_no_channels_module_writes_a_world_requested_instruction():
    paths = sorted(SRC.glob("*.py"))
    assert paths
    offenders = {p.name: m for p in paths if (m := instruction_event_mentions(p.read_text(encoding="utf-8")))}
    assert offenders == {}


def test_CH_RM_OB_01_the_check_finds_every_way_to_spell_the_instruction_event(tmp_path):
    spellings = {
        "plain": 'EVENT = "world.requested"\n',
        "concatenated": 'EVENT = "world." + "requested"\n',
        "implicit": 'EVENT = "world." "requested"\n',
        "fstring": 'KIND = "requested"\nEVENT = f"world.{KIND}"\n',
        "joined": 'EVENT = ".".join(["world", "requested"])\n',
        "via_names": 'A = "world."\nB = "requested"\nEVENT = A + B\n',
        "imported_constant": "from tilo_contracts.events import WORLD_REQUESTED\n",
        "imported_alias": "from somewhere import KIND as world_requested\n",
        "imported_class": "from tilo_contracts import WorldRequested\n",
        "attribute": "import events\nEVENT = events.WORLD_REQUESTED\n",
    }
    for name, source in spellings.items():
        (tmp_path / f"{name}.py").write_text(source, encoding="utf-8")
    found = {p.stem: instruction_event_mentions(p.read_text(encoding="utf-8")) for p in tmp_path.glob("*.py")}

    assert {name for name, hits in found.items() if not hits} == set()


def test_CH_RM_OB_01_the_check_passes_a_module_that_names_other_events(tmp_path):
    clean = tmp_path / "clean.py"
    clean.write_text(
        'import os\nEVENT = "channel." + "opened"\nWORLD = "w_01"\nREQUESTED = "no"\nNOTE = "a world was requested"\n',
        encoding="utf-8",
    )

    assert instruction_event_mentions(clean.read_text(encoding="utf-8")) == []


def test_CH_RM_OB_01_no_channels_module_reads_whatsapp_or_a_message_in_as_an_instruction():
    paths = sorted(SRC.glob("*.py"))
    assert paths
    for path in paths:
        text = path.read_text(encoding="utf-8").lower()
        assert "whatsapp" not in text, path.name
        assert "channel.message_in" not in text, path.name
