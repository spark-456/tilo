"""ADR-0046 invite decisions must agree with the contract's cross-reference cases."""

import importlib
import json

import _ppl10_testlib as t
import pytest
from tilo_people.directory import Directory
from tilo_people.teams import LinkRequest, TeamRequest, decide_link, decide_team

reference = importlib.import_module("_invite_link_lib")
teams_reference = importlib.import_module("_teams_lib")


@pytest.mark.parametrize("kind", ("valid", "invalid"))
def test_SELF_SERVE_TEAMS_INVITE_LINK_decide_matches_the_reference_check(kind):
    folder = t.REPO_ROOT / "contracts" / "fixtures" / "team_invite_link" / "crossref" / kind
    for path in sorted(folder.glob("*.json")):
        case = json.loads(path.read_text(encoding="utf-8"))
        req = case["request"]
        got = decide_link(
            LinkRequest(
                req["actor"],
                req["action"],
                case["org_id"],
                case["now"],
                team=req["team"],
                link=req["link"],
                nonce_sha256=req["nonce_sha256"],
                verified_email=req["verified_email"],
                record=req["record"],
            ),
            Directory.of(case["persons"].values()),
            case["links"],
        )
        assert got is reference.link_permits(case) is (kind == "valid"), path.name


def test_SELF_SERVE_TEAMS_INVITE_LINK_membership_crossref_verdicts_are_unchanged():
    folder = t.REPO_ROOT / "contracts" / "fixtures" / "person.membership" / "crossref"
    for kind in ("valid", "invalid"):
        for path in sorted((folder / kind).glob("*.json")):
            case = json.loads(path.read_text(encoding="utf-8"))
            req = case["request"]
            asked = TeamRequest(
                req["actor"],
                req["action"],
                case["org_id"],
                case["now"],
                person=req["person"],
                team=req["team"],
                record=req["record"],
            )
            assert decide_team(asked, Directory.of(case["persons"].values())) is teams_reference.team_permits(case)
