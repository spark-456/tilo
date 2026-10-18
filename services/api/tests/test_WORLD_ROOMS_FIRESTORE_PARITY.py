"""WORLD-ROOMS-FIRESTORE-PARITY: convene through the deployed Firestore seams."""

from __future__ import annotations

import json

import pytest
from _api_lib import REPO_ROOT, WORLD
from _mroom_a1_lib import make_env
from _ppl11a_lib import PRIYA


def test_WORLD_ROOMS_FIRESTORE_PARITY_repeated_convene_returns_existing_room_in_memory(tmp_path) -> None:
    env = make_env(tmp_path)

    created = env.convene()
    repeated = env.convene()

    assert created.status_code == 201
    assert repeated.status_code == 200
    assert repeated.json() == created.json()
    assert [event["type"] for event in env.room_events()].count("meeting.convened") == 1


@pytest.mark.emulator
def test_WORLD_ROOMS_FIRESTORE_PARITY_repeated_convene_returns_the_existing_room(
    people_rig, pw1b_emulator_host: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tilo_api import deps, durable_store, prod

    project = "demo-world-rooms-parity"
    for name in ("K_SERVICE", "CLOUD_RUN_JOB", "GOOGLE_CLOUD_PROJECT", "TILO_API_DEV"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("FIRESTORE_EMULATOR_HOST", pw1b_emulator_host)
    monkeypatch.setenv("TILO_FIRESTORE_PROJECT", project)
    monkeypatch.setenv("TILO_PEOPLE_STORE", "firestore")
    monkeypatch.setenv("TILO_TEAM_STORE", "firestore")
    monkeypatch.setenv("TILO_SKILLS_STORE", "firestore")
    monkeypatch.setenv("TILO_OUTBOX_STORE", "firestore")
    monkeypatch.setenv("TILO_API_STORE", "firestore")
    deps.get_people_stores.cache_clear()
    durable_store._opened.clear()
    prod.reset()

    rig = people_rig(org=deps.ORG_ID)
    rig.unwire("event_writer")
    rig.as_user(PRIYA, world_id=WORLD)
    stored_layout = json.loads((REPO_ROOT / "contracts/fixtures/layout/valid/village_basic.json").read_text())
    world = deps.WorldRecord(
        owner=PRIYA,
        districts={"D1": deps.DistrictRecord("One", "First district")},
        run_id="r_world_rooms_parity_1",
        layout=stored_layout,
    )
    store, writer = durable_store.deployed()
    store.save(writer, worlds={WORLD: world}, create=(("worlds", WORLD),))
    body = {"lead": "A_dir", "agents": ["A_l1"]}

    created = rig.client.post(f"/v1/worlds/{WORLD}/rooms", json=body)
    assert created.status_code == 201, created.text

    # A retry can reach another service instance after the first response was lost.
    durable_store._opened.clear()
    fresh, _ = durable_store.deployed()
    fresh.load_world(WORLD)
    assert [event["type"] for event in fresh.events[WORLD]].count("meeting.convened") == 1
    repeated = rig.client.post(f"/v1/worlds/{WORLD}/rooms", json=body)

    assert repeated.status_code == 200, repeated.text
    assert repeated.json() == created.json()
    assert [event["type"] for event in fresh.events[WORLD]].count("meeting.convened") == 1
