"""CC-PEOPLE: the twelve new event types and the additive `meeting.started` / `meeting.ended` fields
(registry 1.1.0; people.rules.md "Events", PE-11, PE-12; ADR-0011 optional means absent).

Every new type is `side_effect: false` with no `authz`; payloads carry ids, counts and enums, never
a title, a transcript line, a message body, an address or a link. Each type needs a registry entry
(family and verb spell the key, data schema and fixture paths exist, `story_template` / `trace_row`
use only {actor}, {target} and {data.<required field>}, a filled Story line is at most 140
characters), a data schema 1.0.0 and a valid fixture.

Ambiguity (reported): "P2 must" is read as pillar P2, priority `must`.
"""

from __future__ import annotations

import re

import _people_lib as pl
import pytest
from _events_lib import (
    data_schema_path,
    load_registry_raw,
    registry_entries,
)
from _lib import contracts_dir, errors_for, load_json, load_schema

TYPES = pl.NEW_EVENT_TYPES
BANNED_KEYS = ("title", "body", "text", "message", "link", "url", "address", "email", "transcript", "name", "subject")
PLACEHOLDER = re.compile(r"\{([^{}]*)\}")


def dv(repo_root, registry, type_, data, why=""):
    pl.assert_valid(repo_root, registry, f"events/data/{type_}", data, None, why or type_)


def di(repo_root, registry, type_, data, why=""):
    pl.assert_invalid(repo_root, registry, f"events/data/{type_}", data, None, why or type_)


# ---- registry -------------------------------------------------------------------------------------
@pytest.mark.parametrize("type_", TYPES)
def test_CC_PEOPLE_FR_WLD_03_registry_lists_the_type_with_a_complete_entry(repo_root, type_):
    entries = registry_entries(load_registry_raw(repo_root))
    assert type_ in entries, f"events/registry.yaml must register {type_}"
    entry = entries[type_]
    family, verb = type_.split(".")
    assert entry["family"] == family and entry["verb"] == verb
    assert entry["pillar"] == pl.EVENT_SPECS[type_][0]
    assert entry["priority"] == "must"
    assert entry["side_effect"] is False
    assert "authz_by" not in entry, "a non-side-effect type has no authz_by"
    assert entry["data_schema"] == f"events/data/{type_}.schema.json"
    assert entry["fixture"] == f"fixtures/events/valid/{type_}.json"
    assert (contracts_dir(repo_root) / entry["data_schema"]).is_file()
    assert (contracts_dir(repo_root) / entry["fixture"]).is_file()
    assert entry["default_severity"] in ("info", "fyi", "nudge", "needs_you", "blocked", "gate")
    for key in ("world_effect", "hud_effect", "story_template", "trace_row"):
        assert isinstance(entry[key], str) and entry[key]


@pytest.mark.parametrize("type_", TYPES)
def test_CC_PEOPLE_FR_WLD_03_story_and_trace_templates_use_only_actor_target_and_required_fields(repo_root, type_):
    entry = registry_entries(load_registry_raw(repo_root))[type_]
    required = set(load_json(data_schema_path(repo_root, type_))["required"])
    fixture = load_json(contracts_dir(repo_root) / entry["fixture"])
    for key in ("story_template", "trace_row"):
        for token in PLACEHOLDER.findall(entry[key]):
            ok = token in ("actor", "target") or (token.startswith("data.") and token[5:] in required)
            assert ok, f"{type_} {key}: {{{token}}} is not {{actor}}, {{target}} or {{data.<required field>}}"
    filled = PLACEHOLDER.sub(
        lambda m: str(
            fixture["actor"]
            if m.group(1) == "actor"
            else fixture["target"]
            if m.group(1) == "target"
            else fixture["data"][m.group(1)[5:]]
        ),
        entry["story_template"],
    )
    assert len(filled) <= 140, f"{type_}: a filled Story line is {len(filled)} characters, the limit is 140"


def test_CC_PEOPLE_FR_WLD_03_the_new_types_are_not_in_the_event_schemas_side_effect_list(repo_root):
    entries = registry_entries(load_registry_raw(repo_root))
    assert set(TYPES) <= set(entries), "the new types must be registered first"
    listed = set(load_schema(repo_root, "event")["if"]["properties"]["type"]["enum"])
    assert listed.isdisjoint(TYPES), f"side-effect list must not include {sorted(listed & set(TYPES))}"


# ---- data schemas ---------------------------------------------------------------------------------
@pytest.mark.parametrize("type_", TYPES)
def test_CC_PEOPLE_FR_WLD_03_data_schema_is_closed_titled_and_requires_every_listed_field(repo_root, type_):
    schema = load_json(data_schema_path(repo_root, type_)) if data_schema_path(repo_root, type_).is_file() else None
    assert schema is not None, f"contracts/events/data/{type_}.schema.json must exist"
    assert schema["$id"] == f"https://contracts.tilo.example/events/data/{type_}.schema.json"
    assert schema["x-version"] == "1.0.0"
    assert schema["title"] == pl.data_model_name(type_)
    assert schema["additionalProperties"] is False
    assert sorted(schema["required"]) == sorted(pl.EVENT_SPECS[type_][1])


@pytest.mark.parametrize("type_", TYPES)
def test_CC_PEOPLE_FR_WLD_03_a_valid_payload_passes(repo_root, registry, type_):
    dv(repo_root, registry, type_, pl.event_data(type_))


@pytest.mark.parametrize("type_", TYPES)
def test_CC_PEOPLE_FR_WLD_03_each_required_field_is_required(repo_root, registry, type_):
    for field in pl.EVENT_SPECS[type_][1]:
        di(repo_root, registry, type_, pl.drop(pl.event_data(type_), (field,)), f"{type_} without {field}")


@pytest.mark.parametrize("type_", TYPES)
def test_CC_PEOPLE_PE_11_payloads_never_carry_titles_bodies_addresses_or_links(repo_root, registry, type_):
    for key in BANNED_KEYS:
        di(repo_root, registry, type_, pl.with_(pl.event_data(type_), **{key: "x"}), f"{type_} + {key}")


def _bad_payloads() -> list[tuple[str, str, dict]]:
    e = pl.event_data
    rows: list[tuple[str, str, dict]] = []

    def add(type_: str, label: str, **ov):
        rows.append((type_, label, e(type_, **ov)))

    t = "meeting.minuted"
    for f in ("decisions", "action_items", "unverified"):
        add(t, f"{f} negative", **{f: -1})
        add(t, f"{f} fractional", **{f: 1.5})
        add(t, f"{f} a string", **{f: "2"})
    add(t, "flagged a string", flagged="no")
    add(t, "flagged null", flagged=None)
    add(t, "minutes a bare id", minutes="art_minutes1")
    add(t, "minutes without version", minutes={"artifact_id": "art_minutes1"})
    add(t, "meeting_id of another kind", meeting_id="wi_x")

    t = "work_item.created"
    for s in ("done", "dropped", "Open", "", None):
        add(t, f"status {s!r}", status=s)
    for s in ("call", "calendar", "", None):
        add(t, f"source_kind {s!r}", source_kind=s)
    add(t, "owner not a user", owner="riya")
    add(t, "work_item_id of another kind", work_item_id="mt_x")

    t = "work_item.changed"
    for c in ("created", "deleted", "accepted", "", None):
        add(t, f"change {c!r}", change=c)
    for s in ("removed", "active", "", None):
        add(t, f"status {s!r}", status=s)

    t = "pinboard.item_added"
    add(t, "team scope without a team", scope_kind="team", team=None)
    add(t, "personal scope with a team", scope_kind="personal", team="tm_sales")
    add(t, "scope kind org", scope_kind="org")
    add(t, "team not a team id", team="sales")
    for s in ("removed", "open", None):
        add(t, f"status {s!r}", status=s)
    for m in ("model", "system", "Tilo", None):
        add(t, f"made_by {m!r}", made_by=m)
    for s in ("pinboard", "calendar", ""):
        add(t, f"source_kind {s!r}", source_kind=s)

    t = "pinboard.item_changed"
    for c in ("created", "reopened", "done", "", None):
        add(t, f"change {c!r}", change=c)
    for s in ("open", "done", "", None):
        add(t, f"status {s!r}", status=s)

    t = "mention.added"
    add(t, "team not a team id", team="sales")
    add(t, "user not a user id", user="A_notes")
    add(t, "mention id of another kind", mention_id="pb_x")
    add(t, "team null", team=None)

    t = "mention.removed"
    for r in ("A_notes", "system", "riya", None):
        add(t, f"removed_by {r!r}", removed_by=r)

    t = "calendar.synced"
    for k in ("partial", "Full", "", None):
        add(t, f"kind {k!r}", kind=k)
    for c in (-1, 1.5, "3", None):
        add(t, f"changed {c!r}", changed=c)

    t = "calendar.entry_proposed"
    add(t, "entry id of another kind", entry_id="wi_x")
    for s in ("google", "calendar", "manual", "", None):
        add(t, f"source_kind {s!r}", source_kind=s)

    t = "calendar.entry_changed"
    for c in ("proposed", "created", "synced", "", None):
        add(t, f"change {c!r}", change=c)
    for s in ("open", "active", "", None):
        add(t, f"state {s!r}", state=s)

    t = "assistant.asked"
    for c in ("01j8z3k4m5n6p7q8r9s0t1v2w3", "abc", "", None):
        add(t, f"conversation_id {c!r}", conversation_id=c)
    for m in ("x", "r_01/ab", "r_01/1/2", "https://example.com/m", "1/12", "", None):
        add(t, f"message_ref {m!r}", message_ref=m)
    for s in ("admin", "Plate", "http://example.com", ""):
        add(t, f"screen {s!r}", screen=s)

    t = "assistant.replied"
    for o in ("ok", "Answered", "", None):
        add(t, f"outcome {o!r}", outcome=o)
    for d in ("default", "person", "policy", "", None):
        add(t, f"decided_by {d!r}", decided_by=d)
    add(t, "21 sources", sources=[{"kind": "work_item", "id": "wi_budget1"}] * 21)
    add(t, "source of kind user", sources=[{"kind": "user", "id": "u_riya"}])
    add(t, "source id a url", sources=[{"kind": "event", "id": "https://example.com"}])
    add(t, "source with a title", sources=[{"kind": "work_item", "id": "wi_1", "title": "x"}])
    add(t, "cached a string", cached="no")
    add(t, "ui_action that clicks", ui_action={"kind": "click", "selector": "#go"}, outcome="navigated")
    add(
        t,
        "ui_action with a url",
        ui_action={"kind": "navigate", "route": "plate", "target": None, "url": "https://x.example"},
        outcome="navigated",
    )
    add(t, "answered without a source", outcome="answered", sources=[])
    add(t, "navigated without a ui_action", outcome="navigated", sources=[], ui_action=None)
    add(t, "navigated with a null ui_action and a source", outcome="navigated", ui_action=None)
    return rows


BAD = _bad_payloads()


@pytest.mark.parametrize("type_,label,data", BAD, ids=[f"{t}:{lbl}" for t, lbl, _ in BAD])
def test_CC_PEOPLE_FR_WLD_03_a_payload_that_breaks_a_rule_is_refused(repo_root, registry, type_, label, data):
    di(repo_root, registry, type_, data, label)


def _good_payloads() -> list[tuple[str, str, dict]]:
    e = pl.event_data
    nav = pl.ui_action("navigate", route="meeting", target={"kind": "meeting", "id": "mt_weekly1"})
    return [
        *[("work_item.created", f"status {s}", e("work_item.created", status=s)) for s in ("proposed", "open")],
        *[
            ("work_item.created", f"source_kind {s}", e("work_item.created", source_kind=s))
            for s in ("meeting", "mail", "manual", "pinboard", "request")
        ],
        *[
            ("work_item.changed", f"change {c}", e("work_item.changed", change=c))
            for c in ("confirmed", "edited", "snoozed", "done", "dropped", "reopened", "reassign_requested", "reminded")
        ],
        *[
            ("work_item.changed", f"status {s}", e("work_item.changed", status=s))
            for s in ("proposed", "open", "done", "dropped")
        ],
        (
            "pinboard.item_added",
            "personal, no team",
            e(
                "pinboard.item_added",
                scope_kind="personal",
                team=None,
                status="active",
                made_by="person",
                source_kind=None,
            ),
        ),
        ("pinboard.item_added", "team, tilo, meeting", e("pinboard.item_added")),
        *[
            ("pinboard.item_added", f"source_kind {s}", e("pinboard.item_added", source_kind=s))
            for s in ("meeting", "mail", "call", "request", "manual", None)
        ],
        *[
            ("pinboard.item_changed", f"change {c}", e("pinboard.item_changed", change=c))
            for c in ("edited", "accepted", "removed", "undone", "owner_changed")
        ],
        *[
            ("pinboard.item_changed", f"status {s}", e("pinboard.item_changed", status=s))
            for s in ("proposed", "active", "removed")
        ],
        *[("calendar.synced", f"kind {k}", e("calendar.synced", kind=k)) for k in ("incremental", "full")],
        ("calendar.synced", "nothing changed", e("calendar.synced", changed=0)),
        *[
            ("calendar.entry_proposed", f"source_kind {s}", e("calendar.entry_proposed", source_kind=s))
            for s in ("meeting", "transcript", "request", "mail")
        ],
        *[
            ("calendar.entry_changed", f"change {c}", e("calendar.entry_changed", change=c))
            for c in ("accepted", "declined", "edited", "removed", "shared", "unshared")
        ],
        *[
            ("calendar.entry_changed", f"state {s}", e("calendar.entry_changed", state=s))
            for s in ("proposed", "accepted", "declined", "cancelled")
        ],
        ("assistant.asked", "no screen", e("assistant.asked", screen=None)),
        *[("assistant.asked", f"screen {r}", e("assistant.asked", screen=r)) for r in pl.ROUTES],
        ("assistant.replied", "declined without sources", e("assistant.replied", outcome="declined", sources=[])),
        (
            "assistant.replied",
            "failed without sources",
            e("assistant.replied", outcome="failed", sources=[], decided_by="model"),
        ),
        (
            "assistant.replied",
            "navigated with a ui_action",
            e("assistant.replied", outcome="navigated", sources=[], ui_action=nav),
        ),
        (
            "assistant.replied",
            "answered with 20 sources",
            e("assistant.replied", sources=[{"kind": "event", "id": f"e{n}"} for n in range(20)]),
        ),
        ("assistant.replied", "cached answer", e("assistant.replied", cached=True)),
        *[
            (
                "assistant.replied",
                f"outcome {o}",
                e("assistant.replied", outcome=o, sources=[{"kind": "card", "id": "c1"}], ui_action=nav),
            )
            for o in ("answered", "navigated")
        ],
        *[
            ("assistant.replied", f"source kind {k}", e("assistant.replied", sources=[{"kind": k, "id": "x1"}]))
            for k in ("work_item", "calendar_entry", "meeting", "pinboard_item", "mention", "card", "world", "event")
        ],
    ]


GOOD = _good_payloads()


@pytest.mark.parametrize("type_,label,data", GOOD, ids=[f"{t}:{lbl}" for t, lbl, _ in GOOD])
def test_CC_PEOPLE_FR_WLD_03_a_payload_that_follows_the_rules_is_accepted(repo_root, registry, type_, label, data):
    dv(repo_root, registry, type_, data, label)


# ---- meeting.started / meeting.ended 1.1.0 --------------------------------------------------------
@pytest.mark.parametrize("type_", ["meeting.started", "meeting.ended"])
def test_CC_PEOPLE_FR_MTG_07_meeting_started_and_ended_data_are_1_1_0_and_old_payloads_stay_valid(
    repo_root, registry, type_
):
    schema = load_json(data_schema_path(repo_root, type_))
    assert schema["x-version"] == "1.1.0"
    assert schema["additionalProperties"] is False
    assert schema["required"] == [], "old payloads {} stay valid, so nothing becomes required"
    dv(repo_root, registry, type_, {}, "old payload")
    dv(repo_root, registry, type_, {"meeting_id": "mt_weekly1"}, "with meeting_id")


@pytest.mark.parametrize("type_", ["meeting.started", "meeting.ended"])
def test_CC_PEOPLE_FR_MTG_07_optional_means_absent_never_null(repo_root, registry, type_):
    dv(repo_root, registry, type_, {"meeting_id": "mt_weekly1"}, "meeting_id present")
    di(repo_root, registry, type_, {"meeting_id": None}, "meeting_id null")
    for bad in ("wi_x", "mt_", "weekly", 5):
        di(repo_root, registry, type_, {"meeting_id": bad}, f"meeting_id {bad!r}")
    for key in ("title", "link", "url", "transcript"):
        di(repo_root, registry, type_, {key: "x"}, f"{type_} + {key}")


@pytest.mark.parametrize("reason", ["completed", "left_on_request", "removed", "timeout", "failed"])
def test_CC_PEOPLE_FR_MTG_10_meeting_ended_reason_accepts_the_five_reasons(repo_root, registry, reason):
    dv(repo_root, registry, "meeting.ended", {"meeting_id": "mt_weekly1", "reason": reason}, reason)
    dv(repo_root, registry, "meeting.ended", {"reason": reason}, f"{reason} without meeting_id")


@pytest.mark.parametrize("reason", [None, "crashed", "Completed", "", "left", 0])
def test_CC_PEOPLE_FR_MTG_10_meeting_ended_reason_rejects_null_and_other_values(repo_root, registry, reason):
    dv(repo_root, registry, "meeting.ended", {"reason": "completed"}, "a real reason is valid")
    di(repo_root, registry, "meeting.ended", {"meeting_id": "mt_weekly1", "reason": reason}, repr(reason))


def test_CC_PEOPLE_FR_MTG_10_meeting_started_takes_no_reason(repo_root, registry):
    dv(repo_root, registry, "meeting.started", {"meeting_id": "mt_weekly1"}, "meeting_id is allowed")
    di(repo_root, registry, "meeting.started", {"reason": "completed"}, "reason on meeting.started")


# ---- fixtures -------------------------------------------------------------------------------------
@pytest.mark.parametrize("type_", TYPES)
def test_CC_PEOPLE_FR_WLD_03_the_valid_event_fixture_passes_the_event_and_data_schemas(repo_root, registry, type_):
    path = contracts_dir(repo_root) / "fixtures" / "events" / "valid" / f"{type_}.json"
    assert path.is_file(), f"fixtures/events/valid/{type_}.json must exist"
    event = load_json(path)
    assert event["type"] == type_
    found = [e.message for e in errors_for(load_schema(repo_root, "event"), event, registry)]
    assert not found, f"{type_}: event.schema.json: {found[:3]}"
    dv(repo_root, registry, type_, event["data"], f"{type_} fixture data")
    assert event["authz"] is None, "EV-05: only side-effect types carry authz"
    assert len(event["summary"]) <= 140


@pytest.mark.parametrize("type_", TYPES)
def test_CC_PEOPLE_PE_11_the_fixture_payload_holds_ids_counts_and_enums_only(repo_root, type_):
    event = load_json(contracts_dir(repo_root) / "fixtures" / "events" / "valid" / f"{type_}.json")

    def strings(node):
        if isinstance(node, str):
            yield node
        elif isinstance(node, dict):
            for k, val in node.items():
                yield k
                yield from strings(val)
        elif isinstance(node, list):
            for val in node:
                yield from strings(val)

    for s in strings(event["data"]):
        assert "@" not in s and "http" not in s.lower() and " " not in s and "\n" not in s, f"{type_}: {s!r}"
    assert not set(BANNED_KEYS) & set(event["data"])
