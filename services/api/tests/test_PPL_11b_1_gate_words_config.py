"""PPL-11b slice 11b-1, the supporting modules of FR-PA-13 and FR-PA-17 (API_PPL_11b.md sections 2, 3 and 4): the
strict config loader, the word rules, `people_access.read_as` and `RefGate`. This is the visibility path: every
person row and target goes through the REAL `tilo_people` oracle as the signed-in person, one org per request,
canonical plain data in, a refused id and an unknown id indistinguishable.

Written before any implementation: every test fails today with ModuleNotFoundError for `tilo_api.assistant`.
"""

from __future__ import annotations

import copy
import pathlib

import pytest
import yaml
from _ppl11b_lib import (
    C_GATE,
    LAUNCH,
    MAIL_ID,
    NOW,
    ORG,
    PRIYA,
    RAW,
    SAM,
    STAMP,
    W_LAUNCH,
    W_PRIYA,
    W_VENDOR,
    AccessSpy,
    calendar_entry,
    directory_of,
    hist,
    is_plain,
    maker,
    mod,
    plate_s1,
    stamp,
    u,
    ulid,
    work_item,
)
from _ppl11b_lib import world as world  # noqa: PLC0414  (the fixture)
from hypothesis import given, settings
from hypothesis import strategies as st
from tilo_people import access
from tilo_people.stores import PeopleStores, Stored


# --------------------------------------------------------------------------------------------- the config loader
def _cfg():
    return mod("tilo_api.assistant.config")


def _write(tmp_path: pathlib.Path, raw, name: str = "assistant.yaml") -> pathlib.Path:
    path = tmp_path / name
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return path


def _walk(raw, dotted: str):
    node = raw
    keys = dotted.split(".")
    for key in keys[:-1]:
        node = node[int(key)] if isinstance(node, list) else node[key]
    return node, (int(keys[-1]) if isinstance(node, list) else keys[-1])


def _set(dotted: str, value):
    def apply(raw):
        node, key = _walk(raw, dotted)
        node[key] = value

    return apply


def _del(dotted: str):
    def apply(raw):
        node, key = _walk(raw, dotted)
        del node[key]

    return apply


def _append(dotted: str, value):
    def apply(raw):
        node, key = _walk(raw, dotted)
        node[key].append(value)

    return apply


# index of the intents and routes in config/assistant.yaml: facts 0 mail 1 waiting 2 overdue 3 due_soon
# 4 calendar_today 5 changed 6 pins 7 tasks 8 plate; navigate 0 plate 1 calendar 2 meetings
BAD_CONFIGS = {
    "unknown top-level key": _set("surprise", 1),
    "unknown nested key": _set("answer.surprise", "x"),
    "unknown fact key": _set("facts.0.surprise", 1),
    "unknown route key": _set("navigate.0.surprise", 1),
    "unknown rows key": _set("facts.0.rows.surprise", 1),
    "version 2": _set("version", 2),
    "version as text": _set("version", "1"),
    "missing version": _del("version"),
    "missing question": _del("question"),
    "missing words": _del("words"),
    "missing facts": _del("facts"),
    "missing navigate": _del("navigate"),
    "missing screens": _del("screens"),
    "missing answer": _del("answer"),
    "missing declines": _del("declines"),
    "missing model": _del("model"),
    "missing cost": _del("cost"),
    "missing cache": _del("cache"),
    "max_chars 0": _set("question.max_chars", 0),
    "max_chars 2001": _set("question.max_chars", 2001),
    "max_chars as text": _set("question.max_chars", "500"),
    "max_chars bool": _set("question.max_chars", True),
    "max_chars fraction": _set("question.max_chars", 500.5),
    "day credits 0": _set("cost.user_day_credits", 0),
    "day credits negative": _set("cost.user_day_credits", -1),
    "day credits above the PRD cap": _set("cost.user_day_credits", 50.01),
    "day credits as text": _set("cost.user_day_credits", "50"),
    "day credits bool": _set("cost.user_day_credits", True),
    "day credits nan": _set("cost.user_day_credits", float("nan")),
    "day credits inf": _set("cost.user_day_credits", float("inf")),
    "cache entries 0": _set("cache.per_user_entries", 0),
    "cache entries 1001": _set("cache.per_user_entries", 1001),
    "cache ttl 0": _set("cache.ttl_hours", 0),
    "cache ttl 169": _set("cache.ttl_hours", 169),
    "menu rows 0": _set("model.menu_rows", 0),
    "menu rows 41": _set("model.menu_rows", 41),
    "max output chars 99": _set("model.max_output_chars", 99),
    "max output chars 4001": _set("model.max_output_chars", 4001),
    "role is not a slug": _set("model.role", "Not A Slug"),
    "role empty": _set("model.role", ""),
    "max_lines 0": _set("answer.max_lines", 0),
    "max_lines 21": _set("answer.max_lines", 21),
    "line template with a foreign placeholder": _set("answer.lines.gate", "$label: $evil"),
    "due suffix with $label": _set("answer.due_suffix", " (due $label)"),
    "opening with $time": _set("answer.opening", "Opening $time."),
    "more with a placeholder": _set("answer.more", "More on $label"),
    "decline with a placeholder": _set("declines.unknown", "Try $this"),
    "header with a placeholder": _set("facts.0.header", "Mail $label:"),
    "calendar line with a foreign placeholder": _set("answer.lines.calendar", "$when $label"),
    "lines miss a plate reason": _del("answer.lines.calendar"),
    "lines hold a reason the plate has not": _set("answer.lines.surprise", "$label"),
    "declines miss one": _del("declines.failed"),
    "declines hold an extra one": _set("declines.surprise", "x"),
    "a phrase in two routes": _append("navigate.1.phrases", "plate"),
    "a duplicate intent id": _set("facts.1.id", "mail"),
    "an intent id with a capital": _set("facts.0.id", "Mail"),
    "an intent id over 32 characters": _set("facts.0.id", "a" * 33),
    "a route outside the ui_action enum": _set("navigate.0.route", "admin"),
    "route world needs a target": _set("navigate.0.route", "world"),
    "route meeting needs a target": _set("navigate.0.route", "meeting"),
    "with_context is not a record kind": _set("navigate.2.with_context", "banana"),
    "a control character": _set("declines.unknown", "ok" + chr(7)),
    "a zero-width character": _set("declines.unknown", "ok" + u(0x200B)),
    "a bidi override": _set("declines.unknown", "ok" + u(0x202E)),
    "a line separator": _set("declines.unknown", "ok" + u(0x2028)),
    "a paragraph separator": _set("declines.unknown", "ok" + u(0x2029)),
    "a text over 400 characters": _set("declines.budget", "x" * 401),
    "a null header on an intent that is not the plate": _set("facts.0.header", None),
    "an intent with no when": _set("facts.0.when", []),
    "a when group with no word": _set("facts.0.when", [[]]),
    "within_hours 0": _set("facts.5.rows.within_hours", 0),
    "within_hours 169": _set("facts.5.rows.within_hours", 169),
    "an unknown reason": _set("facts.0.rows.reasons", ["gate", "banana"]),
    "a parked group": _set("facts.2.rows.groups", ["snoozed"]),
    "an unknown ref kind": _set("facts.7.rows.kinds", ["banana"]),
    "has_due as text": _set("facts.3.rows.has_due", "yes"),
    "a word list that is a string": _set("words.fillers", "please"),
    "a missing word list": _del("words.nav_verbs"),
}


def test_FR_PA_13_config_the_shipped_file_loads_into_the_documented_shape():
    cfg = _cfg().load_assistant_config()
    assert cfg.question_max_chars == 500 and cfg.user_day_credits == 50 and 0 < cfg.user_day_credits <= 50
    assert (cfg.cache_per_user_entries, cfg.cache_ttl_hours) == (64, 24)
    assert dict(cfg.model) == {"role": "assistant", "menu_rows": 40, "max_output_chars": 2000}
    assert [f.id for f in cfg.facts] == [i["id"] for i in RAW["facts"]], "config order is precedence"
    assert [r.route for r in cfg.navigate] == [r["route"] for r in RAW["navigate"]]
    assert dict(cfg.declines) == RAW["declines"] and dict(cfg.screens) == RAW["screens"]
    assert cfg.answer["max_lines"] == 10 and cfg.answer["more"] == RAW["answer"]["more"]
    assert cfg.words["fillers"] == frozenset(RAW["words"]["fillers"])
    assert cfg.words["nav_verbs"] == frozenset(RAW["words"]["nav_verbs"])
    plate = next(f for f in cfg.facts if f.id == "plate")
    assert plate.header is None and plate.rows.groups == ("attention", "overdue", "soon", "rest")
    assert all(isinstance(group, frozenset) and group for f in cfg.facts for group in f.when)
    tasks = next(f for f in cfg.facts if f.id == "tasks")
    assert tasks.narrow is True and tasks.rows.kinds == ("world",) and tasks.rows.reasons == ("run", "blocked")
    changed = next(f for f in cfg.facts if f.id == "changed")
    assert changed.rows.within_hours == 24
    nav = {r.route: r for r in cfg.navigate}
    assert nav["meetings"].with_context == "meeting" and "meeting minutes" in nav["meetings"].phrases
    with pytest.raises(Exception):  # noqa: B017,PT011  (a frozen dataclass)
        cfg.question_max_chars = 1  # type: ignore[misc]


@pytest.mark.parametrize("name", sorted(BAD_CONFIGS))
def test_FR_PA_13_config_refuses_a_broken_file_whole(tmp_path, name):
    raw = copy.deepcopy(RAW)
    BAD_CONFIGS[name](raw)
    with pytest.raises(_cfg().AssistantConfigError):
        _cfg().load_assistant_config(_write(tmp_path, raw))


@pytest.mark.parametrize("content", ["", "- a\n- b\n", "just text", "null"])
def test_FR_PA_13_config_refuses_a_file_that_is_not_a_mapping(tmp_path, content):
    path = tmp_path / "assistant.yaml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(_cfg().AssistantConfigError):
        _cfg().load_assistant_config(path)


def test_FR_PA_13_config_the_untouched_copy_loads_so_every_refusal_above_is_about_its_change(tmp_path):
    cfg = _cfg().load_assistant_config(_write(tmp_path, copy.deepcopy(RAW)))
    assert cfg.fingerprint == _cfg().load_assistant_config().fingerprint


def test_FR_PA_13_config_an_error_names_the_key_path_and_never_a_value(tmp_path):
    secret = "SECRET-VALUE-9f2c" + chr(7)
    raw = copy.deepcopy(RAW)
    raw["declines"]["unknown"] = secret
    with pytest.raises(_cfg().AssistantConfigError) as caught:
        _cfg().load_assistant_config(_write(tmp_path, raw))
    message = str(caught.value)
    assert "declines" in message and "SECRET-VALUE" not in message and "9f2c" not in message


def test_FR_PA_13_config_is_read_on_every_call_and_its_fingerprint_follows_the_content(tmp_path):
    path = _write(tmp_path, copy.deepcopy(RAW))
    first = _cfg().load_assistant_config(path)
    raw = copy.deepcopy(RAW)
    raw["declines"]["unknown"] = "Something else entirely."
    _write(tmp_path, raw)
    second = _cfg().load_assistant_config(path)
    assert second.declines["unknown"] == "Something else entirely."
    assert len(first.fingerprint) == 64 and set(first.fingerprint) <= set("0123456789abcdef")
    assert first.fingerprint != second.fingerprint
    reordered = _write(tmp_path, dict(reversed(list(copy.deepcopy(RAW).items()))), "reordered.yaml")
    assert _cfg().load_assistant_config(reordered).fingerprint == _cfg().load_assistant_config().fingerprint, (
        "the fingerprint is of the canonical (key-sorted) content, not of the file bytes"
    )


# --------------------------------------------------------------------------------------------- the word rules
def _words():
    return mod("tilo_api.assistant.words")


def _config():
    return _cfg().load_assistant_config()


@pytest.mark.parametrize(
    ("raw", "key"),
    [
        ("What   IS  ON my   Plate??", "what is on my plate??"),
        (u(0xFF30, 0xFF2C, 0xFF21, 0xFF34, 0xFF25), "plate"),
        ("pla" + u(0x200B) + "te", "plate"),
        ("pla" + u(0x202E) + "te", "plate"),
        ("pla" + u(0xE0041) + "te", "plate"),
        ("What" + u(0x2019) + "s", "what's"),
        ("What" + u(0x2018) + "s", "what's"),
        ("What" + u(0x02BC) + "s", "what's"),
        ("Stra" + u(0xDF) + "e", "strasse"),
        ("a" + u(0xA0) + "b", "a b"),
        ("", ""),
    ],
)
def test_FR_PA_13_words_question_key_normalises(raw, key):
    assert _words().question_key(raw) == key


def test_FR_PA_13_words_question_key_is_cut_to_2000_characters_and_collapses_spaces():
    key = _words().question_key("a" * 2500)
    assert key == "a" * 2000
    spaced = _words().question_key("a " * 1500)
    assert len(spaced) == 2000 and "  " not in spaced


@pytest.mark.parametrize(
    ("key", "tokens"),
    [
        ("what's on my plate?", ("what's", "on", "my", "plate")),
        ("u_priya", ("u", "priya")),
        ("3pm", ("3pm",)),
        ("needs-you", ("needs", "you")),
        (u(0x092F, 0x094B, 0x091C, 0x0928, 0x093E), ()),
        (u(0x041F, 0x043B, 0x0430, 0x043D), ()),
        ("", ()),
    ],
)
def test_FR_PA_13_words_tokens(key, tokens):
    assert _words().tokens(key) == tokens


@pytest.mark.parametrize(
    ("text", "expect"),
    [
        ("can you show my plate", ("show", "my", "plate")),
        ("what's on my plate", ("what", "on", "my", "plate")),
        ("priya's plate", ("priya", "plate")),
        ("show please my plate", ("show", "please", "my", "plate")),  # only LEADING fillers are dropped
        ("please hey ok", ()),
        ("hey tilo can you open settings", ("open", "settings")),
    ],
)
def test_FR_PA_13_words_cut_at_the_apostrophe_and_drop_leading_fillers(text, expect):
    config = _config()
    assert _words().words(_words().question_key(text), config) == expect


@pytest.mark.parametrize(
    ("text", "other"),
    [
        ("What is on Priya's plate?", True),
        ("What is on Priya" + u(0x2019) + "s plate?", True),
        ("What is on Sam's plate?", True),  # even the asker's own first name is a possessive of a name
        ("Show her calendar", True),
        ("what does my manager's plate hold", True),
        ("what are the colleagues doing", True),
        ("what is everyone doing", True),
        ("what's on my plate", False),
        ("what's new", False),
        ("it's due soon", False),
        ("that's overdue", False),
        ("today's calendar", False),
        ("the team's pins", False),
        (
            "what is Priya working on",
            False,
        ),  # no possessive and no third-person word: the model may still only read OUR plate
        ("open the pinboard", False),
        ("", False),
    ],
)
def test_FR_PA_17_words_someone_elses_plate_is_recognised_by_the_words_alone(text, other):
    key = _words().question_key(text)
    assert _words().about_someone_else(key, _config()) is other, text


@settings(max_examples=150, deadline=None)
@given(st.text(max_size=300))
def test_FR_PA_13_words_never_raise_and_are_deterministic(text):
    w, config = _words(), _config()
    key = w.question_key(text)
    assert key == w.question_key(text) and len(key) <= 2000
    assert len(key) == 2000 or key == " ".join(key.split())
    assert w.words(key, config) == w.words(key, config)
    assert isinstance(w.about_someone_else(key, config), bool)
    assert all(t == t.lower() for t in w.tokens(key))


# --------------------------------------------------------------------------------------------- read_as
class SubStr(str):
    pass


class SubDict(dict):
    pass


class SubList(list):
    pass


def _poison(value):
    if isinstance(value, str):
        return SubStr(value)
    if isinstance(value, dict):
        return SubDict({SubStr(k): _poison(v) for k, v in value.items()})
    if isinstance(value, list):
        return SubList(_poison(v) for v in value)
    return value


class PoisonedStore:
    """A store that hands back str, dict and list SUBCLASSES (what a Firestore adapter might)."""

    def __init__(self, inner):
        self._inner, self.kind = inner, inner.kind

    def get(self, org_id, record_id):
        found = self._inner.get(org_id, record_id)
        return None if found is None else Stored(kind=found.kind, record=_poison(found.record), version=found.version)

    def list(self, org_id, field=None, value=None):
        return tuple(
            Stored(kind=s.kind, record=_poison(s.record), version=s.version)
            for s in self._inner.list(org_id, field, value)
        )

    def __getattr__(self, name):
        return getattr(self._inner, name)


def _read(world, kind, rid, *, actor=SAM, owners=None, now=NOW, directory=None, people=None):
    pa = mod("tilo_api.people_access")
    return pa.read_as(
        people or world.spied,
        directory or directory_of(world),
        actor=actor,
        org_id=ORG,
        record_kind=kind,
        record_id=rid,
        now=now,
        source_owners=owners or pa.NoSourceOwners(),
    )


OWN = [
    ("work_item", "wi_budget_notes", "work_items"),
    ("pinboard_item", "pb_kickoff", "pins"),
    ("pinboard_item", "pb_vendor_review", "pins"),
    ("calendar_entry", "ce_plan1", "calendar"),
    ("meeting", "mt_samsync1", "meetings"),
    ("person", SAM, "persons"),
]
NOT_MINE = [
    ("work_item", "wi_priya_1"),
    ("work_item", "wi_sam_proposed"),
    ("pinboard_item", "pb_priya_personal"),
    ("pinboard_item", "pb_priya_proposed"),
    ("calendar_entry", "ce_priya_private"),
    ("meeting", "mt_priya1"),
    ("person", PRIYA),
    ("person", "u_omar"),
    ("work_item", "wi_nowhere"),
    ("work_item", "wi_other_org"),
]


@pytest.mark.parametrize(("kind", "rid", "store"), OWN)
def test_FR_PA_17_read_as_returns_the_persons_own_record_in_full(world, kind, rid, store):
    got = _read(world, kind, rid)
    assert got == getattr(world.stores, store).get(ORG, rid).record and is_plain(got)


@pytest.mark.parametrize(("kind", "rid"), NOT_MINE)
def test_FR_PA_17_read_as_refuses_what_the_person_may_not_read_exactly_like_what_does_not_exist(world, kind, rid):
    assert _read(world, kind, rid) is None


def test_FR_PA_17_read_as_an_attendee_of_a_meeting_is_not_its_owner(world):
    assert _read(world, "meeting", "mt_priya1") is None  # Sam is in attendees[].user: never an identity
    assert _read(world, "meeting", "mt_samsync1", actor=PRIYA) is None
    assert _read(world, "meeting", "mt_samsync1", actor="u_omar") is None  # Omar is Sam's attendee


@pytest.mark.parametrize("kind", ["mention", "card", "world", "mail", "event", "pin", "", None, 5])
def test_FR_PA_17_read_as_names_only_the_five_people_kinds(world, monkeypatch, kind):
    spy = AccessSpy(monkeypatch)
    assert _read(world, kind, "wi_budget_notes") is None
    assert spy.reads == [] and spy.decides == []


@pytest.mark.parametrize(
    "rid",
    [
        "",
        None,
        5,
        b"wi_budget_notes",
        "wi_budget notes",
        "wi_budget_notes\n",
        "../x",
        "wi_" + "a" * 60,
        "WI_BUDGET_NOTES",
        ["wi_budget_notes"],
        {"id": "wi_budget_notes"},
        "wi_budget_notes" + chr(0),
    ],
)
def test_FR_PA_17_read_as_a_malformed_id_is_none_and_never_raises(world, rid):
    assert _read(world, "work_item", rid) is None


def test_FR_PA_17_read_as_asks_the_oracle_as_the_person_with_read_full_and_canonical_plain_data(world, monkeypatch):
    spy = AccessSpy(monkeypatch)
    for kind, rid, _ in OWN:
        _read(world, kind, rid)
    assert len(spy.reads) >= len(OWN)
    for kind, rid, _ in OWN:  # the same with str subclasses for the inputs a caller may hold
        _read(world, kind, SubStr(rid), actor=SubStr(SAM), now=SubStr(NOW))
    for request in spy.reads:
        assert (request.actor, request.action, request.now) == (SAM, "read_full", NOW)
        assert type(request.actor) is str and type(request.action) is str and type(request.now) is str
        assert type(request.record_kind) is str and is_plain(request.record), "no str/dict subclass reaches the oracle"
        for extra in (request.meeting, request.work_item):
            assert extra is None or is_plain(extra)
        assert request.source_owner is None or type(request.source_owner) is str


def test_FR_PA_17_read_as_canonicalises_what_a_store_hands_back(world, monkeypatch):
    spy = AccessSpy(monkeypatch)
    people = PeopleStores(
        persons=PoisonedStore(world.spied.persons),
        meetings=PoisonedStore(world.spied.meetings),
        work_items=PoisonedStore(world.spied.work_items),
        pins=PoisonedStore(world.spied.pins),
        mentions=world.spied.mentions,
        calendar=PoisonedStore(world.spied.calendar),
    )
    for kind, rid, _ in OWN:
        got = _read(world, kind, rid, people=people)
        assert got is None or is_plain(got)
    assert spy.reads and all(is_plain(r.record) for r in spy.reads)


def test_FR_PA_17_read_as_loads_one_org_only(world):
    world.reset_log()
    _read(world, "work_item", "wi_other_org")
    _read(world, "work_item", "wi_budget_notes")
    _read(world, "meeting", "mt_priya1")
    assert world.log and {org for _, _, org, _ in world.log} == {ORG}, "no lookup names another org"


def test_FR_PA_17_read_as_loads_the_source_meeting_of_a_tilo_made_record_from_the_store_never_the_request(world):
    entry = calendar_entry(
        "ce_tilo1",
        SAM,
        "Tilo review slot",
        "2026-10-07T09:00:00.000Z",
        "2026-10-07T09:30:00.000Z",
        source={"kind": "tilo", "from": "meeting", "ref": "mt_samsync1"},
        state="proposed",
        created_by=maker("A_cal", "tilo"),
    )
    world.stores.calendar.create(entry)
    assert _read(world, "calendar_entry", "ce_tilo1") == entry
    assert ("meetings", "get", ORG, "mt_samsync1") in world.log
    world.stores.meetings.delete(ORG, "mt_samsync1", expected_version=1)
    assert _read(world, "calendar_entry", "ce_tilo1") is None, "no source meeting: fail closed"
    other = calendar_entry(
        "ce_tilo2",
        SAM,
        "Tilo review slot two",
        "2026-10-07T10:00:00.000Z",
        "2026-10-07T10:30:00.000Z",
        source={"kind": "tilo", "from": "meeting", "ref": "mt_priya1"},
        state="proposed",
        created_by=maker("A_cal", "tilo"),
    )
    world.stores.calendar.create(other)
    assert _read(world, "calendar_entry", "ce_tilo2") is None, "a meeting another person owns does not source my entry"


def test_FR_PA_17_read_as_loads_the_released_work_item_of_a_calendar_proposal(world):
    minuted = {
        **world.stores.meetings.get(ORG, "mt_priya1").record,
        "status": "minuted",
        "transcript": {"artifact_id": "art_transcript1", "version": 1},
        "minutes": {"artifact_id": "art_minutes1", "version": 1},
        "minutes_confirmed_by": stamp(PRIYA),
    }
    world.replace_record("meetings", minuted)
    item = work_item("wi_released", SAM, "Released action item")
    item.update(
        created_by=maker("A_notes", "tilo"),
        assigned_by=stamp(PRIYA),
        confirmed_by=stamp(PRIYA, "2026-10-02T09:00:00.000Z"),
        source={"kind": "meeting", "ref": "mt_priya1#ai1", "evidence": ["u0004"]},
        history=[hist("A_notes", "created", "proposed"), hist(PRIYA, "confirmed", "open", "2026-10-02T09:00:00.000Z")],
    )
    world.stores.work_items.create(item)
    entry = calendar_entry(
        "ce_rel1",
        SAM,
        "Follow-up slot",
        "2026-10-07T09:00:00.000Z",
        "2026-10-07T09:30:00.000Z",
        source={"kind": "tilo", "from": "meeting", "ref": "mt_priya1#ai1"},
        state="proposed",
        created_by=maker("A_cal", "tilo"),
    )
    world.stores.calendar.create(entry)
    context = access.AccessRequest(
        actor=SAM,
        action="read_full",
        record_kind="calendar_entry",
        record=entry,
        now=NOW,
        meeting=minuted,
        work_item=item,
    )
    assert access.read(context, directory_of(world)) is not None, "fixture check: the oracle allows with this context"
    world.reset_log()
    assert _read(world, "calendar_entry", "ce_rel1") == entry
    assert ("work_items", "list", ORG, None) in world.log
    world.stores.work_items.delete(ORG, "wi_released", expected_version=1)
    assert _read(world, "calendar_entry", "ce_rel1") is None


class FakeOwners:
    def __init__(self, owner):
        self.owner, self.calls = owner, []

    def owner_of(self, org_id, record_kind, record):
        self.calls.append((org_id, record_kind, record.get("id")))
        return self.owner


def _google_entry(world):
    entry = calendar_entry(
        "ce_goog1",
        SAM,
        "Synced event",
        "2026-10-07T09:00:00.000Z",
        "2026-10-07T09:30:00.000Z",
        source={"kind": "google", "ref": "evt_abc123", "synced_at": STAMP},
        created_by=maker("A_calendar_sync", "tilo"),
    )
    world.stores.calendar.create(entry)
    return entry


def test_FR_PA_17_read_as_the_source_owner_comes_from_the_source_store_never_the_record(world):
    entry = _google_entry(world)
    mine, hers = FakeOwners(SAM), FakeOwners(PRIYA)
    assert _read(world, "calendar_entry", "ce_goog1", owners=mine) == entry
    assert mine.calls == [(ORG, "calendar_entry", "ce_goog1")]
    assert _read(world, "calendar_entry", "ce_goog1", owners=hers) is None
    assert _read(world, "calendar_entry", "ce_goog1") is None, "production default: NoSourceOwners, fail closed"
    person_made = FakeOwners(SAM)
    assert _read(world, "work_item", "wi_budget_notes", owners=person_made) is not None
    assert person_made.calls == [], "a person-made record never asks for a source owner"


def test_FR_PA_17_no_source_owners_always_says_none():
    pa = mod("tilo_api.people_access")
    assert pa.NoSourceOwners().owner_of(ORG, "calendar_entry", {"id": "ce_x", "owner": SAM}) is None


# --------------------------------------------------------------------------------------------- RefGate
def _gate(world, plate=None, *, user=SAM):
    from _ppl11b_lib import make_gate  # noqa: PLC0414,PLC0415

    return make_gate(world, plate if plate is not None else plate_s1(user), user=user)


def _ref(kind, rid):
    return mod("tilo_api.assistant.gate").Ref(kind, rid)


def test_FR_PA_17_ref_is_a_frozen_value_that_serialises_as_a_record_ref():
    ref = _ref("work_item", "wi_x")
    assert ref.json() == {"kind": "work_item", "id": "wi_x"} and ref == _ref("work_item", "wi_x") and {ref}
    with pytest.raises(Exception):  # noqa: B017,PT011
        ref.id = "other"  # type: ignore[misc]


GATE_TABLE = [
    ("work_item", "wi_budget_notes", True),
    ("work_item", "wi_priya_1", False),
    ("work_item", "wi_nowhere", False),
    ("work_item", "wi_sam_proposed", False),
    ("pinboard_item", "pb_kickoff", True),
    ("pinboard_item", "pb_priya_personal", False),
    ("pinboard_item", "pb_priya_proposed", False),
    ("calendar_entry", "ce_plan1", True),
    ("calendar_entry", "ce_priya_private", False),
    ("meeting", "mt_samsync1", True),
    ("meeting", "mt_priya1", False),
    ("world", W_LAUNCH, True),
    ("world", W_VENDOR, True),
    ("world", W_PRIYA, False),
    ("world", "w_nowhere", False),
    ("card", C_GATE, True),
    ("card", ulid(999), False),
    ("mail", MAIL_ID, True),
    ("mail", "msg_other", False),
    ("event", C_GATE, False),
    ("mention", "mn_sam1", False),
    ("person", SAM, False),
    ("pin", "pb_kickoff", False),
    ("", "", False),
    ("work_item", "", False),
    ("card", C_GATE + "\n", False),
]


@pytest.mark.parametrize(("kind", "rid", "ok"), GATE_TABLE)
def test_FR_PA_17_gate_allows_a_ref_only_as_the_oracle_and_the_plate_say(world, kind, rid, ok):
    assert _gate(world).allows(_ref(kind, rid)) is ok


def test_FR_PA_17_gate_a_world_is_the_persons_only_when_they_own_it(world):
    from tilo_api.deps import WorldRecord  # noqa: PLC0415

    world.store.worlds["w_weird"] = {"owner": SAM}  # type: ignore[assignment]  (not a WorldRecord)
    world.store.worlds["w_none"] = None  # type: ignore[assignment]
    world.store.worlds["w_lead"] = WorldRecord(owner=PRIYA, districts={})
    gate = _gate(world)
    for wid in ("w_weird", "w_none", "w_lead", W_PRIYA):
        assert gate.allows(_ref("world", wid)) is False, wid


@pytest.mark.parametrize("ref", [("work_item", 5), (None, None), ("card", None), (5, "x"), ("work_item", ["x"])])
def test_FR_PA_17_gate_never_raises_on_a_garbled_ref(world, ref):
    assert _gate(world).allows(_ref(*ref)) is False


def test_FR_PA_17_gate_cards_and_mail_are_named_only_by_the_plate_builder(world):
    empty = _gate(world, {"rows": []})
    assert empty.allows(_ref("card", C_GATE)) is False and empty.allows(_ref("mail", MAIL_ID)) is False
    full = _gate(world)
    assert full.allows(_ref("card", C_GATE)) and full.allows(_ref("mail", MAIL_ID))


def test_FR_PA_17_gate_record_is_the_full_view_memoised_per_request(world, monkeypatch):
    spy = AccessSpy(monkeypatch)
    gate = _gate(world)
    first = gate.record(_ref("work_item", "wi_budget_notes"))
    second = gate.record(_ref("work_item", "wi_budget_notes"))
    assert first == second == world.stores.work_items.get(ORG, "wi_budget_notes").record and is_plain(first)
    assert len([r for r in spy.reads if r.record["id"] == "wi_budget_notes"]) == 1
    assert gate.record(_ref("work_item", "wi_priya_1")) is None and gate.record(_ref("card", C_GATE)) is None


def test_FR_PA_17_gate_viewer_who_left_the_team_loses_every_team_record(world):
    left = [p for p in world.stores.persons.list(ORG) if p.record["id"] == SAM][0]
    gone = {**left.record, "memberships": []}
    world.stores.persons.replace(gone, expected_version=left.version)
    gate = _gate(world)
    for kind, rid in (
        ("pinboard_item", "pb_kickoff"),
        ("pinboard_item", "pb_vendor_review"),
        ("pinboard_item", "pb_flagged"),
        ("calendar_entry", "ce_priya_shared"),
    ):
        assert gate.allows(_ref(kind, rid)) is False, rid
    assert gate.allows(_ref("work_item", "wi_budget_notes")) and gate.allows(_ref("calendar_entry", "ce_plan1"))


CONTEXT_TABLE = [
    (None, "/plate", None),
    ("wi_budget_notes", "/plate", ("work_item", "wi_budget_notes")),
    ("pb_kickoff", "/plate", ("pinboard_item", "pb_kickoff")),
    ("ce_plan1", "/calendar", ("calendar_entry", "ce_plan1")),
    ("mt_samsync1", "/plate", ("meeting", "mt_samsync1")),
    (W_LAUNCH, "/plate", ("world", W_LAUNCH)),
    (C_GATE, "/plate", ("card", C_GATE)),
    (None, f"/world/{W_LAUNCH}", ("world", W_LAUNCH)),
    (None, "/meetings/mt_samsync1", ("meeting", "mt_samsync1")),
    ("wi_priya_1", "/plate", None),  # refused
    ("wi_nowhere", "/plate", None),  # unknown: the same None
    ("wi_priya_1", f"/world/{W_LAUNCH}", ("world", W_LAUNCH)),  # the first candidate is refused, the next is admitted
    ("wi_nowhere", "/meetings/mt_samsync1", ("meeting", "mt_samsync1")),
    (None, f"/world/{W_PRIYA}", None),
    (None, "/meetings/mt_priya1", None),
    (ulid(999), "/plate", None),  # a ULID that is not a card of the plate
    (MAIL_ID, "/plate", None),  # mail is never a selection
    ("wi_budget_notes\n", "/plate", None),  # fullmatch: a trailing newline is no id
    ("wi_budget notes", "/plate", None),
    ("WI_BUDGET_NOTES", "/plate", None),
    ("zz_budget", "/plate", None),
    ("wi_" + "a" * 49, "/plate", None),
    (C_GATE.lower(), "/plate", None),
    (None, "/world/", None),
    (None, "/", None),
]


@pytest.mark.parametrize(("record", "path", "want"), CONTEXT_TABLE)
def test_FR_PA_17_gate_context_ref_picks_the_first_readable_candidate(world, record, path, want):
    got = _gate(world).context_ref(record, path)
    assert (got is None) if want is None else (got == _ref(*want)), (record, path)


def test_FR_PA_17_gate_a_refused_id_and_an_unknown_id_give_the_same_answer_everywhere(world):
    gate = _gate(world)
    for kind, refused, unknown in (
        ("work_item", "wi_priya_1", "wi_zzz_nowhere"),
        ("pinboard_item", "pb_priya_personal", "pb_zzz_nowhere"),
        ("calendar_entry", "ce_priya_private", "ce_zzz_nowhere"),
        ("meeting", "mt_priya1", "mt_zzz_nowhere"),
        ("world", W_PRIYA, "w_zzz_nowhere"),
    ):
        assert gate.allows(_ref(kind, refused)) is gate.allows(_ref(kind, unknown)) is False
        assert gate.record(_ref(kind, refused)) is gate.record(_ref(kind, unknown)) is None
        assert gate.context_ref(refused, "/plate") is gate.context_ref(unknown, "/plate") is None


@pytest.mark.parametrize(
    ("path", "screen"),
    [
        ("/plate", "plate"),
        ("/calendar", "calendar"),
        ("/meetings", "meetings"),
        ("/meetings/mt_samsync1", "meeting"),
        ("/pinboards", "pinboard_team"),
        ("/worlds", "worlds"),
        (f"/world/{W_LAUNCH}", "world"),
        ("/needs-you", "cards"),
        ("/connections", "connections"),
        ("/channels", "channels"),
        ("/autonomy", "autonomy"),
        ("/settings", "settings"),
        ("/", None),
        ("", None),
        ("/unknown", None),
        ("/admin/users", None),
    ],
)
def test_FR_PA_14_screen_of_maps_the_first_path_segment(path, screen):
    assert mod("tilo_api.assistant.gate").screen_of(path, _config()) == screen


def test_FR_PA_17_the_directory_is_not_kept_between_gates_so_a_membership_change_counts_at_once(world):
    assert _gate(world).allows(_ref("pinboard_item", "pb_kickoff"))
    sam = world.stores.persons.get(ORG, SAM)
    world.stores.persons.replace(
        {**sam.record, "memberships": [{"team": "tm_ops", "assigned_by": stamp()}]}, expected_version=sam.version
    )
    assert not _gate(world).allows(_ref("pinboard_item", "pb_kickoff")), f"the pin is in {LAUNCH}: Sam moved to tm_ops"


def test_FR_PA_17_other_orgs_records_are_never_read(world, monkeypatch):
    spy = AccessSpy(monkeypatch)
    gate = _gate(world)
    assert gate.allows(_ref("work_item", "wi_other_org")) is False
    assert gate.context_ref("wi_other_org", "/plate") is None
    assert all(r.record["org_id"] == ORG for r in spy.reads)
