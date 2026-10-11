"""Owner-only join read: a sent receipt, one Calendar read, no bot or model launch."""

import pytest
from _clint2_lib import wait_for
from _mtg09b_lib import MEETING, OWNER, PLANTED_LINK, SAM, HostRig, block_network
from _ppl11c_lib import gone_meeting
from tilo_contracts import MeetingJoin


@pytest.fixture
def hosted(people_rig, monkeypatch):
    block_network(monkeypatch)
    h = HostRig(people_rig())
    h.approve_and_wait_sent()
    wait_for(lambda: h.events("artifact.created"), what="host receipt")
    h.rig.as_user(OWNER)
    return h


def join(h, meeting_id=MEETING):
    return h.rig.client.get(f"/v1/meetings/{meeting_id}/join")


def test_FR_MTG_09_JOIN_b_owner_reads_link_without_events_or_runs(hosted, caplog):
    before = len(hosted.events())
    response = join(hosted)
    assert response.status_code == 200
    assert MeetingJoin.model_validate(response.json()).join_url == PLANTED_LINK
    assert response.headers["cache-control"] == "no-store"
    assert len(hosted.events()) == before
    assert PLANTED_LINK not in caplog.text
    assert hosted.calendar.requests[-1]["params"] == {"fields": "status,hangoutLink"}


def test_FR_MTG_09_JOIN_b_same_404_for_stranger_and_missing(hosted):
    before = len(hosted.calendar.requests)
    hosted.rig.as_user(SAM)
    stranger = join(hosted)
    hosted.rig.as_user(OWNER)
    missing = join(hosted, "mt_missing")
    assert stranger.status_code == missing.status_code == 404
    assert stranger.content == missing.content
    assert len(hosted.calendar.requests) == before


def test_FR_MTG_09_JOIN_b_no_receipt_never_calls_google(hosted):
    hosted.store.events.clear()
    before = len(hosted.calendar.requests)
    assert join(hosted).status_code == 409
    assert len(hosted.calendar.requests) == before


def test_FR_MTG_09_JOIN_b_eleventh_read_is_limited_before_google(hosted):
    for _ in range(10):
        assert join(hosted).status_code == 200
    before = len(hosted.calendar.requests)
    response = join(hosted)
    assert response.status_code == 429
    assert 1 <= int(response.headers["retry-after"]) <= 60
    assert len(hosted.calendar.requests) == before


def test_FR_MTG_09_JOIN_b_deleted_meeting_is_hidden_without_calendar_read(hosted):
    stored = hosted.rig.stored("meetings", MEETING)
    hosted.rig.real.meetings.replace(gone_meeting(stored, "deleted"), expected_version=1)
    before = len(hosted.calendar.requests)
    assert join(hosted).status_code == 404
    assert len(hosted.calendar.requests) == before


def test_FR_MTG_09_JOIN_b_wrong_world_owner_is_hidden(hosted):
    from dataclasses import replace

    from _mtg09b_lib import WORLD

    hosted.store.worlds[WORLD] = replace(hosted.store.worlds[WORLD], owner=SAM)
    before = len(hosted.calendar.requests)
    assert join(hosted).status_code == 404
    assert len(hosted.calendar.requests) == before


def test_FR_MTG_09_JOIN_b_disconnected_host_is_fixed_conflict(hosted):
    hosted.broker.connected = False
    response = join(hosted)
    assert response.status_code == 409
    assert response.json()["detail"] == "host_not_connected"


def test_FR_MTG_09_JOIN_b_hostile_calendar_link_is_never_echoed(hosted, caplog):
    for event in hosted.calendar.events.values():
        event["hangoutLink"] = PLANTED_LINK + "?extra=yes"
    response = join(hosted)
    assert response.status_code == 409
    assert response.json()["detail"] == "no_join_link"
    assert "meet.google.com" not in response.text + caplog.text
