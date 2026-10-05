"""NFR-27 (docs/prd-supplement-2026-10-05.md, user 5 Oct): owner cost alerts.

Requirement: "Owner alerts at 80% and 100% of a uid's cap and above a global daily threshold (alert-only),
through a redacted structured log wired to a Cloud Monitoring email alert."
Acceptance: "Fake ledger crossing each threshold writes one redacted alert log line; no personal data in it."
Related: SEC-16 (1,000 INR lifetime spend cap per uid), NFR-23 (spend-threshold alerts), NFR-24 (the existing
`Alert`s of the daily USD soft/hard caps are a different, older mechanism and are not changed here), SEC-14 /
FR-MEM-05 (no secrets in logs), NFR-26 (structured logs).

The Terraform half (log-based metric, alert policy, email channel) is in
`tests/repo/test_NFR_27_cost_alert_terraform.py`.

Where the implementation goes: new module `packages/metering/src/tilo_metering/cost_alerts.py` (export `CostAlerts` and
`COST_ALERT_EVENT` from `tilo_metering`), plus an optional `cost_alerts=` keyword on `Treasury.__init__` that calls
`cost_alerts.check(ledger)` after every commit.

Public interface pinned by these tests:

    CostAlerts(uid_cap_credits=1000, daily_usd_threshold=5, credit_usd=0.005, sink=<callable taking one str line>)
    CostAlerts.check(ledger: Iterable[LedgerEntry]) -> tuple[dict, ...]   # the alerts newly raised by this call
    COST_ALERT_EVENT == "cost_alert"

`check` recomputes every total from the ledger passed in (it never adds the entries to a running total), so
re-checking the same ledger is idempotent. Only `commit` entries count, as in Treasury's own day totals.

Ambiguities resolved (the PRD does not say; defaults chosen here, for the builder to log in docs/open-questions.md):
  * Units: the per-uid cap (SEC-16 says 1,000 INR) and the ledger are both measured in credits here, so the constructor
    takes `uid_cap_credits`. Turning 1,000 INR into credits is configuration, not this class's business. The global
    daily threshold is in USD, like `spend.daily_usd_soft` (PRD 14.1), converted with `credit_usd`.
  * Exactly at the threshold counts as crossed (>=), as Treasury's own spend alerts do.
  * The per-uid window is lifetime (SEC-16 is a lifetime cap): one 80% line and one 100% line per uid, ever. The global
    window is the UTC day of the commit's reservation (BQ-44), so one line per day.
  * A single commit that jumps over both 80% and 100% writes both lines (80% first).
  * Redaction (PRD 16.1 "secrets never enter logs", supplement NFR-27 "no personal data"): the line carries `uid_ref`, a
    stable one-way digest of the uid (hex), never the uid itself; no run, org, step, email, token or message text.
  * Severity: WARNING for `uid_cap_80` and `global_daily`, ERROR for `uid_cap_100`.
"""

from __future__ import annotations

import json
import re
import socket
from datetime import UTC, date, datetime, timedelta

import pytest
from _metering_testlib import PRICES_V1, metering_config, write_yaml
from hypothesis import given, settings
from hypothesis import strategies as st
from tilo_metering import InMemoryFlagStore, LedgerEntry, MeteringConfig, PriceBook, Reservation, Treasury

AT = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
DAY = AT.date()
UID_CAP = 1000  # credits; 80% = 800, 100% = 1000
DAILY_USD = 5  # = 1000 credits at credit_usd 0.005
HUGE = 10**9


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """No network and no paid call: a connect attempt anywhere in these tests is a failure."""

    def refuse(*_args, **_kwargs):
        raise AssertionError("NFR-27 tests must not open a network connection")

    monkeypatch.setattr(socket.socket, "connect", refuse)


def _alerts(**overrides):
    from tilo_metering import CostAlerts  # missing until NFR-27 is implemented

    lines: list[str] = []
    kwargs = {"uid_cap_credits": UID_CAP, "daily_usd_threshold": HUGE, "credit_usd": 0.005, "sink": lines.append}
    kwargs.update(overrides)
    return CostAlerts(**kwargs), lines


def _commit(user: str, credits: float, *, day: date = DAY, run: str = "r1", org: str = "org1", step: str = "s1"):
    at = datetime(day.year, day.month, day.day, 12, tzinfo=UTC)
    return LedgerEntry("commit", run, user, org, at, step, credits, day=day)


def _parsed(lines: list[str]) -> list[dict]:
    return [json.loads(line) for line in lines]


def _kinds(lines: list[str]) -> list[str]:
    return [p["kind"] for p in _parsed(lines)]


# --- thresholds: per-uid cap ----------------------------------------------------------------------------------------


def test_NFR_27_event_name_constant_is_stable():
    from tilo_metering import COST_ALERT_EVENT

    assert COST_ALERT_EVENT == "cost_alert"


def test_NFR_27_just_below_80_percent_of_uid_cap_writes_nothing():
    alerts, lines = _alerts()
    ledger = [_commit("u1", 799)]
    assert alerts.check(ledger) == ()
    assert lines == []


def test_NFR_27_exactly_80_percent_of_uid_cap_writes_one_line():
    alerts, lines = _alerts()
    ledger = [_commit("u1", 799)]
    alerts.check(ledger)
    ledger.append(_commit("u1", 1))  # 800 = exactly 80%
    raised = alerts.check(ledger)
    assert _kinds(lines) == ["uid_cap_80"]
    assert len(raised) == 1
    line = _parsed(lines)[0]
    assert line["threshold_pct"] == 80
    assert line["spent_credits"] == 800
    assert line["cap_credits"] == UID_CAP


def test_NFR_27_exactly_100_percent_of_uid_cap_writes_a_second_line_once():
    alerts, lines = _alerts()
    ledger = [_commit("u1", 800)]
    alerts.check(ledger)
    ledger.append(_commit("u1", 199))  # 999: still only the 80% line
    alerts.check(ledger)
    assert _kinds(lines) == ["uid_cap_80"]
    ledger.append(_commit("u1", 1))  # 1000 = exactly 100%
    alerts.check(ledger)
    assert _kinds(lines) == ["uid_cap_80", "uid_cap_100"]
    assert _parsed(lines)[1]["threshold_pct"] == 100


def test_NFR_27_one_commit_jumping_over_both_thresholds_writes_both_lines_in_order():
    alerts, lines = _alerts()
    alerts.check([_commit("u1", 1200)])
    assert _kinds(lines) == ["uid_cap_80", "uid_cap_100"]


def test_NFR_27_uid_cap_is_lifetime_across_days_and_runs():
    alerts, lines = _alerts()
    ledger = [_commit("u1", 500, day=DAY, run="r1"), _commit("u1", 299, day=DAY + timedelta(days=1), run="r2")]
    alerts.check(ledger)
    assert lines == []
    ledger.append(_commit("u1", 1, day=DAY + timedelta(days=9), run="r3"))
    alerts.check(ledger)
    assert _kinds(lines) == ["uid_cap_80"]


def test_NFR_27_each_uid_is_counted_and_alerted_on_its_own():
    alerts, lines = _alerts()
    alerts.check([_commit("u1", 500), _commit("u2", 500)])  # 1000 together, 500 each
    assert lines == []
    alerts.check([_commit("u1", 500), _commit("u2", 500), _commit("u2", 300)])  # u2 at 800
    parsed = _parsed(lines)
    assert [p["kind"] for p in parsed] == ["uid_cap_80"]


def test_NFR_27_two_uids_get_different_uid_refs_and_one_uid_keeps_the_same_ref():
    alerts, lines = _alerts()
    alerts.check([_commit("u1", 1000), _commit("u2", 800)])
    parsed = _parsed(lines)
    refs = {(p["kind"], p["uid_ref"]) for p in parsed}
    u1_80 = next(p["uid_ref"] for p in parsed if p["kind"] == "uid_cap_80" and p["spent_credits"] == 1000)
    u1_100 = next(p["uid_ref"] for p in parsed if p["kind"] == "uid_cap_100")
    u2_80 = next(p["uid_ref"] for p in parsed if p["kind"] == "uid_cap_80" and p["spent_credits"] == 800)
    assert len(refs) == 3
    assert u1_80 == u1_100  # the owner can correlate one uid's two alerts
    assert u1_80 != u2_80


# --- once per window, idempotent, never repeated ---------------------------------------------------------------------


def test_NFR_27_calls_after_the_cap_do_not_repeat_the_alert():
    alerts, lines = _alerts()
    ledger = [_commit("u1", 1000)]
    alerts.check(ledger)
    assert len(lines) == 2
    for _ in range(25):  # more spend and more calls: still nothing new
        ledger.append(_commit("u1", 40))
        assert alerts.check(ledger) == ()
    assert len(lines) == 2


def test_NFR_27_replaying_the_same_ledger_is_idempotent():
    alerts, lines = _alerts(daily_usd_threshold=DAILY_USD)
    ledger = [_commit("u1", 1000)]
    alerts.check(ledger)
    first = list(lines)
    assert len(first) == 3  # uid 80, uid 100, global daily
    for _ in range(5):
        assert alerts.check(list(ledger)) == ()
        assert alerts.check(ledger[:1]) == ()
    assert lines == first


# --- thresholds: global daily -----------------------------------------------------------------------------------------


def test_NFR_27_global_daily_below_threshold_writes_nothing():
    alerts, lines = _alerts(uid_cap_credits=HUGE, daily_usd_threshold=DAILY_USD)
    assert alerts.check([_commit("u1", 600), _commit("u2", 399)]) == ()  # 999 credits = US$4.995
    assert lines == []


def test_NFR_27_global_daily_crossing_across_uids_writes_one_line_with_usd_figures():
    alerts, lines = _alerts(uid_cap_credits=HUGE, daily_usd_threshold=DAILY_USD)
    ledger = [_commit("u1", 600), _commit("u2", 400)]  # 1000 credits = exactly US$5
    alerts.check(ledger)
    parsed = _parsed(lines)
    assert [p["kind"] for p in parsed] == ["global_daily"]
    assert parsed[0]["day"] == DAY.isoformat()
    assert parsed[0]["spent_usd"] == pytest.approx(5.0)
    assert parsed[0]["threshold_usd"] == pytest.approx(5.0)
    assert "uid_ref" not in parsed[0]  # a global alert names nobody
    ledger.append(_commit("u3", 700))
    assert alerts.check(ledger) == ()
    assert len(lines) == 1


def test_NFR_27_global_daily_alert_is_once_per_utc_day_and_rearms_next_day():
    alerts, lines = _alerts(uid_cap_credits=HUGE, daily_usd_threshold=DAILY_USD)
    ledger = [_commit("u1", 1000, day=DAY)]
    alerts.check(ledger)
    ledger.append(_commit("u1", 999, day=DAY + timedelta(days=1)))  # below on day 2
    alerts.check(ledger)
    assert len(lines) == 1
    ledger.append(_commit("u2", 1, day=DAY + timedelta(days=1)))  # 1000 on day 2
    alerts.check(ledger)
    days = [p["day"] for p in _parsed(lines)]
    assert days == [DAY.isoformat(), (DAY + timedelta(days=1)).isoformat()]


def test_NFR_27_global_daily_counts_commits_on_their_reservation_day_not_wall_clock():
    alerts, lines = _alerts(uid_cap_credits=HUGE, daily_usd_threshold=DAILY_USD)
    late = datetime(2026, 10, 6, 0, 0, 30, tzinfo=UTC)  # committed just after midnight
    entry = LedgerEntry("commit", "r1", "u1", "o", late, "s1", 1000, day=DAY)  # but reserved on the 5th
    alerts.check([entry])
    assert [p["day"] for p in _parsed(lines)] == [DAY.isoformat()]


def test_NFR_27_only_commit_entries_count_as_spend():
    alerts, lines = _alerts(daily_usd_threshold=DAILY_USD)
    ledger = [
        LedgerEntry("reserve", "r1", "u1", "o", AT, "s1", 5000, day=None),
        LedgerEntry("release", "r1", "u1", "o", AT, "s1"),
        LedgerEntry("grant", "r1", "u1", "o", AT, credits=5000),
        LedgerEntry("usage", "r1", "u1", "o", AT),
        LedgerEntry("commit", "r1", "u1", "o", AT, "s2", None, day=DAY),  # unpriced commit: no credits
    ]
    assert alerts.check(ledger) == ()
    assert lines == []


# --- the log line: structured JSON, stable names, redacted ------------------------------------------------------------

_SEVERITY = {"uid_cap_80": "WARNING", "global_daily": "WARNING", "uid_cap_100": "ERROR"}
_ALLOWED_KEYS = {
    "severity", "event", "kind", "message", "uid_ref", "threshold_pct", "spent_credits", "cap_credits",
    "day", "spent_usd", "threshold_usd", "timestamp", "time",
}  # fmt: skip


def _all_three_lines() -> list[str]:
    alerts, lines = _alerts(daily_usd_threshold=DAILY_USD)
    alerts.check([_commit("u1", 1000)])
    assert len(lines) == 3
    return lines


def test_NFR_27_each_line_is_one_json_object_with_stable_event_and_severity():
    for line in _all_three_lines():
        assert "\n" not in line.strip()  # one line per alert, so Cloud Logging reads it as one entry
        record = json.loads(line)
        assert isinstance(record, dict)
        assert record["event"] == "cost_alert"
        assert record["severity"] == _SEVERITY[record["kind"]]
        assert isinstance(record["message"], str) and record["message"]


def test_NFR_27_line_keys_are_an_allowlist():
    for line in _all_three_lines():
        extra = set(json.loads(line)) - _ALLOWED_KEYS
        assert not extra, f"NFR-27: unexpected keys in the alert line (allowlist only): {sorted(extra)}"


_SECRETISH = [
    "ya29." + "A" * 30,  # a Google OAuth access token shape, assembled at runtime
    "Bearer " + "x" * 24,
    "sk-" + "b" * 32,
    "alice" + "@" + "example.com",
]


@pytest.mark.parametrize("uid", _SECRETISH + ["uid-1234567890abcdef", "firebase|user|42"])
def test_NFR_27_raw_uid_and_ledger_identifiers_never_appear_in_the_line(uid):
    alerts, lines = _alerts(daily_usd_threshold=DAILY_USD)
    entry = LedgerEntry("commit", "run-" + "R" * 8, uid, "org-" + "O" * 8, AT, "step-" + "S" * 8, 1000, day=DAY)
    alerts.check([entry])
    assert len(lines) == 3
    for line in lines:
        assert uid not in line
        for needle in ("R" * 8, "O" * 8, "S" * 8):  # run, org, step ids stay out
            assert needle not in line
        for fragment in ("ya29", "Bearer", "sk-", "@"):
            assert fragment not in line, f"NFR-27: {fragment!r} must not appear in an alert line"
        assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", line)  # no email address of any shape
    refs = [p["uid_ref"] for p in _parsed(lines) if "uid_ref" in p]
    assert len(refs) == 2
    for ref in refs:
        assert re.fullmatch(r"[0-9a-f]{8,64}", ref), "uid_ref is a hex digest, not the uid"


def test_NFR_27_alert_line_holds_no_free_text_from_the_ledger():
    alerts, lines = _alerts()
    marker = "SECRET-BODY-" + "z" * 12  # stands for an email body or prompt text smuggled into a field
    entry = LedgerEntry("commit", marker, "u1", marker, AT, marker, 1000, day=DAY)
    alerts.check([entry])
    assert lines and all(marker not in line for line in lines)


def test_NFR_27_default_sink_writes_one_json_line_per_alert_to_stdout(capsys):
    from tilo_metering import CostAlerts

    CostAlerts(uid_cap_credits=UID_CAP, daily_usd_threshold=HUGE, credit_usd=0.005).check([_commit("u1", 1000)])
    out = capsys.readouterr().out
    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert [json.loads(ln)["kind"] for ln in lines] == ["uid_cap_80", "uid_cap_100"]  # Cloud Run reads stdout JSON


# --- alert-only: never raises, never blocks ---------------------------------------------------------------------------


def test_NFR_27_a_failing_sink_never_raises_into_the_caller():
    def broken(_line: str) -> None:
        raise RuntimeError("log pipe closed")

    alerts, _ = _alerts(sink=broken)
    alerts.check([_commit("u1", 1000)])  # must not raise


def test_NFR_27_malformed_ledger_entries_never_raise():
    alerts, _ = _alerts()
    junk = [
        None,
        object(),
        "commit",
        {"kind": "commit"},
        LedgerEntry("commit", "r", "u", "o", AT, "s", float("nan"), day=DAY),
    ]
    alerts.check(junk)  # an alert path must not be the thing that breaks a call
    alerts.check([_commit("u1", 1000)])  # and still works afterwards


def test_NFR_27_a_sink_that_failed_does_not_lose_the_alert_for_good():
    # alert-only does not mean silent: a failed write is retried on the next check, not marked as sent.
    calls: list[str] = []

    def flaky(line: str) -> None:
        calls.append(line)
        if len(calls) == 1:
            raise OSError("temporary")

    alerts, lines = _alerts(sink=flaky)
    ledger = [_commit("u1", 800)]
    alerts.check(ledger)  # first write fails
    alerts.check(ledger)  # next check tries again
    assert len(calls) == 2 and json.loads(calls[1])["kind"] == "uid_cap_80"
    alerts.check(ledger)  # delivered now: no third write
    assert len(calls) == 2


# --- through Treasury: alert-only, nothing is blocked or changed ------------------------------------------------------


def _treasury(tmp_path, *, cost_alerts):
    book = PriceBook.load(write_yaml(tmp_path, "prices.yaml", PRICES_V1))
    doc = metering_config(run_credits=HUGE, user_day_credits=HUGE, daily_usd_soft=HUGE - 1, daily_usd_hard=HUGE)
    config = MeteringConfig.load(write_yaml(tmp_path, "metering.yaml", doc))
    flags = InMemoryFlagStore()
    return Treasury(config=config, prices=book, flags=flags, cost_alerts=cost_alerts), flags


def _spend(treasury: Treasury, run: str, step: str, credits: float):
    reservation = treasury.reserve(run, step, estimate=credits, at=AT)
    assert isinstance(reservation, Reservation), f"reserve returned {reservation!r}"
    return treasury.commit(reservation, actual=credits, at=AT)


def test_NFR_27_treasury_commits_cross_each_threshold_and_write_one_line_each(tmp_path):
    alerts, lines = _alerts(daily_usd_threshold=DAILY_USD)
    treasury, _flags = _treasury(tmp_path, cost_alerts=alerts)
    treasury.open_run("r1", user_id="u1", org_id="o1", approved=HUGE)
    _spend(treasury, "r1", "s1", 799)
    assert lines == []
    _spend(treasury, "r1", "s2", 1)
    assert _kinds(lines) == ["uid_cap_80"]
    _spend(treasury, "r1", "s3", 200)  # 1000: uid 100% and the global daily US$5
    assert sorted(_kinds(lines)) == ["global_daily", "uid_cap_100", "uid_cap_80"]
    for step in range(4, 9):
        _spend(treasury, "r1", f"s{step}", 50)
    assert len(lines) == 3  # not repeated on every call


def test_NFR_27_alerts_never_block_or_change_treasury_behaviour(tmp_path):
    alerts, _lines = _alerts()
    treasury, flags = _treasury(tmp_path, cost_alerts=alerts)
    treasury.open_run("r1", user_id="u1", org_id="o1", approved=HUGE)
    result = _spend(treasury, "r1", "s1", 1500)  # 150% of the uid cap
    assert result.overrun is False
    assert result.alerts == ()  # the NFR-24 soft/hard Alert list is untouched by NFR-27 lines
    again = treasury.reserve("r1", "s2", estimate=10, at=AT)
    assert isinstance(again, Reservation), "alert-only: past 100% of the uid cap a reservation is still granted"
    assert flags.get("replay_only") is False
    assert treasury.run("r1").halted is False


def test_NFR_27_a_failing_alert_sink_cannot_break_commit(tmp_path):
    def broken(_line: str) -> None:
        raise RuntimeError("log pipe closed")

    alerts, _ = _alerts(sink=broken)
    treasury, _flags = _treasury(tmp_path, cost_alerts=alerts)
    treasury.open_run("r1", user_id="u1", org_id="o1", approved=HUGE)
    _spend(treasury, "r1", "s1", 1000)  # must not raise
    assert [e.kind for e in treasury.ledger].count("commit") == 1  # the commit is still on the ledger
    assert treasury.run("r1").spent == 1000


def test_NFR_27_treasury_without_cost_alerts_still_works(tmp_path):
    book = PriceBook.load(write_yaml(tmp_path, "prices.yaml", PRICES_V1))
    config = MeteringConfig.load(write_yaml(tmp_path, "metering.yaml", metering_config()))
    treasury = Treasury(config=config, prices=book, flags=InMemoryFlagStore())  # the old call shape stays valid
    treasury.open_run("r1", user_id="u1", org_id="o1", approved=100)
    reservation = treasury.reserve("r1", "s1", estimate=10, at=AT)
    assert isinstance(reservation, Reservation)


# --- property: invariants over any spend sequence ---------------------------------------------------------------------

_spend_steps = st.lists(
    st.tuples(st.sampled_from(["a", "b", "c"]), st.integers(0, 2), st.integers(1, 600)), min_size=0, max_size=40
)


@settings(max_examples=150, deadline=None)
@given(steps=_spend_steps)
def test_NFR_27_property_one_line_per_threshold_per_window_and_replay_is_silent(steps):
    alerts, lines = _alerts(daily_usd_threshold=DAILY_USD)
    ledger: list[LedgerEntry] = []
    for i, (uid, day_offset, credits) in enumerate(steps):
        ledger.append(_commit(uid, credits, day=DAY + timedelta(days=day_offset), step=f"s{i}"))
        alerts.check(ledger)

    parsed = _parsed(lines)
    for uid in "abc":
        total = sum(e.credits for e in ledger if e.user == uid)
        kinds = [p["kind"] for p in parsed if p.get("uid_ref") == _ref_of(uid)]
        assert len(set(kinds)) == len(kinds), "one line per threshold per uid"
        assert ("uid_cap_80" in kinds) == (total >= 0.8 * UID_CAP)
        assert ("uid_cap_100" in kinds) == (total >= UID_CAP)
    for offset in range(3):
        day = DAY + timedelta(days=offset)
        day_total = sum(e.credits for e in ledger if e.day == day)
        got = [p for p in parsed if p["kind"] == "global_daily" and p["day"] == day.isoformat()]
        assert len(got) == (1 if day_total * 0.005 >= DAILY_USD - 1e-9 else 0)
    for p in parsed:
        assert set(p) <= _ALLOWED_KEYS
        assert p["event"] == "cost_alert" and p["severity"] == _SEVERITY[p["kind"]]

    before = list(lines)
    assert alerts.check(ledger) == ()  # replaying the whole ledger writes nothing
    assert lines == before


def _ref_of(uid: str) -> str:
    """The uid_ref of a uid, learned from a fresh alerter: it must be stable for one uid."""
    probe, probe_lines = _alerts()
    probe.check([_commit(uid, 1000)])
    return json.loads(probe_lines[0])["uid_ref"]
