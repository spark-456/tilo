"""FR-MTR-10 / BQ-MTR10-4 (ticket T3, SEC-16): a settled live unit is also one Treasury ledger entry.

`SpendMeter` settles each unit on the uid spend ledger (INR minor units, GOLIVE-935). With a Treasury writer wired
(`deps.get_ledger_writer`) it now also records what it settled as ONE `commit` entry (`spend_units.LedgerSink`), so the
Ledger shows live cost. Pinned:

* the entry is exactly what the cap ledger settled (minor units / 8,000 per US$ / `credit_usd`), on the run the meter
  names, for the uid, with the profile and tokens the provider reported; nothing is re-priced;
* an unpriced call records the whole reserve, a unit that reached no model records nothing;
* the write is idempotent per unit id, and a write that fails (store down, bad entry, price sheet unreadable) never
  undoes the settled spend, never raises into the request and leaves one ERROR marker (`treasury_ledger_write_failed`,
  the error type only, never its text);
* on the API: a live intake writes one entry per settled unit for the signed-in uid, a task's units land on the task's
  own run id (so they are on its world's report), and a failing writer changes nothing about the answer;
* the report: unattributed live spend of the person is one pseudo run on `GET /costs`, never on a world.
"""

from __future__ import annotations

import logging
import math
from datetime import UTC, date, datetime
from typing import Any

import pytest
import test_SEC_16_GOLIVE_935_metering as metering_tests
from _sec15_lib import REPO_ROOT
from _sec16_lib import JUDGE_A, ORG, make_caps, make_ledger
from test_SEC_16_api_spend_cap import BIG_LIMIT
from test_SEC_16_GOLIVE_935_metering import UNIT, FakeRouter, Screen, attempt
from tilo_api.spend_units import INR_MINOR_PER_USD
from tilo_metering import LedgerEntry

wired_rig = metering_tests.wired  # the deployed harness of the metering suite, as a fixture of this module

CREDIT_USD = 0.005
MINOR_PER_USD = INR_MINOR_PER_USD  # BQ-GOLIVE935-4/-7: every expected amount below follows the product's rate


def settled_minor_of(tokens_in: int, tokens_out: int, profile: str = "flash-38") -> int:
    """What the cap ledger must settle for one billed call: the profile's price x the rate, rounded up, at least 1."""
    from tilo_providers.config import load_providers_config

    config = load_providers_config(REPO_ROOT / "config" / "models.yaml", REPO_ROOT / "config" / "prices.yaml")
    return max(1, math.ceil(config.cost_usd(profile, tokens_in, tokens_out, at=date.today()) * MINOR_PER_USD))


ONE_UNIT = settled_minor_of(1_000, 500)  # the director call of 1,000 tokens in and 500 out used by these tests


def credits_of(minor: int) -> float:
    return minor / MINOR_PER_USD / CREDIT_USD


class Book:
    """A Treasury writer that remembers: `append_once` keyed, plus an optional failure."""

    def __init__(self, fail: BaseException | None = None) -> None:
        self.entries: list[LedgerEntry] = []
        self.ids: dict[str, LedgerEntry] = {}
        self.fail = fail

    def append(self, entry: LedgerEntry) -> None:
        if self.fail:
            raise self.fail
        self.entries.append(entry)

    def append_once(self, entry_id: str, entry: LedgerEntry) -> None:
        if self.fail:
            raise self.fail
        if entry_id not in self.ids:
            self.ids[entry_id] = entry
            self.entries.append(entry)


def meter_with(ledger: Any, writer: Any, *, run: str = "r_unit", credit_usd: Any = lambda: CREDIT_USD) -> Any:
    from tilo_api.spend import SpendGuard
    from tilo_api.spend_units import LedgerSink, SpendMeter
    from tilo_metering.flags import InMemoryFlagStore
    from tilo_providers.config import load_providers_config

    caps = make_caps(**BIG_LIMIT)
    config = load_providers_config(REPO_ROOT / "config" / "models.yaml", REPO_ROOT / "config" / "prices.yaml")
    sink = LedgerSink(writer, uid=JUDGE_A, org_id=ORG, run_id=run, credit_usd=credit_usd)
    guard = SpendGuard(ledger, InMemoryFlagStore(), caps)
    return SpendMeter(
        guard, uid=JUDGE_A, run_id=run, org_id=ORG, unit_minor=caps.unit_reserve_minor, config=config, sink=sink
    )


def routed(ledger: Any, writer: Any, *, raw: Any = None, attempts: Any = None, **kw: Any) -> Any:
    from tilo_api.spend_units import MeteredRouter

    return MeteredRouter(raw or FakeRouter(ledger, attempts=attempts), meter_with(ledger, writer, **kw))


# --- one settled unit, one entry -------------------------------------------------------------------------------


def test_FR_MTR_10_BQ_MTR10_4_T3_a_settled_unit_is_one_entry_for_exactly_what_the_cap_ledger_settled():
    ledger, book = make_ledger(**BIG_LIMIT), Book()
    routed(ledger, book, attempts=[attempt(tokens_in=1_000, tokens_out=500)]).generate("director", object())

    assert ledger.settled_minor(JUDGE_A) == ONE_UNIT
    (entry,) = book.entries
    assert (entry.kind, entry.run, entry.user, entry.org) == ("commit", "r_unit", JUDGE_A, ORG)
    assert entry.credits == pytest.approx(credits_of(ONE_UNIT)) and entry.at.tzinfo is not None
    assert (entry.usage.profile, entry.usage.tokens_in, entry.usage.tokens_out) == ("flash-38", 1_000, 500)
    assert entry.step == "model"


def test_FR_MTR_10_BQ_MTR10_4_T3_an_unpriced_call_records_the_whole_reserve_and_a_released_unit_nothing():
    from tilo_providers.router import RouterError

    ledger, book = make_ledger(**BIG_LIMIT), Book()
    routed(ledger, book, attempts=[attempt()]).generate("director", object())  # billed, no usage reported
    assert [e.credits for e in book.entries] == [pytest.approx(credits_of(UNIT))]
    assert book.entries[0].usage is None

    failing = FakeRouter(ledger, fail=RouterError("down", [attempt(outcome="error", error_type="QuotaError")]))
    with pytest.raises(RouterError):
        routed(ledger, book, raw=failing).generate("director", object())
    assert len(book.entries) == 1, "nothing reached a model: the hold was released and nothing is recorded"


def test_FR_MTR_10_BQ_MTR10_4_T3_a_billed_failure_and_a_safety_check_are_entries_too():
    from tilo_api.spend_units import MeteredSafety
    from tilo_providers.router import RouterError

    ledger, book = make_ledger(**BIG_LIMIT), Book()
    bad = RouterError("bad reply", [attempt(outcome="schema_invalid", tokens_in=1_000, tokens_out=500)])
    with pytest.raises(RouterError):
        routed(ledger, book, raw=FakeRouter(ledger, fail=bad)).generate("director", object())
    MeteredSafety(Screen(ledger), meter_with(ledger, book)).check("a" * 3_000)  # type: ignore[arg-type]

    assert [(e.step, round(e.credits, 6)) for e in book.entries] == [
        ("model", round(credits_of(ONE_UNIT), 6)),
        ("safety", round(credits_of(1), 6)),
    ]
    assert sum(e.credits for e in book.entries) == pytest.approx(credits_of(ledger.settled_minor(JUDGE_A)))


def test_FR_MTR_10_BQ_MTR10_4_T3_the_entry_id_is_the_unit_so_a_retried_record_counts_once():
    from tilo_api.spend_units import LedgerSink

    book = Book()
    sink = LedgerSink(book, uid=JUDGE_A, org_id=ORG, run_id="r_x", credit_usd=lambda: CREDIT_USD)
    for _ in range(2):
        sink.record("abc", 24, "model", None)
    sink.record("def", 24, "model", None)
    assert sorted(book.ids) == ["unit_abc", "unit_def"] and len(book.entries) == 2


def test_FR_MTR_10_BQ_MTR10_4_T3_a_writer_with_only_append_still_records():
    class AppendOnly:
        def __init__(self) -> None:
            self.rows: list[LedgerEntry] = []

        def append(self, entry: LedgerEntry) -> None:
            self.rows.append(entry)

    ledger, writer = make_ledger(**BIG_LIMIT), AppendOnly()
    routed(ledger, writer, attempts=[attempt(tokens_in=10, tokens_out=10)]).generate("director", object())
    assert len(writer.rows) == 1


# --- a failed ledger write never touches the spend --------------------------------------------------------------


@pytest.mark.parametrize("what", ["store", "price_sheet"])
def test_FR_MTR_10_BQ_MTR10_4_T3_a_failed_ledger_write_keeps_the_settled_spend_and_the_answer(what, caplog):
    from fastapi import HTTPException

    ledger = make_ledger(**BIG_LIMIT)
    book = Book(fail=RuntimeError("secret detail the log must not carry") if what == "store" else None)

    def sheet() -> float:
        raise HTTPException(status_code=503, detail="not_configured")

    extra = {"credit_usd": sheet} if what == "price_sheet" else {}
    router = routed(ledger, book, attempts=[attempt(tokens_in=1_000, tokens_out=500)], **extra)
    with caplog.at_level(logging.ERROR):
        result = router.generate("director", object())

    assert result is not None, "the call's answer is untouched"
    assert ledger.settled_minor(JUDGE_A) == ledger.spent_minor(JUDGE_A) == ONE_UNIT, "the settle stands"
    assert book.entries == []
    assert "treasury_ledger_write_failed" in caplog.text and "secret detail" not in caplog.text


# --- on the API ------------------------------------------------------------------------------------------------


def test_FR_MTR_10_BQ_MTR10_4_T3_a_live_intake_writes_one_entry_per_settled_unit_for_the_signed_in_uid(wired_rig):
    from tilo_api import app, deps

    h, book = wired_rig.h, Book()
    app.dependency_overrides[deps.get_ledger_writer] = lambda: book

    assert h.intake().status_code == 201
    settled = h.ledger.settled_minor(JUDGE_A)

    assert book.entries
    assert {e.user for e in book.entries} == {JUDGE_A} and {e.org for e in book.entries} == {deps.ORG_ID}
    assert all(e.run.startswith("req_") for e in book.entries), "an intake has no task yet: its own request id"
    assert sum(e.credits for e in book.entries) == pytest.approx(credits_of(settled))
    assert len(book.ids) == len(book.entries), "one id per settled unit"


def test_FR_MTR_10_BQ_MTR10_4_T3_a_tasks_units_are_on_the_tasks_own_run_id(wired_rig):
    from tilo_api import app, deps

    h, book = wired_rig.h, Book()
    app.dependency_overrides[deps.get_ledger_writer] = lambda: book
    task = h.intake().json()
    book.entries.clear()

    assert h.client.get(f"/tasks/{task['task_id']}/approaches").status_code == 200

    run_id = h.store.tasks[task["task_id"]].run_id
    assert book.entries and {e.run for e in book.entries} == {run_id}


def test_FR_MTR_10_BQ_MTR10_4_T3_a_failing_writer_changes_nothing_about_the_request(wired_rig, caplog):
    from tilo_api import app, deps

    h = wired_rig.h
    app.dependency_overrides[deps.get_ledger_writer] = lambda: Book(fail=ConnectionError("firestore down"))
    with caplog.at_level(logging.ERROR):
        assert h.intake().status_code == 201
    assert h.ledger.spent_minor(JUDGE_A) == h.ledger.settled_minor(JUDGE_A) > 0
    assert "treasury_ledger_write_failed" in caplog.text and "firestore down" not in caplog.text


def test_FR_MTR_10_BQ_MTR10_4_T3_only_the_owners_task_or_world_names_the_run_an_entry_lands_on():
    from _api_lib import make_world
    from fastapi import FastAPI
    from starlette.requests import Request
    from tilo_api import deps

    store = deps.Store()
    store.worlds["w_mine"] = make_world(owner=JUDGE_A, run_id="r_mine")
    store.tasks["t_mine"] = deps.TaskRecord(
        owner=JUDGE_A, world_id="w_mine", run_id="r_mine", draft={}, brief={}, questions=[], next_seq=1
    )
    app = FastAPI()
    app.dependency_overrides[deps.get_store] = lambda: store
    book = Book()

    def run_of(uid: str, params: dict, meter_run: str) -> str:
        scope = {"type": "http", "app": app, "headers": [], "path_params": params, "query_string": b""}
        book.entries.clear()
        book.ids.clear()
        app.dependency_overrides[deps.get_ledger_writer] = lambda: book
        sink = deps._ledger_sink(Request(scope), uid, meter_run)
        sink.record("u1", 24, "model", None)
        return book.entries[0].run

    assert run_of(JUDGE_A, {"task_id": "t_mine"}, "task_t_mine") == "r_mine"
    assert run_of(JUDGE_A, {"world_id": "w_mine"}, "world_w_mine") == "r_mine"
    assert run_of("u_someone_else", {"task_id": "t_mine"}, "task_t_mine") == "task_t_mine", "not their task"
    assert run_of(JUDGE_A, {"task_id": "t_unknown"}, "task_t_unknown") == "task_t_unknown"
    assert run_of(JUDGE_A, {}, "req_abc") == "req_abc"


# --- the report ------------------------------------------------------------------------------------------------


def test_FR_MTR_10_BQ_MTR10_4_T3_unattributed_live_spend_is_one_pseudo_run_on_costs_and_never_a_world():
    from _api_lib import make_world
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from tilo_api import deps
    from tilo_api.costs import router

    def row(run: str, credits: float, user: str = "u_owner") -> LedgerEntry:
        return LedgerEntry("commit", run, user, ORG, datetime(2026, 10, 13, tzinfo=UTC), step="model", credits=credits)

    entries = [
        row("r_x", 1.0),
        row("req_aaa", 2.0),
        row("req_bbb", 4.0),
        row("task_t1", 8.0),
        row("req_other", 99.0, "u_other"),
    ]
    app = FastAPI()
    app.include_router(router)
    store = deps.Store()
    store.worlds["w_x"] = make_world(owner="u_owner", run_id="r_x")
    principal = deps.Principal(user_id="u_owner", role="owner", world_id="w_x", full_session=True)
    app.dependency_overrides[deps.get_current_principal] = lambda: principal
    app.dependency_overrides[deps.get_store] = lambda: store
    app.dependency_overrides[deps.get_ledger] = lambda: entries
    client = TestClient(app)

    world = client.get("/worlds/w_x/costs").json()
    assert world["totals"]["credits"] == pytest.approx(1.0) and [t["run_id"] for t in world["tasks"]] == ["r_x"]
    everything = client.get("/costs").json()
    assert everything["totals"]["credits"] == pytest.approx(15.0), "the world's 1 and the person's own 14 unattributed"
    live = [t for t in everything["tasks"] if t["run_id"].startswith("r_live_")]
    assert [t["credits"] for t in live] == [pytest.approx(14.0)]
    assert [r["task_type"] for r in everything["by_task_type"] if r["credits"] == pytest.approx(14.0)] == ["live_call"]
