"""ADR35_L6c / FR_CON_02: the production action resolver maps STRUCTURED answers to recipients and declared fields.

Deterministic, generic over the action type, driven by `config/side_effect_fields.yaml`. It never reads prose (the
brief's text, a unit's output): an address that is not the person's own whole answer is not an answer. What is
missing is `Missing` (the run asks the person on a needs-you card); an address is strict (no display name, no CRLF).
"""

from __future__ import annotations

import ast
import pathlib

import pytest
from tilo_api import deps, item_documents, side_effect_fields
from tilo_api.item_documents import DocumentRefused
from tilo_api.side_effect_fields import Missing, Rule, make_resolver, parse_addresses

SRC = pathlib.Path(side_effect_fields.__file__).parent
RULES = {"send_email": Rule("audience", 3, {"subject": "goal"}), "save_file": Rule(None, 0, {"name": "constraints"})}


def resolve(action="send_email", *, answers=None, supplied=None, brief=None, rules=None):
    return make_resolver(rules or RULES)(
        unit={"id": "U4", "title": "Send"},
        action_type=action,
        item={},
        brief=brief or {},
        answers=answers,
        supplied=supplied,
    )


def test_ADR35_L6c_FR_CON_02_a_structured_answer_fills_the_recipients_and_the_declared_fields():
    got = resolve(answers={"audience": "finance@example.com, Ops@Example.org", "goal": "Q3 note"})
    assert got == {"destination": None, "recipients": ["finance@example.com", "Ops@Example.org"],
                   "known_recipients": [], "fields": {"subject": "Q3 note"}}  # fmt: skip


def test_ADR35_L6c_FR_CON_02_what_the_person_typed_on_the_fields_route_wins_over_an_answer():
    got = resolve(
        answers={"audience": "a@example.com", "goal": "old"}, supplied={"recipient": "b@example.com", "subject": "new"}
    )
    assert got["recipients"] == ["b@example.com"] and got["fields"] == {"subject": "new"}


def test_ADR35_L6c_FR_CON_02_prose_is_never_used_a_brief_with_an_address_but_no_answer_asks():
    brief = {
        "goal": "Email bob@example.com the note",
        "audience": "bob@example.com",
        "constraints": ["cc eve@example.com"],
    }
    with pytest.raises(Missing) as asked:
        resolve(brief=brief, answers={})
    assert asked.value.fields == ("recipient",) and asked.value.reason is None


def test_ADR35_L6c_FR_CON_02_an_answer_that_is_not_only_addresses_is_not_used():
    for prose in ("send it to bob@example.com please", "My own team", "bob@example.com; eve@example.com"):
        with pytest.raises(Missing):
            resolve(answers={"audience": prose})


BAD = [
    "Bob <bob@example.org>", "bob@example.org\r\nBcc: eve@example.org", "bob@@example.org", "bob@example",
    "bob @example.org", "bob@example.org\u202e", "b\u00f6b@example.org", ".bob@example.org", "bob..x@example.org",
    "<bob@example.org>",
]  # fmt: skip


@pytest.mark.parametrize("bad", BAD)
def test_ADR35_L6c_FR_CON_02_an_invalid_address_is_refused_with_a_plain_reason(bad):
    with pytest.raises(DocumentRefused) as refused:
        parse_addresses(bad)
    assert refused.value.reason and "\r" not in refused.value.reason
    with pytest.raises(Missing) as asked:  # and as an answer it is a reason on the question, never a recipient
        resolve(answers={"audience": bad})
    assert asked.value.fields == ("recipient",)


def test_ADR35_L6c_FR_CON_02_the_recipient_cap_and_duplicates():
    assert parse_addresses("a@example.com, A@example.com") == ["a@example.com"]
    with pytest.raises(Missing) as asked:
        resolve(answers={"audience": "a@x.io, b@x.io, c@x.io, d@x.io"})
    assert "at most 3" in (asked.value.reason or "")


def test_ADR35_L6c_FR_CON_02_an_action_that_reaches_no_one_has_no_recipients_and_a_bad_field_is_asked_instead():
    got = resolve("save_file", answers={"constraints": "report.md"})
    assert got["recipients"] == [] and got["fields"] == {"name": "report.md"}
    assert resolve("save_file", answers={"constraints": "a/b.md"})["fields"] == {}  # a slash: not a name, ask
    with pytest.raises(LookupError):
        resolve("delete_everything")


def test_ADR35_L6c_FR_CON_02_recipient_on_the_fields_route_is_checked_the_same_way():
    assert (
        side_effect_fields.check_recipient("send_email", "A@Example.com, b@example.org")
        == "A@Example.com, b@example.org"
    )
    with pytest.raises(DocumentRefused):
        side_effect_fields.check_recipient("send_email", "Bob <b@example.org>")
    with pytest.raises(DocumentRefused, match="no recipient"):
        side_effect_fields.check_recipient("save_file", "b@example.org")


def test_ADR35_L6c_FR_CON_02_the_shipped_config_covers_every_document_action_and_is_generic():
    rules, labels = side_effect_fields.load_config()
    assert set(rules) == set(item_documents.KIND_OF)
    assert all((rules[a].cap == 0) == (a in item_documents.NO_RECIPIENT_ACTIONS) for a in rules)
    assert all(rules[a].cap <= side_effect_fields.CONTRACT_CAP for a in rules)
    assert {"recipient", "subject", "name", "title", "start", "end", "time_zone"} <= set(labels)
    assert deps.get_action_resolver().takes_answers is True  # type: ignore[attr-defined]


def test_ADR35_L6c_FR_CON_02_a_bad_config_is_refused_at_load(tmp_path):
    for body in (
        "version: 2\nactions: {}\n",
        "version: 1\nactions: {nonsense: {fields: {}}}\n",
        "version: 1\nactions: {save_file: {recipient: {answer: audience, max: 1}, fields: {}}}\n",
        "version: 1\nactions: {send_email: {recipient: {answer: audience, max: 51}, fields: {}}}\n",
        "version: 1\nactions: {send_email: {fields: {secret: goal}}}\n",
    ):
        path = tmp_path / "c.yaml"
        path.write_text(body, encoding="utf-8")
        with pytest.raises(ValueError):
            side_effect_fields.load_config(path)


def test_ADR35_L6c_FR_CON_02_the_module_names_no_scenario_and_no_connector_internals():
    tree = ast.parse((SRC / "side_effect_fields.py").read_text(encoding="utf-8"))
    imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | {
        a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names
    }
    assert not any(m and m.startswith("tilo_connectors") for m in imported)
