"""D-11 fix round 3 (qa-breaker repro): `WorldWriter._commit` only ever re-checked
`lease.token`, never `lease.expires_at` against the clock, and nothing renewed the lease on a
successful commit.

1. A writer whose lease has lapsed (no takeover has happened yet, so its token is still the one
   recorded on the head) must be refused with `WriterBusy` on its next commit -- the token check
   alone is not a real lease check.
2. A writer that keeps committing faster than `lease_s` must renew its own lease on every
   successful commit, so it never loses the world out from under itself purely for running
   longer than `lease_s`, and a second writer attempting `open()` while the first is still live
   (and renewing) must still get `WriterBusy` even after the first lease's original TTL would
   otherwise have elapsed.
"""

from __future__ import annotations

import pytest
from conftest import FakeClock, world_requested_kwargs


def _writer(store, village_basic_layout: dict, clock: FakeClock, *, writer_id: str, lease_s: float):
    from tilo_harness.writer import WorldWriter

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


def test_D_11_commit_refuses_once_this_writers_own_lease_has_expired(village_basic_layout, fake_clock) -> None:
    """qa-breaker repro 1: MemoryStore, WorldWriter(lease_s=10), open(), clock forward 3600s,
    emit() -- must raise WriterBusy, not write seq 1 with a head whose lease already expired
    3590s ago."""
    from tilo_harness.store import MemoryStore
    from tilo_harness.writer import WriterBusy

    store = MemoryStore()
    writer = _writer(store, village_basic_layout, fake_clock, writer_id="writer_1", lease_s=10.0)
    writer.open()

    fake_clock.advance(3600.0)

    with pytest.raises(WriterBusy):
        writer.emit(**world_requested_kwargs())

    assert store.read_events("org_demo", "w_village_basic") == [], (
        "D-11: a commit attempted after this writer's own lease has expired must write nothing"
    )


def test_D_11_successful_commits_renew_the_lease_so_a_live_writer_outlives_lease_s(
    village_basic_layout, fake_clock
) -> None:
    """A writer that commits every 1s with lease_s=2 must still be able to write at t=100 --
    each successful commit must have pushed `expires_at` forward, not left it frozen at
    `open()`'s `now + lease_s`."""
    from tilo_harness.store import MemoryStore

    store = MemoryStore()
    writer = _writer(store, village_basic_layout, fake_clock, writer_id="writer_1", lease_s=2.0)
    writer.open()

    for _ in range(100):
        writer.emit(**world_requested_kwargs())
        fake_clock.advance(1.0)  # well within lease_s=2, so the lease must never lapse

    stored = store.read_events("org_demo", "w_village_basic")
    assert [e["seq"] for e in stored] == list(range(1, 101)), (
        "D-11: a writer committing faster than lease_s must never be refused for its own expiry"
    )


def test_D_11_a_renewed_lease_still_blocks_a_second_writer_past_the_original_ttl(
    village_basic_layout, fake_clock
) -> None:
    """The other half of renewal: a second writer's `open()` must keep getting WriterBusy for as
    long as the first writer keeps renewing, even once wall time has passed the first lease's
    *original* expiry -- proof the renewal is real, not just a no-op that happens to not raise."""
    from tilo_harness.store import MemoryStore
    from tilo_harness.writer import WriterBusy

    store = MemoryStore()
    writer1 = _writer(store, village_basic_layout, fake_clock, writer_id="writer_1", lease_s=2.0)
    writer2 = _writer(store, village_basic_layout, fake_clock, writer_id="writer_2", lease_s=2.0)
    writer1.open()  # lease expires at t=2 unless renewed

    writer1.emit(**world_requested_kwargs())
    fake_clock.advance(1.0)  # t=1, lease renewed to t=3 by the commit above
    writer1.emit(**world_requested_kwargs())
    fake_clock.advance(1.0)  # t=2, past the *original* expiry -- but renewed again to t=4

    with pytest.raises(WriterBusy):
        writer2.open()

    assert [e["seq"] for e in store.read_events("org_demo", "w_village_basic")] == [1, 2]
