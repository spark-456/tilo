"""FR-SET-01 and FR-SET-02 (ADR-0039, accepted 12 Oct 2026): user_settings.schema.json 1.0.0 and rules USET-01 to
USET-08. `_refusal` is the reference check for USET-02 and USET-03: the tilo-api tests must reach the same verdict
on the same files in `contracts/fixtures/user_settings/crossref/`."""

from __future__ import annotations

import itertools
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pytest
from _lib import contracts_dir, errors_for, list_fixtures, load_json, load_schema

ROOT = "https://contracts.tilo.example/user_settings.schema.json"
FOLDERS = ("user_settings", "user_settings.update")
ROWS = ("decisions", "spend", "finished", "digest", "weekly")
SERVER_OWNED = {"owner_id": "u_alex", "org_id": "org_example", "updated_at": "2026-10-12T09:30:00.000Z"}


def _ref(folder: str) -> dict:
    _, _, key = folder.partition(".")
    return {"$ref": ROOT + (f"#/$defs/{key}" if key else "")}


def _fixture(repo_root, folder: str, name: str) -> dict:
    return load_json(repo_root / "contracts/fixtures" / folder / "valid" / f"{name}.json")


def _zone_known(name: str) -> bool:
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return False
    return True


def _refusal(case) -> str | None:
    """The rule id that refuses this write, or None when it is accepted (USET-02, USET-03)."""
    update = case["update"]
    hours, quiet = update["profile"]["working_hours"], update["quiet_hours"]
    if update["version"] != case["stored_version"]:
        return "USET-02"
    if not hours["start"] < hours["end"] or quiet["start"] == quiet["end"]:
        return "USET-03"
    if not (_zone_known(update["profile"]["time_zone"]) and _zone_known(quiet["timezone"])):
        return "USET-03"
    return None


@pytest.mark.parametrize("folder", FOLDERS)
def test_FR_SET_01_every_valid_fixture_passes_and_every_invalid_one_fails(repo_root, registry, folder):
    valid, invalid = list_fixtures(repo_root, folder, "valid"), list_fixtures(repo_root, folder, "invalid")
    assert valid and invalid
    assert all(not errors_for(_ref(folder), load_json(p), registry) for p in valid)
    assert all(errors_for(_ref(folder), load_json(p), registry) for p in invalid), "each invalid case breaks a rule"


def test_FR_SET_01_every_object_is_closed_and_the_write_body_names_no_server_owned_field(repo_root):
    schema = load_schema(repo_root, "user_settings")
    objects = [schema] + [d for d in schema["$defs"].values() if d.get("type") == "object"]
    assert len(objects) >= 8 and all(o["additionalProperties"] is False for o in objects)
    assert set(schema["required"]) == set(schema["properties"])
    assert (schema["title"], schema["x-version"]) == ("UserSettings", "1.0.0")
    assert set(schema["$defs"]["update"]["properties"]) == {"version", "profile", "notifications", "quiet_hours"}


@pytest.mark.parametrize("field", sorted(SERVER_OWNED))
def test_FR_SET_01_a_write_that_supplies_a_server_owned_field_is_refused(repo_root, registry, field):
    body = _fixture(repo_root, "user_settings.update", "second_save")
    assert errors_for(_ref("user_settings.update"), {**body, field: SERVER_OWNED[field]}, registry)


@pytest.mark.parametrize("version", [0, 1, 7])
def test_FR_SET_01_version_zero_is_the_unsaved_defaults_and_only_that_has_no_time(repo_root, registry, version):
    doc = _fixture(repo_root, "user_settings", "saved_overnight_quiet_hours_with_threshold")
    for updated_at, ok in ((SERVER_OWNED["updated_at"], version > 0), (None, version == 0)):
        found = errors_for(_ref("user_settings"), {**doc, "version": version, "updated_at": updated_at}, registry)
        assert bool(found) is not ok, (version, updated_at)


@pytest.mark.parametrize("row", ROWS)
@pytest.mark.parametrize("channels", list(itertools.product([True, False], repeat=3)))
def test_FR_SET_02_only_the_decisions_row_must_keep_a_channel(repo_root, registry, row, channels):
    body = _fixture(repo_root, "user_settings.update", "second_save")
    body["notifications"][row] = dict(zip(("phone", "email", "slack"), channels, strict=True))
    refused = bool(errors_for(_ref("user_settings.update"), body, registry))
    assert refused is (row == "decisions" and not any(channels)), (row, channels)


def test_FR_SET_02_quiet_hours_have_no_field_that_could_hide_a_gate_and_threshold_is_typed(repo_root, registry):
    defs = load_schema(repo_root, "user_settings")["$defs"]
    assert set(defs["quiet_hours"]["properties"]) == {"enabled", "start", "end", "timezone", "threshold"}
    assert set(defs["money"]["properties"]) == {"amount_minor", "currency"}
    doc = _fixture(repo_root, "user_settings", "saved_overnight_quiet_hours_with_threshold")
    for threshold in ("£1,000", "1000", 1000, {"amount_minor": 1000}, {"amount_minor": 10.5, "currency": "INR"}):
        refused = {**doc, "quiet_hours": {**doc["quiet_hours"], "threshold": threshold}}
        assert errors_for(_ref("user_settings"), refused, registry), threshold


@pytest.mark.parametrize("kind", ["valid", "invalid"])
def test_FR_SET_01_02_crossref_cases_are_shaped_and_reach_the_stated_verdict(repo_root, registry, kind):
    folder = contracts_dir(repo_root) / "fixtures" / "user_settings" / "crossref" / kind
    paths = sorted(folder.glob("*.json"))
    assert len(paths) >= (3 if kind == "valid" else 8)
    seen = set()
    for path in paths:
        case = load_json(path)
        assert set(case) == {"rule", "note", "stored_version", "update"}, path.name
        assert not errors_for(_ref("user_settings.update"), case["update"], registry), path.name
        assert _refusal(case) == case["rule"], path.name
        if kind == "invalid":
            assert path.name.startswith(case["rule"].lower().replace("-", "")), path.name
            seen.add(case["rule"])
    assert seen == ({"USET-02", "USET-03"} if kind == "invalid" else set())


def test_FR_SET_02_quiet_hours_here_are_the_shape_the_channels_filter_reads_and_gates_still_notify(repo_root):
    quiet_hours = pytest.importorskip("tilo_channels.quiet_hours")
    doc = _fixture(repo_root, "user_settings", "saved_overnight_quiet_hours_with_threshold")
    quiet = {**doc["quiet_hours"], "start": "22:00", "end": "07:00", "timezone": "UTC"}
    during = "2026-10-12T23:00:00Z"
    for threshold in (quiet["threshold"], None):
        prefs = {"quiet_hours": {**quiet, "threshold": threshold}}
        window = quiet_hours.parse_quiet_hours(prefs)
        assert window is not None and (window.start, window.end, window.timezone) == ("22:00", "07:00", "UTC")
        assert quiet_hours.is_quiet_hours(prefs, now=during)
        assert quiet_hours.should_notify("gate", prefs=prefs, now=during)
        assert quiet_hours.should_notify("blocked", prefs=prefs, now=during)
        assert not quiet_hours.should_notify("needs_you", prefs=prefs, now=during), "the threshold adds no push"


def test_FR_SET_01_the_rules_file_states_uset_01_to_08(repo_root):
    rules = (repo_root / "contracts/user_settings.rules.md").read_text(encoding="utf-8")
    assert all(f"| USET-0{n} |" in rules for n in range(1, 9))
