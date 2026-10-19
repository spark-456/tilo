"""BQ-CTX-TEAMWORLD, slice TSW-2a (ADR-0040 decision 9 "the API says `in_force: false` and why in a fixed word";
FR-TEAM-01, FR-TEAM-02; PE-31): `GET /worlds/{world_id}/team-shares`, owner only. Security-flagged: it answers who a
world is opened to, so it has the guards of the `PUT` and `DELETE` beside it.
"""

from __future__ import annotations

import dataclasses

import pytest
from _tsw1_lib import ASHA, BEN, CARA, DEV, LATER, LAUNCH, NOW, OPS, ORGOWNER, OTHER_WORLD, WORLD, Rig, share, web
from fastapi import HTTPException
from tilo_api import deps

REASONS = {"revoked", "owner_left_team", "owner_changed", "not_yet"}


@pytest.fixture()
def rig() -> Rig:
    return Rig()


def _get(rig: Rig, world: str = WORLD, **kw):
    return rig.client.get(f"/worlds/{world}/team-shares", **kw)


def _rows(rig: Rig) -> list[dict]:
    got = _get(rig)
    assert got.status_code == 200, got.text
    return got.json()["shares"]


def test_BQ_CTX_TEAMWORLD_FR_TEAM_01_a_world_with_no_share_lists_nothing(rig):
    got = _get(rig)
    assert got.status_code == 200
    assert got.json() == {"world_id": WORLD, "shares": []}
    assert got.headers["cache-control"] == "no-store"


def test_BQ_CTX_TEAMWORLD_FR_TEAM_01_the_owner_lists_a_share_in_force_with_no_reason(rig):
    assert rig.client.put(f"/worlds/{WORLD}/team-shares/{LAUNCH}").status_code == 200
    [row] = _rows(rig)
    assert row == {"team": LAUNCH, "in_force": True, "reason": None, "granted_at": NOW}


def test_BQ_CTX_TEAMWORLD_FR_TEAM_02_a_revoked_share_says_revoked(rig):
    rig.client.put(f"/worlds/{WORLD}/team-shares/{LAUNCH}")
    rig.now = LATER
    assert rig.client.delete(f"/worlds/{WORLD}/team-shares/{LAUNCH}").status_code == 200
    [row] = _rows(rig)
    assert (row["team"], row["in_force"], row["reason"]) == (LAUNCH, False, "revoked")


def test_BQ_CTX_TEAMWORLD_PE_31_an_owner_who_left_the_team_lapses_the_share_and_the_word_says_so(rig):
    rig.grant()
    stored = rig.people.persons.get(deps.ORG_ID, ASHA)
    record = dict(stored.record)
    record["memberships"] = []
    rig.people.persons.replace(record, expected_version=stored.version)
    [row] = _rows(rig)
    assert (row["in_force"], row["reason"]) == (False, "owner_left_team")


def test_BQ_CTX_TEAMWORLD_PE_31_a_share_the_previous_owner_made_is_not_in_force_for_the_new_owner(rig):
    rig.grant()  # Asha's grant
    rig.store.worlds[WORLD].owner = BEN
    rig.as_(web(BEN))
    [row] = _rows(rig)
    assert (row["in_force"], row["reason"]) == (False, "owner_changed")


def test_BQ_CTX_TEAMWORLD_PE_31_a_grant_stamped_in_the_future_is_not_yet_in_force(rig):
    rig.grant(at=LATER)  # the clock reads NOW
    [row] = _rows(rig)
    assert (row["in_force"], row["reason"]) == (False, "not_yet")


def test_BQ_CTX_TEAMWORLD_FR_TEAM_01_only_this_worlds_shares_are_listed_and_each_row_has_four_keys(rig):
    rig.grant()
    rig.grant(team=OPS, by=ORGOWNER)  # not Asha's: the world's owner changed for that one
    rig.grant(world=OTHER_WORLD)
    rows = _rows(rig)
    assert sorted(r["team"] for r in rows) == [LAUNCH, OPS]
    for row in rows:
        assert set(row) == {"team", "in_force", "reason", "granted_at"}
        assert row["reason"] is None or row["reason"] in REASONS
        assert row["in_force"] is (row["reason"] is None)
    assert [r["team"] for r in rows if r["in_force"]] == [LAUNCH]


@pytest.mark.parametrize(
    "principal",
    [
        pytest.param(web(BEN), id="a teammate"),
        pytest.param(web(CARA), id="an outsider"),
        pytest.param(web(ORGOWNER), id="the org owner"),
        pytest.param(web(DEV), id="a person of another org"),
        pytest.param(deps.Principal(ASHA, "owner", world_id=WORLD, channel="web", full_session=True), id="bound"),
        pytest.param(deps.Principal(ASHA, "viewer", world_id=WORLD, channel="web", full_session=True), id="viewer"),
        pytest.param(deps.Principal(ASHA, "team_lead", world_id=None, channel="web", full_session=True), id="lead"),
        pytest.param(deps.Principal(ASHA, "owner", world_id=None, channel="email", full_session=True), id="email"),
        pytest.param(deps.Principal(ASHA, "owner", world_id=None, channel="web", full_session=False), id="no marker"),
        pytest.param(dataclasses.replace(web(ASHA), demo_session=True), id="demo"),
    ],
)
def test_BQ_CTX_TEAMWORLD_PE_31_everyone_but_the_owners_full_session_gets_the_unknown_world_404(rig, principal):
    unknown = _get(rig, world="w_no_such_world")
    rig.grant()
    rig.as_(principal)
    got = _get(rig)
    assert got.status_code == 404
    assert got.content == unknown.content, "one body for every refusal: no membership oracle"


def test_BQ_CTX_TEAMWORLD_PE_31_a_team_reader_of_a_shared_world_still_gets_the_404_not_the_list(rig):
    rig.grant()
    rig.as_(web(BEN))  # a member of the team the world is shared with
    assert _get(rig).status_code == 404


def test_BQ_CTX_TEAMWORLD_FR_TEAM_01_an_unwired_people_store_is_503(rig):
    rig.people_error = HTTPException(status_code=503, detail="not_configured")
    assert _get(rig).status_code == 503


def test_BQ_CTX_TEAMWORLD_FR_TEAM_01_the_list_reads_the_stamp_of_the_record_not_the_request(rig):
    rig.grant()
    got = _get(rig, params={"team": OPS, "world_id": OTHER_WORLD}, headers={"X-Tilo-Team": OPS})
    assert [r["team"] for r in got.json()["shares"]] == [LAUNCH]
    assert share()["granted_by"]["at"] == got.json()["shares"][0]["granted_at"]
