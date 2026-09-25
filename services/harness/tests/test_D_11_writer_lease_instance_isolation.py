"""D-11 fix round: pins two bugs the code, security and qa-breaker reviewers all named in the
same shape -- the single-writer lease was only ever compared by the caller-supplied `writer_id`
label, and `_commit` never re-checked the store's actual head before writing.

1. Two `WorldWriter`s constructed with the *same* `writer_id` string (exactly the qa-breaker
   repro: two processes deriving `writer_id` from the same `--run` both pass `open()` with no
   `WriterBusy`, then both write seq 1). `writer_id` is only a human label; lease ownership must
   be checked against something unique per `WorldWriter` instance, or a second live instance
   slips through and both writers' commits land, corrupting the stream.
2. Even a writer that genuinely still holds a live, correctly-tokened lease must have its commit
   refused when the store's own head has moved past what that writer's local state expects --
   belt-and-suspenders so a write can never overwrite or skip a seq/vseq the store already has.
"""

from __future__ import annotations

import pytest
from conftest import FakeClock, world_requested_kwargs


def _same_id_writers(village_basic_layout: dict, clock: FakeClock, lease_s: float = 30.0):
    from tilo_harness.store import MemoryStore
    from tilo_harness.writer import WorldWriter

    store = MemoryStore()

    def make() -> object:
        return WorldWriter(
            store,
            org_id="org_demo",
            world_id="w_village_basic",
            run_id="r_test_1",
            layout=village_basic_layout,
            writer_id="skeleton_r_test_1",  # deliberately identical on both instances
            lease_s=lease_s,
            clock=clock,
        )

    return store, make(), make()


def test_D_11_second_writer_with_the_same_writer_id_string_still_gets_WriterBusy(
    village_basic_layout, fake_clock
) -> None:
    """qa-breaker repro 1: `writer_id` alone must never be enough to prove lease ownership."""
    from tilo_harness.writer import WriterBusy

    store, a, b = _same_id_writers(village_basic_layout, fake_clock)
    a.open()
    a.emit(**world_requested_kwargs())

    with pytest.raises(WriterBusy):
        b.open()

    assert [e["seq"] for e in store.read_events("org_demo", "w_village_basic")] == [1], (
        "D-11: a second WorldWriter instance sharing writer_id must not be able to open a live lease"
    )


def test_D_11_two_writers_sharing_writer_id_never_produce_duplicate_or_conflicting_seqs(
    village_basic_layout, fake_clock
) -> None:
    """qa-breaker repro 1, full shape: even if b.open() is attempted anyway (a caller ignoring
    the WriterBusy), b must never manage to write a conflicting seq 1 alongside a's."""
    from tilo_harness.writer import WriterBusy

    store, a, b = _same_id_writers(village_basic_layout, fake_clock)
    a.open()
    a.emit(**world_requested_kwargs())

    with pytest.raises(WriterBusy):
        b.open()
    with pytest.raises(WriterBusy):
        b.emit(**world_requested_kwargs())  # b never held a lease; its own commit must also refuse

    stored = store.read_events("org_demo", "w_village_basic")
    assert [e["seq"] for e in stored] == [1]
    assert len({e["seq"] for e in stored}) == len(stored), "D-11: seqs in the stream must be unique"


def test_D_11_commit_rejects_a_write_when_the_stores_head_has_moved_past_local_state(
    village_basic_layout, fake_clock
) -> None:
    """Defense in depth on top of the lease check itself: even a writer holding a live,
    correctly-tokened lease must not write when the store's actual last_seq disagrees with what
    this writer's local state expects."""
    from tilo_harness.store import MemoryStore
    from tilo_harness.writer import WorldWriter, WriterBusy

    store = MemoryStore()
    writer = WorldWriter(
        store,
        org_id="org_demo",
        world_id="w_village_basic",
        run_id="r_test_1",
        layout=village_basic_layout,
        writer_id="writer_1",
        lease_s=30.0,
        clock=fake_clock,
    )
    writer.open()

    # Simulate the store's head having moved on independently of this writer's local WorldState
    # (e.g. a write that landed through some other path), while leaving the lease this writer
    # holds untouched -- the lease check alone would let the next write through.
    def _advance_head_only(head):
        return dict(head, last_seq=head["last_seq"] + 1), None, []

    store.transact("org_demo", "w_village_basic", _advance_head_only)

    with pytest.raises(WriterBusy):
        writer.emit(**world_requested_kwargs())

    assert store.read_events("org_demo", "w_village_basic") == [], (
        "D-11: a commit that disagrees with the store's head must write nothing"
    )
