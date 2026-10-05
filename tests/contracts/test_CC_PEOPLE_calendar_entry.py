"""CC-PEOPLE: contracts/calendar_entry.schema.json and its `$defs` agenda_item and free_busy.

FR-CAL-02 / PE-13 (what a synced Google event keeps: title, start, end, all day, a count of other
attendees; no description, attendee names or addresses, conference link or location), FR-CAL-04 /
PE-14 (a Tilo-made entry is accepted only when a person confirmed it), FR-CAL-06 / PE-04 (a private
entry shows others only its busy interval: `free_busy` has no title).

Shape per the coordinator's change of the brief: `share` is null (private) or `{team}`; `source` is
one of three closed objects (google, manual, tilo); there is no visibility, team or synced_at field.
"""

from __future__ import annotations

import _people_lib as pl
import pytest

REQUIRED = (
    "id",
    "org_id",
    "owner",
    "title",
    "start",
    "end",
    "all_day",
    "attendee_count",
    "source",
    "state",
    "share",
    "created_by",
    "confirmed_by",
    "updated_at",
)
TILO = pl.maker_tilo("A_notes")


def v(repo_root, registry, doc, why=""):
    pl.assert_valid(repo_root, registry, "calendar_entry", doc, None, why or "calendar_entry")


def i(repo_root, registry, doc, why=""):
    pl.assert_invalid(repo_root, registry, "calendar_entry", doc, None, why or "calendar_entry")


def test_CC_PEOPLE_FR_CAL_02_a_minimal_entry_is_valid_for_each_source(repo_root, registry):
    v(repo_root, registry, pl.calendar_entry(), "manual")
    v(repo_root, registry, pl.calendar_entry(source=pl.GOOGLE_SOURCE), "google")
    v(repo_root, registry, pl.calendar_entry(source=pl.TILO_SOURCE, state="proposed"), "tilo")
    v(repo_root, registry, pl.calendar_entry(end=None, all_day=True, attendee_count=500), "all-day, open end")


@pytest.mark.parametrize("field", REQUIRED)
def test_CC_PEOPLE_FR_CAL_02_every_calendar_entry_field_is_required(repo_root, registry, field):
    i(repo_root, registry, pl.drop(pl.calendar_entry(), (field,)), f"entry without {field}")


@pytest.mark.parametrize(
    "extra",
    [
        "description",
        "notes",
        "attendees",
        "attendee_names",
        "attendee_emails",
        "guests",
        "organizer",
        "conference_link",
        "meeting_link",
        "hangout_link",
        "html_link",
        "url",
        "location",
        "visibility",
        "team",
        "synced_at",
    ],
)
def test_CC_PEOPLE_PE_13_no_field_can_hold_a_description_attendee_link_or_location(repo_root, registry, extra):
    i(repo_root, registry, pl.with_(pl.calendar_entry(), **{extra: "x"}), extra)
    i(repo_root, registry, pl.with_(pl.calendar_entry(), **{extra: None}), f"{extra}: null")


@pytest.mark.parametrize("count", [0, 1, 499, 500])
def test_CC_PEOPLE_PE_13_attendee_count_is_a_count_from_zero_to_five_hundred(repo_root, registry, count):
    v(repo_root, registry, pl.calendar_entry(attendee_count=count), str(count))


@pytest.mark.parametrize("count", [-1, 501, 1.5, "3", None, True])
def test_CC_PEOPLE_PE_13_attendee_count_rejects_other_values(repo_root, registry, count):
    i(repo_root, registry, pl.calendar_entry(attendee_count=count), repr(count))


@pytest.mark.parametrize(
    "field,bad",
    [
        ("id", "wi_plan1"),
        ("id", "ce_"),
        ("org_id", "acme"),
        ("owner", "riya"),
        ("owner", None),
        ("start", "2026-10-02"),
        ("start", None),
        ("end", "2026-10-02"),
        ("all_day", "yes"),
        ("all_day", None),
        ("state", "pending"),
        ("state", "Accepted"),
        ("state", None),
        ("updated_at", "2026-10-01"),
        ("title", ""),
    ],
)
def test_CC_PEOPLE_FR_CAL_02_ids_times_and_enums_have_their_shapes(repo_root, registry, field, bad):
    i(repo_root, registry, pl.calendar_entry(**{field: bad}), f"{field}={bad!r}")


@pytest.mark.parametrize("state", ["proposed", "accepted", "declined", "cancelled"])
def test_CC_PEOPLE_FR_CAL_04_state_accepts_the_four_states(repo_root, registry, state):
    v(repo_root, registry, pl.calendar_entry(state=state), state)


def test_CC_PEOPLE_FR_CAL_06_share_is_null_or_exactly_a_team(repo_root, registry):
    v(repo_root, registry, pl.calendar_entry(share=None), "private")
    v(repo_root, registry, pl.calendar_entry(share={"team": "tm_sales"}), "shared with a team")
    for bad in (
        {},
        {"team": None},
        {"team": "sales"},
        {"team": "u_riya"},
        {"team": "tm_Sales"},
        {"team": "tm_sales", "user": "u_riya"},
        {"team": "tm_sales", "note": "x"},
        {"user": "u_riya"},
        {"visibility": "team"},
        "tm_sales",
        "team",
        True,
        ["tm_sales"],
    ):
        i(repo_root, registry, pl.calendar_entry(share=bad), f"share={bad!r}")


def test_CC_PEOPLE_FR_CAL_02_source_google_needs_a_ref_and_a_synced_at_and_nothing_else(repo_root, registry):
    google = pl.GOOGLE_SOURCE
    for ref in ("evt_abc123", "a", "A-b_9", "x" * 128):
        v(repo_root, registry, pl.calendar_entry(source={**google, "ref": ref}), f"ref {ref[:12]}")
    for field in ("ref", "synced_at"):
        i(repo_root, registry, pl.calendar_entry(source=pl.drop(google, (field,))), f"google without {field}")
        i(repo_root, registry, pl.calendar_entry(source={**google, field: None}), f"google with {field} null")
    for ref in ("", "x" * 129, "a:b", "a/b", "a.b", "https://calendar.example.com/e/1", "a b", "a@b"):
        i(repo_root, registry, pl.calendar_entry(source={**google, "ref": ref}), f"ref {ref!r}")
    i(repo_root, registry, pl.calendar_entry(source={**google, "synced_at": "2026-10-01"}), "synced_at date only")
    i(repo_root, registry, pl.calendar_entry(source={**google, "from": "meeting"}), "google with from")
    i(repo_root, registry, pl.calendar_entry(source={**google, "link": "https://example.com"}), "google with a link")


def test_CC_PEOPLE_FR_CAL_02_source_manual_is_just_its_kind(repo_root, registry):
    v(repo_root, registry, pl.calendar_entry(source={"kind": "manual"}), "manual")
    for extra in ({"ref": None}, {"ref": "x"}, {"synced_at": pl.T0}, {"from": "meeting"}, {"note": "x"}):
        i(repo_root, registry, pl.calendar_entry(source={"kind": "manual", **extra}), f"manual with {extra}")


def test_CC_PEOPLE_FR_CAL_04_source_tilo_names_where_it_came_from(repo_root, registry):
    for origin in ("meeting", "transcript", "request", "mail"):
        v(
            repo_root,
            registry,
            pl.calendar_entry(source={"kind": "tilo", "from": origin, "ref": "mt_weekly1"}, state="proposed"),
            origin,
        )
    v(
        repo_root,
        registry,
        pl.calendar_entry(source={"kind": "tilo", "from": "request", "ref": None}, state="proposed"),
        "null ref",
    )
    tilo = pl.TILO_SOURCE
    i(repo_root, registry, pl.calendar_entry(source=pl.drop(tilo, ("from",))), "tilo without from")
    for bad in ("google", "calendar", "Meeting", "", None):
        i(repo_root, registry, pl.calendar_entry(source={**tilo, "from": bad}), f"from {bad!r}")
    for ref in ("https://example.com/m", "a:b", "a/b", "a.b", "", "x" * 97):
        i(repo_root, registry, pl.calendar_entry(source={**tilo, "ref": ref}), f"tilo ref {ref!r}")
    i(repo_root, registry, pl.calendar_entry(source={**tilo, "synced_at": pl.T0}), "tilo with synced_at")
    i(repo_root, registry, pl.calendar_entry(source={**tilo, "note": "x"}), "tilo with an extra key")


@pytest.mark.parametrize(
    "source", [{"kind": "outlook"}, {"kind": "Google"}, {"kind": None}, {"ref": "x"}, {}, None, "google"]
)
def test_CC_PEOPLE_FR_CAL_02_source_kind_is_one_of_three(repo_root, registry, source):
    i(repo_root, registry, pl.calendar_entry(source=source), f"source={source!r}")


def test_CC_PEOPLE_FR_CAL_04_a_tilo_entry_is_accepted_only_when_a_person_confirmed_it(repo_root, registry):
    tilo = pl.TILO_SOURCE
    i(repo_root, registry, pl.calendar_entry(source=tilo, state="accepted", confirmed_by=None), "accepted, unconfirmed")
    v(
        repo_root,
        registry,
        pl.calendar_entry(source=tilo, state="accepted", confirmed_by=pl.assignment()),
        "accepted, confirmed",
    )
    for state in ("proposed", "declined", "cancelled"):
        v(repo_root, registry, pl.calendar_entry(source=tilo, state=state, confirmed_by=None), state)
    i(
        repo_root,
        registry,
        pl.calendar_entry(source=tilo, state="accepted", confirmed_by={"by": "A_notes", "at": pl.T0}),
        "Tilo cannot confirm its own entry",
    )
    v(
        repo_root,
        registry,
        pl.calendar_entry(source=pl.GOOGLE_SOURCE, state="accepted", confirmed_by=None),
        "google needs no confirmation",
    )
    v(
        repo_root,
        registry,
        pl.calendar_entry(source={"kind": "manual"}, state="accepted", confirmed_by=None),
        "manual needs none",
    )
    v(repo_root, registry, pl.calendar_entry(created_by=TILO, source=pl.TILO_SOURCE, state="proposed"), "made by Tilo")


@pytest.mark.parametrize(
    "created_by",
    [None, {"by": "tilo", "ref": "u_owner", "at": pl.T0}, {"by": "person", "ref": "A_notes", "at": pl.T0}, "u_owner"],
)
def test_CC_PEOPLE_FR_CAL_04_created_by_is_a_maker(repo_root, registry, created_by):
    i(repo_root, registry, pl.calendar_entry(created_by=created_by), f"created_by={created_by!r}")


# ---- $defs agenda_item ---------------------------------------------------------------------------
def av(repo_root, registry, doc, why=""):
    pl.assert_valid(repo_root, registry, "calendar_entry", doc, "agenda_item", why or "agenda_item")


def ai(repo_root, registry, doc, why=""):
    pl.assert_invalid(repo_root, registry, "calendar_entry", doc, "agenda_item", why or "agenda_item")


def test_CC_PEOPLE_FR_CAL_05_an_agenda_item_is_valid_for_each_kind_and_source(repo_root, registry):
    av(repo_root, registry, pl.agenda_item())
    av(repo_root, registry, pl.agenda_item(end=None, all_day=True, shared=True))
    for kind in ("event", "due", "reminder", "meeting", "deadline"):
        av(repo_root, registry, pl.agenda_item(kind=kind), kind)
    for src in ("calendar_entry", "work_item", "meeting", "pinboard_item"):
        av(repo_root, registry, pl.agenda_item(source={"kind": src, "id": "x_1"}), src)
    for state in ("proposed", "confirmed"):
        av(repo_root, registry, pl.agenda_item(state=state), state)


@pytest.mark.parametrize("field", ["start", "end", "all_day", "title", "kind", "source", "state", "shared"])
def test_CC_PEOPLE_FR_CAL_05_every_agenda_item_field_is_required(repo_root, registry, field):
    ai(repo_root, registry, pl.drop(pl.agenda_item(), (field,)), f"agenda item without {field}")


@pytest.mark.parametrize(
    "field,bad",
    [
        ("kind", "task"),
        ("kind", "Event"),
        ("kind", None),
        ("state", "accepted"),
        ("state", None),
        ("shared", "yes"),
        ("shared", None),
        ("all_day", 1),
        ("start", "2026-10-02"),
        ("end", "later"),
        ("title", ""),
        ("title", "x" * 141),
        ("title", "a\nb"),
        ("source", {"kind": "mention", "id": "mn_1"}),
        ("source", {"kind": "card", "id": "x"}),
        ("source", {"kind": "work_item", "id": "a:b"}),
        ("source", {"kind": "work_item", "id": "a/b"}),
        ("source", {"kind": "work_item", "id": "a-b"}),
        ("source", {"kind": "work_item", "id": "x" * 65}),
        ("source", {"kind": "work_item", "id": ""}),
        ("source", {"kind": "work_item"}),
        ("source", {"id": "wi_1"}),
        ("source", {"kind": "work_item", "id": "wi_1", "title": "x"}),
        ("source", None),
    ],
)
def test_CC_PEOPLE_FR_CAL_05_agenda_item_values_have_their_shapes(repo_root, registry, field, bad):
    ai(repo_root, registry, pl.agenda_item(**{field: bad}), f"{field}={bad!r}")


def test_CC_PEOPLE_FR_CAL_05_an_agenda_item_source_id_may_be_64_characters(repo_root, registry):
    av(repo_root, registry, pl.agenda_item(source={"kind": "meeting", "id": "m" * 64}), "64 characters")


@pytest.mark.parametrize("extra", ["description", "attendees", "location", "url", "team", "owner"])
def test_CC_PEOPLE_PE_13_an_agenda_item_holds_no_field_beyond_the_contract(repo_root, registry, extra):
    ai(repo_root, registry, pl.with_(pl.agenda_item(), **{extra: "x"}), extra)


# ---- $defs free_busy -----------------------------------------------------------------------------
def fv(repo_root, registry, doc, why=""):
    pl.assert_valid(repo_root, registry, "calendar_entry", doc, "free_busy", why or "free_busy")


def fi(repo_root, registry, doc, why=""):
    pl.assert_invalid(repo_root, registry, "calendar_entry", doc, "free_busy", why or "free_busy")


def test_CC_PEOPLE_FR_CAL_06_free_busy_is_a_user_a_window_and_busy_intervals_only(repo_root, registry):
    fv(repo_root, registry, pl.free_busy())
    fv(repo_root, registry, pl.free_busy(busy=[]), "nobody busy")
    one = {"start": pl.T1, "end": pl.T2}
    fv(repo_root, registry, pl.free_busy(busy=[one] * 200), "200 intervals")
    fi(repo_root, registry, pl.free_busy(busy=[one] * 201), "201 intervals")


@pytest.mark.parametrize("field", ["user", "from", "to", "busy"])
def test_CC_PEOPLE_FR_CAL_06_every_free_busy_field_is_required(repo_root, registry, field):
    fi(repo_root, registry, pl.drop(pl.free_busy(), (field,)), f"free_busy without {field}")


@pytest.mark.parametrize(
    "extra", ["title", "summary", "description", "state", "source", "attendee_count", "location", "entries"]
)
def test_CC_PEOPLE_FR_CAL_06_free_busy_carries_no_title_or_detail(repo_root, registry, extra):
    fi(repo_root, registry, pl.with_(pl.free_busy(), **{extra: "x"}), extra)
    fi(repo_root, registry, pl.put(pl.free_busy(), ("busy", 0, extra), "x"), f"interval with {extra}")


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: pl.put(d, ("user",), "riya"),
        lambda d: pl.put(d, ("user",), "A_notes"),
        lambda d: pl.put(d, ("from",), "2026-10-02"),
        lambda d: pl.put(d, ("to",), None),
        lambda d: pl.put(d, ("busy", 0, "start"), "9am"),
        lambda d: pl.put(d, ("busy", 0, "end"), None),
        lambda d: pl.drop(d, ("busy", 0, "end")),
        lambda d: pl.drop(d, ("busy", 0, "start")),
        lambda d: pl.put(d, ("busy",), {"start": pl.T1, "end": pl.T2}),
    ],
)
def test_CC_PEOPLE_FR_CAL_06_free_busy_values_have_their_shapes(repo_root, registry, mutate):
    fi(repo_root, registry, mutate(pl.free_busy()), "mutated free_busy")
