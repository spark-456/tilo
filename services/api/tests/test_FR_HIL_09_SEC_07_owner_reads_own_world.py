"""FR-HIL-09, SEC-07, SEC-15 (SEC-SWEEP-1, found on tilo-dev): the deployed sign-in principal is role owner with
`world_id=None` (firebase_auth.principal_from_claims: a person is not bound to one world until a route narrows them).
`GET /worlds/{id}`, `/worlds/{id}/events`, `/worlds/{id}/layout` and the pause and stop-all writes required
`principal.world_id == world_id`, so a signed-in owner got the unknown-world 404 for their OWN world.

The rule: a session bound to the world, or, for a web sign-in session bound to no world, the world's record owner with
role owner (`cards.reading_principal` is wider for cards: it also lets an owner tied to another world read; these routes
keep a bound session bound). Never wider: another person's world, a non-owner
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


def refused(client, method: str, path: str):
    """What the caller sees: status and body, so a refusal that says more than the unknown-world 404 is caught."""
    response = client.request(method, path.format(w=WORLD), json={} if method == "POST" else None)
    return response.status_code, response.content


def unknown(client, method: str, path: str):
    response = client.request(method, path.format(w="w_unknown"), json={} if method == "POST" else None)
    return response.status_code, response.content


ALL = [("GET", p) for p in READS] + [("POST", "/worlds/{w}/pause"), ("POST", "/worlds/{w}/autopilot/stop")]
REFUSED_CASES = {
    "a non-owner role with the owner's id and no world": dict(
        user_id=OWNER, role="viewer", world_id=None, districts=("D1",)
    ),
    "an approver with the owner's id": dict(user_id=OWNER, role="approver", world_id=None, districts=("D1",)),
    "a team lead with the owner's id": dict(user_id=OWNER, role="team_lead", world_id=None, districts=("D1",)),
    "the owner's id, bound to another world": dict(user_id=OWNER, role="owner", world_id="w_other"),
    "another owner bound to a third world": dict(user_id=OTHER_USER, role="owner", world_id="w_theirs"),
    "another owner with no world": dict(user_id=OTHER_USER, role="owner", world_id=None),
    "the owner's id on an email session with no world": dict(
        user_id=OWNER, role="owner", world_id=None, channel="email"
    ),
}


@pytest.mark.parametrize("who", sorted(REFUSED_CASES))
@pytest.mark.parametrize(("method", "path"), ALL)
def test_FR_HIL_09_SEC_07_every_refusal_is_the_one_unknown_world_404(client, store, who, method, path):
    seed(store)
    as_principal(make_principal(**REFUSED_CASES[who]))
    got = refused(client, method, path)
    assert got[0] == 404
    assert got == unknown(client, method, path)


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
