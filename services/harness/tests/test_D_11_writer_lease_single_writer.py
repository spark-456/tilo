"""D-11 "One writer per world" (PRD 22.2, 15.3): `WorldWriter` holds a lease on
`orgs/{org}/worlds/{world}` (writer id + expiry, from an injectable clock). A second writer for
the same world is refused while the lease is live, every write re-checks the lease so a writer
whose lease was taken over cannot write any more, and after a crash a new writer takes over once
the lease expires and continues at `last_seq + 1` without overwriting anything already stored.

P0-09 only promises a valid prefix and a clean takeover here; resuming the interrupted run from
checkpoints is FR-AGT-10, a later ticket (ticket brief item 6).
"""

from __future__ import annotations

import pytest
from conftest import FakeClock, world_requested_kwargs


def _writers(village_basic_layout: dict, clock: FakeClock, lease_s: float = 30.0):
    """Two WorldWriters for the same world, sharing one MemoryStore and one clock, so their
    lease expiries are checked against the same simulated wall time."""
    from tilo_harness.store import MemoryStore
    from tilo_harness.writer import WorldWriter

    store = MemoryStore()

    def make(writer_id: str) -> WorldWriter:
        return WorldWriter(
            store,
            org_id="org_demo",
            world_id="w_village_basic",
            run_id="r_test_1",
            layout=village_basic_layout,
            writer_id=writer_id,
            lease_s=lease_s,
            clock=clock,
        )

    return store, make("writer_1"), make("writer_2")


def test_D_11_second_writer_gets_WriterBusy_while_the_lease_is_live(village_basic_layout, fake_clock):
    from tilo_harness.writer import WriterBusy

    store, writer1, writer2 = _writers(village_basic_layout, fake_clock)
    writer1.open()
    writer1.emit(**world_requested_kwargs())

    with pytest.raises(WriterBusy):
        writer2.open()

    assert [e["seq"] for e in store.read_events("org_demo", "w_village_basic")] == [1]


def test_D_11_second_writer_takes_over_after_lease_expiry_and_continues_at_last_seq_plus_1(
    village_basic_layout, fake_clock
):
    store, writer1, writer2 = _writers(village_basic_layout, fake_clock, lease_s=30.0)
    writer1.open()
    writer1.emit(**world_requested_kwargs())  # writer1 "crashes" here, seq 1 is the last write

    fake_clock.advance(31.0)  # past writer1's 30s lease
    writer2.open()  # must succeed now: the lease has expired
    resumed = writer2.emit(**world_requested_kwargs())

    assert resumed["seq"] == 2, "D-11: takeover must continue at last_seq + 1 read from the store, not restart at 1"
    stored = store.read_events("org_demo", "w_village_basic")
    assert [e["seq"] for e in stored] == [1, 2]
    assert stored[0]["type"] == "world.requested", "D-11: takeover must never overwrite an existing event"


def test_D_11_writer_whose_lease_was_taken_over_cannot_write_any_more(village_basic_layout, fake_clock):
    from tilo_harness.writer import WriterBusy

    store, writer1, writer2 = _writers(village_basic_layout, fake_clock, lease_s=30.0)
    writer1.open()
    writer1.emit(**world_requested_kwargs())

    fake_clock.advance(31.0)
    writer2.open()  # takes over the world's lease

    with pytest.raises(WriterBusy):
        writer1.emit(**world_requested_kwargs())  # writer1 does not know it was superseded

    assert [e["seq"] for e in store.read_events("org_demo", "w_village_basic")] == [1], (
        "D-11: every write re-checks the lease inside the same transaction, so the superseded "
        "writer's attempted write must not land in the store"
    )


def test_D_11_second_writer_open_still_refused_just_before_lease_expiry(village_basic_layout, fake_clock):
    """Boundary check on the injectable clock: at t < lease_s the lease is still live."""
    from tilo_harness.writer import WriterBusy

    store, writer1, writer2 = _writers(village_basic_layout, fake_clock, lease_s=30.0)
    writer1.open()
    writer1.emit(**world_requested_kwargs())

    fake_clock.advance(29.0)  # one second before expiry
    with pytest.raises(WriterBusy):
        writer2.open()
    assert [e["seq"] for e in store.read_events("org_demo", "w_village_basic")] == [1]
