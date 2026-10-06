"""FR-INT-15 (supplement 2026-10-05 section 4) config side: `config/capability_gaps.yaml`, its loader
`tilo_planning.gaps.load_gap_policy`, the `Gap` text, and `clean_part`, the label cleaner. "Says plainly what it
could not do and offers alternatives": every gap category carries a configured reason and alternative, so a model
never writes what Tilo can or cannot do (PRD 16.3, BQ-INT15-6). A hard refusal stays for FR-INT-12's categories only:
the two files never share an id (BQ-INT15-1). Interface: `API_FR_INT_15.md`.

The first group of tests reads the shipped YAML directly, so it already holds before the module exists.
"""

from __future__ import annotations

import re
import unicodedata

import pytest
import yaml
from _fr_int_15_lib import (
    CONNECTORS_CONFIG,
    GAP_CONFIG,
    GAP_IDS,
    REFUSAL_CONFIG,
    REFUSAL_IDS,
    gap_config_dict,
    write_connectors,
    write_gap_config,
)
from hypothesis import given, settings
from hypothesis import strategies as st

SLUG = re.compile(r"[a-z][a-z0-9_]{0,63}")
MARKER = "zq7-marker-value"


def gaps():
    import tilo_planning.gaps as module  # noqa: PLC0415

    return module


def shipped():
    return yaml.safe_load(GAP_CONFIG.read_text(encoding="utf-8"))


# --- the shipped file (readable now) ---


def test_FR_INT_15_the_shipped_gap_config_has_seven_categories_each_with_a_reason_and_an_alternative():
    assert GAP_CONFIG.is_file(), "config/capability_gaps.yaml is missing"
    config = shipped()

    assert set(config) == {"nothing_possible", "categories"}
    assert [c["id"] for c in config["categories"]] == list(GAP_IDS)
    for c in config["categories"]:
        assert set(c) == {"id", "reason", "alternative"}
        assert SLUG.fullmatch(c["id"])
        assert 1 <= len(c["reason"]) <= 120 and 1 <= len(c["alternative"]) <= 200, c["id"]
        assert c["reason"].strip() and c["alternative"].strip()
        assert c["alternative"].strip() != c["reason"].strip(), "the alternative is a different thing: what to ask for"
    assert 1 <= len(config["nothing_possible"]) <= 200 and config["nothing_possible"].strip()


def test_FR_INT_15_gap_ids_never_repeat_a_refusal_id_so_a_policy_refusal_is_never_a_gap():
    gap_ids = {c["id"] for c in shipped()["categories"]}
    refusal_ids = {c["id"] for c in yaml.safe_load(REFUSAL_CONFIG.read_text(encoding="utf-8"))["categories"]}

    assert gap_ids and refusal_ids and gap_ids.isdisjoint(refusal_ids)
    assert refusal_ids >= set(REFUSAL_IDS)


def test_FR_INT_15_unapproved_send_no_longer_offers_payments_tilo_would_make():
    """BQ-INT15-8: paying with a person's approval is a gap (money_movement), so the refusal's alternative offers the
    drafts and a payment list the person pays themselves, never payments Tilo makes."""
    by_id = {c["id"]: c for c in yaml.safe_load(REFUSAL_CONFIG.read_text(encoding="utf-8"))["categories"]}
    alternative = by_id["unapproved_send"]["alternative"]

    assert "messages or payments" not in alternative
    assert "pay yourself" in alternative and "drafts" in alternative


# --- the loader ---


def test_FR_INT_15_the_loader_returns_the_shipped_categories_in_file_order_with_exact_match_lookup():
    module = gaps()

    policy = module.load_gap_policy()  # None: config/capability_gaps.yaml and config/connectors.yaml

    config = shipped()
    assert [(c.id, c.reason, c.alternative) for c in policy.categories] == [
        (c["id"], c["reason"], c["alternative"]) for c in config["categories"]
    ]
    assert policy.nothing_possible == config["nothing_possible"]
    assert policy.get("money_movement").id == "money_movement"
    for near_miss in (
        "Money_Movement",
        "money_movement ",
        "money-movement",
        "money_moveme\u200bnt",
        "",
        "credential_handling",
    ):
        assert policy.get(near_miss) is None, repr(near_miss)  # exact match only: no folding, trimming or NFKC


def test_FR_INT_15_services_are_the_connector_names_from_config_in_file_order():
    module = gaps()
    declared = yaml.safe_load(CONNECTORS_CONFIG.read_text(encoding="utf-8"))

    policy = module.load_gap_policy()

    assert list(policy.services) == [c["name"] for c in declared]


def test_FR_INT_15_a_connector_added_to_the_file_is_a_service_with_no_code_change(tmp_path):
    """BQ-INT15-1: adding a connector shrinks `unconnected_service` by editing config only."""
    module = gaps()
    gap_path = write_gap_config(tmp_path / "gaps.yaml", gap_config_dict("a_gap"))
    before = module.load_gap_policy(gap_path, connectors_path=write_connectors(tmp_path / "c1.yaml", ["Gmail"]))
    after = module.load_gap_policy(
        gap_path, connectors_path=write_connectors(tmp_path / "c2.yaml", ["Gmail", "Zeta Mail"])
    )

    assert list(before.services) == ["Gmail"] and list(after.services) == ["Gmail", "Zeta Mail"]
    assert (
        list(module.load_gap_policy(gap_path, connectors_path=write_connectors(tmp_path / "c3.yaml", [])).services)
        == []
    )


def test_FR_INT_15_the_gap_error_is_a_refusal_config_error_so_the_api_503_path_covers_it():
    module = gaps()
    import tilo_planning.refusal as refusal  # noqa: PLC0415

    assert issubclass(module.GapConfigError, refusal.RefusalConfigError)


def test_FR_INT_15_the_constants_are_the_pinned_numbers():
    module = gaps()

    assert (module.MAX_GAPS, module.MAX_PART) == (3, 60)
    assert (module.MAX_REASON, module.MAX_ALTERNATIVE, module.MAX_LEAD) == (120, 200, 200)
    assert module.GAP_LINE == "Not done: {part}. {reason}"
    assert len(module.GAP_LINE.format(part="p" * 60, reason="r" * 120)) <= 200


def test_FR_INT_15_texts_at_exactly_their_limits_load(tmp_path):
    module = gaps()
    config = gap_config_dict("edge", nothing_possible="n" * 200)
    config["categories"][0]["reason"] = "r" * 120
    config["categories"][0]["alternative"] = "a" * 200
    connectors = write_connectors(tmp_path / "c.yaml", ["Gmail"])

    policy = module.load_gap_policy(write_gap_config(tmp_path / "g.yaml", config), connectors_path=connectors)

    assert len(policy.categories[0].reason) == 120 and len(policy.categories[0].alternative) == 200


def _broken(**changes):
    """A valid dict with one rule broken: `categories=` replaces the list, `top=` adds a key, `entry=` edits item 0."""
    config = gap_config_dict("one_gap", "two_gap")
    entry = changes.pop("entry", None)
    if entry is not None:
        config["categories"][0].update(entry)
    config.update(changes.pop("top", {}))
    config.update(changes)
    return config


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "[]\n",
        "just text\n",
        "categories: [unclosed",
        "nothing_possible: ok\n",  # categories missing
        "categories:\n  - {id: a_gap, reason: r, alternative: a}\n",  # nothing_possible missing
        "nothing_possible: ok\ncategories: []\n",
        "nothing_possible: ok\ncategories: not-a-list\n",
        "nothing_possible: !!python/object/apply:os.getcwd []\n"
        "categories:\n  - {id: a_gap, reason: r, alternative: a}\n",
        _broken(top={"extra_key": 1}),
        _broken(nothing_possible=""),
        _broken(nothing_possible="   "),
        _broken(nothing_possible=7),
        _broken(nothing_possible="n" * 201),
        _broken(entry={"extra": "x"}),
        _broken(entry={"id": "Not A Slug"}),
        _broken(entry={"id": "1starts_with_digit"}),
        _broken(entry={"id": "UPPER"}),
        _broken(entry={"id": "a" * 65}),
        _broken(entry={"id": ""}),
        _broken(entry={"id": 7}),
        _broken(entry={"reason": ""}),
        _broken(entry={"reason": "  "}),
        _broken(entry={"reason": 7}),
        _broken(entry={"reason": "r" * 121}),
        _broken(entry={"alternative": ""}),
        _broken(entry={"alternative": "  "}),
        _broken(entry={"alternative": "a" * 201}),
        _broken(entry={"reason": "Same text.", "alternative": "Same text."}),
        _broken(entry={"reason": "Same text.", "alternative": "  Same text.  "}),
        {"nothing_possible": "ok", "categories": ["not-a-mapping"]},
        {"nothing_possible": "ok", "categories": [{"id": "a_gap", "reason": "r"}]},
        {
            "nothing_possible": "ok",
            "categories": [
                {"id": "dup_gap", "reason": "r1", "alternative": "a1"},
                {"id": "dup_gap", "reason": "r2", "alternative": "a2"},
            ],
        },
    ],
    ids=lambda v: "text" if isinstance(v, str) else "dict",
)
def test_FR_INT_15_an_invalid_gap_config_is_refused_at_load(tmp_path, bad):
    module = gaps()
    path = write_gap_config(tmp_path / "bad.yaml", bad)
    connectors = write_connectors(tmp_path / "c.yaml", ["Gmail"])

    with pytest.raises(module.GapConfigError):
        module.load_gap_policy(path, connectors_path=connectors)


def test_FR_INT_15_a_missing_gap_config_is_a_config_error_not_an_empty_policy(tmp_path):
    module = gaps()
    connectors = write_connectors(tmp_path / "c.yaml", ["Gmail"])

    with pytest.raises(module.GapConfigError):
        module.load_gap_policy(tmp_path / "nope.yaml", connectors_path=connectors)


def test_FR_INT_15_an_unreadable_gap_config_is_a_config_error(tmp_path):
    module = gaps()
    connectors = write_connectors(tmp_path / "c.yaml", ["Gmail"])
    directory = tmp_path / "a_directory"
    directory.mkdir()

    with pytest.raises(module.GapConfigError):
        module.load_gap_policy(directory, connectors_path=connectors)


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "{}\n",
        "name: Gmail\n",
        "- just-a-string\n",
        "- {id: gmail}\n",
        "- {id: gmail, name: ''}\n",
        "- {id: gmail, name: '   '}\n",
        "- {id: gmail, name: 7}\n",
        "- {id: gmail, name: [a]}\n",
        "- {id: ok, name: Gmail}\n- {id: bad}\n",
        "- [unclosed",
    ],
)
def test_FR_INT_15_a_connectors_file_that_is_not_a_list_of_named_mappings_is_a_config_error(tmp_path, bad):
    module = gaps()
    gap_path = write_gap_config(tmp_path / "gaps.yaml", gap_config_dict("a_gap"))

    with pytest.raises(module.GapConfigError):
        module.load_gap_policy(gap_path, connectors_path=write_connectors(tmp_path / "c.yaml", bad))


def test_FR_INT_15_a_missing_connectors_file_is_a_config_error(tmp_path):
    module = gaps()
    gap_path = write_gap_config(tmp_path / "gaps.yaml", gap_config_dict("a_gap"))

    with pytest.raises(module.GapConfigError):
        module.load_gap_policy(gap_path, connectors_path=tmp_path / "nope.yaml")


def test_FR_INT_15_a_config_error_names_the_key_never_the_value(tmp_path):
    module = gaps()
    config = gap_config_dict("one_gap")
    config["categories"][0]["reason"] = MARKER + "x" * 130  # too long: the error may name `reason`, not its text
    connectors = write_connectors(tmp_path / "c.yaml", ["Gmail"])

    with pytest.raises(module.GapConfigError) as raised:
        module.load_gap_policy(write_gap_config(tmp_path / "g.yaml", config), connectors_path=connectors)

    assert MARKER not in str(raised.value)


# --- Gap and NothingPossible ---


def test_FR_INT_15_a_gap_is_its_skip_line_and_its_four_key_dict():
    module = gaps()
    gap = module.Gap(
        category="money_movement",
        part="Pay the invoice",
        reason="Tilo does not move money.",
        alternative="Ask for the list.",
    )

    assert gap.skip_line() == "Not done: Pay the invoice. Tilo does not move money."
    assert gap.as_dict() == {
        "category": "money_movement", "part": "Pay the invoice", "reason": "Tilo does not move money.",
        "alternative": "Ask for the list.",
    }  # fmt: skip
    assert list(gap.as_dict()) == ["category", "part", "reason", "alternative"]
    with pytest.raises(Exception):  # noqa: B017, PT011  (frozen dataclass)
        gap.part = "other"


def test_FR_INT_15_the_longest_skip_line_fits_the_plan_schemas_200_characters():
    module = gaps()
    policy = module.load_gap_policy()
    longest_reason = max(len(c.reason) for c in policy.categories)

    gap = module.Gap(category="x", part="p" * module.MAX_PART, reason="r" * longest_reason, alternative="a")

    assert len(gap.skip_line()) <= 10 + 60 + 2 + 120 <= 200


def test_FR_INT_15_nothing_possible_is_not_a_refusal_and_not_an_extraction_error():
    module = gaps()
    import tilo_planning.brief as brief  # noqa: PLC0415
    import tilo_planning.refusal as refusal  # noqa: PLC0415

    gap = module.Gap("physical_world", "Buy the cake", "reason text", "alternative text")
    exc = module.NothingPossible((gap,), "Tilo cannot do any part of this task yet.")

    assert not issubclass(module.NothingPossible, (refusal.TaskRefused, brief.BriefExtractionError))
    assert issubclass(module.NothingPossible, Exception)
    assert exc.gaps == (gap,) and exc.message == "Tilo cannot do any part of this task yet."
    assert str(exc) == "nothing possible: physical_world"


# --- clean_part ---


def no_c_chars(text: str) -> bool:
    return not any(unicodedata.category(ch).startswith("C") for ch in text)


@pytest.mark.parametrize("value", [None, 7, 7.5, True, ["Pay"], {"part": "Pay"}, b"Pay", ("Pay",)])
def test_FR_INT_15_clean_part_refuses_anything_that_is_not_a_string(value):
    assert gaps().clean_part(value) is None


@pytest.mark.parametrize(
    "value",
    ["", "   ", "\u200b\u200b", "\u202e", "\n\t", "\ufeff", "\x00\x07", ".", "...", " . ", "\u200b.\u200b"],
)
def test_FR_INT_15_clean_part_returns_none_when_nothing_visible_is_left(value):
    assert gaps().clean_part(value) is None


def test_FR_INT_15_clean_part_caps_the_raw_length_at_60_not_the_cleaned_length():
    module = gaps()

    assert module.clean_part("a" * 60) == "a" * 60
    assert module.clean_part("a" * 61) is None
    assert module.clean_part("a" * 60 + "\u200b\u200b") is None, (
        "62 raw characters: refused even though cleaning shrinks it"
    )
    assert module.clean_part("\u200b" * 61 + "a") is None


@pytest.mark.parametrize(
    ("raw", "shown"),
    [
        ("Pay the invoice", "Pay the invoice"),
        ("  Pay   the \t invoice  ", None),  # whitespace runs collapse (exact text checked below)
        ("Pay the invoice.", "Pay the invoice"),
        ("Pay the invoice...", "Pay the invoice"),
        ("Pay\u202e the\u200b invoice", "Pay the invoice"),
        ("\ufeffPay the invoice", "Pay the invoice"),
        ("Pay  the   invoice", "Pay the invoice"),
        ("Pay\u00a0the invoice", "Pay the invoice"),  # NBSP is a space (Zs), split() joins it with one space
        ("Pay the \u00e9tude", "Pay the \u00e9tude"),
        ("\uff21\uff22\uff23 fullwidth", "\uff21\uff22\uff23 fullwidth"),  # no NFKC: fullwidth letters stay
        ("\ufb01le the form", "\ufb01le the form"),  # no NFKC: the fi ligature stays
        ("Pay\ue000 now", "Pay now"),  # private use removed
        ("Pay\u0378 now", "Pay now"),  # unassigned removed
        ("Pay\ud800 now", "Pay now"),  # lone surrogate removed
    ],
)
def test_FR_INT_15_clean_part_removes_C_characters_collapses_spaces_and_strips_the_trailing_period(raw, shown):
    module = gaps()

    result = module.clean_part(raw)

    if shown is None:
        assert result == "Pay the invoice"
    else:
        assert result == shown
    assert no_c_chars(result)


@pytest.mark.parametrize(
    "raw", ["line one\nline two", "tab\tseparated", "bell\x07 ring", "nul\x00 byte", "esc\x1b[31m red"]
)
def test_FR_INT_15_clean_part_leaves_no_control_character_in_the_label(raw):
    result = gaps().clean_part(raw)

    assert result is not None and no_c_chars(result) and result == result.strip()


@settings(max_examples=200, deadline=None)
@given(value=st.text(max_size=80))
def test_FR_INT_15_property_clean_part_only_shrinks_and_never_leaves_a_C_character(value):
    result = gaps().clean_part(value)

    if len(value) > 60:
        assert result is None
        return
    if result is None:
        return
    assert 1 <= len(result) <= 60 and len(result) <= len(value)
    assert no_c_chars(result) and result == result.strip() and "  " not in result


@pytest.mark.parametrize(
    "value",
    [
        chr(0x3164), chr(0x2800), chr(0x115F) + chr(0x1160), chr(0x34F), chr(0xFE0F), chr(0x300),
        chr(0x34F) + chr(0xFE0F) + chr(0x300), " " + chr(0x3164) + " " + chr(0x2800) + " ",
    ],
)  # fmt: skip
def test_FR_INT_15_clean_part_returns_none_for_invisible_fillers_and_bare_combining_marks(value):
    assert gaps().clean_part(value) is None


def test_FR_INT_15_clean_part_keeps_a_label_whose_letters_carry_combining_marks():
    label = "Caf" + "e" + chr(0x301) + " order"

    assert gaps().clean_part(label) == label  # a visible letter is there; no NFKC, no stripping of the mark
