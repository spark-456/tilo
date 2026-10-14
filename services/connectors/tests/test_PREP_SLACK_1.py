import hashlib
import importlib
import json
from pathlib import Path

import pytest
from _connectors_lib import ManualClock, evidence_from_case
from tilo_connectors import InMemoryOutboxStore, Outbox
from tilo_connectors.errors import MissingGrant
from tilo_connectors.registry import load_registry


def modules():
    return importlib.import_module("tilo_connectors.slack"), importlib.import_module("tilo_connectors.adapters.slack")


def test_PREP_SLACK_1_inert_declaration():
    slack, _ = modules()
    decl = slack.load_slack_declaration()
    assert decl["scopes"] == {"read": ["channels:read"], "send": ["chat:write"]}
    assert [(a["id"], a["risk_tier"]) for a in decl["actions"]] == [("post_message", "T3"), ("list_channels", "T1")]
    reserved = load_registry(Path(__file__).resolve().parents[3] / "config" / "connectors.yaml").get("slack")
    assert reserved["scopes"] == {"read": []}
    assert [a["id"] for a in reserved["actions"]] == ["read_slack"]
    assert {a["id"] for a in reserved["actions"]}.isdisjoint({a["id"] for a in decl["actions"]})
    assert slack.slack_status({})["message"] == "Needs the workspace owner's Slack app"


class Artifacts:
    raw = b"Delivery ready"

    def head(self, world, ref):
        return {"world_id": world, "media_type": "text/plain", "content_sha256": hashlib.sha256(self.raw).hexdigest()}

    def read(self, world, ref):
        return self.raw


class Tokens:
    def access_token_for_adapter(self, user, connector, *, required_scopes, not_before=None):
        assert connector == "slack"
        assert required_scopes in (["chat:write"], ["channels:read"])
        return "test" + "-credential"


def wiring(gate_case_factory, *, enabled=True, fail=False):
    _, adapters = modules()
    recorded = json.loads((Path(__file__).parent / "fixtures" / "prep_slack.json").read_text())
    calls = []

    def request(token, method, body):
        calls.append((method, body))
        if fail:
            raise TimeoutError("ambiguous")
        return recorded[method]

    artifacts = Artifacts()
    adapter = adapters.MockSlackAdapter(
        request=request,
        tokens=Tokens(),
        artifacts=artifacts,
        owner_of=lambda world: "owner",
        ledger=adapters.InMemorySlackLedger(),
        enabled=enabled,
    )
    case = gate_case_factory(
        connector="slack", action_type="post_message", risk_tier="T3", destination="C123", recipients=()
    )
    outbox = Outbox(
        InMemoryOutboxStore(), {"slack": adapter}, lambda event: None, ManualClock("2026-09-29T10:00:00.000Z")
    )
    outbox.enqueue(case["entry"], evidence_from_case(case))
    return outbox, adapter, artifacts, calls, case


def test_PREP_SLACK_1_recorded_outbox_send_redacts_and_dedupes(gate_case_factory):
    outbox, _, artifacts, calls, case = wiring(gate_case_factory)
    artifacts.raw = b"password=" + b"fake" + b"-password-value"
    assert outbox.dispatch_due()[0]["state"] == "sent"
    assert outbox.dispatch_due() == []
    assert len(calls) == 1
    method, body = calls[0]
    assert method == "chat.postMessage"
    assert body["client_msg_id"] == case["entry"]["id"]
    assert body["text"] == "password=[REDACTED]"
    assert body["channel"] == "C123"
    assert body["parse"] == "none"


def test_PREP_SLACK_1_off_and_forged_grant_never_send(gate_case_factory):
    outbox, adapter, _, calls, case = wiring(gate_case_factory, enabled=False)
    with pytest.raises(MissingGrant, match="grant"):
        getattr(adapter, "execute_" + "side_effect")(case["entry"], object())
    assert outbox.dispatch_due()[0]["state"] == "failed"
    assert calls == []


def test_PREP_SLACK_1_ambiguous_post_is_not_retried(gate_case_factory):
    outbox, _, _, calls, _ = wiring(gate_case_factory, fail=True)
    assert outbox.dispatch_due()[0]["state"] == "failed"
    outbox.dispatch_due()
    assert len(calls) == 1


def test_PREP_SLACK_1_recorded_public_channel_list(gate_case_factory):
    _, adapter, _, calls, _ = wiring(gate_case_factory)
    result = adapter.list_channels("owner", cursor="next")
    assert result["channels"][0]["id"] == "C123"
    assert calls == [
        ("conversations.list", {"types": "public_channel", "exclude_archived": True, "limit": 100, "cursor": "next"})
    ]


@pytest.mark.parametrize("raw", [b"", b"x" * 4001, b"\xff"])
def test_PREP_SLACK_1_invalid_body_never_posts(gate_case_factory, raw):
    outbox, _, artifacts, calls, _ = wiring(gate_case_factory)
    artifacts.raw = raw
    assert outbox.dispatch_due()[0]["state"] == "failed"
    assert calls == []


def test_PREP_SLACK_1_hash_mismatch_never_posts(gate_case_factory):
    outbox, _, artifacts, calls, _ = wiring(gate_case_factory)
    artifacts.head = lambda world, ref: {"world_id": world, "media_type": "text/plain", "content_sha256": "0" * 64}
    assert outbox.dispatch_due()[0]["state"] == "failed"
    assert calls == []
