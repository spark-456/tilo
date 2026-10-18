"""FT-SUP-5: SIGTERM gives live runs a grace period, then records a plain failure before writers close."""

from __future__ import annotations

import threading
from types import SimpleNamespace

from tilo_api import durable_store, runs


class FakeRun:
    def __init__(self, *, ended: bool = False) -> None:
        self._ended = threading.Event()
        if ended:
            self._ended.set()
        self.failures: list[tuple[str, None]] = []

    def fail_for_shutdown(self) -> None:
        self.failures.append((runs.SHUTDOWN_REASON, None))


def test_FT_SUP_5_drain_marks_only_runs_that_do_not_finish_within_the_grace() -> None:
    finished, running = FakeRun(ended=True), FakeRun()
    store = SimpleNamespace(runs={"w_finished": finished, "w_running": running})

    runs.drain_for_shutdown([store], timeout_s=0)

    assert finished.failures == []
    assert running.failures == [(runs.SHUTDOWN_REASON, None)]


def test_FT_SUP_5_close_drains_before_releasing_writer_leases(monkeypatch) -> None:
    order: list[str] = []
    store = SimpleNamespace(runs={})
    writer = SimpleNamespace(reopen=lambda _budget: order.append("writers closed"))
    monkeypatch.setattr(durable_store, "_opened", {("deployed",): (store, writer)})
    monkeypatch.setattr(runs, "drain_for_shutdown", lambda stores, timeout_s: order.append("runs drained"))

    durable_store.close_deployed()

    assert order == ["runs drained", "writers closed"]


def test_FT_SUP_5_shutdown_failure_stops_late_daemon_writes(monkeypatch) -> None:
    run = object.__new__(runs.Run)
    run.world_id = "w_shutdown"
    run.store = SimpleNamespace(events={run.world_id: []})
    run._shutting_down = threading.Event()
    failures: list[tuple[str, None]] = []
    monkeypatch.setattr(run, "_fail", lambda reason, unit: failures.append((reason, unit)))

    run.fail_for_shutdown()

    assert failures == [(runs.SHUTDOWN_REASON, None)]
    assert run._shutting_down.is_set()
