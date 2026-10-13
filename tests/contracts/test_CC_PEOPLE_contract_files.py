"""CC-PEOPLE: the eight new contract files, common.schema.json 1.2.0 and the shared "line" rule.

Requirement trail: FR-WLD-02 and ADR-0002 (file conventions: 2020-12, `$id`, `x-version`, `title`,
closed objects), people.rules.md PE-02/PE-06/PE-11 (the ids, `maker`, `record_ref`, `opaque_ref`),
FR-PA-01/FR-MTG-01/FR-PB-01 (names and titles are one-line text).

Test-writer split: none of the new files exists yet, so every test here fails with
"contracts/<name>.schema.json does not exist (ticket CC-PEOPLE adds it)".
"""

from __future__ import annotations

import re
import string

import _people_lib as pl
import pytest
from _events_lib import load_registry_raw, registry_schema_path
from _lib import errors_for, load_json
from hypothesis import Phase, given, settings
from hypothesis import strategies as st

SCHEMAS = {
    "person": "Person",
    "meeting": "Meeting",
    "minutes": "Minutes",
    "work_item": "WorkItem",
    "pinboard_item": "PinboardItem",
    "mention": "Mention",
    "calendar_entry": "CalendarEntry",
    "ui_action": "UiAction",
}


@pytest.mark.parametrize("name,title", sorted(SCHEMAS.items()))
def test_CC_PEOPLE_FR_WLD_02_schema_file_follows_the_contract_conventions(repo_root, name, title):
    import jsonschema

    schema = pl.load_contract(repo_root, name)
    jsonschema.Draft202012Validator.check_schema(schema)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"] == f"https://contracts.tilo.example/{name}.schema.json"
    if name == "work_item":  # 1.1.0 adds the optional world_id (ADR-0040, PE-33)
        assert tuple(map(int, schema["x-version"].split("."))) >= (1, 1, 0), "work_item is 1.1.0 or later"
    elif name == "meeting":  # 1.1.0 adds world_id (ADR-0020); 1.2.0 tightens the link check (ADR-0016 decision 14)
        assert tuple(map(int, schema["x-version"].split("."))) >= (1, 2, 0), "meeting is 1.2.0 or later"
    elif name in ("calendar_entry", "pinboard_item"):  # 1.1.0: agenda_item.joinable (MJ-10); placement (ADR-0038)
        assert tuple(map(int, schema["x-version"].split("."))) >= (1, 1, 0), f"{name} is 1.1.0 or later"
    else:
        assert schema["x-version"] == "1.0.0"
    assert schema["title"] == title
    assert "allOf" not in schema, "contracts/CLAUDE.md: avoid a root-level allOf (open intersection types)"
    if name != "ui_action":
        assert schema.get("additionalProperties") is False, f"{name}: root additionalProperties must be false"


@pytest.mark.parametrize(
    "name,defs",
    [
        ("calendar_entry", {"agenda_item", "free_busy"}),
        ("ui_action", {"route", "target"}),
    ],
)
def test_CC_PEOPLE_FR_WLD_02_schema_declares_its_named_defs(repo_root, name, defs):
    schema = pl.load_contract(repo_root, name)
    assert defs <= set(schema.get("$defs", {})), f"{name} must declare $defs {sorted(defs)}"
    if name == "calendar_entry":
        for d in defs:
            assert schema["$defs"][d].get("additionalProperties") is False, f"$defs/{d} must be closed"


def test_CC_PEOPLE_FR_WLD_02_common_schema_is_1_3_0_and_keeps_its_old_defs(repo_root):
    schema = pl.load_contract(repo_root, "common")
    # 1.2.0 merged two 1.1.0 releases (#379: pinned); 1.3.0 adds `mail` to record_ref.kind (ADR-0021);
    # later minors are additive (ADR-0002 item 15).
    version = tuple(int(p) for p in schema["x-version"].split("."))
    assert version >= (1, 3, 0), "common carries the people ids, media_type and mail: 1.3.0 or later"
    old = {"ulid", "timestamp", "calendar_date", "authz", "artifact_ref", "destination", "user_id", "org_id"}
    new = {
        "work_item_id",
        "meeting_id",
        "pin_id",
        "mention_id",
        "calendar_entry_id",
        "team_id",
        "utterance_id",
        "opaque_ref",
        "maker",
        "record_ref",
    }
    assert (old | new) <= set(schema["$defs"]), f"common $defs missing {sorted((old | new) - set(schema['$defs']))}"


def test_CC_PEOPLE_FR_WLD_03_registry_files_are_1_1_0_with_the_new_families(repo_root, registry):
    reg_schema = load_json(registry_schema_path(repo_root))
    # 1.1.0 added the people families; later minors are additive (1.2.0: team_rule, ADR-0027).
    assert tuple(int(p) for p in reg_schema["x-version"].split(".")) >= (1, 1, 0)
    families = set(reg_schema["$defs"]["family"]["enum"])
    assert set(pl.NEW_FAMILIES) <= families, f"registry family enum lacks {sorted(set(pl.NEW_FAMILIES) - families)}"
    assert {"meeting", "world", "app"} <= families, "existing families stay"
    raw = load_registry_raw(repo_root)
    assert raw is not None and tuple(int(p) for p in raw["version"].split(".")) >= (1, 1, 0)
    found = [e.message for e in errors_for(reg_schema, raw, registry)]
    assert not found, f"registry.yaml must validate against registry.schema.json: {found[:3]}"


# ---- common $defs: ids ---------------------------------------------------------------------------
ID_CASES = {
    "work_item_id": ("wi_", r"^wi_[0-9A-Za-z_]{1,48}$"),
    "meeting_id": ("mt_", r"^mt_[0-9A-Za-z_]{1,48}$"),
    "pin_id": ("pb_", r"^pb_[0-9A-Za-z_]{1,48}$"),
    "mention_id": ("mn_", r"^mn_[0-9A-Za-z_]{1,48}$"),
    "calendar_entry_id": ("ce_", r"^ce_[0-9A-Za-z_]{1,48}$"),
}


@pytest.mark.parametrize("def_,spec", sorted(ID_CASES.items()))
def test_CC_PEOPLE_PE_11_record_ids_have_one_prefix_and_up_to_48_characters(repo_root, registry, def_, spec):
    prefix = spec[0]
    for ok in (f"{prefix}a", f"{prefix}A_9z", prefix + "x" * 48):
        pl.assert_valid(repo_root, registry, "common", ok, def_, f"{def_} {ok!r}")
    other = next(p for p, _ in ID_CASES.values() if p != prefix)
    for bad in (prefix, prefix + "x" * 49, f"{other}a", f"{prefix}a-b", f"{prefix}a b", "a" + prefix + "a", ""):
        pl.assert_invalid(repo_root, registry, "common", bad, def_, f"{def_} {bad!r}")


def test_CC_PEOPLE_PE_02_team_id_is_lower_case_with_a_tm_prefix(repo_root, registry):
    for ok in ("tm_sales", "tm_a", "tm_" + "x" * 48, "tm_q4_ops"):
        pl.assert_valid(repo_root, registry, "common", ok, "team_id", ok)
    for bad in ("tm_", "tm_Sales", "tm_" + "x" * 49, "sales", "tm-sales", "tl_sales", "u_sales", ""):
        pl.assert_invalid(repo_root, registry, "common", bad, "team_id", bad)


def test_CC_PEOPLE_FR_MTG_02_utterance_id_is_u_and_four_to_six_digits(repo_root, registry):
    for ok in ("u0001", "u0042", "u12345", "u123456"):
        pl.assert_valid(repo_root, registry, "common", ok, "utterance_id", ok)
    for bad in ("u001", "u1234567", "u00a1", "U0001", "0001", "u_0001", "u0001 ", ""):
        pl.assert_invalid(repo_root, registry, "common", bad, "utterance_id", bad)


def test_CC_PEOPLE_PE_11_opaque_ref_can_never_be_a_url(repo_root, registry):
    for ok in ("msg_1", "mt_weekly1", "thread-9#c2", "A" * 96, "a#b-c_d"):
        pl.assert_valid(repo_root, registry, "common", ok, "opaque_ref", ok)
    for bad in (
        "",
        "a" * 97,
        "https://example.com",
        "a:b",
        "a/b",
        "a.b",
        "example.com",
        "a b",
        "a@b",
        "a?b",
        "a%20b",
    ):
        pl.assert_invalid(repo_root, registry, "common", bad, "opaque_ref", bad)


def test_CC_PEOPLE_PE_08_maker_is_a_person_or_tilo_with_the_matching_ref(repo_root, registry):
    good = [
        {"by": "person", "ref": "u_riya", "at": pl.T0},
        {"by": "tilo", "ref": "A_notes", "at": pl.T0},
        {"by": "tilo", "ref": "system", "at": pl.T0},
    ]
    for doc in good:
        pl.assert_valid(repo_root, registry, "common", doc, "maker", str(doc))
    bad = [
        {"by": "person", "ref": "A_notes", "at": pl.T0},
        {"by": "person", "ref": "system", "at": pl.T0},
        {"by": "person", "ref": "tl_sales", "at": pl.T0},
        {"by": "tilo", "ref": "u_riya", "at": pl.T0},
        {"by": "tilo", "ref": "tl_sales", "at": pl.T0},
        {"by": "tilo", "ref": "pol_autoreply", "at": pl.T0},
        {"by": "tilo", "ref": "System", "at": pl.T0},
        {"by": "policy", "ref": "pol_autoreply", "at": pl.T0},
        {"by": "model", "ref": "A_notes", "at": pl.T0},
        {"by": "person", "ref": "u_riya", "at": "2026-10-01"},
        {"by": "person", "ref": "u_riya"},
        {"by": "person", "at": pl.T0},
        {"ref": "u_riya", "at": pl.T0},
        {"by": "person", "ref": "u_riya", "at": pl.T0, "note": "extra"},
        {"by": "person", "ref": None, "at": pl.T0},
    ]
    for doc in bad:
        pl.assert_invalid(repo_root, registry, "common", doc, "maker", str(doc))


def test_CC_PEOPLE_PE_11_record_ref_names_a_kind_and_a_plain_id(repo_root, registry):
    kinds = ("work_item", "calendar_entry", "meeting", "pinboard_item", "mention", "card", "world", "event", "mail")
    for kind in kinds:
        pl.assert_valid(repo_root, registry, "common", {"kind": kind, "id": "wi_1"}, "record_ref", kind)
    pl.assert_valid(repo_root, registry, "common", {"kind": "event", "id": "A" * 64}, "record_ref")
    bad = [
        {"kind": "user", "id": "u_riya"},
        {"kind": "transcript", "id": "x"},
        {"kind": "event", "id": "a" * 65},
        {"kind": "event", "id": ""},
        {"kind": "event", "id": "a:b"},
        {"kind": "event", "id": "a/b"},
        {"kind": "event", "id": "a-b"},
        {"kind": "event"},
        {"id": "wi_1"},
        {"kind": "event", "id": "wi_1", "title": "x"},
    ]
    for doc in bad:
        pl.assert_invalid(repo_root, registry, "common", doc, "record_ref", str(doc))


@settings(max_examples=40, phases=[Phase.generate])
@given(
    def_=st.sampled_from(sorted(ID_CASES) + ["team_id", "utterance_id"]),
    text=st.text(alphabet="wimtpbcenu_abcXYZ0129-:/. ", min_size=0, max_size=14),
)
def test_CC_PEOPLE_PE_11_property_id_defs_accept_exactly_their_pattern(repo_root, registry, def_, text):
    patterns = {
        **{k: v[1] for k, v in ID_CASES.items()},
        "team_id": r"^tm_[0-9a-z_]{1,48}$",
        "utterance_id": r"^u[0-9]{4,6}$",
    }
    expected = re.fullmatch(patterns[def_][1:-1], text) is not None
    got = not pl.problems(repo_root, registry, "common", text, def_)
    assert got == expected, f"{def_}: {text!r} expected valid={expected}"


# ---- "line" strings: one line, bounded, no control characters ---------------------------------------
# (schema file, $defs name or None, factory, path, max length)
LINE_FIELDS = [
    ("person", None, pl.person, ("display_name",), 80),
    ("person", None, pl.person, ("aliases", 0), 40),
    ("meeting", None, pl.meeting, ("title",), 120),
    ("meeting", None, pl.meeting, ("agenda", 0, "title"), 120),
    ("meeting", None, pl.meeting, ("attendees", 0, "name"), 80),
    ("minutes", None, pl.minutes, ("summary", 0, "text"), 240),
    ("minutes", None, pl.minutes, ("decisions", 0, "text"), 240),
    ("minutes", None, pl.minutes, ("action_items", 0, "text"), 240),
    ("minutes", None, pl.minutes, ("action_items", 0, "owner_text"), 80),
    ("minutes", None, pl.minutes, ("action_items", 0, "due_text"), 60),
    ("minutes", None, pl.minutes, ("agenda", 0, "title"), 120),
    ("work_item", None, pl.work_item, ("title",), 140),
    ("work_item", None, pl.work_item, ("due_text",), 60),
    ("pinboard_item", None, pl.pin, ("title",), 140),
    ("pinboard_item", None, lambda: pl.pin(body="A note."), ("body",), 600),
    ("calendar_entry", None, pl.calendar_entry, ("title",), 140),
    ("calendar_entry", "agenda_item", pl.agenda_item, ("title",), 140),
]
LINE_IDS = [f"{s}{'.' + d if d else ''}:{'.'.join(map(str, p))}" for s, d, _, p, _ in LINE_FIELDS]


@pytest.mark.parametrize("schema,def_,factory,path,limit", LINE_FIELDS, ids=LINE_IDS)
def test_CC_PEOPLE_FR_PB_01_line_strings_are_one_bounded_line(repo_root, registry, schema, def_, factory, path, limit):
    base = factory()
    pl.assert_valid(repo_root, registry, schema, base, def_, "the baseline document")
    for ok in ("x", "x" * limit, "Budget review, Q4 (draft) & more"):
        pl.assert_valid(repo_root, registry, schema, pl.put(base, path, ok), def_, f"len {len(ok)}")
    pl.assert_invalid(repo_root, registry, schema, pl.put(base, path, ""), def_, "empty line")
    pl.assert_invalid(repo_root, registry, schema, pl.put(base, path, "x" * (limit + 1)), def_, f"len {limit + 1}")
    for bad in pl.BAD_LINES:
        pl.assert_invalid(repo_root, registry, schema, pl.put(base, path, bad), def_, f"control character {bad!r}")


@settings(max_examples=40, phases=[Phase.generate])
@given(
    text=st.text(alphabet=string.ascii_letters + string.digits, min_size=1, max_size=30),
    control=st.sampled_from([chr(c) for c in range(0, 32)]),
    where=st.integers(min_value=0, max_value=30),
)
def test_CC_PEOPLE_FR_PB_01_property_a_control_character_anywhere_breaks_a_line(
    repo_root, registry, text, control, where
):
    base = pl.pin()
    pl.assert_valid(repo_root, registry, "pinboard_item", pl.put(base, ("title",), text), None, "plain title")
    i = min(where, len(text))
    broken = text[:i] + control + text[i:]
    pl.assert_invalid(repo_root, registry, "pinboard_item", pl.put(base, ("title",), broken), None, repr(broken))
