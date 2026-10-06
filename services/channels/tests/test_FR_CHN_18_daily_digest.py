"""FR-CHN-18 (PRD 11.4, 11.6): Daily digest of automated actions and FYI mail."""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

from tilo_channels.digest import WINDOW_S, DailyDigestBuilder, DigestService, FakeDigestChannel, build_daily_digest

NOW_TS, NOW_EPOCH = "2026-10-06T18:00:00.000Z", 1_791_309_600.0
USER, WORLD, RUN, BASE_URL = "u_owner", "w_digest01", "r_digest01", "https://app.tilo.example"


def _policy_applied_event(
    *,
    seq: int,
    ts: str,
    outbox_id: str,
    level: str = "L2",
    policy_id: str = "pol_auto_1",
    action_type: str = "send_email",
    risk_tier: str = "T2",
    undo_window_s: int = 60,
) -> dict:
    return {
        "v": "1.0",
        "id": f"01J8Z3K4M5N6P7Q8R9S0T1V2{seq:02d}",
        "seq": seq,
        "ts": ts,
        "world_id": WORLD,
        "run_id": RUN,
        "type": "policy.applied",
        "level": level,
        "severity": "info",
        "credits": 0,
        "authz": {"by": "policy", "ref": policy_id, "at": ts},
        "data": {
            "policy_id": policy_id,
            "gate_id": f"G_{seq}",
            "outbox_id": outbox_id,
            "action_type": action_type,
            "connector": "gmail",
            "destination": "thr_1" if level == "L2" else None,
            "district": "D1",
            "risk_tier": risk_tier,
            "level": level,
            "instruction_id": f"01J8Z3K4M5N6P7Q8R9S0T1V3{seq:02d}" if level == "L2" else None,
            "undo_window_s": undo_window_s if level == "L2" else 0,
            "item": {"artifact_id": f"art_{seq}", "version": 1},
            "credits": 0.1,
        },
    }


def _outbox_entry(
    *,
    outbox_id: str,
    created_at: str,
    state: str = "sent",
    action_type: str = "send_email",
    risk_tier: str = "T2",
    undo_window_s: int = 60,
    scheduled_at: str | None = None,
) -> dict:
    return {
        "id": outbox_id,
        "idempotency_key": f"autopilot:{outbox_id}",
        "world_id": WORLD,
        "run_id": RUN,
        "action_type": action_type,
        "connector": "gmail",
        "recipients": ["peer@example.com"],
        "attachments": [],
        "item": {"artifact_id": f"art_{outbox_id[-2:]}", "version": 1},
        "destination": "thr_1",
        "modifiers": [],
        "risk_tier": risk_tier,
        "authz": {"by": "policy", "ref": "pol_auto_1", "at": created_at},
        "undo_window_s": undo_window_s,
        "scheduled_at": scheduled_at or created_at,
        "state": state,
        "created_at": created_at,
    }


def test_FR_CHN_18_lists_every_l2_and_l3_action_in_last_24h_and_misses_none() -> None:
    ob_l2_recent, ob_l3_recent, ob_l2_sched = (
        "01J8Z3K4M5N6P7Q8R9S0T1V2A1",
        "01J8Z3K4M5N6P7Q8R9S0T1V2A2",
        "01J8Z3K4M5N6P7Q8R9S0T1V2A3",
    )
    ob_old, ob_person_l1 = "01J8Z3K4M5N6P7Q8R9S0T1V2A0", "01J8Z3K4M5N6P7Q8R9S0T1V2A9"
    events = [
        _policy_applied_event(seq=1, ts="2026-10-05T17:59:59.000Z", outbox_id=ob_old, level="L2"),
        _policy_applied_event(seq=2, ts="2026-10-05T18:00:01.000Z", outbox_id=ob_l2_recent, level="L2"),
        _policy_applied_event(
            seq=3,
            ts="2026-10-06T09:15:00.000Z",
            outbox_id=ob_l3_recent,
            level="L3",
            action_type="create_draft",
            risk_tier="T1",
            undo_window_s=0,
        ),
        _policy_applied_event(seq=4, ts="2026-10-06T17:59:30.000Z", outbox_id=ob_l2_sched, level="L2"),
        {
            "v": "1.0",
            "id": "01J8Z3K4M5N6P7Q8R9S0T1V299",
            "seq": 5,
            "ts": "2026-10-06T12:00:00.000Z",
            "world_id": WORLD,
            "run_id": RUN,
            "type": "approval.resolved",
            "level": "L1",
            "severity": "info",
            "credits": 0,
            "authz": {"by": "person", "ref": USER, "at": "2026-10-06T12:00:00.000Z"},
            "data": {
                "gate_id": "G_9",
                "card_id": "01J8Z3K4M5N6P7Q8R9S0T1V2C9",
                "outbox_id": ob_person_l1,
                "option": "approve",
            },
        },
    ]
    outbox_entries = [
        _outbox_entry(outbox_id=ob_old, created_at="2026-10-05T17:59:59.000Z", state="sent"),
        _outbox_entry(outbox_id=ob_l2_recent, created_at="2026-10-05T18:00:01.000Z", state="sent"),
        _outbox_entry(
            outbox_id=ob_l3_recent,
            created_at="2026-10-06T09:15:00.000Z",
            state="sent",
            action_type="create_draft",
            risk_tier="T1",
            undo_window_s=0,
        ),
        _outbox_entry(
            outbox_id=ob_l2_sched,
            created_at="2026-10-06T17:59:30.000Z",
            state="scheduled",
            scheduled_at="2026-10-06T18:00:30.000Z",
        ),
    ]
    fyi_mail = [
        {"message_id": "msg_fyi_1", "category": "fyi", "priority": "normal", "triaged_at": NOW_EPOCH - 3600},
        {"message_id": "msg_old_fyi", "category": "fyi", "priority": "low", "triaged_at": NOW_EPOCH - WINDOW_S - 10},
        {"message_id": "msg_reply", "category": "needs_reply", "priority": "high", "triaged_at": NOW_EPOCH - 1800},
    ]

    digest = build_daily_digest(
        user_id=USER, events=events, outbox_entries=outbox_entries, fyi_mail=fyi_mail, now=NOW_TS, base_url=BASE_URL
    )
    assert digest is not None
    assert [a.outbox_id for a in digest.actions] == [ob_l2_recent, ob_l3_recent, ob_l2_sched]
    assert [a.level for a in digest.actions] == ["L2", "L3", "L2"]

    by_id = {a.outbox_id: a for a in digest.actions}
    assert (
        by_id[ob_l2_recent].link_kind == "report"
        and by_id[ob_l2_recent].action_url == f"{BASE_URL}/outbox/{ob_l2_recent}/report"
    )
    assert (
        by_id[ob_l3_recent].link_kind == "report"
        and by_id[ob_l3_recent].action_url == f"{BASE_URL}/outbox/{ob_l3_recent}/report"
    )
    assert (
        by_id[ob_l2_sched].link_kind == "undo"
        and by_id[ob_l2_sched].action_url == f"{BASE_URL}/outbox/{ob_l2_sched}/undo"
    )
    assert [m.message_id for m in digest.fyi_mail] == ["msg_fyi_1"]
    assert all(
        x in digest.rendered_text for x in (ob_l2_recent, ob_l3_recent, ob_l2_sched, by_id[ob_l2_sched].action_url)
    )


def test_FR_CHN_18_empty_day_produces_no_digest_and_sends_nothing() -> None:
    fake_channel, enqueued = FakeDigestChannel(), []

    class FakeOutbox:
        def enqueue(self, entry: dict, evidence: dict) -> dict:
            enqueued.append((entry, evidence))
            return entry

    builder = DailyDigestBuilder(base_url=BASE_URL)
    assert builder.build(user_id=USER, events=[], outbox_entries=[], fyi_mail=[], now=NOW_TS) is None
    svc = DigestService(builder=builder, outbox=FakeOutbox(), dev_channel=fake_channel, world_id=WORLD, run_id=RUN)
    assert svc.deliver_if_non_empty(user_id=USER, recipient="owner@example.com", events=[], now=NOW_TS) is None
    assert enqueued == [] and fake_channel.sent == []


def test_FR_CHN_18_sending_uses_existing_outbox_or_dev_fake_channel_and_has_no_direct_send_path() -> None:
    ob_l2 = "01J8Z3K4M5N6P7Q8R9S0T1V2B1"
    events = [_policy_applied_event(seq=1, ts="2026-10-06T15:00:00.000Z", outbox_id=ob_l2, level="L2")]
    outbox_entries = [_outbox_entry(outbox_id=ob_l2, created_at="2026-10-06T15:00:00.000Z", state="sent")]
    fake_channel, enqueued = FakeDigestChannel(), []

    class FakeOutbox:
        def enqueue(self, entry: dict, evidence: dict) -> dict:
            enqueued.append((entry, evidence))
            return entry

    builder = DailyDigestBuilder(base_url=BASE_URL)
    dev_svc = DigestService(
        builder=builder, outbox=FakeOutbox(), dev_channel=fake_channel, world_id=WORLD, run_id=RUN, dev_mode=True
    )
    dev_res = dev_svc.deliver_if_non_empty(
        user_id=USER, recipient="owner@example.com", events=events, outbox_entries=outbox_entries, now=NOW_TS
    )
    assert dev_res is not None and dev_res["channel"] == "fake" and len(fake_channel.sent) == 1 and enqueued == []

    prod_svc = DigestService(
        builder=builder, outbox=FakeOutbox(), dev_channel=None, world_id=WORLD, run_id=RUN, dev_mode=False
    )
    policy_part = _policy_applied_event(
        seq=2, ts=NOW_TS, outbox_id="01J8Z3K4M5N6P7Q8R9S0T1V2D1", level="L3", undo_window_s=0
    )
    prod_res = prod_svc.deliver_if_non_empty(
        user_id=USER,
        recipient="owner@example.com",
        events=events,
        outbox_entries=outbox_entries,
        now=NOW_TS,
        policy_applied=policy_part,
    )
    assert prod_res is not None and len(enqueued) == 1
    entry, evidence = enqueued[0]
    assert (
        entry["id"] == "01J8Z3K4M5N6P7Q8R9S0T1V2D1"
        and entry["authz"] == policy_part["authz"]
        and evidence["authorised_by"] == policy_part
    )

    spec = importlib.util.find_spec("tilo_channels.digest")
    assert spec is not None and spec.origin
    tree = ast.parse(Path(spec.origin).read_text(encoding="utf-8"))
    imported = {
        alias.name if isinstance(n, ast.Import) else (n.module or "")
        for n in ast.walk(tree)
        for alias in (n.names if isinstance(n, ast.Import | ast.ImportFrom) else [])
    }
    assert not (
        {i.split(".")[0] for i in imported}
        & {"tilo_connectors", "httpx", "requests", "smtplib", "socket", "urllib", "googleapiclient"}
    )
