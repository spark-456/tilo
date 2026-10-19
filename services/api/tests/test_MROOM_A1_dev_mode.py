"""MROOM-A1 in dev mode (`just dev-api`): a free deterministic room model and an in-memory archive; every room event
passes the contract validator the dev writer runs (registry data schemas included). No network, no paid call."""

from __future__ import annotations

from _api_contracts_lib import make_safety_provider
from _api_lib import WORLD
from _mroom_a1_lib import layout
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tilo_api import deps, dev
from tilo_api.meeting_room import router


def test_MROOM_A1_dev_mode_rooms_run_end_to_end_with_validated_events():
    app = FastAPI()
    app.include_router(router)
    dev.install(app, {})
    app.dependency_overrides[deps.get_safety] = lambda: make_safety_provider()
    store = app.dependency_overrides[deps.get_store]()
    store.worlds[WORLD] = deps.WorldRecord(
        owner=dev.DEV_OWNER, districts={}, run_id="r_village_basic_1", layout=layout()
    )
    client = TestClient(app, base_url=f"http://localhost:{dev.PORT}")
    room = client.post(f"/v1/worlds/{WORLD}/rooms", json={"lead": "A_l1", "agents": []})
    assert room.status_code == 201, room.text
    rid = room.json()["room_id"]
    turn = client.post(
        f"/v1/worlds/{WORLD}/rooms/{rid}/turns", json={"to": "A_l1", "text": "What did you do?", "mode": "thinking"}
    )
    assert (
        turn.status_code == 202
        and turn.json()["reply"]["outcome"] == "answered"
        and turn.json()["reply"]["units"] == ["U1"]
    )
    assert client.get(f"/v1/worlds/{WORLD}/rooms/{rid}").json()["turns"][0]["text"] == "What did you do?"
    assert client.post(f"/v1/worlds/{WORLD}/rooms/{rid}/adjourn").json()["reason"] == "person"
    assert [e["type"] for e in store.events[WORLD]] == [
        "meeting.convened",
        "meeting.asked",
        "meeting.replied",
        "meeting.adjourned",
    ]
