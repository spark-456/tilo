"""CH-RM follow-up (issue #388 item 3), FR-HIL-07 as amended (SD-01, ADR-0019): a kill-switch confirmation goes to the
web and by email only. A stored `owner_channels` that still lists whatsapp (or anything else) never repeats it."""

from __future__ import annotations

import pytest
from _api_lib import OWNER, WORLD, as_principal, base_policy, make_principal, make_world


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        (("web", "email"), [{"channel": "web"}, {"channel": "email"}]),
        (("web", "whatsapp", "email"), [{"channel": "web"}, {"channel": "email"}]),
        (("whatsapp",), []),
        (("mobile_web", "sms", "web"), [{"channel": "web"}]),
    ],
)
def test_CH_RM_FR_HIL_07_confirmations_name_only_web_and_email(client, store, writer, stored, expected):
    store.worlds[WORLD] = make_world(owner=OWNER)
    store.worlds[WORLD].owner_channels = stored
    store.policies["pol_a"] = base_policy(id_="pol_a", owner=OWNER, level="L3")
    store.policy_worlds["pol_a"] = WORLD
    as_principal(make_principal(user_id=OWNER, world_id=WORLD))

    resp = client.post(f"/worlds/{WORLD}/autopilot/stop")

    assert resp.status_code == 200, resp.text
    assert resp.json()["confirmations"] == expected
