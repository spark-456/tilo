"""FR-CON-16 / FR-CON-17 / FR-CON-20 (PRD supplement 2026-10-05 s6, SD-03): the shipped configuration.

`config/connectors.yaml` declares `lovable` (auth none, one `send` action `build_handoff`, T3, approval,
irreversible), `config/autonomy.yaml` lists `build_handoff: T3`, and `config/build_partners.yaml` holds the
route limits that `tilo_connectors.handoff.load_build_partners` checks (API_FR_CON_16_17_20.md "Shipped config").
Tests that only read the shipped files pass today; the loader tests fail until `tilo_connectors.handoff` exists.
"""

from __future__ import annotations

import copy
import dataclasses
import json
import pathlib
import re
import unicodedata

import jsonschema
import pytest
import yaml
from _handoff_lib import CONFIG, CONTRACTS, default_partner_yaml, h, registry, schema_registry, write_partners
from _registry_lib import write_config
from tilo_policy import Assessment, SideEffectFacts, load_risk_table

WORD = re.compile(r"[^\W_]+")


def _lovable() -> dict:
    return dict(registry().get("lovable"))


# --- config/connectors.yaml -----------------------------------------------------------------


def test_FR_CON_16_lovable_is_declared_after_gmail_and_drive_and_loads_through_the_registry():
    reg = registry()
    # google_calendar (FR-CAL-08) joins after these three: the order of the first three stays pinned.
    assert reg.ids()[:3] == ("gmail", "google_drive", "lovable")


def test_FR_CON_16_lovable_declaration_is_the_pinned_link_route_connector():
    entry = _lovable()
    assert entry["id"] == "lovable"
    assert entry["auth"] == "none", "no key and no Tilo token on the link route (FR-CON-17)"
    assert entry["scopes"] == {}
    assert entry["capabilities"] == ["send"]
    assert [
        {k: a[k] for k in ("id", "capability", "risk_tier", "gate_type", "irreversible")} for a in entry["actions"]
    ] == [
        {"id": "build_handoff", "capability": "send", "risk_tier": "T3", "gate_type": "approval", "irreversible": True}
    ]
    assert entry["limits"] == {"per_minute": None, "batch_size": None}
    assert entry["data_class"] == {"returns": ["business"], "redact": []}


def test_FR_CON_16_lovable_declaration_validates_against_the_unchanged_connector_contract():
    schema = json.loads((CONTRACTS / "connector.schema.json").read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema, registry=schema_registry())
    assert list(validator.iter_errors(_lovable())) == []


def test_FR_CON_16_lovable_has_no_connection_event_so_its_island_stays_locked():
    # BQ-BUILD-8: an auth-none connector never gets a connection.* event; drawing it is FR-CON-22.
    islands = {i["id"]: i for i in registry().list_for_world()}
    assert islands["lovable"]["state"] == "locked"


# --- config/autonomy.yaml and the policy engine ------------------------------------------------


def test_FR_CON_16_autonomy_lists_build_handoff_as_t3_explicitly():
    raw = yaml.safe_load((CONFIG / "autonomy.yaml").read_text(encoding="utf-8"))
    assert raw["actions"]["build_handoff"] == "T3", "listed, not left to the unlisted-is-T3 default"


def test_FR_CON_16_policy_engine_assesses_build_handoff_as_t3_with_external_sharing():
    table = load_risk_table()
    assert table.assess("build_handoff", SideEffectFacts(external_share=True)) == Assessment(
        "T3", ("external_sharing",)
    )
    assert table.tier_of("build_handoff", []) == "T3", "T3 even before any modifier applies"


# --- config/build_partners.yaml (raw shape; passes without the loader) -----------------------------


def test_FR_CON_16_build_partners_file_has_exactly_the_pinned_keys_and_values():
    raw = default_partner_yaml()
    assert set(raw) == {"partners", "framing_words"}
    assert raw["partners"] == {
        "lovable": {
            "action": "build_handoff",
            "route": "link",
            "max_prompt_chars": 50000,
            "max_url_length": 32000,
            "max_framing_chars": 400,
            "max_excerpt_chars": 4000,
            "max_items": 6,
        }
    }


def test_FR_CON_16_framing_words_are_unique_casefolded_single_words_at_most_300():
    words = default_partner_yaml()["framing_words"]
    assert 0 < len(words) <= 300
    assert len(set(words)) == len(words)
    for w in words:
        assert isinstance(w, str)
        assert WORD.fullmatch(w), w
        assert unicodedata.normalize("NFKC", w).casefold() == w, w


def test_FR_CON_16_framing_words_hold_no_feature_style_or_product_word():
    # BH-03: function words and generic build words only. These would let a writer smuggle a requirement in.
    forbidden = {
        "crypto",
        "payment",
        "checkout",
        "login",
        "dark",
        "blue",
        "red",
        "stripe",
        "paypal",
        "ai",
        "blockchain",
    }
    assert forbidden.isdisjoint(default_partner_yaml()["framing_words"])


def test_FR_CON_16_side_effect_method_names_still_name_execute_side_effect():
    from tilo_connectors.side_effects import SIDE_EFFECT_METHOD_NAMES

    assert "execute_side_effect" in SIDE_EFFECT_METHOD_NAMES


# --- load_build_partners ------------------------------------------------------------------------


def test_FR_CON_16_default_build_partners_path_is_the_shipped_file():
    assert pathlib.Path(h().DEFAULT_BUILD_PARTNERS).resolve() == (CONFIG / "build_partners.yaml").resolve()


def test_FR_CON_16_loader_returns_the_lovable_partner_with_the_shipped_limits():
    partners = h().load_build_partners(registry=registry())
    assert set(partners) == {"lovable"}
    p = partners["lovable"]
    assert (p.connector, p.action, p.route) == ("lovable", "build_handoff", "link")
    assert (p.max_prompt_chars, p.max_url_length, p.max_framing_chars, p.max_excerpt_chars, p.max_items) == (
        50000,
        32000,
        400,
        4000,
        6,
    )
    assert isinstance(p.framing_words, frozenset)
    assert p.framing_words == frozenset(default_partner_yaml()["framing_words"])


def test_FR_CON_16_a_build_partner_config_is_immutable():
    p = h().load_build_partners(registry=registry())["lovable"]
    with pytest.raises(dataclasses.FrozenInstanceError):
        p.max_items = 99  # type: ignore[misc]


def test_FR_CON_17_the_limits_come_from_the_config_file_not_from_a_code_constant(tmp_path):
    path = write_partners(tmp_path, max_prompt_chars=1234, max_url_length=4321, max_excerpt_chars=500, max_items=3)
    p = h().load_build_partners(path, registry=registry())["lovable"]
    assert (p.max_prompt_chars, p.max_url_length, p.max_excerpt_chars, p.max_items) == (1234, 4321, 500, 3)


@pytest.mark.parametrize(
    "limits",
    [
        {"max_prompt_chars": 1, "max_excerpt_chars": 1},
        {"max_prompt_chars": 50000},
        {"max_url_length": 100},
        {"max_url_length": 2_000_000},
        {"max_framing_chars": 1},
        {"max_framing_chars": 1000},
        {"max_items": 1},
        {"max_items": 6},
        {"max_prompt_chars": 1000, "max_excerpt_chars": 1000},
    ],
)
def test_FR_CON_16_loader_accepts_each_limit_at_its_boundary(tmp_path, limits):
    assert h().load_build_partners(write_partners(tmp_path, **limits), registry=registry())["lovable"]


def test_FR_CON_16_loader_accepts_exactly_300_framing_words(tmp_path):
    raw = default_partner_yaml()
    raw["framing_words"] = [f"w{i}" for i in range(300)]
    path = write_partners(tmp_path, raw=raw)
    assert len(h().load_build_partners(path, registry=registry())["lovable"].framing_words) == 300


BAD_LIMITS = [
    ("max_prompt_chars", 0),
    ("max_prompt_chars", 50001),
    ("max_prompt_chars", True),
    ("max_prompt_chars", "50000"),
    ("max_prompt_chars", 50000.0),
    ("max_prompt_chars", None),
    ("max_prompt_chars", -1),
    ("max_url_length", 99),
    ("max_url_length", 2_000_001),
    ("max_url_length", False),
    ("max_url_length", "32000"),
    ("max_framing_chars", 0),
    ("max_framing_chars", 1001),
    ("max_framing_chars", True),
    ("max_excerpt_chars", 0),
    ("max_excerpt_chars", 50001),  # above max_prompt_chars
    ("max_excerpt_chars", 1.5),
    ("max_items", 0),
    ("max_items", 7),
    ("max_items", True),
    ("max_items", "6"),
    ("route", "mcp"),
    ("route", "Link"),
    ("route", None),
    ("action", "send_email"),
    ("action", "share_file"),
    ("action", "BUILD_HANDOFF"),
]


@pytest.mark.parametrize(("key", "value"), BAD_LIMITS)
def test_FR_CON_16_loader_refuses_a_bad_partner_value_and_names_the_key_never_the_value(tmp_path, key, value):
    from tilo_connectors.errors import BuildPartnerConfigError

    raw = default_partner_yaml()
    raw["partners"]["lovable"][key] = value
    with pytest.raises(BuildPartnerConfigError) as ei:
        h().load_build_partners(write_partners(tmp_path, raw=raw), registry=registry())
    assert len(str(ei.value)) <= 500
    assert key in str(ei.value)


def test_FR_CON_16_loader_error_never_echoes_a_value_it_refused(tmp_path):
    from tilo_connectors.errors import BuildPartnerConfigError

    canary = "zz-canary-value-zz"
    raw = default_partner_yaml()
    raw["partners"]["lovable"]["route"] = canary
    with pytest.raises(BuildPartnerConfigError) as ei:
        h().load_build_partners(write_partners(tmp_path, raw=raw), registry=registry())
    assert canary not in str(ei.value)
    assert len(str(ei.value)) <= 500


def test_FR_CON_16_loader_refuses_an_excerpt_cap_above_the_prompt_cap(tmp_path):
    from tilo_connectors.errors import BuildPartnerConfigError

    raw = default_partner_yaml()
    raw["partners"]["lovable"].update(max_prompt_chars=1000, max_excerpt_chars=1001)
    with pytest.raises(BuildPartnerConfigError):
        h().load_build_partners(write_partners(tmp_path, raw=raw), registry=registry())


def test_FR_CON_16_loader_refuses_a_top_level_key_it_does_not_know(tmp_path):
    from tilo_connectors.errors import BuildPartnerConfigError

    raw = default_partner_yaml()
    raw["autosubmit"] = True
    with pytest.raises(BuildPartnerConfigError):
        h().load_build_partners(write_partners(tmp_path, raw=raw), registry=registry())


def test_FR_CON_16_loader_refuses_a_partner_key_it_does_not_know(tmp_path):
    from tilo_connectors.errors import BuildPartnerConfigError

    raw = default_partner_yaml()
    raw["partners"]["lovable"]["mcp_url"] = "https://mcp.lovable.dev"
    with pytest.raises(BuildPartnerConfigError):
        h().load_build_partners(write_partners(tmp_path, raw=raw), registry=registry())


def test_FR_CON_16_loader_refuses_a_partner_the_registry_does_not_declare(tmp_path):
    from tilo_connectors.errors import BuildPartnerConfigError

    raw = default_partner_yaml()
    raw["partners"]["canva"] = copy.deepcopy(raw["partners"]["lovable"])
    with pytest.raises(BuildPartnerConfigError):
        h().load_build_partners(write_partners(tmp_path, raw=raw), registry=registry())


@pytest.mark.parametrize(
    "change",
    [
        {"risk_tier": "T2"},
        {"risk_tier": "T2", "irreversible": False},
        {"irreversible": False},
    ],
)
def test_FR_CON_16_loader_refuses_a_partner_whose_action_is_not_t3_gated_and_irreversible(tmp_path, change):
    """T3, approval and irreversible are checked against the registry, not trusted from the partner file."""
    from tilo_connectors.errors import BuildPartnerConfigError
    from tilo_connectors.registry import load_registry

    entry = _lovable()
    entry["actions"][0].update(change)
    reg = load_registry(write_config(tmp_path, [entry], "connectors.yaml"))
    with pytest.raises(BuildPartnerConfigError):
        h().load_build_partners(write_partners(tmp_path), registry=reg)


def test_FR_CON_16_the_registry_itself_refuses_a_send_action_with_no_gate(tmp_path):
    """A `send` action with gate_type none never loads (connector.schema.json), so the loader is not even reached."""
    from tilo_connectors.registry import ConnectorConfigError, load_registry

    entry = _lovable()
    entry["actions"][0].update(risk_tier="T1", gate_type="none")
    with pytest.raises(ConnectorConfigError):
        load_registry(write_config(tmp_path, [entry], "connectors.yaml"))


def test_FR_CON_16_loader_refuses_a_partner_whose_action_the_connector_does_not_declare(tmp_path):
    from tilo_connectors.errors import BuildPartnerConfigError
    from tilo_connectors.registry import load_registry

    entry = _lovable()
    entry["actions"][0]["id"] = "something_else"
    reg = load_registry(write_config(tmp_path, [entry], "connectors.yaml"))
    with pytest.raises(BuildPartnerConfigError):
        h().load_build_partners(write_partners(tmp_path), registry=reg)


@pytest.mark.parametrize(
    "words",
    [
        ["The"],  # not casefolded
        ["front-end"],  # not one word
        ["front end"],
        ["snake_case"],  # underscore is not a word character
        ["a", "a"],  # duplicate
        [""],
        ["the "],  # trailing space
        [123],
        [None],
        ["ｔｈｅ"],  # fullwidth "the": NFKC changes it
        ["straße"],  # sharp s: casefold changes it
        ["café​"],  # zero-width space inside
        [f"w{i}" for i in range(301)],  # more than 300
    ],
)
def test_FR_CON_16_loader_refuses_a_framing_words_list_that_is_not_unique_casefolded_single_words(tmp_path, words):
    from tilo_connectors.errors import BuildPartnerConfigError

    raw = default_partner_yaml()
    raw["framing_words"] = words
    with pytest.raises(BuildPartnerConfigError):
        h().load_build_partners(write_partners(tmp_path, raw=raw), registry=registry())


@pytest.mark.parametrize(
    "text",
    [
        "partners: [unclosed",
        "- just\n- a list\n",
        "partners: &p {lovable: {action: build_handoff}}\nframing_words: *p\n",
        "partners: {lovable: &x {action: build_handoff}, lovable2: *x}\nframing_words: []\n",
        "",
    ],
)
def test_FR_CON_16_loader_refuses_unreadable_yaml_a_non_mapping_and_aliases(tmp_path, text):
    from tilo_connectors.errors import BuildPartnerConfigError

    path = tmp_path / "build_partners.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(BuildPartnerConfigError):
        h().load_build_partners(path, registry=registry())


def test_FR_CON_16_a_refused_file_loads_nothing_not_even_the_valid_partner(tmp_path):
    from tilo_connectors.errors import BuildPartnerConfigError

    raw = default_partner_yaml()
    raw["framing_words"] = ["The"]
    with pytest.raises(BuildPartnerConfigError):
        h().load_build_partners(write_partners(tmp_path, raw=raw), registry=registry())
