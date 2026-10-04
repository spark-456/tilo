"""CC-PEOPLE: contracts/work_item.schema.json (FR-PA-01, FR-MTG-06, FR-PA-11; people.rules.md
PE-03 who reads it, PE-07 who confirms it, PE-08 what Tilo-made items carry).

A work item has one owner, a status that starts `proposed` when Tilo made it from minutes, a source
with evidence ids (max 5), the maker, who assigned and who confirmed it, a snooze and an append-only
history. `created_by.by tilo` and `status open|done` require `confirmed_by`: Tilo never confirms its
own item.
"""

from __future__ import annotations

import _people_lib as pl
import pytest

REQUIRED = (
    "id",
    "org_id",
    "owner",
    "title",
    "due",
    "due_text",
    "status",
    "source",
    "created_by",
    "assigned_by",
    "confirmed_by",
    "snoozed_until",
    "history",
    "created_at",
    "updated_at",
)
CHANGES = ("created", "confirmed", "edited", "snoozed", "done", "dropped", "reopened", "reassign_requested", "reminded")
STATUSES = ("proposed", "open", "done", "dropped")


def v(repo_root, registry, doc, why=""):
    pl.assert_valid(repo_root, registry, "work_item", doc, None, why or "work_item")


def i(repo_root, registry, doc, why=""):
    pl.assert_invalid(repo_root, registry, "work_item", doc, None, why or "work_item")


def test_CC_PEOPLE_FR_PA_01_a_minimal_work_item_is_valid(repo_root, registry):
    v(repo_root, registry, pl.work_item())
    v(
        repo_root,
        registry,
        pl.work_item(
            due=None,
            due_text=None,
            source={"kind": "manual", "ref": None, "evidence": []},
            assigned_by=None,
            confirmed_by=None,
            snoozed_until=pl.T1,
        ),
        "manual item with nothing optional",
    )


@pytest.mark.parametrize("field", REQUIRED)
def test_CC_PEOPLE_FR_PA_01_every_work_item_field_is_required(repo_root, registry, field):
    i(repo_root, registry, pl.drop(pl.work_item(), (field,)), f"work item without {field}")


@pytest.mark.parametrize("extra", ["description", "body", "pinned", "priority", "score", "team", "transcript", "link"])
def test_CC_PEOPLE_FR_PA_11_a_work_item_holds_no_field_beyond_the_contract(repo_root, registry, extra):
    i(repo_root, registry, pl.with_(pl.work_item(), **{extra: "x"}), extra)


@pytest.mark.parametrize(
    "field,bad",
    [
        ("id", "mt_budget1"),
        ("id", "wi_"),
        ("org_id", "acme"),
        ("owner", "riya"),
        ("owner", "A_notes"),
        ("owner", None),
        ("due", "friday"),
        ("due", "2026-02-30T00:00:00.000Z"),
        ("due", "2026-10-09T09:00:00.000Z"),
        ("snoozed_until", "2026-10-09"),
        ("snoozed_until", "tomorrow"),
        ("created_at", "2026-10-01"),
        ("updated_at", None),
    ],
)
def test_CC_PEOPLE_FR_PA_01_ids_dates_and_timestamps_have_their_shapes(repo_root, registry, field, bad):
    i(repo_root, registry, pl.work_item(**{field: bad}), f"{field}={bad!r}")


@pytest.mark.parametrize("status", STATUSES)
def test_CC_PEOPLE_FR_PA_01_status_accepts_the_four_states(repo_root, registry, status):
    v(repo_root, registry, pl.work_item(status=status), status)


@pytest.mark.parametrize("status", ["pending", "Open", "removed", "", None])
def test_CC_PEOPLE_FR_PA_01_status_has_no_other_value(repo_root, registry, status):
    i(repo_root, registry, pl.work_item(status=status), repr(status))


@pytest.mark.parametrize("kind", ["meeting", "mail", "manual", "pinboard", "request"])
def test_CC_PEOPLE_FR_PA_01_source_kind_accepts_its_five_kinds(repo_root, registry, kind):
    v(repo_root, registry, pl.put(pl.work_item(), ("source", "kind"), kind), kind)


def test_CC_PEOPLE_FR_PA_01_source_has_a_closed_kind_an_opaque_ref_and_at_most_five_evidence_ids(repo_root, registry):
    base = pl.work_item()
    for bad in ("call", "transcript", "Meeting", "", None):
        i(repo_root, registry, pl.put(base, ("source", "kind"), bad), f"source kind {bad!r}")
    for bad in ("https://example.com/m", "a:b", "a/b", "a.b", "", "x" * 97):
        i(repo_root, registry, pl.put(base, ("source", "ref"), bad), f"source ref {bad!r}")
    v(repo_root, registry, pl.put(base, ("source", "ref"), None), "null ref")
    ids = [f"u{n:04d}" for n in range(1, 7)]
    v(repo_root, registry, pl.put(base, ("source", "evidence"), ids[:5]), "5 evidence ids")
    i(repo_root, registry, pl.put(base, ("source", "evidence"), ids), "6 evidence ids")
    i(repo_root, registry, pl.put(base, ("source", "evidence"), ["u1"]), "bad evidence id")
    i(repo_root, registry, pl.put(base, ("source", "quote"), "he said so"), "source holds no quote")


@pytest.mark.parametrize(
    "created_by",
    [
        pl.maker_person("u_owner"),
        pl.maker_tilo("A_notes"),
        pl.maker_tilo("system"),
    ],
)
def test_CC_PEOPLE_PE_08_created_by_is_a_maker(repo_root, registry, created_by):
    v(repo_root, registry, pl.work_item(status="proposed", created_by=created_by, confirmed_by=None), str(created_by))


@pytest.mark.parametrize(
    "created_by",
    [
        {"by": "tilo", "ref": "u_owner", "at": pl.T0},
        {"by": "person", "ref": "A_notes", "at": pl.T0},
        {"by": "policy", "ref": "pol_x", "at": pl.T0},
        {"by": "person", "ref": "u_owner"},
        None,
    ],
)
def test_CC_PEOPLE_PE_08_created_by_rejects_a_wrong_maker(repo_root, registry, created_by):
    i(repo_root, registry, pl.work_item(created_by=created_by), str(created_by))


@pytest.mark.parametrize("field", ["assigned_by", "confirmed_by"])
def test_CC_PEOPLE_PE_07_assigned_and_confirmed_are_person_assignments_or_null(repo_root, registry, field):
    v(repo_root, registry, pl.work_item(**{field: pl.assignment("u_owner")}), field)
    for bad in (
        {"by": "A_notes", "at": pl.T0},
        {"by": "system", "at": pl.T0},
        {"by": "person", "ref": "u_owner", "at": pl.T0},
        {"by": "u_owner"},
        {"at": pl.T0},
        {"by": "u_owner", "at": "yesterday"},
        "u_owner",
    ):
        i(repo_root, registry, pl.work_item(**{field: bad}), f"{field}={bad!r}")


def test_CC_PEOPLE_PE_07_tilo_never_confirms_its_own_item(repo_root, registry):
    tilo = pl.maker_tilo("A_notes")
    for status in ("open", "done"):
        i(repo_root, registry, pl.work_item(created_by=tilo, status=status, confirmed_by=None), f"Tilo-made {status}")
        v(
            repo_root,
            registry,
            pl.work_item(created_by=tilo, status=status, confirmed_by=pl.assignment()),
            f"confirmed {status}",
        )
    for status in ("proposed", "dropped"):
        v(repo_root, registry, pl.work_item(created_by=tilo, status=status, confirmed_by=None), f"Tilo-made {status}")
    i(
        repo_root,
        registry,
        pl.work_item(created_by=tilo, status="open", confirmed_by={"by": "A_notes", "at": pl.T0}),
        "Tilo cannot be the confirmer",
    )
    v(
        repo_root,
        registry,
        pl.work_item(created_by=pl.maker_person(), status="open", confirmed_by=None),
        "person-made open",
    )


def test_CC_PEOPLE_FR_PA_01_history_is_never_empty_and_each_entry_is_closed(repo_root, registry):
    i(repo_root, registry, pl.work_item(history=[]), "empty history")
    v(
        repo_root,
        registry,
        pl.work_item(history=[pl.history_entry(), pl.history_entry(change="done", status="done")]),
        "two entries",
    )
    entry = pl.history_entry()
    for field in ("at", "by", "change", "status"):
        i(repo_root, registry, pl.work_item(history=[pl.drop(entry, (field,))]), f"history entry without {field}")
    i(repo_root, registry, pl.work_item(history=[pl.with_(entry, note="x")]), "extra key in history entry")
    i(repo_root, registry, pl.work_item(history=[pl.with_(entry, at="2026-10-01")]), "history at not a timestamp")


@pytest.mark.parametrize("change", CHANGES)
def test_CC_PEOPLE_FR_PA_01_history_change_accepts_each_listed_change(repo_root, registry, change):
    v(repo_root, registry, pl.work_item(history=[pl.history_entry(change=change)]), change)


@pytest.mark.parametrize("change", ["deleted", "accepted", "removed", "Created", "", None])
def test_CC_PEOPLE_FR_PA_01_history_change_rejects_other_values(repo_root, registry, change):
    i(repo_root, registry, pl.work_item(history=[pl.history_entry(change=change)]), repr(change))


@pytest.mark.parametrize("status", STATUSES)
def test_CC_PEOPLE_FR_PA_01_history_status_is_a_work_item_status(repo_root, registry, status):
    v(repo_root, registry, pl.work_item(history=[pl.history_entry(status=status)]), status)


@pytest.mark.parametrize("status", ["active", "removed", "", None])
def test_CC_PEOPLE_FR_PA_01_history_status_rejects_other_values(repo_root, registry, status):
    i(repo_root, registry, pl.work_item(history=[pl.history_entry(status=status)]), repr(status))


@pytest.mark.parametrize("actor", pl.VALID_ACTORS)
def test_CC_PEOPLE_FR_PA_01_history_by_is_an_event_actor(repo_root, registry, actor):
    v(repo_root, registry, pl.work_item(history=[pl.history_entry(by=actor)]), actor)


@pytest.mark.parametrize("actor", pl.INVALID_ACTORS)
def test_CC_PEOPLE_FR_PA_01_history_by_rejects_anything_that_is_not_an_event_actor(repo_root, registry, actor):
    i(repo_root, registry, pl.work_item(history=[pl.history_entry(by=actor)]), repr(actor))
