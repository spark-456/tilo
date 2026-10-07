"""PPL-11c slice 6 (BQ-273): `check_write` lets a meeting's `world_id` go from absent to a world id, once, alone.

Every other `world_id` change stays `immutable` (`test_PPL_10c_write_checks.py` pins the rest of the meeting rows).
"""

from __future__ import annotations

import copy

import _ppl10_testlib as t
import pytest

WORLD = "w_meeting_q4_plan"


def _check(before, after, actor="u_owner"):
    return t.writes.check_write(t.req(actor, "edit", "meeting", before), after, t.world_directory())


def test_PPL_11c_BQ_273_a_world_id_may_be_added_once_to_a_meeting_that_has_none():
    before = t.meeting()
    assert "world_id" not in before
    assert _check(before, {**copy.deepcopy(before), "world_id": WORLD}) == ()


@pytest.mark.parametrize("actor", ["u_riya", "u_someone_else"])
def test_PPL_11c_BQ_273_only_the_owner_adds_it(actor):
    before = t.meeting()
    assert _check(before, {**copy.deepcopy(before), "world_id": WORLD}, actor) == ("not_allowed",)


def test_PPL_11c_BQ_273_the_world_id_never_moves_with_another_field():
    before = t.meeting()
    assert _check(before, {**copy.deepcopy(before), "world_id": WORLD, "title": "Other"}) == ("immutable",)


def test_PPL_11c_BQ_273_a_world_id_that_is_set_is_never_changed_or_removed():
    before = t.meeting(world_id=WORLD)
    assert _check(before, {**copy.deepcopy(before), "world_id": "w_other"}) == ("immutable",)
    without = copy.deepcopy(before)
    del without["world_id"]
    assert _check(before, without) == ("immutable",)


@pytest.mark.parametrize("world", ["https://evil.example/w", "mt_q4_plan", "w_", "w_bad id", 7, None])
def test_PPL_11c_BQ_273_a_value_that_is_not_a_world_id_is_a_schema_problem(world):
    before = t.meeting()
    assert _check(before, {**copy.deepcopy(before), "world_id": world}) == ("schema",)
