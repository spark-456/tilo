"""CC-PEOPLE: generated Python (`tilo_contracts`) and TypeScript (`@tilo/contracts`) types for the
eight new contracts and the twelve new `<Type>Data` models, and `EVENT_TYPES` listing the 12 new
types (FR-WLD-02 / ADR-0002 decision 8: generated types exist; same check style as
test_FR_WLD_02_generated_types_exist.py and test_CC_SE_generated_types_and_drift.py).
"""

from __future__ import annotations

import re

import _people_lib as pl
import pytest

CONTRACTS_PY_SRC = "packages/contracts-py/src"
CONTRACTS_TS_SRC = "packages/contracts-ts/src"
ROOT_TYPES = ("Person", "Meeting", "Minutes", "WorkItem", "PinboardItem", "Mention", "CalendarEntry", "UiAction")
DATA_TYPES = [pl.data_model_name(t) for t in pl.NEW_EVENT_TYPES]


def _py_text(repo_root) -> str:
    src = repo_root / CONTRACTS_PY_SRC
    assert src.is_dir(), f"{CONTRACTS_PY_SRC}/ must exist"
    return "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in src.rglob("*.py"))


def _ts_text(repo_root) -> str:
    src = repo_root / CONTRACTS_TS_SRC
    assert src.is_dir(), f"{CONTRACTS_TS_SRC}/ must exist"
    files = list(src.rglob("*.ts")) + list(src.rglob("*.d.ts"))
    return "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in files)


@pytest.mark.parametrize("name", [*ROOT_TYPES, *DATA_TYPES])
def test_CC_PEOPLE_FR_WLD_02_python_exposes_the_generated_type(repo_root, name):
    text = _py_text(repo_root)
    pattern = re.compile(rf"^(?:class\s+{name}\b|type\s+{name}\b|{name}\s*(?::[^=\n]+)?=)", re.MULTILINE)
    assert pattern.search(text), f"no generated Python type {name!r} under {CONTRACTS_PY_SRC}/"


@pytest.mark.parametrize("name", [*ROOT_TYPES, *DATA_TYPES])
def test_CC_PEOPLE_FR_WLD_02_typescript_exposes_the_generated_type(repo_root, name):
    text = _ts_text(repo_root)
    pattern = re.compile(rf"\b(?:interface|type)\s+{name}\b")
    assert pattern.search(text), f"no generated TypeScript interface/type {name!r} under {CONTRACTS_TS_SRC}/"


def test_CC_PEOPLE_FR_WLD_03_python_event_types_lists_the_twelve_new_types(repo_root):
    text = _py_text(repo_root)
    start = text.find("EVENT_TYPES")
    assert start >= 0, "EVENT_TYPES must exist in the generated Python package"
    block = text[start : text.find("\n)\n", start)]
    missing = [t for t in pl.NEW_EVENT_TYPES if f'"{t}"' not in block]
    assert not missing, f"EVENT_TYPES lacks {missing}"


def test_CC_PEOPLE_FR_WLD_03_typescript_event_types_lists_the_twelve_new_types(repo_root):
    text = _ts_text(repo_root)
    start = text.find("export const EVENT_TYPES")
    assert start >= 0, "EVENT_TYPES must exist in the generated TypeScript package"
    block = text[start : text.find("] as const", start)]
    missing = [t for t in pl.NEW_EVENT_TYPES if f'"{t}"' not in block]
    assert not missing, f"EVENT_TYPES lacks {missing}"


def test_CC_PEOPLE_FR_WLD_03_the_new_types_are_not_side_effect_types_in_the_generated_code(repo_root):
    py = _py_text(repo_root)
    start = py.find("SIDE_EFFECT_EVENT_TYPES")
    assert start >= 0
    assert "EVENT_TYPES" in py and all(f'"{t}"' in py for t in pl.NEW_EVENT_TYPES), "new types must be generated first"
    block = py[start : py.find("\n)", start)]
    assert not [t for t in pl.NEW_EVENT_TYPES if f'"{t}"' in block], "no new type is a side effect"
