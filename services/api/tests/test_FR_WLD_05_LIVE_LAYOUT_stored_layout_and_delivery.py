"""LIVE-LAYOUT (FR-WLD-05, FR-AGT-02): a deployed run is read by a sign-in session bound to no world, from a record
store that has outlived the in-process `Run`. The layout comes from the stored world record when no run holds it, and
the owner's delivery needs no world-bound session."""

from __future__ import annotations

import copy
import json

from _api_lib import OWNER, WORLD, as_principal, base_event, make_principal, make_world


def _layout(repo_root) -> dict:
    path = repo_root / "contracts" / "fixtures" / "layout" / "valid" / "village_semantic_only.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _unbound_owner():
    return make_principal(world_id=None, channel="web")  # what a deployed Google sign-in is (principal_from_claims)


def test_FR_WLD_05_layout_is_served_from_the_stored_record_when_no_run_holds_it(client, store, repo_root):
    layout = _layout(repo_root)
    world = make_world(owner=OWNER)
    world.layout = copy.deepcopy(layout)
    store.worlds[WORLD] = world  # a run that finished or lives in another instance: store.runs is empty
    as_principal(_unbound_owner())
    response = client.get(f"/worlds/{WORLD}/layout")
    assert response.status_code == 200
    assert response.json() == layout


def test_FR_WLD_05_a_world_with_no_stored_layout_and_no_run_is_still_404(client, store):
    store.worlds[WORLD] = make_world(owner=OWNER)
    as_principal(_unbound_owner())
    assert client.get(f"/worlds/{WORLD}/layout").status_code == 404


def test_FR_AGT_02_owner_delivery_with_an_unbound_sign_in_session(client, store):
    store.worlds[WORLD] = make_world(owner=OWNER)
    kw = {"world_id": WORLD}
    store.events[WORLD] = [
        base_event(seq=1, type_="world.requested", data={"title": "T"}, summary="asked", **kw),
        base_event(seq=2, type_="world.completed", data={"credits_used": 2}, summary="done", **kw),
    ]
    as_principal(_unbound_owner())
    response = client.get(f"/worlds/{WORLD}/delivery")
    assert response.status_code == 200
    assert response.json()["credits_used"] == 2


def test_FR_AGT_02_another_persons_unbound_session_still_gets_the_unknown_world_404(client, store):
    store.worlds[WORLD] = make_world(owner=OWNER)
    store.events[WORLD] = [
        base_event(seq=1, type_="world.completed", data={"credits_used": 2}, summary="d", world_id=WORLD)
    ]
    as_principal(make_principal(user_id="u_someone_else", world_id=None, channel="web"))
    assert client.get(f"/worlds/{WORLD}/delivery").status_code == 404
