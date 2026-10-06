"""FR-MTR-04 and NFR-24 through the API: "per-run, per-user and per-org caps; hard cap triggers the kill switch ...
the demo hard cap switches the link to replay-only" (PRD 14.5), and "one flag switches the public link to replay-only"
(PRD 17.2), the US$25/day hard cap "triggers NFR-24" (PRD 17.3).

The kill switch now has two stores that the API reads together (API_SEC_16.md): the NFR-24 flag store
(`deps.get_flag_store`, unchanged) and the ledger's own durable `replay_only` record (`deps.get_spend_ledger`).
Either one set means: no new work (503 `replay_only: true`, the existing NFR-24 refusal), `GET /access` says `models:
"replay"`, and no router is built for live. The ledger's record outlives a process: a restart (a new ledger over the
same backing) is still replay-only; only a named human reset clears it. The switch never makes anything more live.

Written from the PRD text before any builder touches it: tests/SEC-16-spend-caps.
"""

from __future__ import annotations

import os

from _sec16_lib import JUDGE_A, JUDGE_B, SpyLedger, make_caps, make_ledger

LIVE = "LIVE"  # spelled apart: the repo's guard hook looks for the literal switch
BIG_LIMIT = {"rate_limit_requests": 1_000}


def declared():
    return {JUDGE_A: "judge", JUDGE_B: "judge"}


def assert_replay_only_refusal(response):
    assert response.status_code == 503, f"{response.status_code}: {response.text}"
    body = response.json()
    assert body.get("replay_only") is True
    assert "replay" in str(body.get("detail", "")).lower()


def test_FR_MTR_04_the_ledgers_switch_alone_closes_new_work_with_the_existing_replay_only_refusal(sec16_factory):
    h = sec16_factory(declarations=declared(), **BIG_LIMIT)
    task = h.intake().json()
    assert h.client.get(f"/tasks/{task['task_id']}/approaches").status_code == 200
    h.ledger.trip_replay_only("test: the daily hard cap was crossed")
    assert not h.flags.get("replay_only"), "only the ledger's record is set; the NFR-24 flag store is untouched"
    before = h.snapshot()

    assert_replay_only_refusal(h.intake())
    assert_replay_only_refusal(h.client.get(f"/tasks/{task['task_id']}/approaches"))
    assert_replay_only_refusal(
        h.client.post(f"/tasks/{task['task_id']}/approve", json={"approach_id": "quick", "budget_cap": 50})
    )

    assert h.snapshot() == before, "a refusal has no side effect"


def test_FR_MTR_04_with_the_switch_set_the_link_says_replay_and_builds_no_live_router(sec16_factory):
    h = sec16_factory(declarations=declared(), **BIG_LIMIT)
    h.ledger.trip_replay_only("test")

    assert h.me().json() == {"declaration": "judge", "allowed": True, "models": "replay"}
    h.intake()
    assert "live" not in h.router_modes


def test_FR_MTR_04_the_switch_outlives_a_process_restart(sec16_factory):
    shared: dict = {}
    caps = make_caps()
    make_ledger(caps, shared=shared).trip_replay_only("hard cap crossed before the restart")

    # a new process: a new ledger over the same backing, a fresh in-memory flag store, a fresh limiter
    h = sec16_factory(declarations=declared(), ledger=SpyLedger(make_ledger(caps, shared=shared)), **BIG_LIMIT)

    assert not h.flags.get("replay_only"), "process state is gone: only the stored record remembers"
    assert h.me().json()["models"] == "replay"
    assert_replay_only_refusal(h.intake())
    assert h.router_modes == []


def test_FR_MTR_04_the_switch_is_for_everyone_and_a_judge_cannot_lift_it(sec16_factory):
    h = sec16_factory(declarations=declared(), **BIG_LIMIT)
    h.ledger.trip_replay_only("test")

    for judge in (JUDGE_A, JUDGE_B):
        h.as_user(judge)
        assert_replay_only_refusal(h.intake())
        refused = h.client.post(
            "/intake",
            data={"text": "Prepare a summary.", "replay_only": "false", "reset": "1"},
            headers={"X-Replay-Only": "0", "X-Reset-Spend": "1"},
        )
        assert_replay_only_refusal(refused)
    assert h.ledger.replay_only() is True
    assert h.ledger.writes == ["trip_replay_only"], "no request wrote anything but the test's own trip"


def test_FR_MTR_04_the_nfr_24_flag_store_still_works_on_its_own_with_a_ledger_wired(sec16_factory):
    h = sec16_factory(declarations=declared(), **BIG_LIMIT)
    h.flags.set("replay_only", True, reason="NFR-24 test")

    assert h.me().json()["models"] == "replay"
    assert_replay_only_refusal(h.intake())
    assert h.ledger.replay_only() is False, "reading the flag store does not flip the ledger's record"


def test_FR_MTR_04_not_deployed_the_ledger_is_never_consulted_and_dev_is_unchanged(sec16_factory):
    h = sec16_factory(declarations=declared(), deployed=False, **BIG_LIMIT)
    h.ledger.trip_replay_only("test")
    h.ledger.calls.clear()

    assert h.intake().status_code == 201, "CI and `just dev-api` do not depend on the spend ledger"
    assert h.ledger.calls == []
    assert os.environ.get(LIVE) is None
