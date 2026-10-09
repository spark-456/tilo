"""FR-HIL-09, SEC-07, SEC-15 (SEC-SWEEP-1, found on tilo-dev): the deployed sign-in principal is role owner with
`world_id=None` (firebase_auth.principal_from_claims: a person is not bound to one world until a route narrows them).
`GET /worlds/{id}`, `/worlds/{id}/events`, `/worlds/{id}/layout` and the pause and stop-all writes required
`principal.world_id == world_id`, so a signed-in owner got the unknown-world 404 for their OWN world.

The rule (as `cards.reading_principal` already has it for card reads): a session bound to the world, or the world's
record owner with role owner, on a principal narrowed to that world. Never wider: another person's world, a non-owner
role that merely carries the owner's id, and an unknown world keep the one 404."""

from __future__ import annotations

import types

import pytest
from _api_lib import OWNER, WORLD, as_principal, make_district, make_principal, make_world

OTHER_USER = "u_someone_else"
LAYOUT = {"semantic": {"levels": []}}


def seed(store) -> None:
    store.worlds[WORLD] = make_world(owner=OWNER, districts={"D1": make_district("Mail", "m")})
    store.runs[WORLD] = types.SimpleNamespace(layout=LAYOUT)


def deployed_owner(user_id: str = OWNER):
    """What `principal_from_claims` builds: role owner, no world."""
    return make_principal(user_id=user_id, role="owner", world_id=None, channel="web")


READS = ("/worlds/{w}", "/worlds/{w}/events", "/worlds/{w}/layout")


@pytest.mark.parametrize("path", READS)
def test_FR_HIL_09_SEC_07_a_signed_in_owner_reads_their_own_world(client, store, path):
    seed(store)
    as_principal(deployed_owner())
    assert client.get(path.format(w=WORLD)).status_code == 200


@pytest.mark.parametrize("path", READS)
def test_FR_HIL_09_SEC_07_another_persons_world_is_the_same_404_as_an_unknown_one(client, store, path):
    seed(store)
    as_principal(deployed_owner(OTHER_USER))
    other = client.get(path.format(w=WORLD))
    unknown = client.get(path.format(w="w_unknown"))
    assert (other.status_code, other.content) == (unknown.status_code, unknown.content) == (404, unknown.content)


@pytest.mark.parametrize("role", ["viewer", "approver", "team_lead"])
@pytest.mark.parametrize("path", READS)
def test_FR_HIL_09_SEC_07_the_owners_id_with_another_role_and_no_world_is_still_refused(client, store, path, role):
    seed(store)
    as_principal(make_principal(user_id=OWNER, role=role, world_id=None, districts=("D1",)))
    assert client.get(path.format(w=WORLD)).status_code == 404


def test_FR_HIL_09_SEC_07_a_session_bound_to_another_world_stays_bound_to_it(client, store):
    seed(store)
    as_principal(make_principal(user_id=OTHER_USER, role="owner", world_id="w_theirs"))
    assert client.get(f"/worlds/{WORLD}/events").status_code == 404
    as_principal(make_principal(user_id=OWNER, role="owner", world_id="w_other"))  # the owner's id, bound elsewhere
    assert client.get(f"/worlds/{WORLD}/events").status_code == 404


def test_FR_HIL_09_SEC_07_the_owners_read_is_the_full_view_not_a_scoped_one(client, store):
    seed(store)
    as_principal(deployed_owner())
    body = client.get(f"/worlds/{WORLD}").json()
    assert body["has_hidden_districts"] is False
    assert [d["id"] for d in body["districts"]] == ["D1"]
    assert client.get(f"/worlds/{WORLD}/layout").json() == LAYOUT


@pytest.mark.parametrize("path", ["/worlds/{w}/pause", "/worlds/{w}/autopilot/stop"])
def test_FR_HIL_09_SEC_07_a_signed_in_owner_can_pause_and_stop_their_own_world(client, store, path):
    seed(store)
    as_principal(deployed_owner())
    assert client.post(path.format(w=WORLD), json={}).status_code in (200, 202)


@pytest.mark.parametrize("path", ["/worlds/{w}/pause", "/worlds/{w}/autopilot/stop"])
def test_FR_HIL_09_SEC_07_nobody_else_can_pause_or_stop_it(client, store, path):
    seed(store)
    as_principal(deployed_owner(OTHER_USER))
    assert client.post(path.format(w=WORLD), json={}).status_code == 404
    as_principal(make_principal(user_id=OWNER, role="viewer", world_id=None, districts=("D1",)))
    assert client.post(path.format(w=WORLD), json={}).status_code == 404
