"""FR-CHN-17e: the owner's standing L3 `send_push` policy is made only by the owner's explicit confirm, through the
store and event paths every policy uses; ending it ends delivery at once; a member keeps delivery off.
"""

from __future__ import annotations

import pytest
from _ppl11a_lib import OWNER, PRIYA
from tilo_api import deps, push_policy
from tilo_channels.web_push import SubscriptionStore, load_config
from tilo_policy.schemas import conforms

ENDPOINT = "https://fcm.googleapis.com/fcm/send/" + "a" * 40
KEYS = {"p256dh": "B" + "x" * 86, "auth": "y" * 22}
STATUS, SUBSCRIBE, POLICY = "/v1/push", "/v1/push/subscribe", "/v1/push/policy"


@pytest.fixture()
def rig(people_rig):
    class R:
        def __init__(self) -> None:
            self.p = people_rig()
            self.p.add_people()
            self.push = SubscriptionStore()
            self.store = self.p.event_store  # the store the rig's event writer reads worlds from
            self.p.app.dependency_overrides[deps.get_push_store] = lambda: self.push
            self.p.app.dependency_overrides[deps.get_store] = lambda: self.store

        def on(self, confirm: bool | None = True):
            body: dict = {"on": True} if confirm is None else {"on": True, "confirm": confirm}
            return self.p.post(POLICY, body)

        def changed(self, user: str = OWNER) -> list[dict]:
            return [
                e
                for w, evs in self.store.events.items()
                if self.store.worlds[w].owner == user
                for e in evs
                if e["type"] == "policy.changed"
            ]

    return R()


def test_FR_CHN_17e_no_policy_without_the_explicit_confirm(rig) -> None:
    for body in ({"on": True}, {"on": True, "confirm": False}):
        res = rig.p.post(POLICY, body)
        assert (res.status_code, res.json()["detail"]) == (422, "confirm_required")
    assert rig.store.policies == {} and rig.changed() == []
    assert rig.p.post(POLICY, {"on": True, "confirm": True, "user": PRIYA}).status_code == 422  # no identity field
    assert rig.store.policies == {}
    assert rig.p.get(STATUS).json()["delivery"] == "off_until_owner_policy"
    rig.p.full_session = False
    assert rig.on().status_code == 403
    rig.p.full_session = True
    rig.p.as_user(PRIYA, role="viewer")
    assert rig.on().status_code == 403
    assert rig.store.policies == {}  # a member never creates one, whatever the body says


def test_FR_CHN_17e_confirm_makes_one_owner_policy_through_the_store_and_the_event_path(rig) -> None:
    assert rig.p.post(SUBSCRIBE, {"endpoint": ENDPOINT, "keys": KEYS}).json()["delivery"] == "off_until_owner_policy"
    res = rig.on()
    assert (res.status_code, res.json()["delivery"], res.json()["devices"]) == (200, "ready", 1)
    (policy,) = rig.store.policies.values()
    assert conforms("policy.schema.json", policy)
    assert policy["id"] == push_policy.policy_id(OWNER) and policy["owner"] == OWNER
    assert (policy["action_type"], policy["level"], policy["undo_window_s"]) == ("send_push", "L3", 0)
    assert policy["scope"]["connectors"] == ["web_push"]
    assert policy["limits"]["per_day"] == load_config().per_day
    assert policy["created_by"]["by"] == OWNER and policy["history"][-1]["by"] == OWNER
    (event,) = rig.changed()
    assert event["data"] == {"policy_id": policy["id"], "change": "created", "level": "L3"}
    assert event["authz"]["by"] == "person" and event["authz"]["ref"] == OWNER
    assert rig.on().json()["delivery"] == "ready" and len(rig.store.policies) == 1 and len(rig.changed()) == 1


def test_FR_CHN_17e_off_ends_the_policy_and_removes_devices_at_once_and_on_again_works(rig) -> None:
    rig.p.post(SUBSCRIBE, {"endpoint": ENDPOINT, "keys": KEYS})
    rig.on()
    res = rig.p.post(POLICY, {"on": False})
    assert (res.status_code, res.json()["delivery"], res.json()["devices"]) == (200, "off_until_owner_policy", 0)
    (policy,) = rig.store.policies.values()
    assert policy["level"] == "L1" and policy["history"][-1]["level"] == "L1" and policy["history"][-1]["by"] == OWNER
    assert rig.push.for_user(OWNER) == ()
    assert [e["data"]["level"] for e in rig.changed()] == ["L3", "L1"]
    assert rig.p.get(STATUS).json()["delivery"] == "off_until_owner_policy"
    assert rig.p.post(POLICY, {"on": False}).status_code == 200 and len(rig.changed()) == 2  # nothing more to end
    assert rig.on().json()["delivery"] == "ready"
    assert [e["data"]["level"] for e in rig.changed()] == ["L3", "L1", "L3"]


def test_FR_CHN_17e_another_persons_policy_makes_nothing_ready_for_me_or_for_a_member(rig) -> None:
    rig.p.as_user(PRIYA)
    assert rig.on().json()["delivery"] == "ready"
    rig.p.as_user(OWNER)
    assert rig.p.get(STATUS).json()["delivery"] == "off_until_owner_policy"  # Priya's policy is Priya's
    rig.p.as_user(PRIYA, role="viewer")  # a member role keeps delivery off even where a record names them
    assert rig.p.get(STATUS).json()["delivery"] == "off_until_owner_policy"
