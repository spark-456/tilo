"""CC-PEOPLE: contracts/person.schema.json (PRD 15.1 User entity; FR-PA-01, FR-MTG-05 alias match,
AQ-06 per-person time zone, people.rules.md PE-02 membership, PE-16 export and delete).

A person is a Tilo user: id, org, display name, aliases, email, IANA time zone, preferred channel,
org role and team memberships (each assigned by an org owner, PE-02 "Terms"). No field holds a
password, a token or a phone number (Tilo never handles passwords, root CLAUDE.md).
"""

from __future__ import annotations

import _people_lib as pl
import pytest

REQUIRED = (
    "id",
    "org_id",
    "display_name",
    "aliases",
    "email",
    "time_zone",
    "preferred_channel",
    "org_role",
    "memberships",
    "created_by",
)


def _valid(repo_root, registry, doc, why=""):
    pl.assert_valid(repo_root, registry, "person", doc, None, why or "person")


def _invalid(repo_root, registry, doc, why=""):
    pl.assert_invalid(repo_root, registry, "person", doc, None, why or "person")


def test_CC_PEOPLE_FR_PA_01_a_minimal_person_is_valid(repo_root, registry):
    _valid(repo_root, registry, pl.person())
    _valid(repo_root, registry, pl.person(org_role="owner", aliases=[], memberships=[]), "owner without teams")


@pytest.mark.parametrize("field", REQUIRED)
def test_CC_PEOPLE_FR_PA_01_every_person_field_is_required(repo_root, registry, field):
    _invalid(repo_root, registry, pl.drop(pl.person(), (field,)), f"person without {field}")


@pytest.mark.parametrize("extra", ["password", "token", "phone", "manager", "score", "last_seen", "notes"])
def test_CC_PEOPLE_PE_16_a_person_holds_no_field_beyond_the_contract(repo_root, registry, extra):
    _invalid(repo_root, registry, pl.with_(pl.person(), **{extra: "x"}), f"extra property {extra}")


@pytest.mark.parametrize(
    "field,bad",
    [
        ("id", "riya"),
        ("id", "org_acme"),
        ("id", "u_"),
        ("org_id", "acme"),
        ("org_id", "u_riya"),
        ("email", "not-an-email"),
        ("email", "riya@"),
        ("email", ""),
        ("display_name", ""),
        ("display_name", "R" * 81),
        ("display_name", "Riya\nExample"),
    ],
)
def test_CC_PEOPLE_FR_PA_01_person_ids_email_and_name_are_checked(repo_root, registry, field, bad):
    _invalid(repo_root, registry, pl.person(**{field: bad}), f"{field}={bad!r}")


@pytest.mark.parametrize(
    "zone", ["Asia/Kolkata", "UTC", "Europe/London", "America/New_York", "America/Argentina/Buenos_Aires"]
)
def test_CC_PEOPLE_FR_MTG_05_time_zone_accepts_iana_names(repo_root, registry, zone):
    _valid(repo_root, registry, pl.person(time_zone=zone), zone)


@pytest.mark.parametrize(
    "zone",
    ["", "+05:30", "UTC+05:30", "Asia Kolkata", "Asia/Kolkata extra", "Asia/", "/Kolkata", "../etc/passwd", 5, None],
)
def test_CC_PEOPLE_FR_MTG_05_time_zone_rejects_offsets_and_free_text(repo_root, registry, zone):
    _invalid(repo_root, registry, pl.person(time_zone=zone), f"time_zone={zone!r}")


@pytest.mark.parametrize("channel", list(pl.CHANNELS))
def test_CC_PEOPLE_FR_PA_01_preferred_channel_is_in_app_or_email(repo_root, registry, channel):
    _valid(repo_root, registry, pl.person(preferred_channel=channel), channel)


@pytest.mark.parametrize("channel", ["whatsapp", "sms", "slack", "Web", "", None])
def test_CC_PEOPLE_FR_PA_01_preferred_channel_rejects_anything_else(repo_root, registry, channel):
    _invalid(repo_root, registry, pl.person(preferred_channel=channel), f"channel={channel!r}")


@pytest.mark.parametrize("role", ["owner", "member"])
def test_CC_PEOPLE_PE_02_org_role_is_owner_or_member(repo_root, registry, role):
    _valid(repo_root, registry, pl.person(org_role=role), role)


@pytest.mark.parametrize("role", ["admin", "manager", "Owner", "", None])
def test_CC_PEOPLE_PE_02_org_role_has_no_third_value(repo_root, registry, role):
    _invalid(repo_root, registry, pl.person(org_role=role), f"org_role={role!r}")


def test_CC_PEOPLE_FR_MTG_05_aliases_are_at_most_eight_unique_short_lines(repo_root, registry):
    _valid(repo_root, registry, pl.person(aliases=[f"Alias{i}" for i in range(8)]), "8 aliases")
    _invalid(repo_root, registry, pl.person(aliases=[f"Alias{i}" for i in range(9)]), "9 aliases")
    _invalid(repo_root, registry, pl.person(aliases=["Riya", "Riya"]), "duplicate alias")
    _invalid(repo_root, registry, pl.person(aliases=["R" * 41]), "alias of 41 characters")
    _invalid(repo_root, registry, pl.person(aliases=[""]), "empty alias")
    _invalid(repo_root, registry, pl.person(aliases=["Ri\nya"]), "alias with a newline")
    _invalid(repo_root, registry, pl.person(aliases=[5]), "alias that is not a string")


def test_CC_PEOPLE_PE_02_memberships_are_at_most_eight_assigned_team_entries(repo_root, registry):
    def entry(i):
        return {"team": f"tm_t{i}", "assigned_by": pl.assignment()}

    _valid(repo_root, registry, pl.person(memberships=[entry(i) for i in range(8)]), "8 memberships")
    _invalid(repo_root, registry, pl.person(memberships=[entry(i) for i in range(9)]), "9 memberships")


@pytest.mark.parametrize(
    "membership",
    [
        {"team": "sales", "assigned_by": pl.assignment()},
        {"team": "tm_Sales", "assigned_by": pl.assignment()},
        {"team": "tm_sales"},
        {"assigned_by": pl.assignment()},
        {"team": "tm_sales", "assigned_by": {"by": "A_notes", "at": pl.T0}},
        {"team": "tm_sales", "assigned_by": {"by": "u_owner"}},
        {"team": "tm_sales", "assigned_by": {"by": "u_owner", "at": "2026-10-01"}},
        {"team": "tm_sales", "assigned_by": None},
        {"team": "tm_sales", "assigned_by": pl.assignment(), "role": "lead"},
        {"team": "tm_sales", "assigned_by": {"by": "u_owner", "at": pl.T0, "note": "x"}},
    ],
)
def test_CC_PEOPLE_PE_02_a_membership_names_a_team_and_who_assigned_it_when(repo_root, registry, membership):
    _invalid(repo_root, registry, pl.person(memberships=[membership]), str(membership))


@pytest.mark.parametrize(
    "created_by",
    [None, {"by": "u_owner"}, {"by": "A_notes", "at": pl.T0}, {"by": "u_owner", "at": "yesterday"}, "u_owner"],
)
def test_CC_PEOPLE_PE_02_created_by_is_an_assignment(repo_root, registry, created_by):
    _invalid(repo_root, registry, pl.person(created_by=created_by), f"created_by={created_by!r}")
