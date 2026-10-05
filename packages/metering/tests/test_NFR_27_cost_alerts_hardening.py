"""NFR-27 follow-ups: constructor checks, poisoned entries, strict JSON, sink off the lock, one delivery each."""

from __future__ import annotations

import json
import threading
from datetime import UTC, date, datetime

import pytest
from tilo_metering import CostAlerts, LedgerEntry

DAY = date(2026, 10, 5)


def _commit(user: object, credits: object, *, run: str = "r1") -> LedgerEntry:
    at = datetime(2026, 10, 5, 12, tzinfo=UTC)
    return LedgerEntry("commit", run, user, "org1", at, "s1", credits, day=DAY)  # type: ignore[arg-type]


def _alerts(sink, **overrides) -> CostAlerts:
    kwargs = {"uid_cap_credits": 1000, "daily_usd_threshold": 10**9, "credit_usd": 0.005, "sink": sink}
    kwargs.update(overrides)
    return CostAlerts(**kwargs)


@pytest.mark.parametrize("field", ["uid_cap_credits", "daily_usd_threshold", "credit_usd"])
@pytest.mark.parametrize("bad", [float("nan"), float("inf"), 0, -1, True, "5", None])
def test_NFR_27_constructor_rejects_unusable_numbers(field, bad):
    with pytest.raises(ValueError, match=field):
        _alerts(list.append, **{field: bad})


def test_NFR_27_poisoned_entry_does_not_hide_a_crossing_by_the_others():
    good = _commit("u1", 900)
    no_day = LedgerEntry("commit", "r2", "u2", "org1", None, "s1", 5, day=None)  # type: ignore[arg-type]

    class BadStr:
        def __str__(self) -> str:
            raise RuntimeError("boom")

    bad_user = _commit(BadStr(), 5)
    for bad in (no_day, bad_user):
        lines: list[str] = []
        raised = _alerts(lines.append).check([bad, good])
        assert [r["kind"] for r in raised] == ["uid_cap_80"]
        assert len(lines) == 1


def test_NFR_27_output_is_strict_json_and_a_non_finite_figure_is_not_delivered():
    lines: list[str] = []
    alerts = _alerts(lines.append)
    alerts.check([_commit("u1", 1200)])
    for line in lines:
        json.loads(line, parse_constant=lambda c: pytest.fail(f"non-strict JSON constant {c}"))
    # a threshold that overflows to inf in the figures must be swallowed, not written as "Infinity"
    lines.clear()
    huge = _alerts(lines.append, daily_usd_threshold=1e-300, credit_usd=1e308)
    huge.check([_commit("u1", 1e300)])
    assert all("Infinity" not in line and "NaN" not in line for line in lines)


def test_NFR_27_a_failing_sink_is_retried_and_never_raises():
    calls: list[str] = []

    def flaky(line: str) -> None:
        calls.append(line)
        if len(calls) == 1:
            raise OSError("down")

    alerts = _alerts(flaky)
    ledger = [_commit("u1", 800)]
    assert alerts.check(ledger) == ()
    assert [r["kind"] for r in alerts.check(ledger)] == ["uid_cap_80"]
    assert alerts.check(ledger) == ()


def test_NFR_27_sink_runs_off_the_lock():
    entered, release = threading.Event(), threading.Event()
    seen: list[str] = []

    def slow(line: str) -> None:
        seen.append(line)
        entered.set()
        release.wait(5)

    alerts = _alerts(slow)
    worker = threading.Thread(target=alerts.check, args=([_commit("u1", 800)],))
    worker.start()
    assert entered.wait(5)
    try:
        done: list[object] = []
        other = threading.Thread(target=lambda: done.append(alerts.check([_commit("u2", 10)])))
        other.start()
        other.join(2)
        assert not other.is_alive(), "a slow sink must not block another caller's check"
        assert done == [()]
    finally:
        release.set()
        worker.join(5)


def test_NFR_27_concurrent_checks_deliver_each_alert_once():
    gate = threading.Barrier(2)
    lines: list[str] = []

    def sink(line: str) -> None:
        lines.append(line)

    alerts = _alerts(sink)
    ledger = [_commit("u1", 1000)]
    results: list[tuple[dict, ...]] = []

    def run() -> None:
        gate.wait(5)
        results.append(alerts.check(ledger))

    threads = [threading.Thread(target=run) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5)
    assert sorted(json.loads(line)["kind"] for line in lines) == ["uid_cap_100", "uid_cap_80"]
    assert sum(len(r) for r in results) == 2
