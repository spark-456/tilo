"""CC-PEOPLE: contracts/ui_action.schema.json, the allow-list for the assistant panel
(people.rules.md PE-10; FR-PA-14, FR-PA-16).

A closed union on `kind`: navigate, mark_done, snooze, draft_reply, tag, untag. The closed `route`
and `target` lists are the allow-list; no kind clicks, types, selects or sends, and no variant has a
selector, coordinates, script, url or text field. A model output that does not validate is dropped.
"""

from __future__ import annotations

import _people_lib as pl
import pytest
from hypothesis import Phase, given, settings
from hypothesis import strategies as st

KINDS = tuple(pl.UI_ACTIONS)
FORBIDDEN_PROPS = (
    "selector",
    "coordinates",
    "x",
    "y",
    "script",
    "url",
    "text",
    "href",
    "value",
    "body",
    "html",
    "message",
    "to",
)


def v(repo_root, registry, doc, why=""):
    pl.assert_valid(repo_root, registry, "ui_action", doc, None, why or "ui_action")


def i(repo_root, registry, doc, why=""):
    pl.assert_invalid(repo_root, registry, "ui_action", doc, None, why or "ui_action")


@pytest.mark.parametrize("kind", KINDS)
def test_CC_PEOPLE_PE_10_each_of_the_six_kinds_has_a_valid_form(repo_root, registry, kind):
    v(repo_root, registry, pl.ui_action(kind), kind)


def test_CC_PEOPLE_PE_10_the_route_list_is_closed_and_exactly_the_published_thirteen(repo_root, registry):
    schema = pl.load_contract(repo_root, "ui_action")
    enum = schema["$defs"]["route"]["enum"]
    assert len(enum) == 13 and set(enum) == set(pl.ROUTES), "route enum must be exactly the 13 published routes"
    for route in pl.ROUTES:
        v(repo_root, registry, pl.ui_action("navigate", route=route), route)
        pl.assert_valid(repo_root, registry, "ui_action", route, "route", route)


@pytest.mark.parametrize(
    "route",
    [
        "admin",
        "home",
        "Plate",
        "world_list",
        "http://example.com",
        "https://example.com/plate",
        "../plate",
        "/plate",
        "plate/",
        "",
        None,
        1,
    ],
)
def test_CC_PEOPLE_PE_10_a_route_outside_the_list_is_invalid(repo_root, registry, route):
    i(repo_root, registry, pl.ui_action("navigate", route=route), f"route {route!r}")
    pl.assert_invalid(repo_root, registry, "ui_action", route, "route", f"$defs/route {route!r}")


def test_CC_PEOPLE_PE_10_navigate_target_is_null_or_one_of_six_record_kinds(repo_root, registry):
    for target in pl.TARGETS:
        v(repo_root, registry, pl.ui_action("navigate", route="world", target=target), str(target))
        pl.assert_valid(repo_root, registry, "ui_action", target, "target", str(target))
    # Whether `null` lives inside $defs/target or only at navigate.target is not asserted (brief: "null or one of").
    assert len(pl.TARGETS) == 6


@pytest.mark.parametrize(
    "target",
    [
        {"kind": "user", "id": "u_riya"},
        {"kind": "url", "id": "https://example.com"},
        {"kind": "thread", "id": "thread-1"},
        {"kind": "event", "id": "x"},
        {"kind": "world", "id": "mt_weekly1"},
        {"kind": "meeting", "id": "w_village1"},
        {"kind": "card", "id": "card_1"},
        {"kind": "card", "id": "01j8z3k4m5n6p7q8r9s0t1v2w3"},
        {"kind": "pin", "id": "wi_budget1"},
        {"kind": "work_item", "id": "pb_deadline1"},
        {"kind": "calendar_entry", "id": "wi_budget1"},
        {"kind": "world"},
        {"id": "w_village1"},
        {"kind": "world", "id": "w_village1", "url": "https://example.com"},
        {"kind": "world", "id": "w_village1", "selector": "#go"},
        {},
        "w_village1",
        7,
    ],
)
def test_CC_PEOPLE_PE_10_a_target_of_any_other_kind_or_shape_is_invalid(repo_root, registry, target):
    i(repo_root, registry, pl.ui_action("navigate", target=target), f"target {target!r}")
    pl.assert_invalid(repo_root, registry, "ui_action", target, "target", f"$defs/target {target!r}")


@pytest.mark.parametrize(
    "kind",
    [
        "click",
        "type",
        "select",
        "send",
        "send_email",
        "open_url",
        "run_script",
        "fill",
        "submit",
        "delete",
        "Navigate",
        "",
        None,
        1,
    ],
)
def test_CC_PEOPLE_PE_10_no_kind_clicks_types_selects_or_sends(repo_root, registry, kind):
    i(repo_root, registry, {"kind": kind}, f"kind {kind!r}")
    i(repo_root, registry, pl.with_(pl.ui_action("mark_done"), kind=kind), f"mark_done body, kind {kind!r}")


def test_CC_PEOPLE_PE_10_a_document_without_a_kind_is_invalid(repo_root, registry):
    i(repo_root, registry, {}, "empty object")
    i(repo_root, registry, pl.drop(pl.ui_action("navigate"), ("kind",)), "no kind")
    i(repo_root, registry, None, "null")
    i(repo_root, registry, "navigate", "a bare string")
    i(repo_root, registry, [pl.ui_action("navigate")], "an array")


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("extra", FORBIDDEN_PROPS)
def test_CC_PEOPLE_PE_10_every_variant_is_closed_to_selectors_coordinates_scripts_urls_and_text(
    repo_root, registry, kind, extra
):
    i(repo_root, registry, pl.with_(pl.ui_action(kind), **{extra: "x"}), f"{kind} + {extra}")


@pytest.mark.parametrize("kind", KINDS)
def test_CC_PEOPLE_PE_10_every_variant_requires_all_its_fields(repo_root, registry, kind):
    action = pl.ui_action(kind)
    for field in action:
        if field == "kind":
            continue
        if kind == "navigate" and field == "target":
            continue  # a missing target is not asserted: null is its "no record" form
        i(repo_root, registry, pl.drop(action, (field,)), f"{kind} without {field}")


def test_CC_PEOPLE_PE_10_a_variant_cannot_borrow_another_variants_fields(repo_root, registry):
    i(repo_root, registry, pl.with_(pl.ui_action("mark_done"), route="plate"), "mark_done with a route")
    i(repo_root, registry, pl.with_(pl.ui_action("navigate"), work_item_id="wi_budget1"), "navigate with a work item")
    i(repo_root, registry, pl.with_(pl.ui_action("tag"), until=pl.T1), "tag with until")
    i(repo_root, registry, pl.with_(pl.ui_action("snooze"), thread="thread-1"), "snooze with a thread")
    i(repo_root, registry, pl.with_(pl.ui_action("draft_reply"), user="u_riya"), "draft_reply with a user")


@pytest.mark.parametrize("bad", ["mt_weekly1", "wi_", "budget1", "WI_budget1", None, 5])
def test_CC_PEOPLE_PE_10_mark_done_and_snooze_name_a_work_item_id(repo_root, registry, bad):
    i(repo_root, registry, pl.ui_action("mark_done", work_item_id=bad), f"mark_done {bad!r}")
    i(repo_root, registry, pl.ui_action("snooze", work_item_id=bad), f"snooze {bad!r}")


@pytest.mark.parametrize("until", ["tomorrow", "2026-10-02", "2026-10-02T09:00:00Z", "in 1 hour", None, 1790000000])
def test_CC_PEOPLE_PE_10_snooze_until_is_a_timestamp(repo_root, registry, until):
    i(repo_root, registry, pl.ui_action("snooze", until=until), f"until {until!r}")


@pytest.mark.parametrize(
    "thread",
    ["https://mail.example.com/t/1", "a:b", "a/b", "a.b", "a b", "", "-lead", "x" * 201, "a@b", None, 5],
)
def test_CC_PEOPLE_PE_10_draft_reply_thread_is_a_destination_never_a_url(repo_root, registry, thread):
    i(repo_root, registry, pl.ui_action("draft_reply", thread=thread), f"thread {thread!r}")


def test_CC_PEOPLE_PE_10_draft_reply_accepts_a_destination(repo_root, registry):
    for ok in ("thread-supplier-1", "T9", "a" * 200):
        v(repo_root, registry, pl.ui_action("draft_reply", thread=ok), ok)


@pytest.mark.parametrize("kind", ["tag", "untag"])
def test_CC_PEOPLE_PE_10_tag_and_untag_name_a_pin_and_a_person(repo_root, registry, kind):
    for field, bad in (
        ("pin_id", "wi_budget1"),
        ("pin_id", "pb_"),
        ("pin_id", None),
        ("user", "riya"),
        ("user", "A_notes"),
        ("user", "tm_sales"),
        ("user", None),
    ):
        i(repo_root, registry, pl.ui_action(kind, **{field: bad}), f"{kind} {field}={bad!r}")


@settings(max_examples=40, phases=[Phase.generate])
@given(kind=st.text(min_size=0, max_size=12).filter(lambda s: s not in KINDS))
def test_CC_PEOPLE_PE_10_property_any_kind_outside_the_six_is_invalid(repo_root, registry, kind):
    i(repo_root, registry, {"kind": kind}, f"kind {kind!r}")
    i(repo_root, registry, pl.with_(pl.ui_action("navigate"), kind=kind), f"navigate body, kind {kind!r}")


@settings(max_examples=40, phases=[Phase.generate])
@given(
    kind=st.sampled_from(KINDS),
    extra=st.text(alphabet="abcdefghijklmnopqrstuvwxyz_", min_size=1, max_size=12),
)
def test_CC_PEOPLE_PE_10_property_an_unlisted_property_never_validates(repo_root, registry, kind, extra):
    action = pl.ui_action(kind)
    if extra in action:
        return
    i(repo_root, registry, pl.with_(action, **{extra: "x"}), f"{kind} + {extra}")
