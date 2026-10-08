"""FR-CHN-18 (PRD 11.4, 11.6, FR-HIL-13): DigestService, ports, quiet hours, and real Outbox/policy wiring."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import tilo_policy
from test_FR_CHN_18_daily_digest import (
    BASE_URL,
    NOW_EPOCH,
    NOW_TS,
    RUN,
    USER,
    WORLD,
    _keys,
    _NonceStore,
    _outbox_entry,
    _policy_ev,
)
from tilo_channels.digest import DailyDigestBuilder, DigestArtifacts, DigestService
from tilo_connectors.outbox import InMemoryOutboxStore, Outbox
from tilo_policy.schemas import conforms, event_ok

OWNER_EMAIL = "owner@example.com"
RISK_TABLE = tilo_policy.load_risk_table(Path(__file__).resolve().parents[3] / "config/autonomy.yaml")


def _builder() -> DailyDigestBuilder:
    return DailyDigestBuilder(base_url=BASE_URL, keys=_keys(), nonces=_NonceStore())


def _mailbox(uid: str) -> str | None:
    return OWNER_EMAIL if uid == USER else None


def _digest_policy(level: str = "L3", undo_window_s: int = 60, per_day: int = 1) -> dict[str, Any]:
    created = "2026-10-01T09:00:00.000Z"
    scope = {"connectors": ["gmail"], "recipients": [OWNER_EMAIL], "domains": [], "districts": ["D1"]}
    conds = {"no_attachments": True, "no_new_recipients": True, "no_safety_flags": True}
    hist = [{"by": USER, "at": created, "change": f"Created at {level}", "level": level}]
    pol: dict[str, Any] = {"id": "pol_digest_l3", "owner": USER, "action_type": "send_email", "scope": scope}
    pol |= {"limits": {"per_day": per_day, "credits": 10}, "conditions": conds, "level": level}
    pol |= {"undo_window_s": undo_window_s, "expiry": None, "notify_channel": "email", "team_lead_domains": []}
    return pol | {"created_by": {"by": USER, "at": created}, "changed_by": None, "history": hist}


def _feed() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ob_id, ts = "01J8Z3K4M5N6P7Q8R9S0T1V2B1", "2026-10-06T15:00:00.000Z"
    return [_policy_ev(1, ts, ob_id, "L2")], [_outbox_entry(ob_id, ts, "sent")]


class _RealEnginePort:
    def __init__(self, policies: list[dict[str, Any]], emitted: list[dict[str, Any]], now_ts: str = NOW_TS) -> None:
        self.policies, self.emitted, self.now_ts = policies, emitted, now_ts
        self.proposals: list[tilo_policy.Proposal] = []

    def decide(self, user_id: str, proposal: tilo_policy.Proposal) -> tilo_policy.Decision:
        self.proposals.append(proposal)
        return tilo_policy.decide(
            proposal,
            table=RISK_TABLE,
            policies=self.policies,
            world_owner=user_id,
            applied=self.emitted,
            now=self.now_ts,
        )

    def policy_for(self, user_id: str, policy_id: str) -> dict[str, Any] | None:
        return next((p for p in self.policies if p["id"] == policy_id and p["owner"] == user_id), None)


def _svc(outbox: Outbox, policy: Any, artifacts: DigestArtifacts, emit: Any, prefs: Any = None) -> DigestService:
    return DigestService(
        builder=_builder(),
        outbox=outbox,
        policy=policy,
        artifacts=artifacts,
        emit=emit,
        mailbox=_mailbox,
        preferences=prefs,
        world_id=WORLD,
        world_owner=USER,
        run_id=RUN,
    )


def _deliver(svc: DigestService, now: Any = NOW_TS, recipient: str | None = None) -> dict[str, Any] | None:
    events, entries = _feed()
    return svc.deliver_if_non_empty(user_id=USER, recipient=recipient, events=events, outbox_entries=entries, now=now)


def test_FR_CHN_18_refuses_no_policy_raising_policy_raising_emit_and_respects_quiet_hours() -> None:
    store, emitted = InMemoryOutboxStore(), list[dict[str, Any]]()
    outbox = Outbox(store, connectors={}, emit=lambda _: None, clock=lambda: NOW_TS, world_id=WORLD)
    artifacts = DigestArtifacts()

    assert _deliver(_svc(outbox, None, artifacts, emitted.append)) is None
    assert emitted == [] and store.all_entries() == []

    class _RaisingPolicy:
        def decide(self, user_id: str, proposal: tilo_policy.Proposal) -> tilo_policy.Decision:
            raise RuntimeError("policy unavailable")

        def policy_for(self, user_id: str, policy_id: str) -> dict[str, Any] | None:
            return None

    assert _deliver(_svc(outbox, _RaisingPolicy(), artifacts, emitted.append)) is None
    assert emitted == [] and store.all_entries() == []

    def _raise_emit(_part: dict[str, Any]) -> None:
        raise RuntimeError("event log down")

    l3_pol = _digest_policy(level="L3", undo_window_s=60)
    emit_fail_store = InMemoryOutboxStore()
    emit_fail_outbox = Outbox(emit_fail_store, connectors={}, emit=lambda _: None, clock=lambda: NOW_TS, world_id=WORLD)
    assert _deliver(_svc(emit_fail_outbox, _RealEnginePort([l3_pol], emitted), artifacts, _raise_emit)) is None
    assert emitted == [] and [e["state"] for e in emit_fail_store.all_entries()] == ["cancelled"]

    for blocked in ([_digest_policy(level="L2")], [_digest_policy(level="L1")]):
        assert _deliver(_svc(outbox, _RealEnginePort(blocked, emitted), artifacts, emitted.append)) is None
        assert emitted == [] and store.all_entries() == []

    prefs = {USER: {"quiet_hours": {"start": "22:00", "end": "07:00", "timezone": "UTC"}}}
    qh_artifacts = DigestArtifacts()
    qh_svc = _svc(outbox, _RealEnginePort([l3_pol], emitted, now_ts=NOW_TS), qh_artifacts, emitted.append, prefs)
    assert _deliver(qh_svc, now="2026-10-06T23:30:00.000Z") is None
    assert emitted == [] and store.all_entries() == [] and qh_artifacts._by_ref == {}

    outside = _deliver(qh_svc, now=NOW_TS)
    assert outside is not None and len(emitted) == 1 and len(store.all_entries()) == 1


def test_FR_CHN_18_real_outbox_and_tilo_policy_decide_l3_stores_one_and_refuses_second_same_day() -> None:
    store, emitted = InMemoryOutboxStore(), list[dict[str, Any]]()
    outbox = Outbox(store, connectors={}, emit=lambda _: None, clock=lambda: NOW_TS, world_id=WORLD)
    artifacts = DigestArtifacts()
    l3_pol = _digest_policy(level="L3", undo_window_s=60, per_day=1)
    port = _RealEnginePort([l3_pol], emitted, now_ts=NOW_TS)
    svc = _svc(outbox, port, artifacts, emitted.append)

    assert _deliver(svc, recipient="stranger@example.com") is None
    res = _deliver(svc, now=NOW_EPOCH - 5)
    assert res is not None and len(store.all_entries()) == 1 and len(emitted) == 1
    assert event_ok(emitted[0], ("policy.applied",)) and conforms("outbox.schema.json", res)
    assert res["idempotency_key"] == f"digest:{USER}:2026-10-06" and res["recipients"] == [OWNER_EMAIL]
    assert artifacts.get(res["item"]["artifact_id"], res["item"]["version"])["body_text"].startswith("Daily Digest")
    assert port.proposals[-1].facts.known_recipients == (OWNER_EMAIL,)

    assert _deliver(svc, now="2026-10-06T18:00:10.000Z") is None
    assert len(store.all_entries()) == 1 and len(emitted) == 1

    store2 = InMemoryOutboxStore()
    outbox2 = Outbox(store2, connectors={}, emit=lambda _: None, clock=lambda: NOW_TS, world_id=WORLD)
    svc2 = _svc(outbox2, port, artifacts, emitted.append)
    assert _deliver(svc2, now="2026-10-06T18:00:15.000Z") is None
    assert store2.all_entries() == [] and len(emitted) == 1


def test_FR_CHN_18_662_digest_service_emits_policy_applied_only_after_enqueue_and_logs_exception_type_not_body(
    caplog: Any,
) -> None:
    import logging

    import pytest
    from tilo_connectors.errors import OutboxRefused

    store, emitted = InMemoryOutboxStore(), list[dict[str, Any]]()
    real_outbox = Outbox(store, connectors={}, emit=lambda _: None, clock=lambda: NOW_TS, world_id=WORLD)
    artifacts = DigestArtifacts()
    l3_pol = _digest_policy(level="L3", undo_window_s=60, per_day=1)
    port = _RealEnginePort([l3_pol], emitted, now_ts=NOW_TS)

    class _FlakyOutbox:
        def __init__(self) -> None:
            self.fail_count = 2

        def enqueue(self, entry: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
            if self.fail_count == 2:
                self.fail_count -= 1
                raise OutboxRefused("outbox refused secret digest body leak")
            if self.fail_count == 1:
                self.fail_count -= 1
                raise RuntimeError("transient store error secret digest body leak")
            return real_outbox.enqueue(entry, evidence)

        def cancel(self, outbox_id: str) -> dict[str, Any]:
            return real_outbox.cancel(outbox_id)

        def get(self, outbox_id: str) -> dict[str, Any] | None:
            return real_outbox.get(outbox_id)

        def get_by_idempotency_key(self, world_id: str, idempotency_key: str) -> dict[str, Any] | None:
            return real_outbox.get_by_idempotency_key(world_id, idempotency_key)

        def revoke(self, world_id: str, idempotency_key: str) -> dict[str, Any] | None:
            return real_outbox.revoke(world_id, idempotency_key)

    flaky = _FlakyOutbox()
    svc = _svc(flaky, port, artifacts, emitted.append)  # type: ignore[arg-type]

    # 1. Failed enqueues do NOT emit policy.applied, so they do not count toward per_day=1 cap; logged by type only
    with caplog.at_level(logging.WARNING, logger="tilo_channels.digest"):
        assert _deliver(svc, now=NOW_EPOCH - 2) is None
        assert emitted == [] and store.all_entries() == []
        assert _deliver(svc, now=NOW_EPOCH - 1) is None
        assert emitted == [] and store.all_entries() == []

    msgs = "\n".join(r.getMessage() for r in caplog.records)
    assert "OutboxRefused" in msgs and "RuntimeError" in msgs
    assert "secret digest body leak" not in msgs and "Daily Digest" not in msgs

    # Retry succeeds on the same UTC day because earlier failed enqueues never emitted policy.applied
    ok = _deliver(svc, now=NOW_EPOCH)
    assert ok is not None and len(emitted) == 1 and len(store.all_entries()) == 1

    # 2. Quiet hours with unresolvable timezone fails closed in DigestService and holds the send
    bad_tz_prefs = {USER: {"quiet_hours": {"start": "22:00", "end": "07:00", "timezone": "NoSuch/Zone"}}}
    store_qh, emitted_qh = InMemoryOutboxStore(), list[dict[str, Any]]()
    outbox_qh = Outbox(store_qh, connectors={}, emit=lambda _: None, clock=lambda: NOW_TS, world_id=WORLD)
    svc_qh = _svc(outbox_qh, _RealEnginePort([l3_pol], emitted_qh), DigestArtifacts(), emitted_qh.append, bad_tz_prefs)
    with caplog.at_level(logging.WARNING):
        assert _deliver(svc_qh, now=NOW_TS) is None
    assert emitted_qh == [] and store_qh.all_entries() == []

    # 3. Unexpected bug exceptions are logged by exception type only (never body/message) and not silently swallowed
    class _UnexpectedBugError(Exception):
        pass

    class _BuggyPolicy:
        def decide(self, user_id: str, proposal: tilo_policy.Proposal) -> tilo_policy.Decision:
            raise _UnexpectedBugError("private body text should never appear in logs")

        def policy_for(self, user_id: str, policy_id: str) -> dict[str, Any] | None:
            return None

    caplog.clear()
    bug_svc = _svc(outbox_qh, _BuggyPolicy(), DigestArtifacts(), emitted_qh.append)
    with caplog.at_level(logging.ERROR, logger="tilo_channels.digest"), pytest.raises(_UnexpectedBugError):
        _deliver(bug_svc, now=NOW_TS)
    bug_logs = "\n".join(r.getMessage() for r in caplog.records)
    assert "_UnexpectedBugError" in bug_logs
    assert "private body text" not in bug_logs and "Daily Digest" not in bug_logs
