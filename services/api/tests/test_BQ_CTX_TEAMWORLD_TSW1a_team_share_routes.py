"""BQ-CTX-TEAMWORLD, slice TSW-1a (ADR-0040 decisions 2 and 9; FR-TEAM-01, FR-TEAM-02; PE-31, PE-35):
`PUT` and `DELETE /worlds/{world_id}/team-shares/{team}`, owner only. Security-flagged: these routes decide who
may open a world to a team.
"""

from __future__ import annotations

import dataclasses

import pytest
from _api_lib import FlakyEventWriter, validate_event
from _tsw1_lib import (
    ASHA,
    BEN,
    CARA,
    DEV,
    LATER,
    LAUNCH,
    NOW,
    OPS,
    ORG,
    ORGOWNER,
    OTHER_WORLD,
    WORLD,
    Rig,
    share_id,
    web,
)
from fastapi import HTTPException
from tilo_api import deps


@pytest.fixture()
def rig() -> Rig:
    return Rig()


def _put(rig: Rig, team: str = LAUNCH, world: str = WORLD, **kw):
    return rig.client.put(f"/worlds/{world}/team-shares/{team}", **kw)


def _delete(rig: Rig, team: str = LAUNCH, world: str = WORLD, **kw):
    return rig.client.delete(f"/worlds/{world}/team-shares/{team}", **kw)


def test_BQ_CTX_TEAMWORLD_FR_TEAM_01_the_owner_shares_the_world_with_a_team_they_belong_to(rig):
    got = _put(rig)
    assert got.status_code == 200, got.text
    assert rig.shares() == [
        {
            "id": share_id(WORLD, LAUNCH),
            "org_id": ORG,
            "world_id": WORLD,
            "team": LAUNCH,
            "granted_by": {"by": ASHA, "at": NOW},
            "revoked": None,
        }
    ]
    body = got.json()
    assert (body["world_id"], body["team"], body["state"]) == (WORLD, LAUNCH, "on")


def test_BQ_CTX_TEAMWORLD_FR_TEAM_01_a_mobile_web_full_session_may_share_too(rig):
    rig.as_(dataclasses.replace(web(ASHA), channel="mobile_web"))
    assert _put(rig).status_code == 200


def test_BQ_CTX_TEAMWORLD_PE_19_the_stamp_is_the_session_and_the_server_clock_never_the_body(rig):
    forged = {"granted_by": {"by": BEN, "at": "2000-01-01T00:00:00.000Z"}, "team": OPS, "org_id": "org_x", "revoked": 1}
    got = _put(rig, json=forged, headers={"X-Tilo-Team": OPS}, params={"team": OPS, "granted_by": BEN})
    assert got.status_code == 200
    [record] = rig.shares()
    assert (record["team"], record["org_id"], record["revoked"]) == (LAUNCH, ORG, None)
    assert record["granted_by"] == {"by": ASHA, "at": NOW}
    assert rig.shares() == [r for r in rig.shares() if r["team"] != OPS]


def test_BQ_CTX_TEAMWORLD_PE_35_the_share_writes_one_owner_only_event_in_the_shared_world(rig):
    _put(rig)
    [event] = rig.events_of(WORLD, "world.share_changed")
    validate_event(event)
    assert event["actor"] == ASHA and event["target"] == WORLD
    assert event["vis"] == [] and event["district"] is None and event["authz"] is None
    assert event["data"] == {"team": LAUNCH, "state": "on"}
    assert LAUNCH not in event["summary"] and ASHA not in event["summary"]  # ids live in data, never in prose
    assert rig.events_of(OTHER_WORLD) == []


def test_BQ_CTX_TEAMWORLD_FR_TEAM_01_sharing_twice_is_one_record_and_one_event(rig):
    assert _put(rig).status_code == 200
    rig.now = LATER
    assert _put(rig).status_code == 200
    [record] = rig.shares()
    assert record["granted_by"]["at"] == NOW  # the first grant stands: a retry never restamps it
    assert len(rig.events_of(WORLD, "world.share_changed")) == 1


def test_BQ_CTX_TEAMWORLD_FR_TEAM_02_the_owner_revokes_and_the_revocation_is_stamped_and_logged(rig):
    _put(rig)
    rig.now = LATER
    got = _delete(rig)
    assert got.status_code == 200 and got.json()["state"] == "off"
    [record] = rig.shares()
    assert record["revoked"] == {"by": ASHA, "at": LATER}
    assert record["granted_by"] == {"by": ASHA, "at": NOW}
    states = [e["data"]["state"] for e in rig.events_of(WORLD, "world.share_changed")]
    assert states == ["on", "off"]
    assert _delete(rig).status_code == 200  # an identical retry is idempotent
    assert [e["data"]["state"] for e in rig.events_of(WORLD, "world.share_changed")] == ["on", "off"]


def test_BQ_CTX_TEAMWORLD_FR_TEAM_02_revoking_a_share_that_never_existed_is_the_unknown_404(rig):
    got = _delete(rig)
    assert got.status_code == 404
    assert rig.events_of(WORLD, "world.share_changed") == []


def test_BQ_CTX_TEAMWORLD_FR_TEAM_01_sharing_again_after_a_revoke_replaces_the_record(rig):
    _put(rig)
    rig.now = "2026-10-10T10:00:00.000Z"
    _delete(rig)
    rig.now = LATER
    assert _put(rig).status_code == 200
    [record] = rig.shares()
    assert record["revoked"] is None and record["granted_by"]["at"] == LATER
    assert [e["data"]["state"] for e in rig.events_of(WORLD, "world.share_changed")] == ["on", "off", "on"]


def test_BQ_CTX_TEAMWORLD_FR_TEAM_01_when_the_world_changes_owner_the_new_owner_shares_it_afresh(rig):
    rig.grant()  # Asha's share, still stored
    rig.store.worlds[WORLD].owner = BEN
    rig.as_(web(BEN))
    rig.now = LATER
    assert _put(rig).status_code == 200
    [record] = rig.shares()
    assert record["granted_by"] == {"by": BEN, "at": LATER} and record["revoked"] is None
    rig.as_(web(ASHA))
    assert _delete(rig).status_code == 404  # no longer the owner: no right over it


@pytest.mark.parametrize(
    "principal",
    [
        pytest.param(web(BEN), id="a teammate"),
        pytest.param(web(CARA), id="an outsider"),
        pytest.param(web(ORGOWNER), id="the org owner, who has no revoke right (decision 2)"),
        pytest.param(web(DEV), id="a person of another org"),
        pytest.param(deps.Principal(ASHA, "owner", world_id=WORLD, channel="web", full_session=True), id="bound"),
        pytest.param(deps.Principal(ASHA, "approver", world_id=WORLD, channel="web", full_session=True), id="approver"),
        pytest.param(deps.Principal(ASHA, "viewer", world_id=WORLD, channel="web", full_session=True), id="viewer"),
        pytest.param(deps.Principal(ASHA, "team_lead", world_id=None, channel="web", full_session=True), id="lead"),
        pytest.param(deps.Principal(ASHA, "owner", world_id=None, channel="email", full_session=True), id="email"),
        pytest.param(deps.Principal(ASHA, "owner", world_id=None, channel="web", full_session=False), id="no marker"),
        pytest.param(web(ASHA, demo_session=True), id="demo"),
    ],
)
def test_BQ_CTX_TEAMWORLD_PE_31_everyone_but_the_owners_full_session_gets_the_unknown_world_404(rig, principal):
    unknown = _put(rig, world="w_no_such_world")
    rig.as_(principal)
    rig.grant()  # something there to revoke, so a different answer would show
    for call in (_put, _delete):
        got = call(rig)
        assert got.status_code == 404
        assert got.content == unknown.content, "one body for every refusal: no membership oracle"
    assert [r["granted_by"]["by"] for r in rig.shares()] == [ASHA] and rig.shares()[0]["revoked"] is None
    assert rig.events_of(WORLD, "world.share_changed") == []


def test_BQ_CTX_TEAMWORLD_PE_31_the_owner_shares_only_with_a_team_they_belong_to(rig):
    for team in (OPS, "tm_nobody_has_this"):
        got = _put(rig, team=team)
        assert got.status_code == 403
    assert rig.shares() == [] and rig.events_of(WORLD, "world.share_changed") == []


def test_BQ_CTX_TEAMWORLD_PE_31_the_owners_membership_must_be_assigned_by_an_org_owner(rig):
    ashas = rig.people.persons.get(ORG, ASHA)
    record = ashas.record
    record["memberships"] = [{"team": LAUNCH, "assigned_by": {"by": BEN, "at": "2026-10-01T09:00:00.000Z"}}]
    rig.people.persons.replace(record, expected_version=ashas.version)
    assert _put(rig).status_code == 403  # Ben is a member, not an org owner: no membership in PE-02 terms


def test_BQ_CTX_TEAMWORLD_PE_31_a_malformed_team_in_the_path_is_the_unknown_404(rig):
    assert _put(rig, team="tm_BAD").status_code == 404
    assert _put(rig, team="u_asha").status_code == 404
    assert rig.shares() == []


def test_BQ_CTX_TEAMWORLD_PE_35_a_grant_whose_event_cannot_be_written_leaves_no_share(rig):
    rig.writer = FlakyEventWriter(rig.store, failing=True)
    got = _put(rig)
    assert got.status_code == 503
    assert rig.shares() == []  # the record is removed again: nothing is shared without its event
    assert rig.events_of(WORLD, "world.share_changed") == []


def test_BQ_CTX_TEAMWORLD_PE_35_a_revoke_whose_event_cannot_be_written_stays_revoked_and_the_retry_logs_it(rig):
    _put(rig)
    good = rig.writer
    rig.writer = FlakyEventWriter(rig.store, failing=True)
    rig.now = LATER
    assert _delete(rig).status_code == 503
    [record] = rig.shares()
    assert record["revoked"] == {"by": ASHA, "at": LATER}, "fail closed: the share is already withdrawn"
    rig.writer = good
    rig.now = "2026-10-12T09:00:00.000Z"
    assert _delete(rig).status_code == 200
    [record] = rig.shares()
    assert record["revoked"]["at"] == LATER  # the retry never restamps
    assert [e["data"]["state"] for e in rig.events_of(WORLD, "world.share_changed")] == ["on", "off"]


def test_BQ_CTX_TEAMWORLD_FR_TEAM_01_an_unwired_people_store_is_503_and_writes_nothing(rig):
    rig.people_error = HTTPException(status_code=503, detail="not_configured")
    for call in (_put, _delete):
        assert call(rig).status_code == 503
    assert rig.events_of(WORLD, "world.share_changed") == []


def test_BQ_CTX_TEAMWORLD_FR_TEAM_01_the_sample_project_cannot_be_shared(rig):
    got = rig.client.put("/worlds/w_sample_village_basic/team-shares/tm_launch")
    assert got.status_code == 409 and got.json() == {"detail": "sample_is_a_replay"}
    assert rig.shares() == []
