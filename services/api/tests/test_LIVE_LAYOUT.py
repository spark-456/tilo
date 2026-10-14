"""LIVE-LAYOUT: missing records remain distinct from fabricated layouts or proposals."""

from _api_lib import OWNER, WORLD, as_principal, make_principal, make_world


def test_LIVE_LAYOUT_FR_WLD_05_mounted_route_keeps_missing_layout_and_access_private(client, store):
    store.worlds[WORLD] = make_world(owner=OWNER)
    as_principal(make_principal())
    assert client.get(f"/worlds/{WORLD}/events").status_code == 200
    assert client.get(f"/worlds/{WORLD}/layout").status_code == 404
    as_principal(make_principal(world_id="w_other"))
    assert client.get(f"/worlds/{WORLD}/events").status_code == 404
    assert client.get(f"/worlds/{WORLD}/layout").status_code == 404


def test_LIVE_LAYOUT_FR_AGT_15_mounted_proposals_route_does_not_grant_owner_expert_access(client, store):
    from tilo_api import app, console

    store.worlds[WORLD] = make_world(owner=OWNER)
    app.dependency_overrides[console.get_team_leads] = lambda: []
    as_principal(make_principal())
    assert client.get(f"/worlds/{WORLD}/skill-proposals").status_code == 403
    as_principal(make_principal(world_id="w_other"))
    assert client.get(f"/worlds/{WORLD}/skill-proposals").status_code == 404
