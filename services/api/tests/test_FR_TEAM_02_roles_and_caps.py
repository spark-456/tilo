"""FR-TEAM-02: you can't change your own role; role and personal limits feed the per-user cap."""

import pytest
from tilo_api.team_rules import RoleChangeRefused, change_role, effective_user_cap

PEOPLE = {"u_owner": "Owner", "u_appr": "Approver", "u_mem": "Member", "u_view": "Viewer"}


@pytest.mark.parametrize("who", list(PEOPLE))
@pytest.mark.parametrize("new", ["Owner", "Approver", "Member", "Viewer"])
def test_FR_TEAM_02_nobody_changes_their_own_role(who, new):
    with pytest.raises(RoleChangeRefused) as err:
        change_role(PEOPLE, who, who, new)
    assert err.value.reason == "own_role"


def test_FR_TEAM_02_owner_changes_another_role_and_input_is_untouched():
    out = change_role(PEOPLE, "u_owner", "u_mem", "Approver")
    assert out["u_mem"] == "Approver" and PEOPLE["u_mem"] == "Member"


@pytest.mark.parametrize("actor", ["u_mem", "u_view"])
def test_FR_TEAM_02_members_and_viewers_change_no_roles(actor):
    with pytest.raises(RoleChangeRefused):
        change_role(PEOPLE, actor, "u_view" if actor == "u_mem" else "u_mem", "Approver")


def test_FR_TEAM_02_only_the_owner_grants_or_takes_owner():
    with pytest.raises(RoleChangeRefused):
        change_role(PEOPLE, "u_appr", "u_mem", "Owner")
    with pytest.raises(RoleChangeRefused):
        change_role(PEOPLE, "u_appr", "u_owner", "Member")
    assert change_role(PEOPLE, "u_appr", "u_mem", "Viewer")["u_mem"] == "Viewer"


@pytest.mark.parametrize(("actor", "target", "new"), [("u_owner", "nobody", "Member"), ("u_owner", "u_mem", "Admin")])
def test_FR_TEAM_02_unknown_person_or_role_is_refused(actor, target, new):
    with pytest.raises(RoleChangeRefused):
        change_role(PEOPLE, actor, target, new)


def test_FR_TEAM_02_limits_feed_the_per_user_cap_as_the_smallest_of_them():
    assert effective_user_cap(role_limit_minor=25_000, personal_limit_minor=None, lifetime_cap_minor=100_000) == 25_000
    assert effective_user_cap(role_limit_minor=None, personal_limit_minor=5_000, lifetime_cap_minor=100_000) == 5_000
    assert (
        effective_user_cap(role_limit_minor=25_000, personal_limit_minor=40_000, lifetime_cap_minor=100_000) == 25_000
    )
    assert effective_user_cap(role_limit_minor=None, personal_limit_minor=None, lifetime_cap_minor=100_000) == 100_000
    assert effective_user_cap(role_limit_minor=0, personal_limit_minor=5_000, lifetime_cap_minor=100_000) == 0  # Viewer


def test_FR_TEAM_02_a_limit_never_lifts_the_sec16_lifetime_cap():
    assert (
        effective_user_cap(role_limit_minor=900_000, personal_limit_minor=None, lifetime_cap_minor=100_000) == 100_000
    )


@pytest.mark.parametrize("bad", [-1, 1.5, True])
def test_FR_TEAM_02_bad_limits_are_refused(bad):
    with pytest.raises((TypeError, ValueError)):
        effective_user_cap(role_limit_minor=bad, personal_limit_minor=None, lifetime_cap_minor=1)
