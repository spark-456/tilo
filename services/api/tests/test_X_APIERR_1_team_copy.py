"""Role refusals keep their authorization and mutation guarantees with readable copy."""

from _team_routes_lib import OWNER, ROLES, team_api


def test_X_APIERR_1_self_removal_has_a_sentence_and_keeps_the_team():
    with team_api() as api:
        response = api.delete(f"/v1/team/members/{OWNER}")
        assert response.status_code == 409
        assert response.json()["detail"] == "The team must keep at least one Owner."
        assert api.store.read().roles == ROLES


def test_X_APIERR_1_own_role_change_has_a_sentence_and_keeps_the_team():
    with team_api() as api:
        response = api.put(f"/v1/team/members/{OWNER}/role", {"role": "Viewer"})
        assert response.status_code == 409
        assert response.json()["detail"] == "You cannot change your own role."
        assert api.store.read().roles == ROLES
