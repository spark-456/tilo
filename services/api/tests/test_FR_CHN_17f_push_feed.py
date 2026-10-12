"""FR-CHN-17f: the push feed. A new gate card of a person who turned push on (device + their own L3 policy) becomes one
notice through the policy engine and the outbox, sent by tilo-channels over an OIDC-checked call (a fake transport
here); fixed text, a path built from the card id; nothing for anyone else; nothing twice; nothing in dev or CI.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import httpx
import pytest
from _ppl11a_lib import OWNER, PRIYA
from test_S_06_cards_feed import START, World, at
from tilo_api import deps, push_feed, push_policy
from tilo_api.push_send import ChannelsPushRpc, PushRpcAdapter
from tilo_channels.web_push import SubscriptionStore
from tilo_connectors import InMemoryOutboxStore
from tilo_connectors.errors import SideEffectRefused
from tilo_harness.validator import repo_validator

ENDPOINT = "https://fcm.googleapis.com/fcm/send/" + "a" * 40
KEYS = {"p256dh": "B" + "x" * 86, "auth": "y" * 22}
URL = "https://tilo-channels-abc123.a.run.app"
NULL_TRACE = dict.fromkeys(("model_role", "profile", "tokens_in", "tokens_out", "tool", "latency_ms", "archive_ref"))


class Channels:
    """tilo-channels, in process: records every call and answers like its send route."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.status, self.gone = 200, list[int]()

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.calls.append({"path": request.url.path, "auth": request.headers.get("authorization"), "body": body})
        if self.status != 200:
            return httpx.Response(self.status, json={"detail": "down"})
        n = len(body["devices"])
        return httpx.Response(200, json={"delivered": n - len(self.gone), "gone": self.gone, "refused": []})


class Feed:
    def __init__(self, people_rig: Any) -> None:
        self.p = people_rig()
        self.p.add_people()
        self.store, self.writer = self.p.event_store, self.p.events
        self.subs, self.outbox_store, self.channels = SubscriptionStore(), InMemoryOutboxStore(), Channels()
        self.now = datetime.fromisoformat(at(60).replace("Z", "+00:00"))
        rpc = ChannelsPushRpc(
            URL, token_for=lambda audience: "id-token", transport=httpx.MockTransport(self.channels.handler)
        )
        self.adapter = PushRpcAdapter(subscriptions=self.subs, rpc=rpc, final_error=SideEffectRefused)

    def turn_on(self, user: str, endpoint: str = ENDPOINT) -> None:
        self.subs.add(user, {"endpoint": endpoint, "keys": KEYS})
        push_policy.set_on(self.store, self.writer, user, at(1), True)

    def sweep(self) -> int:
        return push_feed.sweep(
            subs=self.subs, store=self.store, outbox_store=self.outbox_store, adapter=self.adapter,
            people=self.p.real, writer=self.writer, clock=lambda: self.now,
        )  # fmt: skip


@pytest.fixture()
def feed(people_rig):
    return Feed(people_rig)


def test_FR_CHN_17f_a_new_gate_card_is_one_fixed_text_notice_through_policy_and_outbox(feed) -> None:
    card = World(feed.store, "w_a", OWNER).add("gate", created_at=at(30))
    feed.turn_on(OWNER)
    assert feed.sweep() == 1
    (call,) = feed.channels.calls
    assert call["path"] == "/internal/push/send" and call["auth"] == "Bearer id-token"
    assert call["body"]["devices"] == [{"endpoint": ENDPOINT, "keys": KEYS}]
    assert call["body"]["title"] == push_feed.TITLE and call["body"]["body"] == ""
    assert call["body"]["path"] == f"/park/home?card={card['id']}" and call["body"]["tag"] == f"gate-{card['id']}"
    (entry,) = feed.outbox_store.all_entries()
    assert entry["state"] == "sent" and entry["action_type"] == "send_push" and entry["authz"]["by"] == "policy"
    assert entry["undo_window_s"] == 0 and entry["connector"] == "web_push"
    desk_events = [
        e for evs in feed.store.events.values() for e in evs if e["type"] in ("policy.applied", "data.transfer")
    ]
    assert sorted(e["type"] for e in desk_events) == ["data.transfer", "policy.applied"]
    assert {e["authz"]["by"] for e in desk_events} == {"policy"}  # every side-effect event carries authz
    for event in desk_events:  # the contract validator accepts what the feed wrote
        assert repo_validator().problems({**event, "trace": event.get("trace") or NULL_TRACE}) == []


def test_FR_CHN_17f_the_second_pass_a_restart_and_a_second_card_queue_exactly_once_each(feed) -> None:
    world = World(feed.store, "w_a", OWNER)
    world.add("gate", created_at=at(30))
    feed.turn_on(OWNER)
    assert (feed.sweep(), feed.sweep(), feed.sweep()) == (1, 0, 0)
    assert len(feed.channels.calls) == 1 and len(feed.outbox_store.all_entries()) == 1
    world.add("gate", created_at=at(40))
    assert feed.sweep() == 1 and len(feed.channels.calls) == 2 and len(feed.outbox_store.all_entries()) == 2


def test_FR_CHN_17f_only_people_who_turned_push_on_and_only_new_gate_cards_of_their_own(feed) -> None:
    World(feed.store, "w_a", OWNER).add("gate", created_at=at(30))
    World(feed.store, "w_p", PRIYA).add("gate", created_at=at(31))
    feed.subs.add(OWNER, {"endpoint": ENDPOINT, "keys": KEYS})  # a device but no policy: nothing
    assert feed.sweep() == 0 and feed.channels.calls == []
    feed.turn_on(PRIYA, ENDPOINT + "p")  # Priya's policy and device: only Priya's card, only Priya's device
    assert feed.sweep() == 1
    (call,) = feed.channels.calls
    assert [d["endpoint"] for d in call["body"]["devices"]] == [ENDPOINT + "p"]
    assert all(e["connector"] == "web_push" for e in feed.outbox_store.all_entries())
    # the owner has no policy yet, so their card still waits; once they turn it on, it goes to their own device only
    feed.turn_on(OWNER)
    assert feed.sweep() == 1
    assert [d["endpoint"] for d in feed.channels.calls[-1]["body"]["devices"]] == [ENDPOINT]


@pytest.mark.parametrize("kind", ["needs_you", "consent", "meeting"])
def test_FR_CHN_17f_only_gate_cards_and_only_fresh_ones_are_pushed(feed, kind: str) -> None:
    world = World(feed.store, "w_a", OWNER)
    feed.turn_on(OWNER)
    world.add(kind, created_at=at(30))
    world.add("gate", created_at=START)  # older than the feed window once the clock is an hour on
    feed.now = datetime.fromisoformat(at(3600).replace("Z", "+00:00"))
    assert feed.sweep() == 0 and feed.channels.calls == []


def test_FR_CHN_17f_ending_the_policy_ends_the_feed_at_once(feed) -> None:
    world = World(feed.store, "w_a", OWNER)
    feed.turn_on(OWNER)
    push_policy.set_on(feed.store, feed.writer, OWNER, at(2), False)
    world.add("gate", created_at=at(30))
    assert feed.sweep() == 0 and feed.channels.calls == [] and feed.outbox_store.all_entries() == []


def test_FR_CHN_17f_a_down_channels_service_never_duplicates_and_a_gone_device_is_removed(feed) -> None:
    World(feed.store, "w_a", OWNER).add("gate", created_at=at(30))
    feed.turn_on(OWNER)
    feed.channels.status = 503
    feed.sweep()
    assert len(feed.outbox_store.all_entries()) == 1  # queued once, not sent
    assert [e["state"] for e in feed.outbox_store.all_entries()] != ["sent"]
    feed.channels.status, feed.channels.gone = 200, [0]
    feed.now = datetime.fromisoformat(at(400).replace("Z", "+00:00"))
    feed.sweep()
    assert len(feed.outbox_store.all_entries()) == 1  # still one entry, however many passes
    assert feed.subs.for_user(OWNER) == ()  # the push service said the device is gone: removed


def test_FR_CHN_17f_nothing_is_sent_without_the_channels_url_or_with_a_wrong_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TILO_CHANNELS_URL", raising=False)
    assert deps.get_push_rpc() is None
    for bad in ("http://tilo-channels.a.run.app", "https://evil.example", "https://x.a.run.app.evil.example"):
        monkeypatch.setenv("TILO_CHANNELS_URL", bad)
        assert deps.get_push_rpc() is None
    monkeypatch.setenv("TILO_CHANNELS_URL", URL)
    assert isinstance(deps.get_push_rpc(), ChannelsPushRpc)
