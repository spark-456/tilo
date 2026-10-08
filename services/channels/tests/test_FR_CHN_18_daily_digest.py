"""FR-CHN-18 (PRD 11.4, 11.6): Daily digest builder, signed links, scoping, and validation."""

from __future__ import annotations

import datetime as dt
import secrets
from typing import Any

import pytest
from tilo_channels.digest import WINDOW_S, DailyDigestBuilder
from tilo_channels.links import KeyRing, LinkRefused

NOW_TS, NOW_EPOCH = "2026-10-06T18:00:00.000Z", 1_791_309_600.0
USER, WORLD, RUN = "u_owner", "w_digest01", "r_digest01"
BASE_URL = "https://app.tilo.example"


class _NonceStore:
    def __init__(self) -> None:
        self._used: set[str] = set()

    def consume(self, nonce: str, expires_at: dt.datetime) -> bool:
        if nonce in self._used:
            return False
        self._used.add(nonce)
        return True


def _keys() -> KeyRing:
    return KeyRing({"k_digest": secrets.token_bytes(32)}, active="k_digest")


def _policy_ev(
    seq: int, ts: str, outbox_id: str, level: str = "L2", action_type: str = "send_email", world_id: str = WORLD
) -> dict[str, Any]:
    inst_id = f"01J8Z3K4M5N6P7Q8R9S0T1V3{seq:02d}" if level == "L2" else None
    data: dict[str, Any] = {"policy_id": "pol_auto_1", "gate_id": f"G{seq}", "outbox_id": outbox_id}
    data |= {"action_type": action_type, "connector": "gmail", "district": "D1", "level": level}
    data |= {"destination": "thr_1" if level == "L2" else None, "risk_tier": "T2" if level == "L2" else "T1"}
    data |= {"instruction_id": inst_id, "undo_window_s": 60 if level == "L2" else 0}
    data["item"] = {"artifact_id": f"art_{seq}", "version": 1}
    env: dict[str, Any] = {"v": "1.0", "id": f"01J8Z3K4M5N6P7Q8R9S0T1V2{seq:02d}", "seq": seq, "ts": ts}
    authz = {"by": "policy", "ref": "pol_auto_1", "at": ts}
    return env | {"world_id": world_id, "run_id": RUN, "type": "policy.applied", "authz": authz, "data": data}


def _outbox_entry(
    outbox_id: str, created_at: str, state: str = "sent", scheduled_at: str | None = None, world_id: str = WORLD
) -> dict[str, Any]:
    row: dict[str, Any] = {"id": outbox_id, "idempotency_key": f"autopilot:{outbox_id}", "world_id": world_id}
    row |= {"run_id": RUN, "action_type": "send_email", "connector": "gmail", "recipients": ["peer@example.com"]}
    row |= {"attachments": [], "item": {"artifact_id": f"art_{outbox_id[-2:]}", "version": 1}, "destination": "thr_1"}
    authz = {"by": "policy", "ref": "pol_auto_1", "at": created_at}
    return row | {
        "modifiers": [],
        "risk_tier": "T2",
        "authz": authz,
        "undo_window_s": 60,
        "scheduled_at": scheduled_at or created_at,
        "state": state,
        "created_at": created_at,
    }


def test_FR_CHN_18_lists_every_l2_and_l3_action_in_last_24h_with_signed_links_and_scoping() -> None:
    ob_l2, ob_l3, ob_sched = "01J8Z3K4M5N6P7Q8R9S0T1V2A1", "01J8Z3K4M5N6P7Q8R9S0T1V2A2", "01J8Z3K4M5N6P7Q8R9S0T1V2A3"
    ob_old, ob_missing = "01J8Z3K4M5N6P7Q8R9S0T1V2A0", "01J8Z3K4M5N6P7Q8R9S0T1V2A9"
    ob_foreign, ob_inject = "01J8Z3K4M5N6P7Q8R9S0T1V2A8", "01J8Z3K4M5N6P7Q8R9S0T1V2A7"
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
    ]

    builder = DailyDigestBuilder(base_url=BASE_URL, keys=_keys(), nonces=_NonceStore())
    digest = builder.build(
        user_id=USER, world_ids=(WORLD,), events=events, outbox_entries=outbox_entries, fyi_mail=fyi_mail, now=NOW_TS
    )
    assert digest is not None and [a.outbox_id for a in digest.actions] == [ob_l2, ob_l3, ob_sched]
    assert digest.skipped_outbox_ids == (ob_missing, ob_inject) and len(digest.skipped_fyi_ids) == 1
    assert "- 2 actions not listed" in digest.rendered_text
    assert [m.message_id for m in digest.fyi_mail] == ["msg_fyi_1"] and "evil.example" not in digest.rendered_text
    assert "/l/" not in repr(digest) and "/l/" not in repr(digest.actions[0])
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


def test_FR_CHN_18_redeem_without_now_uses_real_clock_and_refuses_expired_link() -> None:
    ob_id, issued_ts = "01J8Z3K4M5N6P7Q8R9S0T1V2C1", "2026-10-04T12:00:00.000Z"
    real_now = dt.datetime(2026, 10, 6, 18, 0, 0, tzinfo=dt.UTC)
    builder = DailyDigestBuilder(base_url=BASE_URL, keys=_keys(), nonces=_NonceStore(), clock=lambda: real_now)
    digest = builder.build(
        user_id=USER,
        world_ids=(WORLD,),
        events=[_policy_ev(1, issued_ts, ob_id, "L2")],
        outbox_entries=[_outbox_entry(ob_id, issued_ts, "sent")],
        now=issued_ts,
    )
    assert digest is not None
    report_token = digest.actions[0].report_url.removeprefix(f"{BASE_URL}/l/")
    with pytest.raises(LinkRefused, match="expired"):
        builder.redeem(report_token, outbox_id=ob_id, option="report", viewer=USER)
    real_now = dt.datetime(2026, 10, 5, 10, 0, 0, tzinfo=dt.UTC)
    ok = builder.redeem(report_token, outbox_id=ob_id, option="report", viewer=USER)
    assert (ok.card_id, ok.user_id, ok.option) == (ob_id, USER, "report")
