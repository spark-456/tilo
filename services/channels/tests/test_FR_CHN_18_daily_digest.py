"""FR-CHN-18 (PRD 11.4, 11.6): Daily digest of automated actions and FYI mail."""

from __future__ import annotations

import pytest
import tilo_policy
from tilo_channels.digest import WINDOW_S, DailyDigestBuilder, DigestService, FakeDigestChannel, build_daily_digest

NOW_TS, NOW_EPOCH = "2026-10-06T18:00:00.000Z", 1_791_309_600.0
USER, WORLD, RUN, BASE_URL = "u_owner", "w_digest01", "r_digest01", "https://app.tilo.example"


def _policy_ev(seq: int, ts: str, outbox_id: str, level: str = "L2", action_type: str = "send_email") -> dict:
    return {
        "v": "1.0", "id": f"01J8Z3K4M5N6P7Q8R9S0T1V2{seq:02d}", "seq": seq, "ts": ts,
        "world_id": WORLD, "run_id": RUN, "type": "policy.applied", "level": level, "severity": "info", "credits": 0,
        "authz": {"by": "policy", "ref": "pol_auto_1", "at": ts},
        "data": {
            "policy_id": "pol_auto_1", "gate_id": f"G_{seq}", "outbox_id": outbox_id, "action_type": action_type,
            "connector": "gmail", "destination": "thr_1" if level == "L2" else None, "district": "D1",
            "risk_tier": "T2" if level == "L2" else "T1", "level": level,
            "instruction_id": f"01J8Z3K4M5N6P7Q8R9S0T1V3{seq:02d}" if level == "L2" else None,
            "undo_window_s": 60 if level == "L2" else 0, "item": {"artifact_id": f"art_{seq}", "version": 1},
            "credits": 0.1,
        },
    }  # fmt: skip


def _outbox_entry(outbox_id: str, created_at: str, state: str = "sent", scheduled_at: str | None = None) -> dict:
    return {
        "id": outbox_id, "idempotency_key": f"autopilot:{outbox_id}", "world_id": WORLD, "run_id": RUN,
        "action_type": "send_email", "connector": "gmail", "recipients": ["peer@example.com"], "attachments": [],
        "item": {"artifact_id": f"art_{outbox_id[-2:]}", "version": 1}, "destination": "thr_1", "modifiers": [],
        "risk_tier": "T2", "authz": {"by": "policy", "ref": "pol_auto_1", "at": created_at}, "undo_window_s": 60,
        "scheduled_at": scheduled_at or created_at, "state": state, "created_at": created_at,
    }  # fmt: skip


def _decision(outcome: str = "run_after_undo", level: str = "L2") -> tilo_policy.Decision:
    allow = outcome != "ask"
    return tilo_policy.Decision(
        outcome=outcome, tier="T2", level=level, modifiers=(),  # type: ignore[arg-type]
        policy_id="pol_digest_1" if allow else None, undo_window_s=60 if outcome == "run_after_undo" else None,
        reason="digest policy decision", authz={"by": "policy", "ref": "pol_digest_1", "at": NOW_TS} if allow else None,
    )  # fmt: skip


def test_FR_CHN_18_lists_every_l2_and_l3_action_in_last_24h_and_skips_missing_entry() -> None:
    ob_l2, ob_l3, ob_sched, ob_old, ob_missing = (
        "01J8Z3K4M5N6P7Q8R9S0T1V2A1", "01J8Z3K4M5N6P7Q8R9S0T1V2A2", "01J8Z3K4M5N6P7Q8R9S0T1V2A3",
        "01J8Z3K4M5N6P7Q8R9S0T1V2A0", "01J8Z3K4M5N6P7Q8R9S0T1V2A9",
    )  # fmt: skip
    events = [
        _policy_ev(1, "2026-10-05T17:59:59.000Z", ob_old, "L2"),
        _policy_ev(2, "2026-10-05T18:00:01.000Z", ob_l2, "L2"),
        _policy_ev(3, "2026-10-06T09:15:00.000Z", ob_l3, "L3", "create_draft"),
        _policy_ev(4, "2026-10-06T17:59:30.000Z", ob_sched, "L2"),
        _policy_ev(5, "2026-10-06T17:59:45.000Z", ob_missing, "L2"),
        {"type": "approval.resolved", "level": "L1", "ts": "2026-10-06T12:00:00.000Z", "data": {"outbox_id": "ob_l1"}},
    ]
    outbox_entries = [
        _outbox_entry(ob_old, "2026-10-05T17:59:59.000Z", "sent"),
        _outbox_entry(ob_l2, "2026-10-05T18:00:01.000Z", "sent"),
        _outbox_entry(ob_l3, "2026-10-06T09:15:00.000Z", "sent"),
        _outbox_entry(ob_sched, "2026-10-06T17:59:30.000Z", "scheduled", "2026-10-06T18:00:30.000Z"),
    ]
    fyi_mail = [
        {"message_id": "msg_fyi_1", "category": "fyi", "priority": "normal", "triaged_at": NOW_EPOCH - 3600},
        {"message_id": "msg_old_fyi", "category": "fyi", "priority": "low", "triaged_at": NOW_EPOCH - WINDOW_S - 10},
        {"message_id": "msg_reply", "category": "needs_reply", "priority": "high", "triaged_at": NOW_EPOCH - 1800},
    ]

    digest = build_daily_digest(
        user_id=USER, events=events, outbox_entries=outbox_entries, fyi_mail=fyi_mail, now=NOW_TS, base_url=BASE_URL
    )
    assert digest is not None and [a.outbox_id for a in digest.actions] == [ob_l2, ob_l3, ob_sched]
    assert digest.skipped_outbox_ids == (ob_missing,) and [m.message_id for m in digest.fyi_mail] == ["msg_fyi_1"]
    by_id = {a.outbox_id: a for a in digest.actions}
    assert by_id[ob_l2].link_kind == "report" and by_id[ob_l2].action_url == f"{BASE_URL}/outbox/{ob_l2}/report"
    assert by_id[ob_l3].link_kind == "report" and by_id[ob_l3].action_url == f"{BASE_URL}/outbox/{ob_l3}/report"
    assert by_id[ob_sched].link_kind == "undo" and by_id[ob_sched].action_url == f"{BASE_URL}/outbox/{ob_sched}/undo"


def test_FR_CHN_18_policy_port_allow_deny_missing_and_dev_mode() -> None:
    fake_channel, enqueued, proposals = FakeDigestChannel(), [], []

    class FakeOutbox:
        def enqueue(self, entry: dict, evidence: dict) -> dict:
            enqueued.append((entry, evidence))
            return entry

    class FakePolicy:
        def __init__(self, reply: tilo_policy.Decision | None) -> None:
            self.reply = reply

        def decide(self, user_id: str, proposal: tilo_policy.Proposal) -> tilo_policy.Decision:
            proposals.append((user_id, proposal))
            if self.reply is None:
                raise RuntimeError("policy unavailable")
            return self.reply

    builder = DailyDigestBuilder(base_url=BASE_URL)
    with pytest.raises(ValueError, match="dev_channel"):
        DigestService(builder=builder, outbox=FakeOutbox(), dev_channel=None, world_id=WORLD, run_id=RUN, dev_mode=True)

    ob_l2 = "01J8Z3K4M5N6P7Q8R9S0T1V2B1"
    events = [_policy_ev(1, "2026-10-06T15:00:00.000Z", ob_l2, "L2")]
    outbox_entries = [_outbox_entry(ob_l2, "2026-10-06T15:00:00.000Z", "sent")]

    dev_svc = DigestService(
        builder=builder, outbox=FakeOutbox(), dev_channel=fake_channel, world_id=WORLD, run_id=RUN, dev_mode=True
    )
    assert dev_svc.deliver_if_non_empty(user_id=USER, recipient="owner@example.com", events=[], now=NOW_TS) is None
    dev_res = dev_svc.deliver_if_non_empty(
        user_id=USER, recipient="owner@example.com", events=events, outbox_entries=outbox_entries, now=NOW_TS
    )
    assert dev_res is not None and dev_res["channel"] == "fake" and len(fake_channel.sent) == 1 and enqueued == []

    for bad_reply in (_decision(outcome="ask", level="L1"), None):
        svc = DigestService(
            builder=builder, outbox=FakeOutbox(), policy=FakePolicy(bad_reply), world_id=WORLD, run_id=RUN
        )
        res = svc.deliver_if_non_empty(
            user_id=USER, recipient="owner@example.com", events=events, outbox_entries=outbox_entries, now=NOW_TS
        )
        assert res is None and enqueued == []

    allow_svc = DigestService(
        builder=builder, outbox=FakeOutbox(), policy=FakePolicy(_decision()), world_id=WORLD, run_id=RUN
    )
    prod_res = allow_svc.deliver_if_non_empty(
        user_id=USER, recipient="owner@example.com", events=events, outbox_entries=outbox_entries, now=NOW_TS
    )
    assert prod_res is not None and len(enqueued) == 1
    entry, evidence = enqueued[0]
    applied = evidence["authorised_by"]
    assert entry["id"] == applied["data"]["outbox_id"] and entry["id"] != ob_l2
    assert entry["idempotency_key"] == f"digest:{USER}:{NOW_TS}" and entry["recipients"] == ["owner@example.com"]
    assert entry["authz"] == {"by": "policy", "ref": "pol_digest_1", "at": NOW_TS}
    assert proposals[-1][1].facts.recipients == ("owner@example.com",)
