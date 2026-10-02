"""FR-HIL-09, SEC-07, CL-INT-4 item 4: the owner's events view is the full event record (PRD 15.3), so it carries
`v`, `world_id`, `run_id` and `item` that event.schema.json requires; every other role's redacted view is unchanged
(it never had those four, and still has exactly its allowlisted keys)."""

from __future__ import annotations

from _api_lib import OWNER, WORLD, as_principal, base_event, make_district, make_principal, make_world

D1, D2 = "D1", "D2"
ITEM = {"kind": "parcel", "artifact_id": "art_reply_draft", "label": "Reply draft"}
FOUR = ("v", "world_id", "run_id", "item")
SCOPED_KEYS = {
    "seq", "id", "ts", "type", "actor", "target", "level", "severity", "credits", "summary", "authz", "district",
    "cause", "vis", "data", "trace",
}  # fmt: skip


def seed(store) -> list[dict]:
    store.worlds[WORLD] = make_world(
        owner=OWNER, districts={D1: make_district("Mail", "m"), D2: make_district("Ops", "o")}
    )
    store.events[WORLD] = [
        base_event(seq=1, type_="world.started", data={"budget_cap": 40}),
        {**base_event(seq=2, type_="agent.working", data={"unit": None}, district=D1, vis=[D1]), "item": ITEM},
    ]
    return store.events[WORLD]


def test_FR_HIL_09_SEC_07_CL_INT_4_owner_view_has_v_world_id_run_id_and_item(client, store):
    stored = seed(store)
    as_principal(make_principal())
    events = client.get(f"/worlds/{WORLD}/events").json()["events"]
    assert events == stored, "the owner's view is the stored record, whole"
    for e in events:
        assert all(k in e for k in FOUR)
        assert (e["v"], e["world_id"], e["run_id"]) == ("1.0", WORLD, "r_village_basic_1")
    assert [e["item"] for e in events] == [None, ITEM]


def test_FR_HIL_09_SEC_07_CL_INT_4_owner_view_validates_against_the_event_schema(client, store):
    from _api_lib import validate_event

    seed(store)
    as_principal(make_principal())
    for e in client.get(f"/worlds/{WORLD}/events").json()["events"]:
        validate_event(e)


def test_FR_HIL_09_SEC_07_CL_INT_4_scoped_views_are_unchanged(client, store):
    seed(store)
    for role in ("viewer", "approver", "team_lead"):
        as_principal(make_principal(user_id=f"u_{role}", role=role, districts=(D1,)))
        events = client.get(f"/worlds/{WORLD}/events").json()["events"]
        assert len(events) == 2
        for e in events:
            assert set(e) == SCOPED_KEYS, role
            assert not any(k in e for k in FOUR), role
        assert [e["id"] for e in events] == ["v1", "v2"]


def test_FR_HIL_09_SEC_07_CL_INT_4_a_user_with_the_owners_id_but_another_role_gets_the_scoped_view(client, store):
    seed(store)
    as_principal(make_principal(user_id=OWNER, role="viewer", districts=(D2,)))
    events = client.get(f"/worlds/{WORLD}/events").json()["events"]
    assert [set(e) for e in events] == [SCOPED_KEYS]  # D1's event is dropped whole, the rest is unchanged
