"""CC-PEOPLE: every new contract ships valid and invalid fixtures (contracts/CLAUDE.md: "Every change
ships with valid and invalid fixtures"; ADR-0002 `fixtures/<name>/valid|invalid/`, and
`fixtures/<name>.<def>/` for a `$defs` entry; people.rules.md "Fixtures").

Each valid file validates; each invalid file is refused; there is at least one of each.
"""

from __future__ import annotations

import _people_lib as pl
import pytest
from _lib import load_json

# (fixture folder, schema file, $defs name or None)
TARGETS = [
    ("person", "person", None),
    ("meeting", "meeting", None),
    ("minutes", "minutes", None),
    ("work_item", "work_item", None),
    ("pinboard_item", "pinboard_item", None),
    ("mention", "mention", None),
    ("calendar_entry", "calendar_entry", None),
    ("ui_action", "ui_action", None),
    ("calendar_entry.agenda_item", "calendar_entry", "agenda_item"),
    ("calendar_entry.free_busy", "calendar_entry", "free_busy"),
]
IDS = [t[0] for t in TARGETS]


@pytest.mark.parametrize("folder,schema,def_", TARGETS, ids=IDS)
def test_CC_PEOPLE_FR_WLD_02_valid_fixtures_exist_and_validate(repo_root, registry, folder, schema, def_):
    files = pl.fixture_files(repo_root, f"{folder}/valid")
    assert files, f"contracts/fixtures/{folder}/valid/ must hold at least one file"
    for path in files:
        pl.assert_valid(repo_root, registry, schema, load_json(path), def_, f"{folder}/valid/{path.name}")


@pytest.mark.parametrize("folder,schema,def_", TARGETS, ids=IDS)
def test_CC_PEOPLE_FR_WLD_02_invalid_fixtures_exist_and_are_refused(repo_root, registry, folder, schema, def_):
    files = pl.fixture_files(repo_root, f"{folder}/invalid")
    assert files, f"contracts/fixtures/{folder}/invalid/ must hold at least one file"
    for path in files:
        pl.assert_invalid(repo_root, registry, schema, load_json(path), def_, f"{folder}/invalid/{path.name}")
