import hashlib
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta

import pytest
from _connectors_lib import ManualClock, evidence_from_case
from tilo_channels.links import CardState, KeyRing, LinkService
from tilo_channels.quiet_hours import NotificationGate
from tilo_channels.slack_approval import SlackApprovalAdapter, render_approval
from tilo_connectors import InMemoryOutboxStore, Outbox
from tilo_connectors.errors import MissingGrant


class Dedupe:
    def __init__(self):
        self.keys = set()

    def claim(self, key, ttl_s):
        assert ttl_s == 86400
        if key in self.keys:
            return False
        self.keys.add(key)
        return True


class Artifacts:
    def __init__(self, world, raw):
        self.world, self.raw = world, raw

    def head(self, world, ref):
        return {
            "world_id": self.world,
            "media_type": "text/plain",
            "content_sha256": hashlib.sha256(self.raw).hexdigest(),
        }

    def read(self, world, ref):
        return self.raw


def rig(factory, *, flag="1", kind="gate", fail=False):
    case = factory(connector="slack", action_type="post_message", risk_tier="T3", destination="D123", recipients=())
    card = {
        "id": "card1",
        "world_id": case["entry"]["world_id"],
        "kind": kind,
        "rung": kind,
        "what_happened": "Approval needed @everyone <@U123>",
        "why_it_matters": "Review changes",
        "gate": {"risk_tier": "T3", "irreversible": True} if kind == "gate" else None,
        "options": [{"label": "Approve", "suggested": False, "irreversible": True}],
        "safe_default": "Skip",
        "answer_channels": ["app"],
    }
    now = [datetime(2026, 9, 29, 10, tzinfo=UTC)]
    links = LinkService(
        keys=KeyRing({"test": b"x" * 32}, "test"),
        nonces=None,
        clock=lambda: now[0],
        cards=lambda cid: CardState(card, False),
        base_url="https://tilo.example",
    )
    link = links.issue(card_id=card["id"], user_id="owner", action="open")
    artifacts = Artifacts(card["world_id"], render_approval(card, link).encode())
    calls = []

    def client(body):
        calls.append(body)
        if fail:
            raise TimeoutError("private provider detail")
        return {"ok": True, "channel": body["channel"], "ts": "1"}

    adapter = SlackApprovalAdapter(
        client=client,
        artifacts=artifacts,
        projection=lambda entry: (card, link),
        links=links,
        recipient=lambda world, user: "D123" if user == "owner" else "D999",
        notifications=NotificationGate(
            preferences={
                "owner": {
                    "quiet_hours": {"start": "09:00", "end": "11:00", "timezone": "UTC"},
                }
            },
            clock=lambda: now[0],
        ),
        dedupe=Dedupe(),
        environ={"TILO_SLACK_CHANNEL": flag},
    )
    outbox = Outbox(
        InMemoryOutboxStore(), {"slack": adapter}, lambda event: None, ManualClock("2026-09-29T10:00:00.000Z")
    )
    outbox.enqueue(case["entry"], evidence_from_case(case))
    return outbox, adapter, artifacts, calls, card, now, case


def test_signed_open_dm_only_through_outbox(gate_case_factory):
    outbox, adapter, artifacts, calls, card, now, case = rig(gate_case_factory)
    with pytest.raises(MissingGrant):
        getattr(adapter, "execute_" + "side_effect")(case["entry"], object())
    assert calls == []
    assert outbox.dispatch_due()[0]["state"] == "sent"
    assert outbox.dispatch_due() == []
    assert len(calls) == 1
    body = calls[0]
    assert body["channel"] == "D123"
    assert body["client_msg_id"] == case["entry"]["id"]
    assert "@everyone" not in body["text"] and "<@" not in body["text"]
    assert "https://tilo.example/l/" in body["text"]
    assert body["mrkdwn"] is False and body["unfurl_links"] is False
    assert "blocks" not in body


@pytest.mark.parametrize("flag", ["", "0", "true", "yes"])
def test_flag_is_default_off(gate_case_factory, flag):
    outbox, _, _, calls, *_ = rig(gate_case_factory, flag=flag)
    assert outbox.dispatch_due()[0]["state"] == "failed"
    assert calls == []


@pytest.mark.parametrize("kind,expected", [("needs_you", "failed"), ("gate", "sent"), ("blocked", "sent")])
def test_existing_quiet_hours_and_gate_exception(gate_case_factory, kind, expected):
    outbox, _, _, calls, *_ = rig(gate_case_factory, kind=kind)
    assert outbox.dispatch_due()[0]["state"] == expected
    assert len(calls) == (expected == "sent")


@pytest.mark.parametrize("fault", ["artifact", "world", "recipient", "expired"])
def test_changed_or_unbound_projection_never_sends(gate_case_factory, fault):
    outbox, adapter, artifacts, calls, card, now, _ = rig(gate_case_factory)
    if fault == "artifact":
        artifacts.raw += b"changed"
    elif fault == "world":
        card["world_id"] = "other"
    elif fault == "recipient":
        adapter._recipient = lambda world, user: "D999"
    else:
        now[0] += timedelta(days=2)
    assert outbox.dispatch_due()[0]["state"] == "failed"
    assert calls == []


def test_ambiguous_delivery_reservation_survives(gate_case_factory):
    outbox, adapter, _, calls, _, _, case = rig(gate_case_factory, fail=True)
    assert outbox.dispatch_due()[0]["state"] == "failed"
    outbox.dispatch_due()
    key = f"slack-approval:{case['entry']['world_id']}:{case['entry']['id']}:D123"
    assert adapter._dedupe.claim(key, 86400) is False
    assert len(calls) == 1


@pytest.mark.parametrize("flag", ["0", "1"])
def test_app_routes_never_import_adapter(flag):
    code = "import sys; import tilo_channels.app; assert 'tilo_channels.slack_approval' not in sys.modules"
    result = subprocess.run(
        [sys.executable, "-c", code], env={**os.environ, "TILO_SLACK_CHANNEL": flag}, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
