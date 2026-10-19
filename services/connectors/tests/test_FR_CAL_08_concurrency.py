"""FR-CAL-08: two syncs of one person commit once. API_FR_CAL_08.md "Hostile cases: Concurrency", "run_due"
(the non-blocking per-user lock, `busy`), "Commit" (compare-and-set, `superseded`), "register, forget".

Threads, fakes and Events only (no sleeps, no network); every wait has a timeout so a deadlock in the code
under test fails the test instead of hanging it. Every test fails today with ModuleNotFoundError:
tilo_connectors.calendar_sync (or .calendar_cache, .adapters.calendar).
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta

from _calendar_lib import PRIYA, make_cal_env, make_conn, make_entry, make_state, outcome_for

OPEN = "2026-10-07T03:30:00.000Z"  # 09:00 in Asia/Kolkata
BASE = datetime(2026, 10, 8, 4, 0, tzinfo=UTC)
WAIT = 20


def _only(outcomes):
    return outcome_for(outcomes, PRIYA)


def _events(ce, n=2):
    for k in range(n):
        ce.cal.add_event(PRIYA, f"evt{k}", f"Event {k}", BASE + timedelta(days=k), BASE + timedelta(days=k, hours=1))


def _in_thread(target, *args):
    box: dict = {}

    def run():
        try:
            box["result"] = target(*args)
        except BaseException as exc:  # noqa: BLE001 - surfaced by the test
            box["error"] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread, box


def _join(thread, box):
    thread.join(WAIT)
    assert not thread.is_alive(), "the run did not finish: a deadlock or a lost wake-up"
    assert "error" not in box, repr(box.get("error"))
    return box["result"]


def test_FR_CAL_08_while_one_run_is_blocked_on_page_one_another_run_due_returns_busy_with_zero_requests():
    ce = make_cal_env(start=OPEN)
    _events(ce)
    entered, release = ce.cal.block_on_request(1)
    thread, box = _in_thread(ce.run)
    try:
        assert entered.wait(WAIT), "the first run reached the fake"

        busy = _only(ce.run())

        assert (busy.status, busy.reason, busy.requests) == ("skipped", "busy", 0)
        assert (busy.kind, busy.changed, busy.screened, busy.skipped, busy.emitted) == (None, 0, 0, 0, False)
        assert len(ce.cal.requests) == 1, "the busy run sent nothing"
    finally:
        release.set()
    first = _only(_join(thread, box))

    assert first.status == "synced" and first.kind == "full" and first.changed == 2
    assert len(ce.calendar_parts()) == 1


def test_FR_CAL_08_two_instances_on_one_store_both_fetch_exactly_one_commits_and_emits():
    ce = make_cal_env(start=OPEN)
    _events(ce)
    second = ce.new_sync()
    entered, release = ce.cal.block_on_request(1)
    thread, box = _in_thread(ce.sync.run_due)  # instance A: blocked on its first request
    try:
        assert entered.wait(WAIT)

        winner = _only(second.run_due())  # instance B: runs to completion first
    finally:
        release.set()
    loser = _only(_join(thread, box))

    assert (winner.status, winner.kind, winner.changed, winner.emitted) == ("synced", "full", 2, True)
    assert (loser.status, loser.reason, loser.emitted, loser.changed) == ("aborted", "superseded", False, 0)
    assert len(ce.cal.requests_of(PRIYA)) == 2, "both fetched"
    assert len(ce.calendar_parts()) == 1, "exactly one event"
    state = ce.state()
    assert state.generation == 1 and len(ce.store.entries(PRIYA)) == 2
    assert ce.calendar_parts()[0]["key"] == f"{state.connection.connection_id}:1"


def test_FR_CAL_08_three_overlapping_instances_commit_once():
    ce = make_cal_env(start=OPEN)
    _events(ce, 3)
    instances = [ce.sync, ce.new_sync(), ce.new_sync()]
    ce.cal.rendezvous(3)  # every request waits until all three runs have sent theirs
    runs = [_in_thread(i.run_due) for i in instances]

    outcomes = [_only(_join(t, b)) for t, b in runs]

    assert sorted((o.status, o.reason) for o in outcomes) == [("aborted", "superseded")] * 2 + [("synced", None)]
    assert len(ce.cal.requests_of(PRIYA)) == 3
    assert len(ce.calendar_parts()) == 1 and ce.state().generation == 1
    assert sum(o.emitted for o in outcomes) == 1


def test_FR_CAL_08_forget_while_a_run_is_blocked_ends_the_run_superseded_with_an_empty_cache_and_no_event():
    ce = make_cal_env(start=OPEN)
    _events(ce)
    entered, release = ce.cal.block_on_request(1)
    thread, box = _in_thread(ce.run)
    try:
        assert entered.wait(WAIT)
        forgetter, fbox = _in_thread(ce.sync.forget, PRIYA)
        _join(forgetter, fbox)  # forget does not wait for the run
    finally:
        release.set()
    out = _only(_join(thread, box))

    assert (out.status, out.reason, out.emitted) == ("aborted", "superseded", False)
    assert ce.store.get(PRIYA) is None
    assert ce.store.entries(PRIYA) == (), "nothing the run fetched was written back"
    assert ce.parts == []


def test_FR_CAL_08_property_of_the_store_n_writers_from_one_state_exactly_one_wins():
    from tilo_connectors.calendar_cache import InMemoryCalendarStore

    store = InMemoryCalendarStore()
    conn = make_conn()
    base = store.add(make_state(conn))
    writers = 8
    barrier = threading.Barrier(writers)
    results: list[bool] = []
    lock = threading.Lock()

    def write(n):
        barrier.wait(WAIT)
        ok = store.commit(
            base, make_state(conn, generation=1), upserts=[make_entry(conn, f"w{n}", title=f"Writer {n}")], removals=[]
        )
        with lock:
            results.append(ok)

    threads = [threading.Thread(target=write, args=(n,), daemon=True) for n in range(writers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(WAIT)

    assert sorted(results) == [False] * (writers - 1) + [True]
    assert len(store.entries(PRIYA)) == 1 and store.get(PRIYA).generation == 1
