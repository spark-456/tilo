"""PIN-FIRESTORE-PARITY: exercise the pin route through the deployed Firestore seams."""

from __future__ import annotations

import pytest
from _ppl11a_lib import PRIYA
from _ppl11c_fs_lib import person


@pytest.mark.emulator
def test_PIN_FIRESTORE_PARITY_create_uses_real_people_and_api_stores(
    people_rig, pw1b_emulator_host: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tilo_api import deps, durable_store, prod

    project = "demo-pin-firestore-parity"
    org = "org_pin_firestore_parity"
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

    rig = people_rig(org=org)
    rig.unwire("people_stores", "event_writer", "desk_worlds")
    stores = deps.get_people_stores()
    stores.persons.create(person(PRIYA, org, email="priya.pin.parity@example.com"))
    rig.as_user(PRIYA)

    created = rig.client.post("/v1/pinboards", json={"title": "A durable pin"})

    assert created.status_code == 201, created.text
    pin_id = created.json()["id"]
    assert stores.pins.get(org, pin_id).record == created.json()

    # A request routed to another Cloud Run instance must not inherit the first instance's
    # idle Desk-world lease and roll its already-written pin back as a 503 WriterBusy.
    durable_store._opened.clear()
    second = rig.client.post("/v1/pinboards", json={"title": "A pin from another instance"})

    assert second.status_code == 201, second.text
    listed = rig.client.get("/v1/pinboards").json()["items"]
    assert {row["id"] for row in listed} == {created.json()["id"], second.json()["id"]}
