"""BQ-CTX-TEAMWORLD, slice TSW-1b (ADR-0040 decision 6; FR-TEAM-04 to FR-TEAM-06; PE-03 as amended, PE-31, PE-33):
`decide` learns `read_team` (a work item's team view) and `create` of a work item that names a `world_id`.

Every file of `contracts/fixtures/world_share/crossref/` must reach the verdict of the reference oracle
(`tests/contracts/_people_lib.py`, `world_share_permits`), through `tilo_people.crossref.verdict_for_case`. The 14
actions of PPL-10a stay as they are; `read_team` is the one new action and reads work items only.
"""

from __future__ import annotations

import copy
import json

import _ppl10_testlib as t
import pytest
from _ppl10_testlib import access, crossref, pl

CROSSREF = t.REPO_ROOT / "contracts" / "fixtures" / "world_share" / "crossref"
TEAM_VIEW = ("id", "title", "status", "due", "owner", "world_id")


def _load(kind):
    return [(p.stem, json.loads(p.read_text(encoding="utf-8"))) for p in sorted((CROSSREF / kind).glob("*.json"))]


VALID, INVALID = _load("valid"), _load("invalid")


def _request(case):
    built, directory = crossref.case_request(case)
    return built, directory


def _teammate_case():
    return copy.deepcopy(dict(VALID)["teammate_reads_team_work_item"])


@pytest.mark.parametrize("case", t.case_params(VALID))
def test_BQ_CTX_TEAMWORLD_PE_33_every_valid_share_case_is_allowed_and_the_oracle_agrees(case):
    assert pl.world_share_permits(case) is True
    assert crossref.verdict_for_case(case).allowed is True


@pytest.mark.parametrize("case", t.case_params(INVALID))
def test_BQ_CTX_TEAMWORLD_PE_33_every_invalid_share_case_is_refused_and_the_oracle_agrees(case):
    assert pl.world_share_permits(case) is False
    assert crossref.verdict_for_case(case).allowed is False


def test_BQ_CTX_TEAMWORLD_PE_33_a_team_read_is_the_team_view_and_exactly_six_keys():
    case = _teammate_case()
    request, directory = _request(case)
    verdict = access.decide(request, directory)
    assert (verdict.allowed, verdict.view) == (True, "team")
    got = access.read(request, directory)
    assert tuple(got) == TEAM_VIEW and got["world_id"] == case["record"]["data"]["world_id"]
    assert got == {k: case["record"]["data"][k] for k in TEAM_VIEW}


def test_BQ_CTX_TEAMWORLD_PE_33_the_14_actions_are_unchanged_and_read_team_is_a_work_item_view_only():
    assert tuple(access.ACTIONS) == tuple(t.ACTIONS) and len(access.ACTIONS) == 14
    assert "read_team" not in access.READS
    for kind in ("pinboard_item", "meeting", "calendar_entry", "person"):
        assert access.project(kind, "team", {"id": "x"}) is None
    assert access.project("work_item", "team", {"id": "wi_x", "source": {"ref": "SECRET"}}) == {"id": "wi_x"}


def test_BQ_CTX_TEAMWORLD_PE_33_without_the_share_or_the_world_owner_in_the_request_nothing_is_read():
    request, directory = _request(_teammate_case())
    for missing in ({"world_share": None}, {"world_owner": None}, {"world_share": None, "world_owner": None}):
        bare = type(request)(**{**request.__dict__, **missing})
        assert access.decide(bare, directory).allowed is False


def test_BQ_CTX_TEAMWORLD_PE_33_the_team_view_is_never_a_way_to_read_in_full_or_to_change():
    case = _teammate_case()
    request, directory = _request(case)
    for action in ("read_full", "read_status", "edit", "mark_done", "confirm"):
        other = type(request)(**{**request.__dict__, "action": action})
        assert access.decide(other, directory).allowed is False, action


def test_BQ_CTX_TEAMWORLD_PE_33_tilo_never_reads_or_makes_an_item_in_a_world():
    case = _teammate_case()
    request, directory = _request(case)
    tilo = type(request)(**{**request.__dict__, "actor": "A_director"})
    assert access.decide(tilo, directory).allowed is False
    made = copy.deepcopy(case["record"]["data"])
    made["created_by"] = {"by": "tilo", "ref": "A_director", "at": made["created_at"]}
    creating = type(request)(**{**request.__dict__, "action": "create", "actor": "A_director", "record": made})
    assert access.decide(creating, directory).allowed is False


def test_BQ_CTX_TEAMWORLD_PE_33_a_share_of_another_org_than_the_item_reads_nothing():
    case = _teammate_case()
    request, directory = _request(case)
    foreign = {**request.world_share, "org_id": "org_elsewhere"}
    other = type(request)(**{**request.__dict__, "world_share": foreign})
    assert access.decide(other, directory).allowed is False
