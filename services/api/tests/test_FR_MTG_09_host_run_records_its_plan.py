"""FR-MTG-09: a hosted meeting's fixed plan is recorded (`world.planned`) like any run's; the run no longer hands the
base class an empty approach, which made the best-effort plan record raise KeyError on every meeting run."""

from __future__ import annotations

import pytest
from _mtg09b_lib import HostRig, block_network


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    block_network(monkeypatch)


@pytest.fixture()
def hr(people_rig):
    return HostRig(people_rig())


def test_FR_MTG_09_a_hosted_meeting_run_records_world_planned_without_a_caught_error(hr, caplog):
    assert hr.host().status_code == 200
    hr.wait_gate()
    planned = hr.events("world.planned")
    assert len(planned) == 1
    assert planned[0]["data"]["approach"] == "invite"
    assert planned[0]["data"]["credits"] == {"min": 0, "max": 0}
    assert not [r for r in caplog.records if "KeyError" in r.getMessage()]
