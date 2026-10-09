"""FR-TEAM-02 on tilo-api (issues #621, #629): roles and personal spend limits through routes.

Done-when: "You can't change your own role; limits feed the per-user cap." The route takes the actor from the verified
session and the actor's team role from the STORED roles map (every test principal's session role is "owner"), only
the Owner changes roles (BQ-TEAMACC-2), a change is applied with a compare-and-set so two Owners demoting each other
from one stale snapshot leave exactly one Owner, and no change ever leaves zero Owners. Remove is Owner-only, keyed by
person id, never the last Owner, and hands the person's worlds to the Owner in the same write. Invites are validated
on the server. Every refusal is a 4xx or the 503 of replay-only, never a 500.
"""

from __future__ import annotations

import pytest
from _team_routes_lib import (
    APPROVER,
    MEMBER,
    NOT_FOUND,
    OWNER,
    OWNER_2,
    ROLES,
    STRANGER,
    VIEWER,
    state,
    team_api,
)


def _roles(view: dict) -> dict[str, str]:
    return {m["id"]: m["role"] for m in view["members"]}


# --- reading -----------------------------------------------------------------------------------------------------


def test_FR_TEAM_02_a_member_reads_the_roles_and_the_owner_reads_every_limit() -> None:
    with team_api() as api:
        view = api.get().json()
        assert _roles(view) == ROLES
        assert view["me"] == {"id": OWNER, "role": "Owner"}
        assert {m["id"]: m["limit_minor"] for m in view["members"]}[APPROVER] == 100_000
        mine = api.as_(MEMBER).get().json()
        assert mine["me"] == {"id": MEMBER, "role": "Member"}
        assert all(m["limit_minor"] is None for m in mine["members"] if m["id"] != MEMBER)  # no one else's limit


def test_FR_TEAM_02_a_person_outside_the_team_gets_one_404_on_every_route() -> None:
    with team_api() as api:
        api.as_(STRANGER)
        for response in (
            api.get(),
            api.put(f"/v1/team/members/{MEMBER}/role", {"role": "Viewer"}),
            api.put(f"/v1/team/members/{MEMBER}/limit", {"limit_minor": 1}),
            api.delete(f"/v1/team/members/{MEMBER}"),
            api.post("/v1/team/invites", {"email": "a@b.co", "role": "Member"}),
            api.put("/v1/team/switches/weekend", {"on": True}),
            api.put("/v1/team/tools/gmail", {"level": "read"}),
        ):
            assert (response.status_code, response.json()) == (404, NOT_FOUND)


def test_FR_TEAM_02_the_matrix_is_served_from_the_engine_config() -> None:
    from tilo_api.team_rules import load_capabilities

    with team_api() as api:
        served = api.as_(VIEWER).get().json()["capabilities"]
    assert served == [{"key": c.key, "label": c.label, "roles": list(c.roles)} for c in load_capabilities().values()]


# --- changing a role -----------------------------------------------------------------------------------------------


def test_FR_TEAM_02_the_owner_changes_a_role_and_the_store_keeps_it() -> None:
    with team_api() as api:
        response = api.put(f"/v1/team/members/{MEMBER}/role", {"role": "Approver"})
        assert response.status_code == 200, response.text
        assert _roles(response.json())[MEMBER] == "Approver"
        assert api.store.read().roles[MEMBER] == "Approver"


def test_FR_TEAM_02_you_cannot_change_your_own_role() -> None:
    with team_api(state(roles={**ROLES, OWNER_2: "Owner"})) as api:
        response = api.put(f"/v1/team/members/{OWNER}/role", {"role": "Member"})
        assert response.status_code == 409
        assert api.store.read().roles[OWNER] == "Owner"


@pytest.mark.parametrize("actor", [APPROVER, MEMBER, VIEWER])
def test_FR_TEAM_02_only_the_owner_changes_roles_whatever_the_session_says(actor: str) -> None:
    with team_api() as api:
        response = api.as_(actor).put(
            f"/v1/team/members/{VIEWER if actor != VIEWER else MEMBER}/role", {"role": "Owner"}
        )
        assert response.status_code == 403
        assert api.store.read().roles == ROLES


@pytest.mark.parametrize("role", ["Team Lead", "owner", "Admin", "", "Owner "])
def test_FR_TEAM_02_an_unknown_or_legacy_role_is_refused(role: str) -> None:
    with team_api() as api:
        assert api.put(f"/v1/team/members/{MEMBER}/role", {"role": role}).status_code == 422
        assert api.store.read().roles == ROLES


def test_FR_TEAM_02_an_unknown_person_is_404() -> None:
    with team_api() as api:
        assert api.put(f"/v1/team/members/{STRANGER}/role", {"role": "Viewer"}).status_code == 404


def test_FR_TEAM_02_two_owners_demoting_each_other_from_a_stale_snapshot_leave_exactly_one_owner() -> None:
    from tilo_api.team_store import InMemoryTeamStore

    class Stale(InMemoryTeamStore):
        """The first read hands out the snapshot from before the other Owner's change landed."""

        def __init__(self, before: object, after: object) -> None:
            super().__init__(after)  # type: ignore[arg-type]
            self.before: object | None = before

        def read(self):  # type: ignore[no-untyped-def]
            if self.before is not None:
                stale, self.before = self.before, None
                return stale
            return super().read()

    both = state(roles={**ROLES, OWNER_2: "Owner"})
    after = InMemoryTeamStore(both)
    assert after.compare_and_set(both.version, both.with_roles({**both.roles, OWNER_2: "Member"}))  # OWNER won
    with team_api(store=Stale(both, after.read())) as api:
        response = api.as_(OWNER_2).put(f"/v1/team/members/{OWNER}/role", {"role": "Member"})
        assert response.status_code == 403  # re-checked on the fresh state: OWNER_2 is no Owner any more
        roles = api.store.read().roles
    assert [p for p, r in roles.items() if r == "Owner"] == [OWNER]


def test_FR_TEAM_02_a_change_that_would_leave_no_owner_is_refused() -> None:
    from tilo_api.team_rules import RoleChangeRefused
    from tilo_api.team_store import TeamState, apply_role_change

    lone = TeamState(roles={OWNER: "Owner", OWNER_2: "Member"})
    with pytest.raises(RoleChangeRefused) as refused:
        apply_role_change(lone, actor=OWNER_2, target=OWNER, role="Member")  # what a stale "both Owners" view tries
    assert refused.value.reason == "not_allowed"
    with pytest.raises(RoleChangeRefused):
        apply_role_change(lone, actor=OWNER, target=OWNER, role="Member")
    assert apply_role_change(lone, actor=OWNER, target=OWNER_2, role="Owner").roles == {
        OWNER: "Owner",
        OWNER_2: "Owner",
    }


# --- personal limits ---------------------------------------------------------------------------------------------


def test_FR_TEAM_02_the_owner_sets_a_personal_limit_and_others_cannot() -> None:
    with team_api() as api:
        assert api.put(f"/v1/team/members/{MEMBER}/limit", {"limit_minor": 5_000}).status_code == 200
        assert api.store.read().limits[MEMBER] == 5_000
        assert api.put(f"/v1/team/members/{MEMBER}/limit", {"limit_minor": None}).status_code == 200
        assert api.store.read().limits.get(MEMBER) is None
        assert api.as_(APPROVER).put(f"/v1/team/members/{MEMBER}/limit", {"limit_minor": 1}).status_code == 403
        for bad in (-1, 1.5, "10", True):
            assert api.as_(OWNER).put(f"/v1/team/members/{MEMBER}/limit", {"limit_minor": bad}).status_code == 422


# --- removing a person -------------------------------------------------------------------------------------------


def test_FR_TEAM_02_remove_is_owner_only_keyed_by_id_and_hands_the_worlds_to_the_owner() -> None:
    with team_api(state(worlds={"w_1": MEMBER, "w_2": MEMBER, "w_3": APPROVER})) as api:
        assert api.as_(APPROVER).delete(f"/v1/team/members/{MEMBER}").status_code == 403
        response = api.as_(OWNER).delete(f"/v1/team/members/{MEMBER}")
        assert response.status_code == 200, response.text
        after = api.store.read()
    assert MEMBER not in after.roles and MEMBER not in after.limits
    assert after.worlds == {"w_1": OWNER, "w_2": OWNER, "w_3": APPROVER}


def test_FR_TEAM_02_the_last_owner_and_yourself_cannot_be_removed() -> None:
    with team_api() as api:
        assert api.delete(f"/v1/team/members/{OWNER}").status_code == 409
        assert api.delete(f"/v1/team/members/{STRANGER}").status_code == 404
        assert api.store.read().roles == ROLES


# --- invites -----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "email",
    [
        "a@b",
        "not-an-email",
        "josé@b.co",
        "a​@b.co",
        "a@b.co‮",
        "a\u0085@b.co",
        "a@b.co\r\nBcc: x@y.co",
        "a@@b.co",
        "a" * 250 + "@b.co",
    ],
)
def test_FR_TEAM_02_the_server_validates_an_invite_email_itself(email: str) -> None:
    with team_api() as api:
        assert api.post("/v1/team/invites", {"email": email, "role": "Member"}).status_code == 422
        assert api.store.read().invites == {}


def test_FR_TEAM_02_the_owner_invites_and_no_one_else_can() -> None:
    with team_api() as api:
        assert api.as_(APPROVER).post("/v1/team/invites", {"email": "new@b.co", "role": "Member"}).status_code == 403
        response = api.as_(OWNER).post("/v1/team/invites", {"email": "new@b.co", "role": "Member"})
        assert response.status_code == 201, response.text
        assert list(api.store.read().invites.values()) == [{"email": "new@b.co", "role": "Member"}]
        assert api.post("/v1/team/invites", {"email": "x@b.co", "role": "Owner"}).status_code == 422


# --- route hygiene -----------------------------------------------------------------------------------------------


def test_FR_TEAM_02_writes_are_json_only_closed_bodies_and_refused_while_replay_only() -> None:
    with team_api() as api:
        path = f"/v1/team/members/{MEMBER}/role"
        assert (
            api.client.put(path, content='{"role": "Viewer"}', headers={"content-type": "text/plain"}).status_code
            == 415
        )
        assert api.put(path, {"role": "Viewer", "actor": OWNER}).status_code == 422
        assert api.put(path, {"role": "Viewer", "at": "2020-01-01T00:00:00.000Z"}).status_code == 422
        api.flags.on.add("replay_only")
        refused = api.put(path, {"role": "Viewer"})
        assert refused.status_code == 503 and refused.json()["replay_only"] is True
        assert api.get().status_code == 200  # a read still works
        assert api.store.read().roles == ROLES
        assert api.get().headers["cache-control"] == "no-store"


def test_FR_TEAM_02_a_broken_store_or_config_is_a_refusal_never_a_500() -> None:
    from tilo_api.team_store import InMemoryTeamStore

    class Broken(InMemoryTeamStore):
        def compare_and_set(self, expected_version: int, new: object) -> bool:  # type: ignore[override]
            raise RuntimeError("store down")

    with team_api(store=Broken(state())) as api:
        response = api.put(f"/v1/team/members/{MEMBER}/role", {"role": "Viewer"})
        assert response.status_code == 503
        assert "store down" not in response.text
