"""FR-CHN-17b: the person's own web-push subscription routes (PRD 11, 16; BQ-CHN17-1, BQ-CHN17b-1).

Full web sign-in session only; the owner is the verified principal; the endpoint is validated as untrusted input and
capped per person; nothing sensitive is returned or logged; and the answer says plainly that push is off until the
owner's own standing `send_push` policy exists.
"""

from __future__ import annotations

import logging

import pytest
from _ppl11a_lib import OWNER, PRIYA
from tilo_api import deps, push_policy
from tilo_channels.web_push import SubscriptionStore, load_config

ENDPOINT = "https://fcm.googleapis.com/fcm/send/" + "a" * 40
KEYS = {"p256dh": "B" + "x" * 86, "auth": "y" * 22}
SUBSCRIBE, UNSUBSCRIBE, STATUS = "/v1/push/subscribe", "/v1/push/unsubscribe", "/v1/push"


def _policy(owner: str, level: str = "L3") -> dict:
    return {"id": push_policy.policy_id(owner), "owner": owner, "action_type": "send_push", "level": level}


@pytest.fixture()
def rig(people_rig):
    class R:
        def __init__(self) -> None:
            self.p = people_rig()
            self.p.add_people()
            self.push = SubscriptionStore()
            self.world_store = deps.Store()
            self.p.app.dependency_overrides[deps.get_push_store] = lambda: self.push
            self.p.app.dependency_overrides[deps.get_store] = lambda: self.world_store

        def sub(self, endpoint: str = ENDPOINT, **over):
            return self.p.post(SUBSCRIBE, {"endpoint": endpoint, "keys": KEYS, **over})

    return R()


def test_FR_CHN_17b_subscribe_stores_for_the_principal_and_says_push_is_off_until_the_owner_policy(rig) -> None:
    res = rig.sub()
    assert (res.status_code, res.json()) == (
        200,
        {"devices": 1, "delivery": "off_until_owner_policy", "public_key": None},
    )
    assert res.headers["cache-control"] == "no-store"
    assert [s.endpoint for s in rig.push.for_user(OWNER)] == [ENDPOINT] and rig.push.for_user(PRIYA) == ()
    assert ENDPOINT not in res.text and KEYS["auth"] not in res.text
    assert rig.sub().json()["devices"] == 1  # the same device again replaces
    rig.world_store.policies[push_policy.policy_id(OWNER)] = _policy(OWNER)
    assert rig.p.get(STATUS).json() == {"devices": 1, "delivery": "ready", "public_key": None}
    rig.world_store.policies[push_policy.policy_id(OWNER)] = _policy(OWNER, level="L1")
    assert rig.p.get(STATUS).json()["delivery"] == "off_until_owner_policy"
    rig.world_store.policies.clear()
    rig.world_store.policies[push_policy.policy_id(PRIYA)] = _policy(PRIYA)  # someone else's covers nothing
    assert rig.p.get(STATUS).json()["delivery"] == "off_until_owner_policy"


def test_FR_CHN_17b_only_a_full_web_session_and_never_another_person(rig) -> None:
    rig.p.full_session = False
    assert rig.sub().status_code == 403 and rig.p.get(STATUS).status_code == 403
    rig.p.full_session = True
    rig.p.channel = "email"
    assert rig.sub().status_code == 403
    rig.p.channel = "mobile_web"
    assert rig.sub().status_code == 200
    rig.p.sign_out()
    assert rig.sub().status_code == 401
    rig.p.as_user(PRIYA)
    assert rig.p.get(STATUS).json()["devices"] == 0  # one person's devices are never another's
    assert rig.sub(user_id=OWNER).status_code == 422  # identity is never a body field
    assert [s.endpoint for s in rig.push.for_user(OWNER)] == [ENDPOINT] and rig.push.for_user(PRIYA) == ()


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://fcm.googleapis.com/fcm/send/x",
        "https://169.254.169.254/latest/meta-data",
        "https://evil.example/push",
        "https://fcm.googleapis.com/" + "a" * 2100,
        "javascript:alert(1)",
    ],
)
def test_FR_CHN_17b_endpoint_is_untrusted_input_and_never_echoed(rig, endpoint: str) -> None:
    res = rig.sub(endpoint)
    assert res.status_code == 422 and endpoint not in res.text
    assert rig.push.for_user(OWNER) == ()
    bad_keys = rig.p.post(SUBSCRIBE, {"endpoint": ENDPOINT, "keys": {"p256dh": "short", "auth": "!!"}})
    assert bad_keys.status_code == 422 and "short" not in bad_keys.text


def test_FR_CHN_17b_per_person_cap_unsubscribe_and_no_key_in_logs(rig, caplog: pytest.LogCaptureFixture) -> None:
    cap = load_config().max_subscriptions
    with caplog.at_level(logging.DEBUG):
        for n in range(cap):
            assert rig.sub(f"{ENDPOINT}{n}").status_code == 200
        over = rig.sub(f"{ENDPOINT}over")
        assert (over.status_code, over.json()["detail"]) == (409, "device_limit")
        gone = rig.p.post(UNSUBSCRIBE, {"endpoint": f"{ENDPOINT}0"})
        assert gone.status_code == 200 and gone.json()["devices"] == cap - 1
        assert rig.p.post(UNSUBSCRIBE, {"endpoint": f"{ENDPOINT}0"}).json()["devices"] == cap - 1  # idempotent
        assert rig.sub(f"{ENDPOINT}over").status_code == 200  # a freed slot is usable
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert KEYS["auth"] not in joined and KEYS["p256dh"] not in joined and ENDPOINT not in joined
    assert rig.p.post(UNSUBSCRIBE, {"endpoint": ENDPOINT, "extra": 1}).status_code == 422


def test_FR_CHN_17b_without_a_wired_store_the_route_is_503_not_configured(rig) -> None:
    rig.p.app.dependency_overrides.pop(deps.get_push_store)
    res = rig.sub()
    assert (res.status_code, res.json()["detail"]) == (503, "not_configured")


def test_FR_CHN_17d_status_carries_the_public_key_only_when_it_has_the_shape_of_one(
    rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = "B" + "x" * 86
    monkeypatch.setenv("TILO_WEBPUSH_VAPID_PUBLIC_KEY", key)
    assert rig.p.get(STATUS).json()["public_key"] == key
    for bad in ("short", "has space " + "x" * 90, "<script>" + "x" * 90):
        monkeypatch.setenv("TILO_WEBPUSH_VAPID_PUBLIC_KEY", bad)
        assert rig.p.get(STATUS).json()["public_key"] is None
