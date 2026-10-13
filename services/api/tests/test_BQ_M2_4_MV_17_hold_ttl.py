"""BQ-M2-4, ADR-0042 decision 14 (MV-17): holds expire. (a) In the claim: a hold open longer than `hold_ttl_s`
(3 x `voice.live.timeout_s`, 60 s shipped) is settled at the whole unit by the next reserve or close of that claim, so
a bot that died in the middle of a reply does not hold the meeting's Live voice until the claim ends. (b) In the ledger:
a `hold:{unit id}` document carries `expires_at` (reserve time plus one hour) and an expired `held` hold is settled at
its own amount by the next reserve of that uid and by the schedule tick; the count is what it already was and only its
status closes. Fake verifier, the in-memory ledger and the Firestore fake; no network, no paid call."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pytest
from _adr35_l2_fake import OccFirestore
from _mv_lib import MEETING, OTHER_MEETING, OWNER, OWNER_2, UNIT, Rig, new_key
from _sec16_lib import AT, JUDGE_A, JUDGE_B, ORG, SpyLedger
from test_SEC_16_GOLIVE_935_firestore_spend_ledger import emulator_db, make, reserve  # noqa: F401  (fixture)


@pytest.fixture
def rig(monkeypatch):
    return Rig(monkeypatch)


def hold_doc(db, reservation):
    return db.document(f"orgs/{ORG}/spend_ledger/hold:{reservation.id}").get().to_dict()


# --- (a) in the claim ---------------------------------------------------------------------------------------------


def test_BQ_M2_4_MV_17_a_hold_open_past_the_ttl_is_settled_at_the_unit_and_the_next_reserve_may_go_live(rig):
    nonce, first, second = rig.attend(), new_key(), new_key()
    assert rig.reserve(nonce, first).json() == {"decision": "live"}
    assert rig.reserve(nonce, second).json() == {"decision": "replay", "reason": "hold_open"}
    rig.clock.advance(61)  # past 3 x 20 s
    assert rig.reserve(nonce, second).json() == {"decision": "live"}
    assert (rig.settled(), rig.spent()) == (UNIT, 2 * UNIT)  # the dead reply counted at the unit, the new one held
    assert "release" not in rig.ledger.names


def test_BQ_M2_4_MV_17_exactly_the_ttl_is_not_yet_expired_and_the_ttl_follows_the_config(rig):
    nonce, first = rig.attend(), new_key()
    rig.reserve(nonce, first)
    rig.clock.advance(60)
    assert rig.reserve(nonce, new_key()).json()["reason"] == "hold_open"
    rig.config = replace(rig.config, hold_ttl_s=5.0)
    assert rig.reserve(nonce, new_key()).json() == {"decision": "live"}  # 60 s open is past a 5 s ttl
    assert rig.settled() == UNIT


def test_BQ_M2_4_MV_17_a_close_sweeps_too_and_a_late_settled_close_of_the_swept_key_counts_nothing_twice(rig):
    nonce, key = rig.attend(), new_key()
    rig.reserve(nonce, key)
    rig.clock.advance(61)
    unknown = rig.close(nonce, new_key())  # another key: no hold, but the stale one is settled first
    assert unknown.status_code == 409 and rig.settled() == UNIT
    late = rig.close(nonce, key, usage={"prompt_token_count": 1, "response_token_count": 1})
    assert (late.status_code, late.json()) == (200, {"outcome": "settled"})
    assert (rig.settled(), rig.spent()) == (UNIT, UNIT)  # not priced down, not counted twice


def test_BQ_M2_4_MV_17_a_late_release_of_a_swept_key_is_409_and_never_refunds_the_unit(rig):
    nonce, key = rig.attend(), new_key()
    rig.reserve(nonce, key)
    rig.clock.advance(61)
    assert rig.reserve(nonce, new_key()).json() == {"decision": "live"}
    refused = rig.close(nonce, key, "released")
    assert (refused.status_code, refused.json()) == (409, {"error": "no_hold"})
    assert rig.settled() == UNIT


def test_BQ_M2_4_MV_17_each_claim_is_swept_on_its_own_and_the_claim_end_settles_nothing_twice(rig):
    mine, other = rig.attend(), rig.attend(OTHER_MEETING, uid=OWNER_2)
    k1, k2 = new_key(), new_key()
    rig.reserve(mine, k1)
    rig.clock.advance(61)
    rig.reserve(other, k2, meeting_id=OTHER_MEETING)  # the other claim's hold is fresh
    assert rig.reserve(mine, new_key()).json() == {"decision": "live"}  # sweeps only its own claim
    assert (rig.settled(OWNER), rig.settled(OWNER_2)) == (UNIT, 0)
    rig.claims.end(MEETING, mine)
    assert (rig.settled(OWNER), rig.spent(OWNER)) == (2 * UNIT, 2 * UNIT)  # k1 once, the live one at the whole unit


# --- (b) in the ledger --------------------------------------------------------------------------------------------


def test_BQ_M2_4_MV_17_a_ledger_hold_carries_expires_at_one_hour_after_the_reserve():
    db = OccFirestore()
    held = reserve(make(db), JUDGE_A, 100)
    assert hold_doc(db, held)["expires_at"].startswith((AT + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S"))


def test_BQ_M2_4_MV_17_an_expired_held_hold_is_settled_at_its_own_amount_with_the_totals_unchanged():
    db = OccFirestore()
    ledger = make(db, uid_lifetime_minor=1_000)
    old = reserve(ledger, JUDGE_A, 100, run_id="r_old")
    fresh = reserve(ledger, JUDGE_A, 40, run_id="r_new", at=AT + timedelta(minutes=50))
    gone = reserve(ledger, JUDGE_A, 30, run_id="r_gone")
    ledger.release(gone)
    before = (ledger.spent_minor(JUDGE_A), ledger.settled_minor(JUDGE_A))
    assert before == (140, 0)
    assert ledger.settle_expired(AT + timedelta(hours=1, minutes=1)) == 1  # only `old` is past its hour
    assert hold_doc(db, old)["status"] == "settled" and hold_doc(db, old)["actual_minor"] == 100
    assert hold_doc(db, fresh)["status"] == "held"
    assert (ledger.spent_minor(JUDGE_A), ledger.settled_minor(JUDGE_A)) == (140, 100)  # the count is what it was
    assert ledger.settle_expired(AT + timedelta(hours=1, minutes=1)) == 0  # nothing twice
    with pytest.raises(KeyError):
        ledger.release(old)  # a late release of the same unit cannot give the count back
    assert (ledger.spent_minor(JUDGE_A), ledger.settled_minor(JUDGE_A)) == (140, 100)


def test_BQ_M2_4_MV_17_the_next_reserve_of_that_uid_settles_its_expired_holds_and_no_other_uids():
    db = OccFirestore()
    ledger = make(db, uid_lifetime_minor=1_000)
    mine, theirs = reserve(ledger, JUDGE_A, 100, run_id="r_a"), reserve(ledger, JUDGE_B, 100, run_id="r_b")
    later = AT + timedelta(hours=2)
    assert not hasattr(reserve(ledger, JUDGE_A, 10, run_id="r_c", at=later), "reason")
    assert hold_doc(db, mine)["status"] == "settled" and hold_doc(db, theirs)["status"] == "held"


def test_BQ_M2_4_MV_17_a_failing_sweep_never_blocks_a_reserve_or_loosens_a_cap():
    db = OccFirestore()
    ledger = make(db, uid_lifetime_minor=150)
    held = reserve(ledger, JUDGE_A, 100, run_id="r_a")
    ledger._client.collection = lambda _p: (_ for _ in ()).throw(ConnectionError("query"))  # type: ignore[method-assign]
    over = reserve(ledger, JUDGE_A, 100, run_id="r_b", at=AT + timedelta(hours=2))
    assert over.reason == "uid_lifetime"  # the expired hold still counts toward the cap
    assert hold_doc(db, held)["status"] == "held"


@pytest.mark.emulator
def test_BQ_M2_4_MV_17_emulator_an_expired_hold_is_settled_totals_unchanged(emulator_db):  # noqa: F811
    ledger = make(emulator_db, uid_lifetime_minor=1_000)
    reserve(ledger, JUDGE_A, 100)
    assert ledger.settle_expired(AT + timedelta(minutes=30), uid=JUDGE_A) == 0
    assert ledger.settle_expired(AT + timedelta(hours=2), uid=JUDGE_A) == 1  # the query needs no composite index
    assert (ledger.spent_minor(JUDGE_A), ledger.settled_minor(JUDGE_A)) == (100, 100)
    assert make(emulator_db, uid_lifetime_minor=1_000).settle_expired(AT + timedelta(hours=2)) == 0


# --- the schedule tick --------------------------------------------------------------------------------------------


def test_BQ_M2_4_MV_17_the_schedule_tick_settles_expired_ledger_holds_and_a_failure_changes_nothing(monkeypatch):
    from tilo_api import deps, schedules

    db = OccFirestore()
    ledger = make(db, uid_lifetime_minor=1_000)
    old = reserve(ledger, JUDGE_A, 100)
    request = SimpleNamespace(app=SimpleNamespace(dependency_overrides={deps.get_spend_cap_ledger: lambda: ledger}))
    schedules._sweep_spend(request, lambda: AT + timedelta(minutes=30))  # type: ignore[arg-type]
    assert hold_doc(db, old)["status"] == "held"  # not expired yet
    schedules._sweep_spend(request, lambda: AT + timedelta(hours=2))  # type: ignore[arg-type]
    assert hold_doc(db, old)["status"] == "settled"

    def unwired():
        raise RuntimeError("no ledger")

    request.app.dependency_overrides[deps.get_spend_cap_ledger] = unwired
    schedules._sweep_spend(request, lambda: AT + timedelta(hours=3))  # type: ignore[arg-type]  # never raises
    request.app.dependency_overrides[deps.get_spend_cap_ledger] = lambda: SpyLedger(object())  # no such method
    schedules._sweep_spend(request, lambda: AT + timedelta(hours=3))  # type: ignore[arg-type]


def test_BQ_M2_4_MV_17_no_ledger_wired_is_not_a_warning_on_every_tick(caplog):
    from fastapi import HTTPException
    from tilo_api import deps, schedules

    def unwired():
        raise HTTPException(status_code=503, detail="not_configured")

    request = SimpleNamespace(app=SimpleNamespace(dependency_overrides={deps.get_spend_cap_ledger: unwired}))
    with caplog.at_level("WARNING"):
        schedules._sweep_spend(request, lambda: AT)  # type: ignore[arg-type]
    assert not [r for r in caplog.records if "spend hold sweep failed" in r.getMessage()]


def test_BQ_M2_4_MV_17_a_failing_whole_settle_is_logged_once_by_class_and_still_raises(caplog):
    from tilo_api.meeting_voice_claims import Hold

    class Broken:
        def settle_unit(self, *_a: object) -> None:
            raise RuntimeError("store down: secret detail")

    hold = Hold(plan=object(), guard=Broken(), unit=100, reserved_at=0.0)  # type: ignore[arg-type]
    with caplog.at_level("WARNING"):
        for _ in range(3):
            with pytest.raises(RuntimeError):
                hold.settle_whole()
    lines = [r.getMessage() for r in caplog.records if "settle failed" in r.getMessage()]
    assert lines == ["meeting voice hold settle failed (RuntimeError)"], "once, by class, no detail"
    assert hold.state == "open"
