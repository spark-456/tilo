"""SEC-16 / GOLIVE-935 (BQ-SEC16-1, BQ-PW-3-1): the durable spend-cap ledger on Firestore and its wiring.

The `FirestoreSpendLedger` runs against `_adr35_l2_fake.OccFirestore` (a transaction aborts if a document it read
changed, as Firestore does) and, as an emulator-marked rig, over the real emulator (`TILO_FIRESTORE_EMULATOR_TESTS=1`
or `--outbox-emulator`, like the outbox store suite). What is pinned:

* the `SpendLedger` protocol's behaviour (the same cases `API_SEC_16.md` states for the in-memory ledger): exactly the
  cap passes, one over is refused, settled plus outstanding both count, an overrun is recorded in full, the global day
  trips the durable switch, a restart (a new object over the same documents) keeps every total and the switch;
* idempotency: a retried settle, release or reserve (same unit id) never counts twice;
* concurrency: many reserves race and the cap is never passed;
* documents are org-scoped under `orgs/{org}/spend_ledger`;
* fail closed: an unreadable store raises (so the guard denies live) and a malformed switch document reads as set;
* the `deps.get_spend_cap_ledger` seam: Firestore when deployed with a valid project, memory off Cloud Run, a 503
  (so replay, never uncapped) when Firestore cannot be built; and the API on it: live when allowed, replay for a
  capped uid, the kill switch or an unreadable ledger.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from typing import Any

import pytest
from _adr35_l2_fake import OccFirestore
from _sec16_lib import AT, JUDGE_A, JUDGE_B, ORG, OTHER_ORG, SpyLedger, make_caps
from test_SEC_16_api_spend_cap import BIG_LIMIT, assert_cap_refusal, declared, fill

ROOT = f"orgs/{ORG}/spend_ledger"


class Flaky(OccFirestore):
    """The store, with an outage switch: every document call raises while `broken`."""

    broken = False

    def document(self, path: str) -> Any:
        if self.broken:
            raise ConnectionError("firestore is unreachable")
        return super().document(path)


def make(db: Any = None, caps: Any = None, **overrides: Any) -> Any:
    from tilo_api.spend_firestore import FirestoreSpendLedger

    return FirestoreSpendLedger(db if db is not None else OccFirestore(), caps or make_caps(**overrides), org_id=ORG)


def reserve(ledger: Any, uid: str = JUDGE_A, minor: int = 100, **kw: Any) -> Any:
    kw = {"run_id": "r_1", "org_id": ORG, "at": AT, **kw}
    return ledger.reserve(uid=uid, amount_minor=minor, **kw)


def spend_once(ledger: Any, uid: str, minor: int, **kw: Any) -> None:
    held = reserve(ledger, uid, minor, **kw)
    assert not hasattr(held, "reason"), held
    ledger.settle(held, minor)


# --- the protocol's behaviour --------------------------------------------------------------------------------


def test_SEC_16_firestore_ledger_exactly_the_cap_passes_and_one_over_is_refused():
    ledger = make(uid_lifetime_minor=1_000)
    assert not hasattr(reserve(ledger, minor=1_000), "reason")
    refused = reserve(ledger, minor=1, run_id="r_2")
    assert refused.reason == "uid_lifetime"
    assert ledger.spent_minor(JUDGE_A) == 1_000


@pytest.mark.parametrize(
    ("caps", "reason"),
    [
        ({"run_minor": 150}, "run"),
        ({"org_day_minor": 150}, "org_day"),
        ({"global_day_hard_minor": 150}, "global_hard"),
    ],
)
def test_SEC_16_firestore_ledger_refuses_per_run_org_day_and_global_day_with_the_reason(caps, reason):
    ledger = make(**caps)
    assert not hasattr(reserve(ledger, minor=100), "reason")
    assert reserve(ledger, JUDGE_B, 100).reason == reason


def test_SEC_16_firestore_ledger_settle_records_the_actual_in_full_and_marks_an_overrun():
    ledger = make(uid_lifetime_minor=1_000)
    held = reserve(ledger, minor=100)
    assert ledger.spent_minor(JUDGE_A) == 100 and ledger.settled_minor(JUDGE_A) == 0
    assert ledger.settle(held, 250).overrun is True
    assert ledger.settled_minor(JUDGE_A) == ledger.spent_minor(JUDGE_A) == 250
    held = reserve(ledger, minor=100, run_id="r_2")
    assert ledger.settle(held, 40).overrun is False
    assert ledger.settled_minor(JUDGE_A) == 290


def test_SEC_16_firestore_ledger_release_returns_the_hold_and_a_bad_actual_changes_nothing():
    ledger = make()
    held = reserve(ledger, minor=100)
    with pytest.raises(TypeError):
        ledger.settle(held, 1.5)
    assert ledger.spent_minor(JUDGE_A) == 100, "the hold stays after a bad actual"
    ledger.release(held)
    assert ledger.spent_minor(JUDGE_A) == 0


def test_SEC_16_firestore_ledger_the_global_day_trips_the_durable_switch_once():
    ledger = make(global_day_hard_minor=300)
    spend_once(ledger, JUDGE_A, 300)
    assert ledger.replay_only() is True, "settling the day to its hard cap flips the switch"
    assert reserve(ledger, JUDGE_B, 1).reason == "replay_only"
    assert ledger.trip_replay_only("again") is False


def test_SEC_16_firestore_ledger_a_reserve_over_the_global_day_trips_the_switch():
    ledger = make(global_day_hard_minor=300)
    assert reserve(ledger, minor=400).reason == "global_hard"
    assert ledger.replay_only() is True


def test_SEC_16_firestore_ledger_only_a_named_human_reset_clears_the_switch():
    ledger = make()
    assert ledger.trip_replay_only("test") is True
    with pytest.raises((TypeError, ValueError)):
        ledger.reset_replay_only(by=" ")
    assert ledger.replay_only() is True
    ledger.reset_replay_only(by="owner")
    assert ledger.replay_only() is False
    assert not hasattr(reserve(ledger), "reason")


def test_SEC_16_firestore_ledger_a_restart_keeps_totals_holds_and_the_switch():
    db = OccFirestore()
    first = make(db)
    spend_once(first, JUDGE_A, 300)
    held = reserve(first, JUDGE_A, 100, run_id="r_2")
    first.trip_replay_only("test")

    second = make(db)  # a new process over the same documents
    assert second.settled_minor(JUDGE_A) == 300 and second.spent_minor(JUDGE_A) == 400
    assert second.replay_only() is True
    second.release(held)  # the hold made before the restart is still releasable
    assert second.spent_minor(JUDGE_A) == 300


def test_SEC_16_firestore_ledger_a_day_is_the_utc_day_of_at():
    ledger = make(global_day_hard_minor=200)
    spend_once(ledger, JUDGE_A, 150, at=datetime(2026, 10, 6, 23, 59, tzinfo=UTC))
    next_day = datetime(2026, 10, 7, 0, 1, tzinfo=UTC)
    assert not hasattr(reserve(ledger, JUDGE_B, 150, at=next_day, run_id="r_2"), "reason")
    assert reserve(ledger, JUDGE_B, 100, at=AT, run_id="r_3").reason == "global_hard"


def test_SEC_16_firestore_ledger_rejects_bad_input_before_touching_the_store():
    db = OccFirestore()
    ledger = make(db)
    for bad in (
        {"amount_minor": 1.5},
        {"amount_minor": True},
        {"amount_minor": -1},
        {"at": datetime(2026, 10, 6, 12, 0)},
        {"uid": ""},
        {"uid": "a/b"},
        {"run_id": ""},
    ):
        args = {"uid": JUDGE_A, "run_id": "r_1", "org_id": ORG, "amount_minor": 1, "at": AT, **bad}
        with pytest.raises((TypeError, ValueError)):
            ledger.reserve(**args)
    assert db.touched == []


# --- idempotency ---------------------------------------------------------------------------------------------


def test_SEC_16_firestore_ledger_a_retried_settle_or_release_never_counts_twice():
    ledger = make()
    held = reserve(ledger, minor=100)
    first = ledger.settle(held, 250)
    assert ledger.settle(held, 250) == first
    assert ledger.settled_minor(JUDGE_A) == 250 and ledger.spent_minor(JUDGE_A) == 250

    other = reserve(ledger, minor=100, run_id="r_2")
    ledger.release(other)
    ledger.release(other)
    assert ledger.spent_minor(JUDGE_A) == 250
    with pytest.raises(KeyError):  # a hold released cannot also be settled, nor a settled one released
        ledger.settle(other, 10)
    with pytest.raises(KeyError):
        ledger.release(held)


def test_SEC_16_firestore_ledger_a_reserve_retried_with_its_unit_id_is_one_hold():
    ledger = make()
    one = reserve(ledger, minor=100, unit_id="unit_1")
    two = reserve(ledger, minor=100, unit_id="unit_1")
    assert one == two and ledger.spent_minor(JUDGE_A) == 100
    with pytest.raises(ValueError):  # the same unit id with other terms is not a retry
        reserve(ledger, minor=999, unit_id="unit_1")
    ledger.settle(one, 100)
    with pytest.raises(ValueError):  # and a closed unit is never opened again
        reserve(ledger, minor=100, unit_id="unit_1")
    assert ledger.spent_minor(JUDGE_A) == 100


def test_SEC_16_firestore_ledger_an_unknown_or_forged_reservation_is_a_key_error():
    from tilo_api.spend import Reservation

    ledger = make()
    held = reserve(ledger, minor=100)
    forged = Reservation(id=held.id, uid=JUDGE_B, run_id="r_1", org_id=ORG, amount_minor=1)
    for call in (lambda r: ledger.settle(r, 1), ledger.release):
        with pytest.raises(KeyError):
            call(forged)
        with pytest.raises(KeyError):
            call(Reservation(id="nope", uid=JUDGE_A, run_id="r_1", org_id=ORG, amount_minor=1))
    assert ledger.spent_minor(JUDGE_A) == 100


# --- concurrency and storage ---------------------------------------------------------------------------------


def test_SEC_16_firestore_ledger_concurrent_reserves_never_pass_the_cap():
    db = OccFirestore()
    ledger = make(db, uid_lifetime_minor=1_000)
    won: list[Any] = []
    guard = threading.Lock()

    def work(n: int) -> None:
        try:
            result = reserve(make(db, uid_lifetime_minor=1_000), JUDGE_A, 100, run_id=f"r_{n}")
        except Exception:  # contention beyond its attempts: not a reservation, so replay (fail closed)
            return
        if not hasattr(result, "reason"):
            with guard:
                won.append(result)

    threads = [threading.Thread(target=work, args=(n,)) for n in range(24)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert 1 <= len(won) <= 10
    assert ledger.spent_minor(JUDGE_A) == 100 * len(won) <= 1_000


def test_SEC_16_firestore_ledger_documents_live_under_the_org_and_a_second_org_day_is_its_own():
    db = OccFirestore()
    ledger = make(db, org_day_minor=150)
    spend_once(ledger, JUDGE_A, 100)
    assert not hasattr(reserve(ledger, JUDGE_B, 100, org_id=OTHER_ORG, run_id="r_2"), "reason")
    assert reserve(ledger, JUDGE_B, 100, org_id=ORG, run_id="r_3").reason == "org_day"
    assert db.touched and all(p.startswith(ROOT + "/") for p in db.touched)


def test_SEC_16_firestore_ledger_an_unreadable_store_raises_and_a_malformed_switch_reads_as_set():
    db = Flaky()
    ledger = make(db)
    spend_once(ledger, JUDGE_A, 100)
    db.broken = True
    for call in (ledger.replay_only, lambda: ledger.spent_minor(JUDGE_A), lambda: reserve(ledger)):
        with pytest.raises(ConnectionError):
            call()
    db.broken = False
    db.put(f"{ROOT}/switch", {"on": "no"})  # not a bool: a hand-written document is never believed
    assert ledger.replay_only() is True
    assert reserve(ledger).reason == "replay_only"
    db.put(f"{ROOT}/uid:{JUDGE_B}", {"settled_minor": "1", "held_minor": 0})
    with pytest.raises(ValueError):
        reserve(ledger, JUDGE_B)


# --- the seam and the API on it ------------------------------------------------------------------------------


def _deployed(monkeypatch, **env: str) -> None:
    from tilo_api import deps, prod

    monkeypatch.setenv("K_SERVICE", "tilo-api")
    monkeypatch.delenv("FIRESTORE_EMULATOR_HOST", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(deps, "_spend_ledger_retry_at", None)
    prod.reset()


def test_GOLIVE_935_deployed_with_a_project_the_seam_is_the_firestore_ledger(monkeypatch):
    from tilo_api import deps, prod
    from tilo_api.spend_firestore import FirestoreSpendLedger

    _deployed(monkeypatch, TILO_FIRESTORE_PROJECT="tilo-dev-123456")
    db = OccFirestore()
    built: list[str] = []
    monkeypatch.setattr(prod, "build_client", lambda project: built.append(project) or db)

    ledger = deps.get_spend_cap_ledger()

    assert isinstance(ledger, FirestoreSpendLedger) and built == ["tilo-dev-123456"]
    assert deps.get_spend_cap_ledger()._client is db, "one client per process"
    prod.reset()


def test_GOLIVE_935_off_cloud_run_the_seam_is_one_process_wide_memory_ledger(monkeypatch):
    from tilo_api import deps
    from tilo_api.spend import InMemorySpendLedger

    monkeypatch.delenv("K_SERVICE", raising=False)
    monkeypatch.delenv("CLOUD_RUN_JOB", raising=False)
    first = deps.get_spend_cap_ledger()
    assert isinstance(first, InMemorySpendLedger)
    spend_once(first, JUDGE_A, 100)
    assert deps.get_spend_cap_ledger().settled_minor(JUDGE_A) == 100


@pytest.mark.parametrize("project", [None, "", "Not A Project!", "a"])
def test_GOLIVE_935_deployed_without_a_valid_project_the_seam_refuses(monkeypatch, project):
    from fastapi import HTTPException
    from tilo_api import deps

    _deployed(monkeypatch)
    monkeypatch.delenv("TILO_FIRESTORE_PROJECT", raising=False)
    if project is not None:
        monkeypatch.setenv("TILO_FIRESTORE_PROJECT", project)

    with pytest.raises(HTTPException) as caught:
        deps.get_spend_cap_ledger()
    assert caught.value.status_code == 503


def test_GOLIVE_935_a_client_that_cannot_be_built_is_a_503_that_backs_off(monkeypatch):
    from fastapi import HTTPException
    from tilo_api import deps, prod

    _deployed(monkeypatch, TILO_FIRESTORE_PROJECT="tilo-dev-123456")
    attempts: list[int] = []

    def boom(project: str) -> Any:
        attempts.append(1)
        raise OSError("no credentials")

    monkeypatch.setattr(prod, "build_client", boom)

    for _ in range(3):
        with pytest.raises(HTTPException) as caught:
            deps.get_spend_cap_ledger()
        assert caught.value.status_code == 503
    assert len(attempts) == 1, "inside the backoff window no new build is tried"
    monkeypatch.setattr(deps, "_spend_ledger_retry_at", None)
    prod.reset()


def _api(sec16_factory, db: Any = None, **kw: Any) -> Any:
    caps = make_caps(**{**BIG_LIMIT, **kw})
    ledger = SpyLedger(make(db if db is not None else OccFirestore(), caps))
    return sec16_factory(declarations=declared(), ledger=ledger, **{**BIG_LIMIT, **kw})


def test_GOLIVE_935_deployed_and_live_the_api_goes_live_on_the_firestore_ledger(sec16_factory):
    h = _api(sec16_factory)
    assert h.me().json() == {"declaration": "judge", "allowed": True, "models": "live"}
    assert h.intake().status_code == 201
    assert set(h.router_modes) == {"live"}


def test_GOLIVE_935_a_capped_uid_is_refused_and_labelled_replay_on_the_firestore_ledger(sec16_factory):
    h = _api(sec16_factory)
    fill(h, JUDGE_A, h.caps.uid_lifetime_minor)
    assert h.me().json()["models"] == "replay"
    assert_cap_refusal(h.intake())
    assert h.router_modes == []
    h.as_user(JUDGE_B)
    assert h.intake().status_code == 201 and set(h.router_modes) == {"live"}


def test_GOLIVE_935_the_kill_switch_replays_on_the_firestore_ledger(sec16_factory):
    h = _api(sec16_factory)
    h.ledger.trip_replay_only("test")
    assert h.me().json()["models"] == "replay"
    refused = h.intake()
    assert refused.status_code == 503 and refused.json().get("replay_only") is True
    assert h.router_modes == []


def test_GOLIVE_935_an_unreadable_ledger_replays_and_replay_work_still_runs(sec16_factory):
    db = Flaky()
    h = _api(sec16_factory, db)
    db.broken = True
    assert h.me().json() == {"declaration": "judge", "allowed": True, "models": "replay"}
    assert h.intake().status_code == 201
    assert set(h.router_modes) == {"replay"}, h.router_modes


def test_GOLIVE_935_no_ledger_wired_still_replays(sec16_factory):
    h = sec16_factory(declarations=declared(), ledger=None, **BIG_LIMIT)
    assert h.me().json()["models"] == "replay"
    assert h.intake().status_code == 201
    assert set(h.router_modes) == {"replay"}


# --- the real emulator (off unless asked: `just test-outbox-emulator` style, see the outbox store suite) ----------


@pytest.fixture
def emulator_db(request):
    import contextlib
    import os
    import urllib.request
    import uuid

    asked = request.config.getoption("--outbox-emulator", default=False)
    if not (asked or os.environ.get("TILO_FIRESTORE_EMULATOR_TESTS") == "1"):
        pytest.skip("the Firestore emulator rig is off: pass --outbox-emulator or set TILO_FIRESTORE_EMULATOR_TESTS=1")
    from google.auth.credentials import AnonymousCredentials
    from google.cloud import firestore
    from tilo_harness.emulator import running_emulator

    with running_emulator() as host:
        assert host.split(":")[0] in ("127.0.0.1", "localhost", "[::1]")
        project = f"demo-spend-{uuid.uuid4().hex[:10]}"
        client = firestore.Client(project=project, credentials=AnonymousCredentials())
        try:
            yield client
        finally:
            url = f"http://{host}/emulator/v1/projects/{project}/databases/(default)/documents"
            with contextlib.suppress(OSError):
                urllib.request.urlopen(urllib.request.Request(url, method="DELETE"), timeout=15).close()  # noqa: S310
            client.close()


@pytest.mark.emulator
def test_SEC_16_firestore_ledger_on_the_emulator_caps_settles_and_trips(emulator_db):
    ledger = make(emulator_db, uid_lifetime_minor=1_000, global_day_hard_minor=5_000)
    held = reserve(ledger, minor=600)
    assert reserve(ledger, minor=500, run_id="r_2").reason == "uid_lifetime"
    assert ledger.settle(held, 700).overrun is True
    assert ledger.settle(held, 700).overrun is True and ledger.settled_minor(JUDGE_A) == 700
    assert reserve(ledger, minor=300, run_id="r_3").amount_minor == 300
    assert make(emulator_db, uid_lifetime_minor=1_000).spent_minor(JUDGE_A) == 1_000, "a second instance, same totals"
    assert ledger.trip_replay_only("emulator") is True and ledger.trip_replay_only("again") is False
    assert reserve(ledger, JUDGE_B).reason == "replay_only"
