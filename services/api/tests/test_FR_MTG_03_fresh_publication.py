"""Fresh server clock and source checks at provider return and final publication (offline)."""

import pytest
from _ppl11a_lib import SAM
from _ppl11c_lib import artifact_paths
from test_FR_MTG_03_analysis_publication import integration  # noqa: F401
from test_FR_MTG_03_owner_analysis_mode import owner_call  # noqa: F401
from test_FR_MTG_03_owner_minutes_caller import call, caller_app  # noqa: F401
from tilo_people.errors import VersionConflict


def change_source(c, change):
    stored = c.rig.real.meetings.get(c.rig.org, "mt_q4_plan")
    if change == "expiry":
        c.writer.now = stored.record["delete_transcript_after"]
    elif change == "owner":
        c.rig.event_store.worlds[c.scope.world_id].owner = SAM
    elif change == "run":
        c.rig.event_store.worlds[c.scope.world_id].run_id = "r_rival_run"
    elif change == "erasure":
        for record in c.rig.artifacts.retention().records():
            if stored.record["transcript"]["artifact_id"] in record.record_id:
                c.rig.artifacts._purge(record.record_id)
    elif change == "meeting_owner":
        c.rig.real.meetings.replace({**stored.record, "owner": SAM}, expected_version=stored.version)
    else:
        c.rig.real.meetings.replace({**stored.record, "title": "Rival write"}, expected_version=stored.version)


@pytest.mark.parametrize("boundary", ["provider", "staging"])
@pytest.mark.parametrize("change", ["expiry", "owner", "run", "erasure", "meeting_owner", "version"])
def test_FR_MTG_03_04_fresh_source_refused_without_publication(caller_app, monkeypatch, boundary, change):  # noqa: F811
    c = caller_app
    monkeypatch.delenv("LIVE", raising=False)
    c.app.dependency_overrides[c.budget_seam] = lambda: 2
    if boundary == "provider":
        c.router.during = lambda: change_source(c, change)
    else:
        put = c.rig.artifacts.put

        def stage(*args, **kwargs):
            made = put(*args, **kwargs)
            change_source(c, change)
            return made

        monkeypatch.setattr(c.rig.artifacts, "put", stage)
    response = call(c)
    assert response.status_code in (404, 409)
    assert c.rig.stored("meetings", "mt_q4_plan")["minutes"] is None
    assert not c.rig.events.calls
    assert not any("art_integrated_minutes" in path for path in artifact_paths(c.rig))


def test_FR_MTG_03_final_replace_remains_cas_and_purges_staged_minutes(caller_app, monkeypatch):  # noqa: F811
    c = caller_app
    c.app.dependency_overrides[c.budget_seam] = lambda: 2
    replace = c.rig.real.meetings.replace

    def rival(after, *, expected_version):
        stored = c.rig.real.meetings.get(c.rig.org, after["id"])
        assert expected_version == stored.version
        replace({**stored.record, "title": "Concurrent commit"}, expected_version=stored.version)
        raise VersionConflict()

    monkeypatch.setattr(c.rig.real.meetings, "replace", rival)
    assert call(c).status_code == 409
    assert c.rig.stored("meetings", "mt_q4_plan")["minutes"] is None
    assert not c.rig.events.calls
    assert not any("art_integrated_minutes" in path for path in artifact_paths(c.rig))


def test_FR_MTG_03_stable_source_publishes_one_unconfirmed_minutes(caller_app):  # noqa: F811
    c = caller_app
    c.app.dependency_overrides[c.budget_seam] = lambda: 2
    response = call(c)
    assert response.status_code == 200
    assert response.json()["minutes_confirmed_by"] is None
    assert len(c.rig.event_store.events[c.scope.world_id]) == 1
    assert call(c).status_code == 409
    assert len(c.rig.event_store.events[c.scope.world_id]) == 1


@pytest.mark.parametrize("change", ["artifact_expiry", "screening", "artifact_run"])
def test_FR_MTG_04_changed_artifact_metadata_refuses_at_provider_return(caller_app, monkeypatch, change):  # noqa: F811
    c = caller_app
    c.app.dependency_overrides[c.budget_seam] = lambda: 2
    original = c.rig.artifacts.head
    changed = False

    def head(scope, ref):
        result = original(scope, ref)
        if changed and result is not None:
            if change == "artifact_expiry":
                result.doc["created_at"] = "2025-01-01T00:00:00.000Z"
            elif change == "screening":
                result.doc["screening"] = "flagged"
            else:
                result.doc["run_id"] = "r_rival_run"
        return result

    def during():
        nonlocal changed
        changed = True

    monkeypatch.setattr(c.rig.artifacts, "head", head)
    c.router.during = during
    assert call(c).status_code == 409
    assert c.rig.stored("meetings", "mt_q4_plan")["minutes"] is None
    assert not c.rig.events.calls
    assert not any("art_integrated_minutes" in path for path in artifact_paths(c.rig))
