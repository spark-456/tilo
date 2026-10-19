"""FR-PB-01 to FR-PB-05 (ADR-0038, accepted 12 Oct 2026): pinboard_item.schema.json 1.1.0 `placement` and the
proposed rule PE-36 (owner-only placement, no scope transfer, never the title). `_refusal` is the reference check:
once builders add the `place` action, the tilo-api and tilo_people tests must reach the same verdict on the same
files in `contracts/fixtures/pinboard_item/crossref/`."""

from __future__ import annotations

import pytest
from _lib import contracts_dir, errors_for, load_json, load_schema

ROOT = "https://contracts.tilo.example/pinboard_item.schema.json"
CASE_KEYS = {"rule", "note", "members", "actor", "before", "after"}


def _ref(key: str = "") -> dict:
    return {"$ref": ROOT + (f"#/$defs/{key}" if key else "")}


def _pin(repo_root, name: str) -> dict:
    return load_json(repo_root / "contracts/fixtures/pinboard_item/valid" / name)


def _cases(repo_root, kind):
    return sorted((contracts_dir(repo_root) / "fixtures" / "pinboard_item" / "crossref" / kind).glob("*.json"))


def _refusal(case) -> str | None:
    """PE-36: the rule id that refuses this move, or None when it is granted."""
    before, after, actor = case["before"], case["after"], case["actor"]
    if before["status"] != "active":
        return "PE-36"
    keys = set(before) | set(after)
    if any(before.get(k) != after.get(k) for k in keys if k != "placement"):
        return "PE-36"
    scope = before["scope"]
    if scope["kind"] == "personal":
        mine = actor == scope["user"]
    else:
        mine = actor == before["set_up_by"] and actor in case["members"]
    return None if mine else "PE-36"


def test_FR_PB_placement_is_optional_closed_and_names_no_user_team_or_scope(repo_root):
    schema = load_schema(repo_root, "pinboard_item")
    placement = schema["$defs"]["placement"]
    assert "placement" not in schema["required"], "old records without placement stay valid"
    assert schema["properties"]["placement"] == {"$ref": "#/$defs/placement"}
    assert set(placement["properties"]) == set(placement["required"]) == {"board", "column", "order"}
    assert placement["additionalProperties"] is False
    assert placement["properties"]["order"]["type"] == "integer"
    assert (placement["properties"]["order"]["minimum"], placement["properties"]["order"]["maximum"]) == (0, 9999)
    assert tuple(int(p) for p in schema["x-version"].split(".")) >= (1, 1, 0)


@pytest.mark.parametrize(
    ("value", "ok"),
    [("launch", True), ("a", True), ("a" * 32, True), ("col_2", True), ("a" * 33, False), ("2col", False)]
    + [("Launch", False), ("in progress", False), ("doing\n", False), ("", False), ("de-fault", False)],
)
def test_FR_PB_board_and_column_are_bounded_ids(repo_root, registry, value, ok):
    for field in ("board", "column"):
        placement = {"board": "launch", "column": "doing", "order": 0, field: value}
        found = errors_for(_ref("placement"), placement, registry)
        assert bool(found) is not ok, (field, value)


@pytest.mark.parametrize(
    ("order", "ok"), [(0, True), (9999, True), (-1, False), (10000, False), (1.5, False), ("1", False), (None, False)]
)
def test_FR_PB_order_is_a_bounded_non_negative_integer(repo_root, registry, order, ok):
    placement = {"board": "launch", "column": "doing", "order": order}
    assert bool(errors_for(_ref("placement"), placement, registry)) is not ok, order


def test_FR_PB_a_placed_entry_validates_and_the_placement_never_replaces_the_title(repo_root, registry):
    for name in ("team_active_placed.json", "personal_note_placed.json"):
        pin = _pin(repo_root, name)
        assert not errors_for(_ref(), pin, registry), name
        assert "title" not in pin["placement"], "placement carries no title"
    assert "title" not in load_schema(repo_root, "pinboard_item")["$defs"]["placement"]["properties"]


@pytest.mark.parametrize("kind", ["valid", "invalid"])
def test_FR_PB_crossref_cases_are_shaped_and_reach_the_stated_verdict(repo_root, registry, kind):
    cases = _cases(repo_root, kind)
    assert len(cases) >= (3 if kind == "valid" else 10)
    for path in cases:
        case = load_json(path)
        assert set(case) == CASE_KEYS, path.name
        for side in ("before", "after"):
            assert not errors_for(_ref(), case[side], registry), (path.name, side)
        assert _refusal(case) == case["rule"], path.name
        if kind == "invalid":
            assert case["rule"] == "PE-36" and path.name.startswith("pe36_"), path.name


def test_FR_PB_every_other_field_is_named_by_the_rule_and_the_row_says_it_is_proposed(repo_root):
    rules = (repo_root / "contracts/people.rules.md").read_text(encoding="utf-8")
    row = next(line for line in rules.splitlines() if line.startswith("| PE-36 |"))
    schema = load_schema(repo_root, "pinboard_item")
    assert "Proposed" in row and "tilo_people.writes" in row and "never changes the title" in row
    for field in set(schema["properties"]) - {"placement", "id"}:
        assert f"`{field}`" in row, field
    adr = (repo_root / "docs/adr/0038-owner-only-pin-placement.md").read_text(encoding="utf-8")
    assert "Accepted by the user, 12 Oct 2026" in adr.splitlines()[2]
