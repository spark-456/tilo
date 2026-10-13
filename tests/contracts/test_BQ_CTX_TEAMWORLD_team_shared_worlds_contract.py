"""BQ-CTX-TEAMWORLD, slice TSW-0 (ADR-0040, accepted 12 Oct 2026): `world_share.schema.json` 1.0.0,
`work_item.schema.json` 1.1.0 (optional `world_id`), registry 1.5.0 with `world.share_changed`, and the rules
PE-03 (amended) and PE-31 to PE-35.

`_people_lib.world_share_permits` is the reference check: once TSW-1 teaches `tilo_people.decide` the `read_team`
action, its tests must reach the same verdicts on the same files in `contracts/fixtures/world_share/crossref/`.
That folder is separate from `person/crossref` on purpose: the PPL-10a suite runs every file of the latter through
`decide`, which refuses `read_team` until TSW-1."""

from __future__ import annotations

import _people_lib as pl
import pytest
import yaml
from _lib import contracts_dir, errors_for, load_json, load_schema

# Each check of the reference oracle and a named invalid case that is refused by that check alone.
KILLERS = {
    "revoked": "pe31_world_share_revoked",
    "granter_is_world_owner": "pe31_share_granted_by_someone_who_is_not_the_world_owner",
    "granted_not_in_future": "pe31_share_dated_in_the_future",
    "owner_in_team": "pe31_world_owner_membership_not_assigned_by_an_org_owner",
    "membership_predates_grant": "pe31_world_owner_rejoined_after_the_grant",
    "id_derived": "pe31_share_id_not_derived",
    "same_org": "pe31_share_of_another_org",
    "item_in_the_share_world": "pe31_share_of_another_world",
    "person_made": "pe33_item_not_its_creators_own",
    "open_or_done": "pe33_dropped_work_item",
    "not_flagged": "pe33_flagged_work_item",
    "actor_same_org": "pe33_person_of_another_org_reads_team_work_item",
    "actor_in_team": "pe33_outsider_reads_team_work_item",
    "item_owner_in_team": "pe33_item_owner_left_the_team",
    "creator_reads_world": "pe33_member_creates_item_in_world_not_shared_with_them",
}
NOT_IN_A_TEAM_VIEW = {"source", "evidence", "history", "assigned_by", "snoozed_until", "flagged", "confirmed_by"}


def _version(schema):
    return tuple(int(p) for p in schema["x-version"].split("."))


def _cases(repo_root, kind):
    cases = pl.load_share_cases(repo_root, kind)
    assert cases, f"contracts/fixtures/world_share/crossref/{kind}/ must hold at least one case"
    return cases


def test_BQ_CTX_TEAMWORLD_PE_31_world_share_is_a_closed_record_with_no_role_scope_or_districts(repo_root):
    schema = load_schema(repo_root, "world_share")
    assert schema["x-version"] == "1.0.0" and schema["title"] == "WorldShare"
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    assert set(schema["properties"]) == {"id", "org_id", "world_id", "team", "granted_by", "revoked"}
    assert not {"role", "scope", "districts", "permissions"} & set(schema["properties"])


def test_BQ_CTX_TEAMWORLD_PE_33_work_item_gains_an_optional_world_id_only(repo_root):
    schema = load_schema(repo_root, "work_item")
    assert _version(schema)[0] == 1 and _version(schema) >= (1, 1, 0)
    assert "world_id" in schema["properties"] and "world_id" not in schema["required"]
    by = schema["dependentSchemas"]["world_id"]["properties"]["created_by"]["properties"]["by"]
    assert by == {"const": "person"}, "a Tilo-made item never has a world_id"


def test_BQ_CTX_TEAMWORLD_PE_33_team_view_has_six_keys_and_leaks_none_of_the_private_fields(repo_root):
    assert pl.TEAM_VIEW_FIELDS == ("id", "title", "status", "due", "owner", "world_id")
    properties = set(load_schema(repo_root, "work_item")["properties"])
    assert set(pl.TEAM_VIEW_FIELDS) <= properties
    assert not NOT_IN_A_TEAM_VIEW & set(pl.TEAM_VIEW_FIELDS)
    assert pl.SHARE_REQUEST_KINDS == (*pl.REQUEST_KINDS, "read_team"), "the 14 actions of tilo_people stay as they are"
    assert "read_team" not in pl.READS, "READS stays read_full and read_status"


def test_BQ_CTX_TEAMWORLD_PE_35_world_share_changed_is_registered_and_authorises_nothing(repo_root):
    registry = yaml.safe_load((repo_root / "contracts/events/registry.yaml").read_text(encoding="utf-8"))
    assert tuple(int(p) for p in str(registry["version"]).split(".")) >= (1, 5, 0)
    entry = registry["types"]["world.share_changed"]
    assert (entry["family"], entry["verb"], entry["side_effect"]) == ("world", "share_changed", False)
    assert "authz_by" not in entry
    assert "world.share_changed" not in load_schema(repo_root, "event")["if"]["properties"]["type"]["enum"]
    event = load_json(repo_root / "contracts" / entry["fixture"])
    assert (event["vis"], event["district"], event["authz"]) == ([], None, None)
    assert event["target"] == event["world_id"], "event.schema.json has no null target: it is the world's own id"


@pytest.mark.parametrize(
    "data", [{"team": "tm_launch", "state": "removed"}, {"state": "on"}, {"team": "u_owner", "state": "on"}]
)
def test_BQ_CTX_TEAMWORLD_PE_35_world_share_changed_data_refuses_a_bad_state_or_team(repo_root, registry, data):
    schema = load_schema(repo_root, "events/data/world.share_changed")
    assert errors_for(schema, data, registry)
    assert not errors_for(schema, {"team": "tm_launch", "state": "off"}, registry)


@pytest.mark.parametrize("kind", ["valid", "invalid"])
def test_BQ_CTX_TEAMWORLD_PE_31_crossref_cases_are_shape_valid(repo_root, registry, kind):
    for path, case in _cases(repo_root, kind):
        found = pl.share_case_shape_problems(repo_root, registry, case)
        assert not found, f"{kind}/{path.name}: every part must be shape-valid, got {found[:3]}"


def test_BQ_CTX_TEAMWORLD_PE_33_every_valid_case_is_granted_and_every_invalid_one_refused(repo_root):
    for path, case in _cases(repo_root, "valid"):
        assert case["rule"] is None and pl.world_share_permits(case), f"valid/{path.name}: {case['note']}"
    for path, case in _cases(repo_root, "invalid"):
        assert case["rule"] in pl.SHARE_RULES, f"invalid/{path.name}: rule must be one of {pl.SHARE_RULES}"
        assert path.name.startswith(case["rule"].lower().replace("-", "") + "_"), f"invalid/{path.name}: name the rule"
        assert not pl.world_share_permits(case), f"invalid/{path.name}: granted, must be refused"


def test_BQ_CTX_TEAMWORLD_PE_31_a_valid_share_id_is_derived_from_its_world_and_team(repo_root):
    share = load_json(contracts_dir(repo_root) / "fixtures/world_share/valid/active.json")
    assert share["id"] == pl.share_id(share["world_id"], share["team"])
    assert pl.share_id("w_launch_plan", "tm_launch") != pl.share_id("w_launch_plan", "tm_ops")


@pytest.mark.parametrize("check", sorted(KILLERS))
def test_BQ_CTX_TEAMWORLD_PE_31_PE_33_dropping_a_check_lets_its_named_case_through(repo_root, check):
    assert set(KILLERS) == set(pl.SHARE_CHECKS), "every oracle check has a named killer case"
    cases = {path.stem: case for path, case in _cases(repo_root, "invalid")}
    case = cases[KILLERS[check]]
    assert not pl.world_share_permits(case)
    assert pl.world_share_permits(case, skip=frozenset({check})), f"{check} is not load-bearing for {KILLERS[check]}"


def test_BQ_CTX_TEAMWORLD_every_new_or_amended_rule_has_an_invalid_case(repo_root):
    covered = {case["rule"] for _, case in _cases(repo_root, "invalid")}
    assert set(pl.SHARE_RULES) <= covered, f"no invalid case for {sorted(set(pl.SHARE_RULES) - covered)}"
