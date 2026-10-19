"""SELF-SERVE-TEAMS (ADR-0044): `tilo_people.teams.decide_team` and the amended `Directory.is_member` / `is_lead`
reach the verdicts of the reference check `tests/contracts/_teams_lib.team_permits` on every file of
`contracts/fixtures/person.membership/crossref/`, and `access.decide` grants the PE-20 inviter's name the same way."""

from __future__ import annotations

import json

import _ppl10_testlib as t
import _teams_lib as tl
import pytest
from tilo_people.access import AccessRequest, decide
from tilo_people.directory import Directory
from tilo_people.teams import TeamRequest, decide_team

FOLDER = t.REPO_ROOT / "contracts" / "fixtures" / "person.membership" / "crossref"
CASES = [
    pytest.param(kind, json.loads(p.read_text(encoding="utf-8")), id=f"{kind}/{p.stem}")
    for kind in ("valid", "invalid")
    for p in sorted((FOLDER / kind).glob("*.json"))
]


def _request(case: dict) -> TeamRequest:
    r = case["request"]
    return TeamRequest(
        r["actor"], r["action"], case["org_id"], case["now"], person=r["person"], team=r["team"], record=r["record"]
    )


def test_SELF_SERVE_TEAMS_the_folder_holds_both_kinds():
    kinds = [c.values[0] for c in CASES]
    assert kinds.count("valid") >= 19 and kinds.count("invalid") >= 27


@pytest.mark.parametrize(("kind", "case"), CASES)
def test_SELF_SERVE_TEAMS_decide_team_matches_the_reference_check(kind, case):
    d = Directory.of(case["persons"].values())
    got = decide_team(_request(case), d)
    assert got is tl.team_permits(case) is (kind == "valid"), case["note"]


@pytest.mark.parametrize(("kind", "case"), CASES)
def test_SELF_SERVE_TEAMS_PE_02_is_member_and_is_lead_match_the_terms(kind, case):
    persons, now = case["persons"], case["now"]
    d = Directory.of(persons.values())
    teams = {m["team"] for p in persons.values() for m in p["memberships"]}
    for user in persons:
        for team in teams:
            assert d.is_member(user, team, now) is t.pl.is_member(persons, user, team, now), (user, team)
            assert d.is_lead(user, team, now) is t.pl.is_lead(persons, user, team, now), (user, team)


@pytest.mark.parametrize(("kind", "case"), [c for c in CASES if c.values[1]["request"]["action"] == "read_directory"])
def test_SELF_SERVE_TEAMS_PE_20_access_decide_reads_the_inviters_name_the_same_way(kind, case):
    r, persons = case["request"], case["persons"]
    d = Directory.of(persons.values())
    request = AccessRequest(r["actor"], "read_directory", "person", persons[r["person"]], case["now"])
    assert decide(request, d).allowed is (kind == "valid"), case["note"]


def test_SELF_SERVE_TEAMS_a_malformed_request_is_refused_never_raised():
    d = Directory.of([])
    for bad in (
        TeamRequest("nobody", "create_team", "org_example", t.NOW, team="tm_x"),
        TeamRequest("u_a", "make_owner", "org_example", t.NOW),
        TeamRequest("u_a", "self_join", "org_example", "yesterday", record={}),
        TeamRequest("u_a", "self_join", "org_example", t.NOW, record=None),
    ):
        assert decide_team(bad, d) is False
