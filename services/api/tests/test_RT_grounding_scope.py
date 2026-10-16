"""RT-02, RT-03, RT-07: the stores' read rules decide every hit, at query time (ADR-0049; ADR-0040/0044 team rules).
Real people oracle, shares and artifact store; a fake embedder; no network."""

from __future__ import annotations

import pytest
from _rt_lib import ORG, GroundingRig, team_pin
from _tsw1_lib import ASHA, BEN, CARA, LATER, LAUNCH, WORLD, person, share
from tilo_api import app

PLAN = "launch plan budget schedule"


@pytest.fixture
def rig():
    yield GroundingRig()
    app.dependency_overrides.clear()


def test_RT_03_a_team_deliverable_reaches_a_member_only_while_the_share_is_in_force(rig):
    rig.deliver(PLAN)
    assert rig.grounding.index_deliverables(WORLD) == 1
    assert [h.text for h in rig.search(ASHA, "launch plan")] == [PLAN]  # the owner reads her own
    assert rig.search(BEN, "launch plan") == []  # no share: a teammate has nothing
    rig.grant()
    rig.grounding.index_deliverables(WORLD)  # the next run end re-scopes the chunk to the team
    assert [h.text for h in rig.search(BEN, "launch plan")] == [PLAN]
    assert rig.search(CARA, "launch plan") == []  # another team never
    stored = rig.people.world_shares.list(ORG)[0]
    rig.people.world_shares.replace(
        {**stored.record, "revoked": {"by": ASHA, "at": LATER}}, expected_version=stored.version
    )
    assert rig.search(BEN, "launch plan") == []  # revoked: refused at the very next query, before any sweep
    assert len(rig.search(ASHA, "launch plan")) == 1
    assert rig.grounding.sweep() == 1  # and the sweep deletes the team chunk
    assert list(rig.backend.scan(ORG)) == []


def test_RT_03_a_removed_member_is_refused_at_once(rig):
    rig.deliver(PLAN)
    rig.grant()
    rig.grounding.index_deliverables(WORLD)
    assert len(rig.search(BEN, "launch plan")) == 1
    ben = rig.people.persons.get(ORG, BEN)
    rig.people.persons.replace({**ben.record, "memberships": []}, expected_version=ben.version)
    assert rig.search(BEN, "launch plan") == []


def test_RT_03_a_pin_made_personal_or_removed_is_refused_and_swept(rig):
    rig.people.pins.create(team_pin())
    rig.grounding.index_pin(rig.people.pins.get(ORG, "pb_launch").record)
    assert [h.source["id"] for h in rig.search(BEN, "launch checklist")] == ["pb_launch"]
    pin = rig.people.pins.get(ORG, "pb_launch")
    rig.people.pins.replace({**pin.record, "scope": {"kind": "personal", "user": ASHA}}, expected_version=pin.version)
    assert rig.search(BEN, "launch checklist") == []  # the team chunk no longer matches the pin's scope
    assert rig.grounding.sweep() == 1
    rig.grounding.index_pin(rig.people.pins.get(ORG, "pb_launch").record)  # the next write re-indexes it as hers
    assert rig.search(BEN, "launch checklist") == [] and len(rig.search(ASHA, "launch checklist")) == 1


def test_RT_07_a_removed_pin_and_a_deleted_world_take_their_chunks_with_them(rig):
    rig.people.pins.create(team_pin(team=None))
    rig.grounding.index_pin(rig.people.pins.get(ORG, "pb_launch").record)
    pin = rig.people.pins.get(ORG, "pb_launch")
    rig.people.pins.replace({**pin.record, "status": "removed"}, expected_version=pin.version)
    rig.grounding.index_pin(rig.people.pins.get(ORG, "pb_launch").record)
    assert list(rig.backend.scan(ORG)) == []
    rig.deliver(PLAN)
    rig.grounding.index_deliverables(WORLD)
    del rig.store.worlds[WORLD]
    assert rig.search(ASHA, "launch plan") == [] and rig.grounding.sweep() == 1


def test_RT_01_only_clean_run_outputs_are_indexed_not_uploads_or_flagged_pins(rig):
    rig.deliver("an uploaded transcript like text", origin="upload")
    rig.grounding.index_deliverables(WORLD)
    pin = team_pin(team=None) | {"flagged": True}
    rig.people.pins.create(pin)
    rig.grounding.index_pin(pin)
    assert list(rig.backend.scan(ORG)) == []


def test_RT_03_another_orgs_person_is_never_a_caller(rig):
    rig.people.persons.create(person("u_zed", org="org_elsewhere"))
    rig.deliver(PLAN)
    rig.grounding.index_deliverables(WORLD)
    rig.grant(by=ASHA)
    assert rig.grounding.store.search(ORG, ASHA, "launch")[0].source["id"].startswith("art_")
    from tilo_memory.chunks import ChunkError

    with pytest.raises(ChunkError):
        rig.grounding.store.search(ORG, "u_zed", "launch")  # not a person of this org
    assert share()["team"] == LAUNCH
