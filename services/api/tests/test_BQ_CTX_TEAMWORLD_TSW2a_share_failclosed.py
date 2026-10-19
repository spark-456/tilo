"""BQ-CTX-TEAMWORLD, TSW-2a fail-closed follow-ups F1 to F3 of SEC-REVIEW-13 (issue #927) on
`PUT /worlds/{world_id}/team-shares/{team}`. Security-flagged: these decide who may open a world to a team.

F1 a lapsed standing grant (the owner left the team and came back) is replaced by a fresh stamp;
F2 an idempotent re-PUT whose event append fails never deletes the standing share (it retries the event only);
F3 an event failure whose compensating delete also fails ends revoked, never a live share with no event.
"""

from __future__ import annotations

import pytest
from _api_lib import FlakyEventWriter
from _tsw1_lib import ASHA, LAUNCH, NOW, T_GRANT, WORLD, Rig

BEFORE_MEMBERSHIP = "2026-09-30T09:00:00.000Z"  # earlier than Asha's membership (T_MEMBER), so the grant has lapsed


@pytest.fixture()
def rig() -> Rig:
    return Rig()


def _put(rig: Rig):
    return rig.client.put(f"/worlds/{WORLD}/team-shares/{LAUNCH}")


def test_BQ_CTX_TEAMWORLD_F1_a_lapsed_standing_grant_is_restamped_by_the_next_put(rig):
    rig.grant(at=BEFORE_MEMBERSHIP, by=ASHA)
    got = _put(rig)
    assert got.status_code == 200
    assert got.json()["in_force"] is True
    [record] = rig.shares()
    assert record["granted_by"] == {"by": ASHA, "at": NOW}
    assert record["revoked"] is None
    assert [e["data"]["state"] for e in rig.events_of(WORLD, "world.share_changed")] == ["on"]


def test_BQ_CTX_TEAMWORLD_F2_a_failed_event_on_a_standing_share_never_deletes_it(rig):
    rig.grant(at=T_GRANT, by=ASHA)
    rig.writer = FlakyEventWriter(rig.store, failing=True)
    got = _put(rig)
    assert got.status_code == 503
    [record] = rig.shares()
    assert record["granted_by"]["at"] == T_GRANT, "the standing share is untouched"
    assert record["revoked"] is None


def test_BQ_CTX_TEAMWORLD_F2_the_retry_writes_the_missing_event_and_never_restamps(rig):
    rig.grant(at=T_GRANT, by=ASHA)
    good = rig.writer
    rig.writer = FlakyEventWriter(rig.store, failing=True)
    assert _put(rig).status_code == 503
    rig.writer = good
    assert _put(rig).status_code == 200
    [record] = rig.shares()
    assert record["granted_by"]["at"] == T_GRANT
    assert [e["data"]["state"] for e in rig.events_of(WORLD, "world.share_changed")] == ["on"]


def test_BQ_CTX_TEAMWORLD_F3_a_failed_delete_is_retried_and_the_share_goes(rig, monkeypatch):
    rig.writer = FlakyEventWriter(rig.store, failing=True)
    real = rig.people.world_shares.delete
    calls = {"n": 0}

    def flaky_delete(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("store hiccup")
        return real(*args, **kwargs)

    monkeypatch.setattr(rig.people.world_shares, "delete", flaky_delete)
    assert _put(rig).status_code == 503
    assert rig.shares() == []
    assert calls["n"] == 2


def test_BQ_CTX_TEAMWORLD_F3_a_delete_that_keeps_failing_falls_back_to_a_revoke_stamp(rig, monkeypatch):
    rig.writer = FlakyEventWriter(rig.store, failing=True)

    def broken_delete(*args, **kwargs):
        raise RuntimeError("store down")

    monkeypatch.setattr(rig.people.world_shares, "delete", broken_delete)
    assert _put(rig).status_code == 503
    [record] = rig.shares()
    assert record["revoked"] == {"by": ASHA, "at": NOW}, "not a live share without its event: fail closed"
    assert rig.events_of(WORLD, "world.share_changed") == []
