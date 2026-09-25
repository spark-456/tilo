"""FR-WLD-02 (ticket P0-02 section 4; PRD 15.2 "both Python and TypeScript
types are generated from them").

Checks that generated Python (packages/contracts-py) and TypeScript
(packages/contracts-ts) types exist for each of the eleven CP0 schemas. The
generation tool is the builder's choice (ticket names
datamodel-code-generator / json-schema-to-typescript only as an example), so
this does not assume a particular file layout -- it looks for a Python class
or a TypeScript interface/type whose name is the schema's PascalCase name
somewhere under each package's generated tree. `.gitattributes` already fixes
*where* that tree is: `packages/contracts-py/src/**` and
`packages/contracts-ts/src/**` are marked `linguist-generated=true`.
"""

from __future__ import annotations

import re

import pytest
from _lib import SCHEMA_NAMES

CONTRACTS_PY_SRC = "packages/contracts-py/src"
CONTRACTS_TS_SRC = "packages/contracts-ts/src"


def _pascal(name: str) -> str:
    return "".join(part[:1].upper() + part[1:] for part in name.split("_") if part)


@pytest.mark.parametrize("name", SCHEMA_NAMES)
def test_FR_WLD_02_generated_python_type_exists(repo_root, name):
    src = repo_root / CONTRACTS_PY_SRC
    assert src.is_dir(), (
        f"FR-WLD-02: {CONTRACTS_PY_SRC}/ must exist and contain generated pydantic v2 models for "
        "every contracts/ schema (packages/contracts-py, package tilo_contracts, a uv workspace "
        "member)"
    )
    class_name = _pascal(name)
    pattern = re.compile(rf"\bclass\s+{re.escape(class_name)}\b")
    hit = any(pattern.search(p.read_text(encoding="utf-8", errors="ignore")) for p in src.rglob("*.py"))
    assert hit, (
        f"FR-WLD-02: no generated Python class named {class_name!r} found under {CONTRACTS_PY_SRC}/ "
        f"for contracts/{name}.schema.json"
    )


@pytest.mark.parametrize("name", SCHEMA_NAMES)
def test_FR_WLD_02_generated_typescript_type_exists(repo_root, name):
    src = repo_root / CONTRACTS_TS_SRC
    assert src.is_dir(), (
        f"FR-WLD-02: {CONTRACTS_TS_SRC}/ must exist and contain generated TypeScript types for "
        "every contracts/ schema (packages/contracts-ts, package @tilo/contracts, a pnpm workspace "
        "member)"
    )
    type_name = _pascal(name)
    pattern = re.compile(rf"\b(?:interface|type)\s+{re.escape(type_name)}\b")
    ts_files = list(src.rglob("*.ts")) + list(src.rglob("*.d.ts"))
    hit = any(pattern.search(p.read_text(encoding="utf-8", errors="ignore")) for p in ts_files)
    assert hit, (
        f"FR-WLD-02: no generated TypeScript interface/type named {type_name!r} found under "
        f"{CONTRACTS_TS_SRC}/ for contracts/{name}.schema.json"
    )


def test_FR_WLD_02_generated_trees_are_marked_generated(repo_root):
    attrs = (repo_root / ".gitattributes").read_text(encoding="utf-8")
    for entry in (f"{CONTRACTS_PY_SRC}/** linguist-generated=true", f"{CONTRACTS_TS_SRC}/** linguist-generated=true"):
        assert entry in attrs, f"FR-WLD-02: .gitattributes must mark generated output: {entry!r}"
