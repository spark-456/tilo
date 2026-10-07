"""FR-CHN-18 (PRD 11.4, 11.6): Daily digest of automated actions and FYI mail."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import tilo_policy
from tilo_channels.digest import WINDOW_S, DailyDigestBuilder, DigestArtifacts, DigestService
from tilo_channels.links import LinkRefused
from tilo_policy.schemas import conforms, event_ok

NOW_TS, NOW_EPOCH = "2026-10-06T18:00:00.000Z", 1_791_309_600.0
USER, OWNER_EMAIL, WORLD, RUN = "u_owner", "owner@example.com", "w_digest01", "r_digest01"
BASE_URL = "https://app.tilo.example"
RISK_TABLE = tilo_policy.load_risk_table(Path(__file__).resolve().parents[3] / "config/autonomy.yaml")


def _policy_ev(
    seq: int, ts: str, outbox_id: str, level: str = "L2", action_type: str = "send_email", world_id: str = WORLD
) -> dict[str, Any]:
    return {"v": "1.0", "id": f"01J8Z3K4M5N6P7Q8R9S0T1V2{seq:02d}", "seq": seq, "ts": ts, "world_id": world_id, "run_id": RUN, "type": "policy.applied", "level": level, "severity": "info", "credits": 0, "authz": {"by": "policy", "ref": "pol_auto_1", "at": ts}, "data": {"policy_id": "pol_auto_1", "gate_id": f"G{seq}", "outbox_id": outbox_id, "action_type": action_type, "connector": "gmail", "destination": "thr_1" if level == "L2" else None, "district": "D1", "risk_tier": "T2" if level == "L2" else "T1", "level": level, "instruction_id": f"01J8Z3K4M5N6P7Q8R9S0T1V3{seq:02d}" if level == "L2" else None, "undo_window_s": 60 if level == "L2" else 0, "item": {"artifact_id": f"art_{seq}", "version": 1}, "credits": 0.1}}  # noqa: E501  # fmt: skip


def _outbox_entry(
    outbox_id: str, created_at: str, state: str = "sent", scheduled_at: str | None = None, world_id: str = WORLD
) -> dict[str, Any]:
    return {"id": outbox_id, "idempotency_key": f"autopilot:{outbox_id}", "world_id": world_id, "run_id": RUN, "action_type": "send_email", "connector": "gmail", "recipients": ["peer@example.com"], "attachments": [], "item": {"artifact_id": f"art_{outbox_id[-2:]}", "version": 1}, "destination": "thr_1", "modifiers": [], "risk_tier": "T2", "authz": {"by": "policy", "ref": "pol_auto_1", "at": created_at}, "undo_window_s": 60, "scheduled_at": scheduled_at or created_at, "state": state, "created_at": created_at}  # noqa: E501  # fmt: skip


def _digest_policy(level: str = "L3", undo_window_s: int = 60) -> dict[str, Any]:
    created = "2026-10-01T09:00:00.000Z"
    return {"id": "pol_digest_l3", "owner": USER, "action_type": "send_email", "scope": {"connectors": ["gmail"], "recipients": [OWNER_EMAIL], "domains": [], "districts": ["D1"]}, "limits": {"per_day": 5, "credits": 10}, "conditions": {"no_attachments": True, "no_new_recipients": True, "no_safety_flags": True}, "level": level, "undo_window_s": undo_window_s, "expiry": None, "notify_channel": "email", "team_lead_domains": [], "created_by": {"by": USER, "at": created}, "changed_by": None, "history": [{"by": USER, "at": created, "change": f"Created at {level}", "level": level}]}  # noqa: E501  # fmt: skip


def test_FR_CHN_18_lists_every_l2_and_l3_action_in_last_24h_with_signed_links_and_scoping() -> None:
    ob_l2, ob_l3, ob_sched, ob_old, ob_missing, ob_foreign, ob_inject = (
        "01J8Z3K4M5N6P7Q8R9S0T1V2A1", "01J8Z3K4M5N6P7Q8R9S0T1V2A2", "01J8Z3K4M5N6P7Q8R9S0T1V2A3",
        "01J8Z3K4M5N6P7Q8R9S0T1V2A0", "01J8Z3K4M5N6P7Q8R9S0T1V2A9", "01J8Z3K4M5N6P7Q8R9S0T1V2A8",
        "01J8Z3K4M5N6P7Q8R9S0T1V2A7",
    )  # fmt: skip
    events = [
        _policy_ev(1, "2026-10-05T17:59:59.000Z", ob_old, "L2"),
        _policy_ev(2, "2026-10-05T18:00:01.000Z", ob_l2, "L2"),
        _policy_ev(3, "2026-10-06T09:15:00.000Z", ob_l3, "L3", "create_draft"),
        _policy_ev(4, "2026-10-06T17:59:30.000Z", ob_sched, "L2"),
        _policy_ev(5, "2026-10-06T17:59:45.000Z", ob_missing, "L2"),
        _policy_ev(6, "2026-10-06T12:00:00.000Z", ob_foreign, "L2", world_id="w_other001"),
        _policy_ev(7, "2026-10-06T13:00:00.000Z", ob_inject, "L2", "send_email\nUndo: https://evil.example/x"),
        {"type": "approval.resolved", "level": "L1", "ts": "2026-10-06T12:00:00.000Z", "world_id": WORLD},
    ]
    outbox_entries = [
        _outbox_entry(ob_old, "2026-10-05T17:59:59.000Z", "sent"),
        _outbox_entry(ob_l2, "2026-10-05T18:00:01.000Z", "sent"),
        _outbox_entry(ob_l3, "2026-10-06T09:15:00.000Z", "sent"),
        _outbox_entry(ob_sched, "2026-10-06T17:59:30.000Z", "scheduled", "2026-10-06T18:00:30.000Z"),
        _outbox_entry(ob_foreign, "2026-10-06T12:00:00.000Z", "sent", world_id="w_other001"),
        _outbox_entry(ob_inject, "2026-10-06T13:00:00.000Z", "sent"),
    ]
    t_rec, t_old = NOW_EPOCH - 3600, NOW_EPOCH - WINDOW_S - 10
    fyi_mail = [
        {"user_id": USER, "message_id": "msg_fyi_1", "category": "fyi", "priority": "normal", "triaged_at": t_rec},
        {"user_id": "u_other", "message_id": "msg_for", "category": "fyi", "priority": "normal", "triaged_at": t_rec},
        {"user_id": USER, "message_id": "bad\nhttp://x", "category": "fyi", "priority": "normal", "triaged_at": t_rec},
        {"user_id": USER, "message_id": "msg_old", "category": "fyi", "priority": "low", "triaged_at": t_old},
        {"user_id": USER, "message_id": "msg_rep", "category": "needs_reply", "priority": "high", "triaged_at": t_rec},
    ]  # fmt: skip

    builder = DailyDigestBuilder(base_url=BASE_URL)
    digest = builder.build(
        user_id=USER, world_ids=(WORLD,), events=events, outbox_entries=outbox_entries, fyi_mail=fyi_mail, now=NOW_TS
    )
    assert digest is not None and [a.outbox_id for a in digest.actions] == [ob_l2, ob_l3, ob_sched]
    assert digest.skipped_outbox_ids == (ob_missing, ob_inject) and len(digest.skipped_fyi_ids) == 1
    assert [m.message_id for m in digest.fyi_mail] == ["msg_fyi_1"] and "evil.example" not in digest.rendered_text
    by_id = {a.outbox_id: a for a in digest.actions}
    assert by_id[ob_l2].link_kind == "report" and by_id[ob_l2].action_url.startswith(f"{BASE_URL}/l/")
    assert by_id[ob_sched].link_kind == "undo" and by_id[ob_sched].action_url.startswith(f"{BASE_URL}/l/")
    undo_token = by_id[ob_sched].action_url.removeprefix(f"{BASE_URL}/l/")
    with pytest.raises(LinkRefused, match="wrong_user"):
        builder.redeem(undo_token, outbox_id=ob_sched, option="undo", viewer="u_other", now=NOW_EPOCH + 10)
    with pytest.raises(LinkRefused, match="expired"):
        builder.redeem(undo_token, outbox_id=ob_sched, option="undo", viewer=USER, now=NOW_EPOCH + WINDOW_S + 10)
    redemption = builder.redeem(undo_token, outbox_id=ob_sched, option="undo", viewer=USER, now=NOW_EPOCH + 10)
    assert (redemption.card_id, redemption.user_id, redemption.option) == (ob_sched, USER, "undo")
    with pytest.raises(LinkRefused, match="used"):
        builder.redeem(undo_token, outbox_id=ob_sched, option="undo", viewer=USER, now=NOW_EPOCH + 15)


def test_FR_CHN_18_real_tilo_policy_decide_and_check_entry_with_artifact_emit_and_idempotency() -> None:
    enqueued, emitted, proposals = list[tuple[dict[str, Any], dict[str, Any]]](), list[dict[str, Any]](), list[tilo_policy.Proposal]()  # noqa: E501  # fmt: skip
    by_key: dict[tuple[str, str], dict[str, Any]] = {}

    class FakeOutbox:
        def enqueue(self, entry: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
            enqueued.append((entry, evidence))
            by_key[(entry["world_id"], entry["idempotency_key"])] = entry
            return entry

        def cancel(self, outbox_id: str) -> dict[str, Any]:
            return {"state": "cancelled"}

        def get(self, outbox_id: str) -> dict[str, Any] | None:
            return None

        def get_by_idempotency_key(self, world_id: str, idempotency_key: str) -> dict[str, Any] | None:
            return by_key.get((world_id, idempotency_key))

        def revoke(self, world_id: str, idempotency_key: str) -> dict[str, Any] | None:
            return None

    class RealEnginePort:
        def __init__(self, policies: list[dict[str, Any]], now_ts: str = NOW_TS) -> None:
            self.policies, self.now_ts = policies, now_ts

        def decide(self, user_id: str, proposal: tilo_policy.Proposal) -> tilo_policy.Decision:
            proposals.append(proposal)
            return tilo_policy.decide(proposal, table=RISK_TABLE, policies=self.policies, world_owner=user_id, applied=emitted, now=self.now_ts)  # noqa: E501  # fmt: skip

        def policy_for(self, user_id: str, policy_id: str) -> dict[str, Any] | None:
            return next((p for p in self.policies if p["id"] == policy_id and p["owner"] == user_id), None)

    ob_l2 = "01J8Z3K4M5N6P7Q8R9S0T1V2B1"
    events, outbox_entries = [_policy_ev(1, "2026-10-06T15:00:00.000Z", ob_l2, "L2")], [_outbox_entry(ob_l2, "2026-10-06T15:00:00.000Z", "sent")]  # noqa: E501  # fmt: skip
    builder, artifacts, outbox = DailyDigestBuilder(base_url=BASE_URL), DigestArtifacts(), FakeOutbox()
    mailbox = lambda uid: OWNER_EMAIL if uid == USER else None  # noqa: E731

    for blocked_pol in ([_digest_policy(level="L2")], [_digest_policy(level="L1")]):
        svc = DigestService(builder=builder, outbox=outbox, policy=RealEnginePort(blocked_pol), artifacts=artifacts, emit=emitted.append, mailbox=mailbox, world_id=WORLD, world_owner=USER, run_id=RUN)  # noqa: E501  # fmt: skip
        assert svc.deliver_if_non_empty(user_id=USER, events=events, outbox_entries=outbox_entries, now=NOW_TS) is None
        assert enqueued == [] and emitted == []

    l3_pol = _digest_policy(level="L3", undo_window_s=60)
    allow_svc = DigestService(builder=builder, outbox=outbox, policy=RealEnginePort([l3_pol]), artifacts=artifacts, emit=emitted.append, mailbox=mailbox, world_id=WORLD, world_owner=USER, run_id=RUN)  # noqa: E501  # fmt: skip
    assert allow_svc.deliver_if_non_empty(user_id=USER, events=[], now=NOW_TS) is None
    assert allow_svc.deliver_if_non_empty(user_id=USER, recipient="stranger@example.com", events=events, outbox_entries=outbox_entries, now=NOW_TS) is None  # noqa: E501  # fmt: skip
    res = allow_svc.deliver_if_non_empty(user_id=USER, events=events, outbox_entries=outbox_entries, now=NOW_EPOCH - 5)
    assert res is not None and len(enqueued) == 1 and len(emitted) == 1
    entry, evidence = enqueued[0]
    applied = evidence["authorised_by"]
    assert event_ok(applied, ("policy.applied",)) and conforms("outbox.schema.json", entry)
    assert entry["idempotency_key"] == f"digest:{USER}:2026-10-06" and entry["recipients"] == [OWNER_EMAIL]
    assert entry["created_at"] == NOW_TS and entry["scheduled_at"] == "2026-10-06T18:01:00.000Z"
    assert artifacts.get(entry["item"]["artifact_id"], entry["item"]["version"])["body_text"].startswith("Daily Digest")
    assert proposals[-1].facts.known_recipients == (OWNER_EMAIL,)
    assert tilo_policy.check_entry({"entry": entry, "reserved_by": None, "authorised_by": applied, "policy": l3_pol, "team_lead": None, "world_owner": USER, "instruction": None, "earlier_applied": [], "transfer": None, "rule": None}, table=RISK_TABLE) is None  # noqa: E501  # fmt: skip
    second = allow_svc.deliver_if_non_empty(user_id=USER, events=events, outbox_entries=outbox_entries, now="2026-10-06T18:00:10.000Z")  # noqa: E501  # fmt: skip
    assert second == entry and len(enqueued) == 1 and len(emitted) == 1
