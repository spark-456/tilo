"""FR-AGT-14 SCHED_PLAN (issue #656, BQ-DEVH-2): a schedule snapshots the FULL offered approach list beside the chosen
one, so a scheduled run can compile a plan (contracts/plan.schema.json wants 2 to 3 approaches).

Store side: the optional `Schedule.approaches` survives the doc functions and both stores as a copy, and a document
written before the field existed still loads (as None)."""

from __future__ import annotations

import copy
from typing import Any

import pytest
from fr_agt_14_store_support import make_record, memory_rig
from tilo_harness.schedule_store import schedule_from_doc, schedule_to_doc

OFFERED = [
    {"id": "quick", "label": "Quick scan", "credits": {"min": 30, "max": 45}},
    {"id": "deep", "label": "Deep dive", "credits": {"min": 60, "max": 90}},
    {"id": "mid", "label": "Middle way", "credits": {"min": 40, "max": 60}},
]


def _with_offered(schedule_id: str = "sched_a") -> Any:
    return make_record(schedule_id, approach=copy.deepcopy(OFFERED[0]), approaches=copy.deepcopy(OFFERED))


def test_FR_AGT_14_SCHED_PLAN_the_doc_functions_round_trip_the_offered_list() -> None:
    schedule = _with_offered()
    doc = schedule_to_doc(schedule)
    assert doc["approaches"] == OFFERED
    assert schedule_from_doc(doc) == schedule


def test_FR_AGT_14_SCHED_PLAN_an_old_document_without_the_field_loads_as_none() -> None:
    doc = schedule_to_doc(make_record("sched_old"))
    doc.pop("approaches", None)  # written before this ticket
    assert schedule_from_doc(doc).approaches is None
    assert make_record("sched_old").approaches is None


@pytest.mark.parametrize("bad", ["quick", {"id": "quick"}, [["quick"]], [None]])
def test_FR_AGT_14_SCHED_PLAN_a_document_with_a_malformed_list_is_refused_by_the_doc_reader(bad: Any) -> None:
    doc = schedule_to_doc(_with_offered())
    doc["approaches"] = bad
    with pytest.raises(ValueError):
        schedule_from_doc(doc)


def test_FR_AGT_14_SCHED_PLAN_the_memory_store_round_trips_the_list_as_a_copy() -> None:
    rig = memory_rig()
    schedule = _with_offered()
    assert rig.store.create(schedule, max_per_owner=10) is True
    got = rig.store.get("sched_a")
    assert got.approaches == OFFERED
    got.approaches[0]["label"] = "changed after read"
    assert rig.store.get("sched_a").approaches == OFFERED
    schedule.approaches[1]["label"] = "changed after create"
    assert rig.store.get("sched_a").approaches == OFFERED
