"""PPL-11b slice 11b-2, the route `POST /v1/assistant/ask` with rules only (API_PPL_11b.md sections 1, 6, 7 and
10.1 to 10.3): FR-PA-14 navigation by allow-list and FR-PA-17 panel privacy (EP-1, EP-3b, EP-5 to EP-8), plus the
FR-PA-13 route clauses (A13-7). The route is wired with the REAL `tilo_people` oracle over in-memory stores, a fake
plate source, a scripted `Decider`, the fake event writer and an in-memory raw archive; nothing leaves the process.

Acceptance (PRD addendum FR-PA-14): 30 intents, at least 90% resolved by rules with no model call; 200 fuzzed model
outputs execute 0 actions; a `navigate` is offered or executed only for a target the signed-in person may read.
FR-PA-17 (E-PRIV panel cases): "what is on Priya's plate", a navigate target in someone else's personal board, a
tag on a non-member: all refused with 0 leaked fields, the refusal text chosen from the question, the config and
the person's own data only.

Written before any implementation: every test fails today (no route, no `tilo_api.assistant`).
"""

from __future__ import annotations

import concurrent.futures
import inspect
import json
import pathlib
import string
import threading

import pytest
from _api_lib import assert_part_carries_no_stamped_fields
from _ppl11b_lib import (
    ANSWER,
    C_GATE,
    DECLINES,
    FLAGGED_TITLE,
    MAIL_ID,
    NOW,
    ORG,
    OTHER_ORG,
    PRIYA,
    PRIYA_TITLES,
    RAW,
    SAM,
    UNMATCHED,
    W_LAUNCH,
    W_PRIYA,
    W_VENDOR,
    AccessSpy,
    DirectorySpy,
    FailingNthWriter,
    LockedEventWriter,
    ScriptedDecider,
    ask_body,
    assert_body_shape,
    assert_events_valid,
    assert_no_leak,
    body_lines,
    build_world,
    decision,
    desk_ids,
    expected_facts,
    fuzz_replies,
    intent_context,
    intent_expected,
    lines_of,
    load_intents,
    load_questions,
    make_gate,
    mod,
    model_decision,
    navigate_to,
    person,
    plate_buggy,
    plate_lena,
    plate_s0,
    plate_s1,
    principal,
    run_answer,
    strip_volatile,
    ulid,
    unwire_plate_sources,
)
from _ppl11b_lib import rig_factory as rig_factory  # noqa: PLC0414  (the fixture)
from _ppl11b_lib import world as world  # noqa: PLC0414  (the fixture)
from tilo_archive import verify_chain
from tilo_people.stores import erase_person
from tilo_policy.schemas import conforms

QUESTIONS = load_questions()
INTENTS = load_intents()
ASKED_SUMMARY = "A question was asked in the assistant panel."
REPLIED_SUMMARY = {
    "navigated": "The assistant opened a screen.",
    "declined": "The assistant declined.",
    "failed": "The assistant could not answer.",
}
SENTINELS = [
    *PRIYA_TITLES.values(),
    "wi_priya_1",
    "wi_priya_2",
    "pb_priya_personal",
    "pb_priya_proposed",
    "ce_priya_private",
    "mt_priya1",
    "OTHER-ORG-SECRET",
    "wi_other_org",
]


def _ok(response):
    assert response.status_code == 200, response.text
    body = response.json()
    assert_body_shape(body)
    return body


def _replied_summary(body):
    if body["outcome"] == "answered":
        return f"The assistant answered from {len(body['sources'])} records."
    return REPLIED_SUMMARY[body["outcome"]]


def _check_events(rig, body, *, user=SAM, screen="plate", actor="system", extra_events=0):
    """The asked and replied events of ONE request in the person's Desk world (API_PPL_11b.md section 1, Events)."""
    world_id, run_id = desk_ids(user)
    evs = rig.events(user)
    assert [e["type"] for e in evs] == ["assistant.asked", "assistant.replied", *["memory.hit"] * extra_events]
    asked, replied = evs[0], evs[1]
    records = rig.archive_records(user)
    kinds = [r["kind"] for r in records]
    assert (
        kinds[0] == "channel_in"
        and kinds[-1] == "channel_out"
        and set(kinds) <= {"channel_in", "model_call", "channel_out"}
    )
    assert verify_chain(records) == []
    for ev in (asked, replied):
        assert (ev["world_id"], ev["run_id"], ev["target"], ev["vis"], ev["authz"], ev["severity"]) == (
            world_id,
            run_id,
            user,
            "all",
            None,
            "info",
        )
        assert (ev["level"], ev["district"], ev["item"]) == (None, None, None)
    assert (asked["actor"], asked["summary"], asked["credits"], asked["cause"]) == (user, ASKED_SUMMARY, 0, None)
    assert set(asked["trace"].values()) == {None}
    assert asked["data"] == {"conversation_id": body["conversation_id"], "message_ref": f"{run_id}/1", "screen": screen}
    assert replied["actor"] == actor and replied["summary"] == _replied_summary(body) and replied["cause"] is None
    assert replied["credits"] == body["cost"]["credits"]
    out_ref = f"{run_id}/{records[-1]['seq']}"
    assert replied["data"] == {
        "conversation_id": body["conversation_id"],
        "message_ref": out_ref,
        "outcome": body["outcome"],
        "decided_by": body["decided_by"],
        "sources": body["sources"],
        "ui_action": body["ui_action"],
        "cached": body["cached"],
    }
    assert_events_valid(evs)
    for call in rig.writer.calls:
        assert_part_carries_no_stamped_fields(call.part)
        assert call.world_id == world_id
    return evs, records


def _identical(a, b):
    assert strip_volatile(a) == strip_volatile(b)


# --------------------------------------------------------------------------------------------- who may ask, bodies
def test_FR_PA_17_no_signed_in_person_gets_401_and_nothing_is_stored(rig_factory):
    rig = rig_factory(who=None)
    response = rig.ask("What is on my plate?")
    assert response.status_code == 401
    assert rig.nothing_stored() and desk_ids(SAM)[0] not in rig.store.worlds and rig.plate_source.calls == []


@pytest.mark.parametrize("channel", ["web", "mobile_web"])
def test_FR_PA_17_the_web_and_mobile_web_sessions_may_ask(rig_factory, channel):
    rig = rig_factory(who=principal(channel=channel))
    assert _ok(rig.ask("What is on my plate?"))["outcome"] == "answered"


def test_FR_PA_17_an_email_session_is_refused_before_anything_is_stored(rig_factory):
    rig = rig_factory(who=principal(channel="email"))
    response = rig.ask("What is on my plate?")
    assert response.status_code == 403 and response.json() == {"error": "channel"}
    assert rig.nothing_stored() and desk_ids(SAM)[0] not in rig.store.worlds and rig.plate_source.calls == []


@pytest.mark.parametrize("role", ["owner", "team_lead", "approver", "viewer"])
def test_FR_PA_17_role_and_world_membership_are_ignored_the_panel_is_person_scoped(rig_factory, role):
    rig = rig_factory(who=principal(role=role, world_id=W_PRIYA))
    body = _ok(rig.ask("What is on my plate?"))
    assert body_lines(body) == expected_facts("plate", plate_s1()["rows"]).lines
    _ok(rig.ask("What is waiting for me?"))
    assert_no_leak(rig.surfaces(), SENTINELS)


def test_FR_PA_17_the_person_is_the_session_never_the_body(rig_factory):
    rig = rig_factory(plates={SAM: plate_s1(), PRIYA: plate_s0(PRIYA)})
    for key in ("user", "user_id", "actor", "person", "org", "org_id"):
        response = rig.post(ask_body("What is on my plate?", **{key: PRIYA}))
        assert response.status_code == 422 and response.json() == {"error": "bad_body"}, key
    assert rig.nothing_stored()
    sam = _ok(rig.ask("What is on my plate?"))
    rig.set_principal(principal(PRIYA))
    priya = _ok(rig.ask("What is on my plate?"))
    assert sam["outcome"] == "answered" and priya["outcome"] == "declined" and priya["text"] == "Your plate is empty."
    assert [c[0] for c in rig.plate_source.calls] == [SAM, PRIYA]
    assert len(rig.events(SAM)) == 2 and len(rig.events(PRIYA)) == 2, "each person's events are in their own Desk world"
    assert desk_ids(SAM)[0] != desk_ids(PRIYA)[0]


BAD_BODIES = [
    ("an extra top-level key", ask_body("hi", surprise=1), "bad_body"),
    ("a list body", ["hi"], "bad_body"),
    ("a string body", "hi", "bad_body"),
    ("no context", {"question": "hi"}, "bad_body"),
    ("no question", {"context": {"route": "/plate", "record": None}}, "bad_body"),
    ("question as a number", ask_body(5), "bad_body"),
    ("question as null", ask_body(None), "bad_body"),
    ("question as a list", ask_body(["hi"]), "bad_body"),
    ("an empty question", ask_body(""), "question_length"),
    ("a blank question", ask_body("   "), "question_length"),
    ("a question of 501 characters", ask_body("a" * 501), "question_length"),
    ("context as a string", {"question": "hi", "context": "/plate"}, "bad_context"),
    ("context without a route", {"question": "hi", "context": {"record": None}}, "bad_context"),
    ("context without a record key", {"question": "hi", "context": {"route": "/plate"}}, "bad_context"),
    (
        "an extra context key",
        {"question": "hi", "context": {"route": "/plate", "record": None, "user": PRIYA}},
        "bad_context",
    ),
    ("a route without a slash", ask_body("hi", route="plate"), "bad_context"),
    ("a route with a space", ask_body("hi", route="/pl ate"), "bad_context"),
    ("a route with a query", ask_body("hi", route="/plate?x=1"), "bad_context"),
    ("a route of 201 characters", ask_body("hi", route="/" + "a" * 200), "bad_context"),
    ("a route with a newline", ask_body("hi", route="/plate\n"), "bad_context"),
    ("a route as null", ask_body("hi", route=None), "bad_context"),
    ("a route as a number", ask_body("hi", route=7), "bad_context"),
    ("a record with a space", ask_body("hi", record="wi x"), "bad_context"),
    ("a record of 65 characters", ask_body("hi", record="a" * 65), "bad_context"),
    ("a record as a number", ask_body("hi", record=5), "bad_context"),
    ("an empty record", ask_body("hi", record=""), "bad_context"),
    ("a record with a path", ask_body("hi", record="../x"), "bad_context"),
    ("a record with a trailing newline", ask_body("hi", record="wi_budget_notes\n"), "bad_context"),
    ("a label of 121 characters", ask_body("hi", label="l" * 121), "bad_context"),
    (
        "a label as a number",
        {"question": "hi", "context": {"route": "/plate", "record": None, "label": 5}},
        "bad_context",
    ),
    ("a lowercase conversation id", ask_body("hi", conversation_id="01jb5vq0000000000000009311"), "bad_conversation"),
    ("a short conversation id", ask_body("hi", conversation_id="abc"), "bad_conversation"),
    ("a conversation id with a trailing newline", ask_body("hi", conversation_id=ulid(5) + "\n"), "bad_conversation"),
    (
        "a conversation id as a number",
        {"question": "hi", "context": {"route": "/plate", "record": None}, "conversation_id": 5},
        "bad_conversation",
    ),
]


@pytest.mark.parametrize(("label", "body", "error"), BAD_BODIES, ids=[b[0] for b in BAD_BODIES])
def test_FR_PA_17_a_malformed_body_is_422_and_stores_and_emits_nothing(rig_factory, label, body, error):
    rig = rig_factory(decider=ScriptedDecider())
    response = rig.post(body)
    assert response.status_code == 422 and response.json() == {"error": error}, response.text
    assert rig.nothing_stored() and desk_ids(SAM)[0] not in rig.store.worlds
    assert rig.plate_source.calls == [] and rig.decider.calls == 0


@pytest.mark.parametrize(
    ("label", "raw"),
    [
        ("invalid JSON", b"{"),
        ("not UTF-8", b"\xff\xfe{}"),
        ("NaN", b'{"question": NaN, "context": {"route": "/plate", "record": null}}'),
        (
            "a lone surrogate",
            b'{"question": "a' + bytes([92]) + b'ud800", "context": {"route": "/plate", "record": null}}',
        ),
    ],
)
def test_FR_PA_17_a_body_that_is_not_strict_json_text_is_422_bad_body(rig_factory, label, raw):
    rig = rig_factory()
    response = rig.raw(raw)
    assert response.status_code == 422 and response.json() == {"error": "bad_body"}, label
    assert rig.nothing_stored()


@pytest.mark.parametrize("content_type", ["text/plain", "application/x-www-form-urlencoded", "multipart/form-data", ""])
def test_FR_PA_17_only_application_json_is_read(rig_factory, content_type):
    rig = rig_factory()
    raw = json.dumps(ask_body("What is on my plate?")).encode()
    response = rig.client.post(
        "/v1/assistant/ask", content=raw, headers={"content-type": content_type} if content_type else {}
    )
    assert response.status_code == 415 and response.json() == {"error": "content_type"}
    assert rig.nothing_stored()


def test_FR_PA_17_json_with_a_charset_or_any_case_is_still_read(rig_factory):
    rig = rig_factory()
    raw = json.dumps(ask_body("What is on my plate?")).encode()
    assert rig.raw(raw, "Application/JSON; charset=utf-8").status_code == 200


def test_FR_PA_19_the_body_is_capped_at_8192_bytes_and_the_question_at_500_characters(rig_factory):
    rig = rig_factory()
    raw = json.dumps(ask_body("What is on my plate?")).encode()
    assert rig.raw(raw + b" " * (8192 - len(raw))).status_code == 200
    response = rig.raw(raw + b" " * (8193 - len(raw)))
    assert response.status_code == 413 and response.json() == {"error": "too_large"}
    assert len(rig.events()) == 2, "only the accepted request stored anything"
    assert _ok(rig.ask("a" * 500))["outcome"] == "declined"


def test_FR_PA_17_a_422_never_echoes_the_input_back(rig_factory):
    rig = rig_factory()
    secret_text = "zebraquartz-" + "x" * 600
    response = rig.post(ask_body(secret_text))
    assert response.status_code == 422 and "zebraquartz" not in response.text


def test_FR_PA_13_the_conversation_id_is_echoed_or_minted(rig_factory):
    rig = rig_factory()
    given = ulid(777)
    body = _ok(rig.ask("What is on my plate?", conversation_id=given))
    assert body["conversation_id"] == given
    assert all(e["data"]["conversation_id"] == given for e in rig.events())
    minted = _ok(rig.ask("What is on my plate?"))["conversation_id"]
    assert conforms("common.schema.json#/$defs/ulid", minted) and minted != given
    explicit_null = _ok(
        rig.post(
            {
                "question": "What is on my plate?",
                "context": {"route": "/plate", "record": None},
                "conversation_id": None,
            }
        )
    )
    assert conforms("common.schema.json#/$defs/ulid", explicit_null["conversation_id"])


# --------------------------------------------------------------------------------------------- A13-7 events
@pytest.mark.parametrize("n", [1, 4, 11, 17])
def test_FR_PA_13_A13_7_the_route_answers_with_the_template_and_the_events_agree(rig_factory, n):
    q = QUESTIONS[n - 1]
    decider = ScriptedDecider()
    rig = rig_factory(decider=decider)
    body = _ok(rig.ask(q["text"]))
    want = expected_facts(q["intent"], plate_s1()["rows"], narrow_title=q["narrow_title"])
    assert (body["outcome"], body["decided_by"], body["cached"]) == ("answered", "rules", False)
    assert body_lines(body) == want.lines and body["ui_action"] == want.ui_action
    assert body["sources"] == [{"kind": k, "id": i} for k, i in want.sources][:20] and body["sources"]
    assert body["cost"] == {"model_calls": 0, "credits": 0.0, "saved_credits": 0.0}
    _check_events(rig, body)
    assert decider.calls == 0 and rig.now_calls == 1, "the server clock is read once per request"
    assert rig.plate_source.calls == [(SAM, NOW)]


def test_FR_PA_13_the_asked_screen_comes_from_the_route_the_panel_was_opened_on(rig_factory):
    rig = rig_factory()
    for route, screen in (
        ("/plate", "plate"),
        ("/calendar", "calendar"),
        ("/meetings/mt_samsync1", "meeting"),
        ("/pinboards", "pinboard_team"),
        ("/somewhere/else", None),
        ("/", None),
    ):
        rig.store.events.clear()
        body = _ok(rig.ask("What is on my plate?", route=route))
        assert rig.events()[0]["data"]["screen"] == screen, route
        assert_events_valid(rig.events())
        assert body["outcome"] == "answered"


def test_FR_PA_13_an_unknown_question_over_the_route_is_declined_with_what_the_panel_can_show(rig_factory):
    rig = rig_factory(decider=None)
    body = _ok(rig.ask("Write me a poem about Mondays"))
    assert (body["outcome"], body["decided_by"], body["text"]) == ("declined", "rules", DECLINES["unknown"])
    assert (
        body["sources"] == []
        and body["ui_action"] is None
        and body["lines"] == [{"text": DECLINES["unknown"], "source": None}]
    )
    _check_events(rig, body)


def test_FR_PA_13_question_and_answer_text_live_only_in_the_redacted_raw_archive(rig_factory):
    from _ppl11b_lib import FAKE_KEY  # noqa: PLC0415

    rig = rig_factory()
    question = f"What is on my plate? my token is {FAKE_KEY}"
    body = _ok(rig.ask(question, route="/plate", record="wi_budget_notes"))
    records = rig.archive_records()
    assert [r["kind"] for r in records] == ["channel_in", "channel_out"]
    assert set(records[0]["payload"]) == {"conversation_id", "question", "route", "record"}
    assert records[0]["payload"]["question"].startswith("What is on my plate? my token is ")
    assert FAKE_KEY not in json.dumps(records), "the archive redactor runs before anything is written (PE-16)"
    assert records[0]["payload"]["route"] == "/plate" and records[0]["payload"]["record"] == "wi_budget_notes"
    assert records[1]["payload"] == {
        "conversation_id": body["conversation_id"],
        "outcome": "answered",
        "decided_by": "rules",
        "text": body["text"],
    }
    titles = [r["title"] for r in plate_s1()["rows"] if r["title"]]
    surfaces = rig.surfaces()
    for name in ("events", "parts", "logs"):
        assert_no_leak({name: surfaces[name]}, ["What is on my plate", FAKE_KEY, *titles], where=name)


def test_FR_PA_17_logs_carry_codes_and_ids_only_never_text(rig_factory):
    rig = rig_factory(decider=ScriptedDecider(model_decision("decline")))
    unique = "zebraquartz-unique-marker"
    for q in (QUESTIONS[0]["text"], f"{unique} what should I look at first", "What is on Priya's plate?"):
        rig.ask(q)
    titles = [r["title"] for r in plate_s1()["rows"] if r["title"]]
    assert_no_leak(
        {"logs": rig.logs()}, [unique, "What is on", "Priya's plate", *titles, DECLINES["unknown"][:30], *SENTINELS]
    )


# --------------------------------------------------------------------------------------------- failures and 503s
@pytest.mark.parametrize(
    "seam_name", ["get_store", "get_event_writer", "get_run_archive", "get_people_stores", "get_plate_source"]
)
def test_FR_PA_17_a_seam_that_is_not_wired_answers_503_not_configured_and_stores_nothing(
    rig_factory, seam_name, monkeypatch
):
    rig = rig_factory()
    rig.unwire(seam_name)
    if seam_name == "get_plate_source":
        unwire_plate_sources(
            monkeypatch
        )  # the sources under it read the store now (PEOPLE-SEAMS-1): unwired on purpose
    response = rig.ask("What is on my plate?")
    assert response.status_code == 503 and response.json() == {"detail": "not_configured"}, seam_name
    assert rig.writer.calls == [] and rig.archive.lines.lines == {} and rig.all_events() == []


def test_FR_PA_17_an_unusable_config_answers_503_not_configured(rig_factory, monkeypatch):
    from tilo_api import deps  # noqa: PLC0415

    config_module = mod("tilo_api.assistant.config")

    def broken(*args, **kwargs):
        raise config_module.AssistantConfigError("answer.max_lines: out of range")

    monkeypatch.setattr(config_module, "load_assistant_config", broken)
    monkeypatch.setattr(deps, "load_assistant_config", broken, raising=False)
    rig = rig_factory()
    response = rig.ask("What is on my plate?")
    assert response.status_code == 503 and response.json() == {"detail": "not_configured"}
    assert rig.writer.calls == [] and rig.archive.lines.lines == {}


@pytest.mark.parametrize("which", [1, 2])
def test_FR_PA_19_a_writer_that_refuses_an_event_answers_503_write_failed(rig_factory, which):
    from tilo_api import deps  # noqa: PLC0415

    rig = rig_factory()
    rig.writer = FailingNthWriter(rig.store, which)
    response = rig.ask("What is on my plate?")
    assert response.status_code == 503 and response.json() == {"detail": "write_failed"}
    assert rig.writer.attempts == which
    rig.writer = FailingNthWriter(rig.store, which, deps.EventRejected("same id, different content"))
    assert rig.ask("What is on my plate?").json() == {"detail": "write_failed"}


def _plates_that_fail():
    good = plate_s1()
    bad_row = plate_s1()
    bad_row["rows"][0]["ref"]["id"] = "bad id with spaces"
    extra_key = {**plate_s1(), "surprise": 1}
    missing = {k: v for k, v in plate_s1().items() if k != "fingerprint"}
    return {
        "another person's plate": plate_s1(PRIYA),
        "a plate with a bad row ref": bad_row,
        "a plate with an extra key": extra_key,
        "a plate without a fingerprint": missing,
        "a fingerprint that is no hash": {**good, "fingerprint": "xyz"},
        "no plate": None,
    }


@pytest.mark.parametrize("name", sorted(_plates_that_fail()))
def test_FR_PA_13_a_plate_that_is_missing_or_wrong_gives_a_failed_answer_not_an_invented_one(rig_factory, name):
    decider = ScriptedDecider()
    rig = rig_factory(decider=decider)
    plate = _plates_that_fail()[name]
    if plate is None:
        rig.plate_source.plates.pop(SAM)
    else:
        rig.plate_source.plates[SAM] = plate
    body = _ok(rig.ask("What is on my plate?"))
    assert (body["outcome"], body["decided_by"], body["text"]) == ("failed", "rules", DECLINES["failed"])
    assert body["sources"] == [] and body["ui_action"] is None and body["cost"]["model_calls"] == 0
    evs, records = _check_events(rig, body)
    assert [r["kind"] for r in records] == ["channel_in", "channel_out"]
    assert "assistant.plate_unavailable" in rig.logs()
    assert decider.calls == 0, "steps 6 to 8 are skipped"
    assert_no_leak(rig.surfaces(archive=False), ["What is on my plate", "Send the quote"])


def test_FR_PA_13_a_plate_builder_that_raises_is_logged_by_code_and_the_message_stays_out_of_the_logs(rig_factory):
    class Boom:
        def build(self, user, now):
            raise RuntimeError("PRIYA-PRIVATE-1 detail that must not be logged")

    rig = rig_factory()
    rig.plate_source = Boom()
    body = _ok(rig.ask("What is on my plate?"))
    assert body["outcome"] == "failed" and "assistant.plate_unavailable" in rig.logs()
    assert_no_leak({"logs": rig.logs(), "body": json.dumps(body)}, ["PRIYA-PRIVATE-1", "detail that must not"])


def test_FR_PA_13_an_unexpected_error_inside_the_answer_is_failed_and_logged_by_type_only(rig_factory):
    def explode(ask):
        raise RuntimeError("SECRET-MESSAGE PRIYA-PRIVATE-2 must stay out")

    rig = rig_factory(decider=ScriptedDecider(default=explode))
    body = _ok(rig.ask(UNMATCHED))
    assert (body["outcome"], body["text"], body["decided_by"]) == ("failed", DECLINES["failed"], "rules")
    _check_events(rig, body)
    assert "RuntimeError" in rig.logs()
    assert_no_leak(rig.surfaces(archive=False), ["SECRET-MESSAGE", "PRIYA-PRIVATE-2", UNMATCHED])


def test_FR_PA_13_a_desk_id_held_by_another_persons_world_refuses_cleanly(rig_factory):
    from tilo_api.deps import WorldRecord  # noqa: PLC0415

    rig = rig_factory()
    rig.store.worlds[desk_ids(SAM)[0]] = WorldRecord(owner=PRIYA, districts={})
    response = rig.ask("What is on my plate?")
    assert response.status_code == 503
    assert rig.all_events() == [] and rig.archive.lines.lines == {}


def test_FR_PA_13_the_desk_world_is_made_once_per_person_with_the_person_as_owner(rig_factory):
    rig = rig_factory()
    for _ in range(3):
        _ok(rig.ask("What is on my plate?"))
    world_id, run_id = desk_ids(SAM)
    record = rig.store.worlds[world_id]
    assert (record.owner, record.run_id, dict(record.districts)) == (SAM, run_id, {})
    assert [w for w in rig.store.worlds if w.startswith("w_desk_")] == [world_id]
    assert [e["seq"] for e in rig.events()] == [1, 2, 3, 4, 5, 6], "seq strictly increasing"
    assert conforms("common.schema.json#/$defs/world_id", world_id) and conforms(
        "common.schema.json#/$defs/run_id", run_id
    )


def _desk_lock(desk, store, user):
    """The spec writes `desk.lock(user)` and also says the lock is kept on the Store: accept either signature."""
    return desk.lock(store, user) if len(inspect.signature(desk.lock).parameters) >= 2 else desk.lock(user)


def test_FR_PA_13_the_desk_helper_ids_and_one_lock_per_person(world):
    desk = mod("tilo_api.desk")
    first = desk.ensure_desk(world.store, org_id=ORG, user=SAM)
    again = desk.ensure_desk(world.store, org_id=ORG, user=SAM)
    assert (first.world_id, first.run_id) == desk_ids(SAM) == (again.world_id, again.run_id)
    lock = _desk_lock(desk, world.store, SAM)
    assert lock is _desk_lock(desk, world.store, SAM) and lock is not _desk_lock(desk, world.store, PRIYA)
    assert isinstance(lock, type(threading.Lock()))
    if len(inspect.signature(desk.lock).parameters) >= 2:
        assert lock is not _desk_lock(desk, build_world().store, SAM), "the lock lives on the Store instance"


# --------------------------------------------------------------------------------------------- concurrency
def test_FR_PA_13_concurrent_questions_from_one_person_keep_a_valid_archive_chain_and_ordered_events(rig_factory):
    rig = rig_factory()
    rig.writer = LockedEventWriter(rig.store)
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(lambda _: rig.ask("What is on my plate?"), range(16)))
    assert all(r.status_code == 200 for r in responses)
    evs, records = rig.events(), rig.archive_records()
    assert len(evs) == 32 and len(records) == 32
    assert verify_chain(records) == [] and [r["seq"] for r in records] == list(range(1, 33))
    assert [e["seq"] for e in evs] == list(range(1, 33))
    order = {}
    for position, e in enumerate(evs):
        order.setdefault(e["data"]["conversation_id"], []).append((position, e["type"]))
    assert len(order) == 16
    for pairs in order.values():
        assert [t for _, t in pairs] == ["assistant.asked", "assistant.replied"] and pairs[0][0] < pairs[1][0]
    assert [w for w in rig.store.worlds if w.startswith("w_desk_")] == [desk_ids(SAM)[0]]


# --------------------------------------------------------------------------------------------- replay-only
def test_FR_PA_19_replay_only_answers_by_rules_and_never_calls_the_model(rig_factory):
    decider = ScriptedDecider(model_decision("intent", intent="plate", credits=0.5))
    rig = rig_factory(decider=decider)
    rig.flags.set("replay_only", True, reason="NFR-24 test")
    unmatched = _ok(rig.ask(UNMATCHED))
    assert (unmatched["outcome"], unmatched["decided_by"], unmatched["text"]) == (
        "declined",
        "rules",
        DECLINES["rules_only"],
    )
    assert _ok(rig.ask(QUESTIONS[0]["text"]))["outcome"] == "answered"
    assert _ok(rig.ask("Open settings"))["outcome"] == "navigated"
    assert decider.calls == 0 and unmatched["cost"]["model_calls"] == 0
    rig.flags.set("replay_only", False, reason="NFR-24 test")
    assert _ok(rig.ask(UNMATCHED))["decided_by"] == "model" and decider.calls == 1


def test_FR_PA_19_with_no_decider_wired_an_unmatched_question_is_declined_unknown(rig_factory):
    rig = rig_factory(decider=None)
    body = _ok(rig.ask(UNMATCHED))
    assert (body["outcome"], body["decided_by"], body["text"]) == ("declined", "rules", DECLINES["unknown"])


# --------------------------------------------------------------------------------------------- the decision table
def _decided(choice, **kw):
    return decision(choice, **kw)


DECISION_CASES = {
    "decline": (lambda: model_decision("decline"), "declined", "model", DECLINES["unknown"]),
    "dropped": (lambda: model_decision("dropped"), "declined", "model", DECLINES["dropped"]),
    "unavailable": (lambda: _decided("unavailable"), "declined", "rules", DECLINES["rules_only"]),
    "budget": (lambda: _decided("budget"), "declined", "rules", DECLINES["budget"]),
    "flagged": (lambda: _decided("flagged"), "declined", "rules", DECLINES["flagged"]),
}


@pytest.mark.parametrize("name", sorted(DECISION_CASES))
def test_FR_PA_14_each_model_choice_maps_to_one_fixed_outcome_and_text(rig_factory, name):
    make, outcome, decided_by, text = DECISION_CASES[name]
    rig = rig_factory(decider=ScriptedDecider(make()))
    body = _ok(rig.ask(UNMATCHED))
    assert (body["outcome"], body["decided_by"], body["text"]) == (outcome, decided_by, text)
    assert body["sources"] == [] and body["ui_action"] is None
    called = name in ("decline", "dropped")
    _check_events(rig, body, actor="A_assistant" if called else "system")
    assert len(rig.archive_records()) == (3 if called else 2)


def test_FR_PA_14_a_model_that_picks_a_fact_intent_gets_the_template_answer_and_the_model_trace(rig_factory):
    decider = ScriptedDecider(model_decision("intent", intent="pins", credits=0.25))
    rig = rig_factory(decider=decider)
    body = _ok(rig.ask(UNMATCHED))
    want = expected_facts("pins", plate_s1()["rows"])
    assert (body["outcome"], body["decided_by"], body["cached"]) == ("answered", "model", False)
    assert body_lines(body) == want.lines
    assert body["cost"] == {"model_calls": 1, "credits": 0.25, "saved_credits": 0.0}
    evs, records = _check_events(rig, body, actor="A_assistant")
    assert [r["kind"] for r in records] == ["channel_in", "model_call", "channel_out"]
    call = records[1]["payload"]
    assert call == {
        "conversation_id": body["conversation_id"],
        "role": "assistant",
        "profile": "ast-main",
        "prompt": "PROMPT-TEXT",
        "output": "RAW-REPLY-TEXT",
        "tokens_in": 120,
        "tokens_out": 12,
    }
    assert evs[1]["trace"] == {
        "model_role": "assistant",
        "profile": "ast-main",
        "tokens_in": 120,
        "tokens_out": 12,
        "tool": None,
        "latency_ms": 7,
        "archive_ref": f"{desk_ids(SAM)[1]}/2",
    }
    assert evs[1]["credits"] == 0.25


def test_FR_PA_19_a_cache_hit_has_no_model_call_no_trace_and_one_memory_hit_with_the_saving(rig_factory):
    cached = model_decision(
        "intent",
        intent="plate",
        cached=True,
        model_calls=0,
        saved=0.3,
        profile=None,
        tokens_in=None,
        tokens_out=None,
        latency_ms=None,
        prompt=None,
        raw=None,
    )
    rig = rig_factory(decider=ScriptedDecider(cached))
    body = _ok(rig.ask(UNMATCHED))
    assert body["cached"] is True and body["decided_by"] == "model"
    assert body["cost"] == {"model_calls": 0, "credits": 0.0, "saved_credits": 0.3}
    evs, records = _check_events(rig, body, actor="A_assistant", extra_events=1)
    assert [r["kind"] for r in records] == ["channel_in", "channel_out"], "a cache hit makes no model_call record"
    assert set(evs[1]["trace"].values()) == {None}
    hit = evs[2]
    assert (hit["type"], hit["actor"], hit["target"], hit["credits"], hit["cause"]) == (
        "memory.hit",
        "A_assistant",
        SAM,
        0,
        evs[1]["id"],
    )
    assert hit["data"] == {"origin_cost": 0.3, "lookup_cost": 0, "saved": 0.3}
    assert hit["summary"] == "The assistant reused an earlier answer." and set(hit["trace"].values()) == {None}
    assert hit["world_id"] == desk_ids(SAM)[0] and hit["vis"] == "all"


def test_FR_PA_19_a_cache_hit_that_saved_nothing_writes_no_memory_hit(rig_factory):
    rig = rig_factory(decider=ScriptedDecider(model_decision("decline", cached=True, model_calls=0, saved=0.0)))
    body = _ok(rig.ask(UNMATCHED))
    assert body["cached"] is True
    assert [e["type"] for e in rig.events()] == ["assistant.asked", "assistant.replied"]


# --------------------------------------------------------------------------------------------- A14-1: 30 intents
def _expected_opening(intent):
    route = intent["expect"]["route"]
    screen = ANSWER["target_screens"].get(route) or {r["route"]: r["describe"] for r in RAW["navigate"]}[route]
    return string.Template(ANSWER["opening"]).substitute(screen=screen)


@pytest.mark.parametrize("intent", INTENTS, ids=lambda i: f"i{i['n']:02d}_{i['by']}")
def test_FR_PA_14_A14_1_each_of_30_intents_navigates_to_exactly_the_expected_document(rig_factory, intent):
    want = intent_expected(intent)
    by_model = intent["by"] == "model"
    decider = ScriptedDecider(default=model_decision("navigate", action=want, credits=0.1) if by_model else None)
    rig = rig_factory(decider=decider)
    body = _ok(rig.ask(intent["text"], **intent_context(intent)))
    assert body["outcome"] == "navigated" and body["ui_action"] == want, intent["text"]
    assert conforms("ui_action.schema.json", body["ui_action"])
    assert body["decided_by"] == ("model" if by_model else "rules")
    assert decider.calls == (1 if by_model else 0)
    assert body["cost"]["model_calls"] == (1 if by_model else 0)
    target = want["target"]
    assert body["lines"] == [{"text": _expected_opening(intent), "source": target}]
    assert body["sources"] == ([target] if target else [])
    _check_events(rig, body, actor="A_assistant" if by_model else "system")


def test_FR_PA_14_A14_1_at_least_27_of_30_intents_need_no_model_call(rig_factory):
    decider = ScriptedDecider(default=lambda ask: model_decision("decline"))
    rig = rig_factory(decider=decider)
    rules = 0
    for intent in INTENTS:
        body = _ok(rig.ask(intent["text"], **intent_context(intent)))
        rules += body["decided_by"] == "rules" and body["outcome"] == "navigated"
    assert rules >= 27 and decider.calls == 30 - rules
    assert rules == 28, "with config/assistant.yaml: intents 27 and 28 match no rule"


def test_FR_PA_14_the_menu_a_model_is_shown_carries_the_plate_rows_and_the_selection_only(rig_factory):
    decider = ScriptedDecider(model_decision("decline"))
    rig = rig_factory(decider=decider)
    _ok(rig.ask(UNMATCHED, record="mt_samsync1", route="/meetings/mt_samsync1"))
    ask = decider.asks[0]
    assert (ask.user, ask.org_id, ask.now, ask.screen) == (SAM, ORG, NOW, "meeting")
    assert (ask.context.kind, ask.context.id) == ("meeting", "mt_samsync1")
    assert ask.menu.context is not None and ask.menu.context.ref == ask.context
    row_refs = {(r.ref.kind, r.ref.id) for r in ask.menu.rows}
    assert ("work_item", "wi_budget_notes") in row_refs and ("card", C_GATE) in row_refs
    assert not any("priya" in r.ref.id for r in ask.menu.rows)
    assert len(ask.menu.rows) <= 40 and len(ask.menu.fingerprint) == 64
    assert {(r.kind, r.id) for r in ask.menu.refs} == row_refs | {("meeting", "mt_samsync1")}
    assert ask.plate_fingerprint == plate_s1()["fingerprint"]
    assert ask.question == UNMATCHED


# ------------------------------------------------------------------------- A14-3 (actions), A14-4/5/6
def _fuzzed_actions():
    """The actions of the fuzzed replies that carry one. A reply with DUPLICATE keys is left out here: read as plain
    JSON (last key wins) its action is a valid navigate, and only `parse_decision` (slice 3) can drop such a reply.
    The 200 fuzzed REPLIES, duplicate keys included, run through the real Router in test_PPL_11b_3 (A14-3)."""
    out = []
    for category, text in fuzz_replies():
        try:
            pairs = json.loads(text, object_pairs_hook=lambda p: p)
            value = json.loads(text)
        except (ValueError, RecursionError):
            continue
        try:
            if _has_duplicate_keys(pairs):
                continue
        except RecursionError:
            continue
        if isinstance(value, dict) and value.get("choice") == "navigate" and "action" in value and len(value) == 2:
            out.append((category, value["action"]))
    return out


def _has_duplicate_keys(node):
    if isinstance(node, list) and node and all(isinstance(p, tuple) and len(p) == 2 for p in node):
        keys = [k for k, _ in node]
        return len(set(keys)) != len(keys) or any(_has_duplicate_keys(v) for _, v in node)
    if isinstance(node, list):
        return any(_has_duplicate_keys(v) for v in node)
    return False


def test_FR_PA_14_A14_3_every_fuzzed_action_a_model_could_return_is_dropped_with_nothing_executed(rig_factory):
    actions = _fuzzed_actions()
    assert len(actions) >= 95
    it = iter(actions)
    decider = ScriptedDecider(default=lambda ask: model_decision("navigate", action=next(it)[1]))
    rig = rig_factory(decider=decider)
    before = rig.world.snapshot()
    writes_before = len([c for c in rig.world.log if c[1] in {"create", "replace", "delete"}])
    for category, _ in actions:
        response = rig.ask(UNMATCHED)
        assert response.status_code == 200, category
        body = response.json()
        assert (body["outcome"], body["text"], body["ui_action"], body["decided_by"]) == (
            "declined",
            DECLINES["dropped"],
            None,
            "model",
        ), category
    assert rig.world.snapshot() == before
    assert len([c for c in rig.world.log if c[1] in {"create", "replace", "delete"}]) == writes_before
    types = [e["type"] for e in rig.all_events()]
    assert types == ["assistant.asked", "assistant.replied"] * len(actions), "nothing but the two events per request"
    assert not [t for t in types if t.startswith(("mention.", "work_item.", "pinboard.", "calendar."))]


def test_FR_PA_14_A14_4_a_navigate_is_executed_only_for_a_menu_row_on_the_route_that_opens_it(rig_factory):
    target = {"kind": "work_item", "id": "wi_rate_sheet"}
    cases = [
        ("a menu row on its own route", navigate_to("plate", target), True),
        ("a team pin on its team route", navigate_to("pinboard_team", {"kind": "pin", "id": "pb_kickoff"}), True),
        ("a card on the cards route", navigate_to("cards", {"kind": "card", "id": C_GATE}), True),
        ("a world on the world route", navigate_to("world", {"kind": "world", "id": W_LAUNCH}), True),
        ("the calendar row", navigate_to("calendar", {"kind": "calendar_entry", "id": "ce_plan1"}), True),
        ("a screen with no target", navigate_to("autonomy"), True),
        (
            "route and target kind disagree (a meeting Sam owns)",
            navigate_to("plate", {"kind": "meeting", "id": "mt_samsync1"}),
            False,
        ),
        (
            "a team pin on the personal route",
            navigate_to("pinboard_personal", {"kind": "pin", "id": "pb_kickoff"}),
            False,
        ),
        (
            "a readable record that is not on the menu",
            navigate_to("plate", {"kind": "work_item", "id": "wi_s2_01"}),
            False,
        ),
        (
            "a readable meeting that is not on the menu",
            navigate_to("meeting", {"kind": "meeting", "id": "mt_samsync1"}),
            False,
        ),
        (
            "Sam's personal pin, which is not on the plate",
            navigate_to("pinboard_personal", {"kind": "pin", "id": "pb_sam_personal"}),
            False,
        ),
        ("someone else's work item", navigate_to("plate", {"kind": "work_item", "id": "wi_priya_1"}), False),
        (
            "someone else's personal pin",
            navigate_to("pinboard_personal", {"kind": "pin", "id": "pb_priya_personal"}),
            False,
        ),
        ("someone else's meeting", navigate_to("meeting", {"kind": "meeting", "id": "mt_priya1"}), False),
        ("someone else's world", navigate_to("world", {"kind": "world", "id": W_PRIYA}), False),
        ("a screen that takes no target, given one", navigate_to("worlds", {"kind": "world", "id": W_LAUNCH}), False),
    ]
    for label, action, ok in cases:
        rig = rig_factory(decider=ScriptedDecider(model_decision("navigate", action=action)))
        body = _ok(rig.ask(UNMATCHED))
        if ok:
            assert (body["outcome"], body["ui_action"], body["decided_by"]) == ("navigated", action, "model"), label
        else:
            assert (body["outcome"], body["text"], body["ui_action"]) == ("declined", DECLINES["dropped"], None), label


def test_FR_PA_14_A14_4_the_selected_record_is_a_legal_target_and_nothing_else_off_the_plate_is(rig_factory):
    action = navigate_to("meeting", {"kind": "meeting", "id": "mt_samsync1"})
    selected = rig_factory(decider=ScriptedDecider(model_decision("navigate", action=action)))
    assert _ok(selected.ask(UNMATCHED, record="mt_samsync1", route="/plate"))["outcome"] == "navigated"
    unselected = rig_factory(decider=ScriptedDecider(model_decision("navigate", action=action)))
    assert _ok(unselected.ask(UNMATCHED))["text"] == DECLINES["dropped"]


def test_FR_PA_14_A14_5_a_row_that_becomes_unreadable_between_the_menu_and_the_vet_is_dropped(world):
    gate_mod = mod("tilo_api.assistant.gate")
    state = {"armed": False}

    class FlippingGate(gate_mod.RefGate):
        def allows(self, ref):
            return False if state["armed"] else super().allows(ref)

    action = navigate_to("plate", {"kind": "work_item", "id": "wi_rate_sheet"})
    control = run_answer(
        world, plate_s1(), UNMATCHED, decider=ScriptedDecider(model_decision("navigate", action=action))
    )
    assert control.outcome == "navigated" and control.ui_action == action
    flipping = ScriptedDecider(
        model_decision("navigate", action=action), on_decide=lambda ask: state.update(armed=True)
    )
    answer = run_answer(
        world, plate_s1(), UNMATCHED, decider=flipping, gate=make_gate(world, plate_s1(), gate_cls=FlippingGate)
    )
    assert (answer.outcome, answer.decided_by, answer.decline, answer.ui_action) == (
        "declined",
        "model",
        "dropped",
        None,
    )
    assert lines_of(answer) == [(DECLINES["dropped"], None)]


def test_FR_PA_14_A14_6_open_this_with_no_readable_selection_is_declined_no_selection(rig_factory):
    decider = ScriptedDecider()
    rig = rig_factory(decider=decider)
    body = _ok(rig.ask("Open this"))
    assert (body["outcome"], body["decided_by"], body["text"]) == ("declined", "rules", DECLINES["no_selection"])
    assert body["ui_action"] is None and body["sources"] == [] and decider.calls == 0
    _check_events(rig, body)


@pytest.mark.parametrize("text", ["Open this", "Show it", "Take me there", "Open this task", "open the selected one"])
def test_FR_PA_14_the_context_words_need_a_selection_and_never_guess_one(rig_factory, text):
    rig = rig_factory(decider=ScriptedDecider())
    body = _ok(rig.ask(text))
    assert body["text"] == DECLINES["no_selection"] and body["ui_action"] is None


# ---------------------------------------------------------------------------- navigation module units
def test_FR_PA_14_route_targets_pin_which_target_kinds_open_on_which_route():
    nav = mod("tilo_api.assistant.navigation")
    want = {
        "plate": {"work_item", None},
        "calendar": {"calendar_entry", None},
        "meetings": {None},
        "meeting": {"meeting"},
        "pinboard_team": {"pin", None},
        "pinboard_personal": {"pin", None},
        "worlds": {None},
        "world": {"world"},
        "cards": {"card", None},
        "connections": {None},
        "channels": {None},
        "autonomy": {None},
        "settings": {None},
    }
    assert {k: set(v) for k, v in nav.ROUTE_TARGETS.items()} == want
    schema = pathlib.Path(__file__).resolve().parents[3] / "contracts" / "ui_action.schema.json"
    assert set(nav.ROUTE_TARGETS) == set(json.loads(schema.read_text(encoding="utf-8"))["$defs"]["route"]["enum"])


ROUTE_FOR = [
    (("work_item", "wi_budget_notes"), "plate", {"kind": "work_item", "id": "wi_budget_notes"}),
    (("calendar_entry", "ce_plan1"), "calendar", {"kind": "calendar_entry", "id": "ce_plan1"}),
    (("meeting", "mt_samsync1"), "meeting", {"kind": "meeting", "id": "mt_samsync1"}),
    (("world", W_LAUNCH), "world", {"kind": "world", "id": W_LAUNCH}),
    (("card", C_GATE), "cards", {"kind": "card", "id": C_GATE}),
    (("pinboard_item", "pb_kickoff"), "pinboard_team", {"kind": "pin", "id": "pb_kickoff"}),
    (("pinboard_item", "pb_sam_personal"), "pinboard_personal", {"kind": "pin", "id": "pb_sam_personal"}),
    (("mail", MAIL_ID), "plate", None),
]


@pytest.mark.parametrize(("ref", "route", "target"), ROUTE_FOR, ids=[r[0][0] for r in ROUTE_FOR])
def test_FR_PA_14_route_for_names_the_one_route_that_opens_a_readable_ref(world, ref, route, target):
    nav, gate_mod = mod("tilo_api.assistant.navigation"), mod("tilo_api.assistant.gate")
    gate = make_gate(world, plate_s1())
    assert nav.route_for(gate_mod.Ref(*ref), gate) == {"kind": "navigate", "route": route, "target": target}


@pytest.mark.parametrize(
    "ref",
    [
        ("work_item", "wi_priya_1"),
        ("pinboard_item", "pb_priya_personal"),
        ("meeting", "mt_priya1"),
        ("world", W_PRIYA),
        ("card", ulid(999)),
        ("mail", "msg_other"),
        ("event", C_GATE),
        ("mention", "mn_sam1"),
        ("person", SAM),
        ("work_item", "wi_nowhere"),
    ],
)
def test_FR_PA_17_route_for_gives_none_for_a_ref_the_gate_refuses(world, ref):
    nav, gate_mod = mod("tilo_api.assistant.navigation"), mod("tilo_api.assistant.gate")
    assert nav.route_for(gate_mod.Ref(*ref), make_gate(world, plate_s1())) is None


def test_FR_PA_14_vet_navigate_returns_a_copy_only_for_a_conforming_menu_row(world):
    nav, gate_mod = mod("tilo_api.assistant.navigation"), mod("tilo_api.assistant.gate")
    decider = ScriptedDecider(model_decision("decline"))
    gate = make_gate(world, plate_s1())
    run_answer(world, plate_s1(), UNMATCHED, decider=decider, gate=gate)
    menu = decider.asks[0].menu
    good = navigate_to("plate", {"kind": "work_item", "id": "wi_rate_sheet"})
    vetted = nav.vet_navigate(good, menu, gate)
    assert vetted == good and vetted is not good and vetted["target"] is not good["target"]
    for bad in (
        None,
        "navigate",
        5,
        [],
        {},
        navigate_to("plate", {"kind": "work_item", "id": "wi_s2_01"}),
        {**good, "extra": 1},
        {"kind": "mark_done", "work_item_id": "wi_rate_sheet"},
        navigate_to("pinboard_personal", {"kind": "pin", "id": "pb_kickoff"}),
    ):
        assert nav.vet_navigate(bad, menu, gate) is None, bad
    assert gate_mod.Ref("work_item", "wi_rate_sheet") in menu.refs


MATCH_CASES = [
    ("open the calendar", None, ("calendar", None)),
    ("show my plate", None, ("plate", None)),
    ("take me to the pinboard", None, ("pinboard_team", None)),
    ("open this", ("meeting", "mt_samsync1"), ("meeting", {"kind": "meeting", "id": "mt_samsync1"})),
    ("show the meeting minutes", ("work_item", "wi_budget_notes"), ("meetings", None)),  # context is not a meeting
    ("show the meeting minutes", ("meeting", "mt_samsync1"), ("meeting", {"kind": "meeting", "id": "mt_samsync1"})),
    ("open the budget notes", None, ("plate", {"kind": "work_item", "id": "wi_budget_notes"})),
    ("go to the calendar", ("work_item", "wi_budget_notes"), ("calendar", None)),  # a with_context only for its kind
]


@pytest.mark.parametrize(("text", "context", "want"), MATCH_CASES)
def test_FR_PA_14_match_navigation_resolves_phrases_the_selection_and_titles(world, text, context, want):
    nav, gate_mod, words = (
        mod("tilo_api.assistant.navigation"),
        mod("tilo_api.assistant.gate"),
        mod("tilo_api.assistant.words"),
    )
    config = mod("tilo_api.assistant.config").load_assistant_config()
    plate, gate = plate_s1(), make_gate(world, plate_s1())
    ctx = gate_mod.Ref(*context) if context else None
    got = nav.match_navigation(words.question_key(text), plate["rows"], ctx, gate, config)
    assert got is not None and got.decline is None
    route, target = want
    assert got.action == {"kind": "navigate", "route": route, "target": target}


@pytest.mark.parametrize(
    "text",
    [
        "what is on my plate",
        "open",
        "open the",
        "open the on",
        "open the 3pm",
        "open the share",
        "show me what is overdue",
        "navigate",
        "switch",
        "i want to open settings",
        "open the nothing at all",
    ],
)
def test_FR_PA_14_match_navigation_says_nothing_when_no_rule_is_sure(world, text):
    nav, words = mod("tilo_api.assistant.navigation"), mod("tilo_api.assistant.words")
    config = mod("tilo_api.assistant.config").load_assistant_config()
    plate = plate_s1()
    assert nav.match_navigation(words.question_key(text), plate["rows"], None, make_gate(world, plate), config) is None


def test_FR_PA_14_two_rows_that_both_fit_the_title_words_are_never_guessed_between(rig_factory):
    rig = rig_factory(decider=None)
    body = _ok(rig.ask("Open the share"))  # "Share the budget notes" and "Share the rate sheet with Acme"
    assert body["outcome"] == "declined" and body["ui_action"] is None


def test_FR_PA_14_a_word_of_two_letters_alone_never_selects_a_row(rig_factory):
    rig = rig_factory(decider=None)
    assert _ok(rig.ask("Open the ab"))["ui_action"] is None


# --------------------------------------------------------------------------------------------- FR-PA-17 panel cases
OTHER_PERSON_PHRASES = [
    "What is on Priya's plate?",
    "Show her calendar",
    "what is her plate",
    "What does Omar's calendar look like",
    "Open Priya's board",
    "What's on his plate",
    "show my manager's calendar",
    "Tell me about everyone's tasks",
    "what is on Priya" + chr(0x2019) + "s plate",
    "WHAT IS ON PRIYA'S PLATE",
]


@pytest.mark.parametrize("text", OTHER_PERSON_PHRASES)
def test_FR_PA_17_EP_2_a_question_about_another_person_gets_the_one_fixed_refusal_and_looks_nothing_up(
    rig_factory, monkeypatch, text
):
    spy = AccessSpy(monkeypatch)
    decider = ScriptedDecider()
    rig = rig_factory(decider=decider)
    body = _ok(rig.ask(text))
    assert (body["outcome"], body["decided_by"], body["text"]) == ("declined", "rules", DECLINES["other_person"])
    assert body["sources"] == [] and body["ui_action"] is None and decider.calls == 0
    assert {r.record["id"] for r in spy.all_requests()} <= {SAM}, "nothing but the asker's own record was read"
    _check_events(rig, body)
    assert_no_leak(rig.surfaces(), [*SENTINELS, "Priya Nair"])


def _ep1_variant(name):
    world = build_world()
    if name in ("no_priya", "priya_other_org"):
        erase_person(world.stores, ORG, PRIYA)
        if name == "priya_other_org":
            world.stores.persons.create(person(PRIYA, "Priya Nair", org=OTHER_ORG))
    return world


@pytest.mark.parametrize("variant", ["teammate_with_open_items", "no_priya", "priya_other_org", "askers_own_name"])
def test_FR_PA_17_EP_1_what_is_on_priyas_plate_gives_identical_bodies_whatever_exists(
    rig_factory, monkeypatch, variant
):
    spy = AccessSpy(monkeypatch)
    rig = rig_factory(world=_ep1_variant(variant), decider=ScriptedDecider())
    text = "What is on Sam's plate?" if variant == "askers_own_name" else "What is on Priya's plate?"
    body = _ok(rig.ask(text))
    reference = _ok(rig_factory(world=build_world(), decider=ScriptedDecider()).ask("What is on Priya's plate?"))
    _identical(body, reference)
    assert (body["outcome"], body["text"], body["sources"]) == ("declined", DECLINES["other_person"], [])
    assert rig.decider.calls == 0
    assert not [r for r in spy.all_requests() if r.record["id"] in (PRIYA, "wi_priya_1", "wi_priya_2", "wi_priya_3")]
    evs, _ = _check_events(rig, body)
    assert evs[1]["data"]["sources"] == [] and evs[1]["summary"] == "The assistant declined."
    assert_no_leak(rig.surfaces(), [*SENTINELS, "Priya Nair"])


def test_FR_PA_17_EP_1_the_four_variants_leave_the_same_event_data_apart_from_the_ids(rig_factory):
    seen = []
    for variant in ("teammate_with_open_items", "no_priya", "priya_other_org"):
        rig = rig_factory(world=_ep1_variant(variant))
        rig.ask("What is on Priya's plate?")
        replied = rig.events()[1]
        seen.append({k: v for k, v in replied["data"].items() if k not in ("conversation_id", "message_ref")})
    assert seen[0] == seen[1] == seen[2]


EP3_PAIRS = [
    ("a personal pin of Priya's", {"record": "pb_priya_personal"}, {"record": "pb_nowhere"}),
    ("a work item of Priya's", {"record": "wi_priya_1"}, {"record": "wi_nowhere"}),
    ("a meeting of Priya's", {"record": "mt_priya1"}, {"record": "mt_nowhere"}),
    ("a calendar entry of Priya's", {"record": "ce_priya_private"}, {"record": "ce_nowhere"}),
    ("a proposed item for Sam from Priya's minutes", {"record": "wi_sam_proposed"}, {"record": "wi_nowhere"}),
    ("the path of Priya's meeting", {"route": "/meetings/mt_priya1"}, {"route": "/meetings/mt_nowhere"}),
    ("the path of Priya's world", {"route": f"/world/{W_PRIYA}"}, {"route": "/world/w_nowhere"}),
]


@pytest.mark.parametrize(("what", "refused_kw", "nowhere_kw"), EP3_PAIRS, ids=[p[0] for p in EP3_PAIRS])
def test_FR_PA_17_EP_3_open_this_on_someone_elses_record_is_the_same_answer_as_on_a_record_that_exists_nowhere(
    rig_factory, what, refused_kw, nowhere_kw
):
    refused = rig_factory(decider=ScriptedDecider())
    nowhere = rig_factory(decider=ScriptedDecider())
    a, b = _ok(refused.ask("Open this", **refused_kw)), _ok(nowhere.ask("Open this", **nowhere_kw))
    assert (a["outcome"], a["text"], a["ui_action"]) == ("declined", DECLINES["no_selection"], None), what
    _identical(a, b)
    skip = ("conversation_id", "message_ref")
    assert {k: v for k, v in refused.events()[1]["data"].items() if k not in skip} == {
        k: v for k, v in nowhere.events()[1]["data"].items() if k not in skip
    }
    assert refused.decider.calls == 0
    assert_no_leak(refused.surfaces(archive=False), SENTINELS)


def test_FR_PA_17_EP_3_a_model_navigate_to_someone_elses_personal_pin_is_the_same_as_to_a_pin_that_exists_nowhere(
    rig_factory,
):
    def attempt(pin_id):
        action = navigate_to("pinboard_personal", {"kind": "pin", "id": pin_id})
        rig = rig_factory(decider=ScriptedDecider(model_decision("navigate", action=action)))
        return rig, _ok(rig.ask(UNMATCHED))

    refused_rig, refused = attempt("pb_priya_personal")
    nowhere_rig, nowhere = attempt("pb_nowhere")
    assert refused["text"] == DECLINES["dropped"] and refused["ui_action"] is None
    _identical(refused, nowhere)
    assert_no_leak(refused_rig.surfaces(), SENTINELS)
    assert {
        k: v for k, v in refused_rig.events()[1]["data"].items() if k not in ("conversation_id", "message_ref")
    } == {k: v for k, v in nowhere_rig.events()[1]["data"].items() if k not in ("conversation_id", "message_ref")}


def test_FR_PA_17_EP_5_a_person_who_left_the_team_gets_none_of_the_teams_pins(rig_factory):
    decider = ScriptedDecider(default=model_decision("decline"))
    rig = rig_factory(who=principal("u_lena"), plates={"u_lena": plate_lena()}, decider=decider)
    body = _ok(rig.ask("What is pinned for me?"))
    assert (body["outcome"], body["decided_by"], body["text"]) == ("declined", "rules", "No pins need you.")
    assert body["sources"] == [] and decider.calls == 0
    _check_events(rig, body, user="u_lena")
    open_it = _ok(rig.ask("Open the kickoff checklist"))
    assert open_it["outcome"] == "declined" and open_it["ui_action"] is None, "a refused row's title resolves nothing"
    assert decider.calls == 1 and decider.asks[0].menu.rows == (), "and the model is not offered the pin either"
    assert "assistant.plate_row_refused pinboard_item" in rig.logs()
    assert_no_leak(rig.surfaces(user="u_lena", archive=False), ["pb_kickoff", "Kickoff checklist"])


def test_FR_PA_17_EP_5_a_member_resolves_the_same_title_a_leaver_cannot(rig_factory):
    rig = rig_factory(decider=ScriptedDecider())
    body = _ok(rig.ask("Open the kickoff checklist"))
    assert body["ui_action"] == navigate_to("pinboard_team", {"kind": "pin", "id": "pb_kickoff"})


def test_FR_PA_17_a_viewer_who_leaves_the_team_mid_session_loses_its_pins_at_once(rig_factory):
    rig = rig_factory(decider=ScriptedDecider(default=model_decision("decline")))
    first = _ok(rig.ask("What is pinned for me?"))
    assert first["outcome"] == "answered" and len(first["sources"]) == 3
    sam = rig.world.stores.persons.get(ORG, SAM)
    rig.world.stores.persons.replace({**sam.record, "memberships": []}, expected_version=sam.version)
    second = _ok(rig.ask("What is pinned for me?"))
    assert (second["outcome"], second["text"], second["sources"]) == ("declined", "No pins need you.", [])
    nav = _ok(rig.ask("Open the kickoff checklist"))
    assert nav["ui_action"] is None
    assert_no_leak(
        {"body": second["text"] + nav["text"]}, ["Kickoff checklist", "Vendor review checklist", FLAGGED_TITLE]
    )
    menu_ask = rig.decider
    _ok(rig.ask(UNMATCHED))
    menu = menu_ask.asks[-1].menu
    assert not [r for r in menu.rows if r.ref.kind == "pinboard_item"], "no gated-out pin is offered to the model"


def test_FR_PA_17_EP_6_the_calendar_answer_holds_only_the_askers_own_rows(rig_factory, monkeypatch):
    spy = AccessSpy(monkeypatch)
    rig = rig_factory(decider=ScriptedDecider(model_decision("decline")))
    body = _ok(rig.ask("What is on my calendar today?"))
    assert body_lines(body) == expected_facts("calendar_today", plate_s1()["rows"]).lines
    assert_no_leak(rig.surfaces(), [PRIYA_TITLES["ce_priya_private"], PRIYA_TITLES["ce_priya_shared"], "ce_priya_"])
    for request in spy.all_requests():
        assert request.record["id"] not in ("ce_priya_private", "ce_priya_shared")
    asked = rig.decider
    _ok(rig.ask(UNMATCHED))
    assert_no_leak(
        {"menu": repr(asked.asks[0].menu)}, [PRIYA_TITLES["ce_priya_private"], PRIYA_TITLES["ce_priya_shared"]]
    )


def test_FR_PA_17_EP_7_a_plate_builder_bug_never_names_another_persons_rows(rig_factory, monkeypatch):
    spy = AccessSpy(monkeypatch)
    decider = ScriptedDecider(default=model_decision("decline"))
    rig = rig_factory(plates={SAM: plate_buggy()}, decider=decider)
    answered = []
    for q in (
        "What is on my plate?",
        "What is pinned for me?",
        "What changed since yesterday?",
        "What is waiting for me?",
        "How are my tasks going?",
        "Open the PRIYA-PRIVATE-5 proposed team pin",
        "Open the PRIYA-PRIVATE-4 personal board note",
    ):
        body = _ok(rig.ask(q))
        answered.append(body)
        assert not [
            s
            for s in body["sources"]
            if s["id"] in ("pb_priya_personal", "pb_priya_proposed", "wi_sam_proposed", "wi_priya_1")
        ], q
        assert (
            body["ui_action"] is None
            or body["ui_action"]["target"] is None
            or body["ui_action"]["target"]["id"]
            not in ("pb_priya_personal", "pb_priya_proposed", "wi_sam_proposed", "wi_priya_1")
        )
    _ok(rig.ask(UNMATCHED))
    menu = decider.asks[-1].menu
    refused = {"pb_priya_personal", "pb_priya_proposed", "wi_sam_proposed", "wi_priya_1"}
    assert not [r for r in menu.rows if r.ref.id in refused] and not [r for r in menu.refs if r.id in refused]
    assert_no_leak({"bodies": json.dumps(answered), "menu": repr(menu)}, SENTINELS)
    logs = rig.logs()
    assert "assistant.plate_row_refused pinboard_item" in logs and "assistant.plate_row_refused work_item" in logs
    assert_no_leak({"logs": logs}, [*SENTINELS, "pb_priya"])
    assert {(r.actor, r.action) for r in spy.reads} == {(SAM, "read_full")}


def test_FR_PA_17_EP_8_a_viewer_of_someone_elses_world_reads_only_their_own_tasks(rig_factory):
    viewer = principal(role="viewer", world_id=W_PRIYA)
    rig = rig_factory(who=viewer, decider=ScriptedDecider())
    other = rig_factory(who=viewer, decider=ScriptedDecider())
    here = _ok(rig.ask("How is this going?", route=f"/world/{W_PRIYA}"))
    nowhere = _ok(other.ask("How is this going?", route="/world/w_nowhere"))
    assert [t for t, _ in body_lines(here)] == [
        "Your tasks:",
        "Launch site refresh: blocked",
        "Vendor onboarding: running",
    ]
    _identical(here, nowhere)
    open_here = _ok(rig.ask("Open this", route=f"/world/{W_PRIYA}"))
    open_nowhere = _ok(other.ask("Open this", route="/world/w_nowhere"))
    assert open_here["text"] == DECLINES["no_selection"] and open_here["ui_action"] is None
    _identical(open_here, open_nowhere)
    assert_no_leak(rig.surfaces(archive=False), [W_PRIYA, *SENTINELS])


def test_FR_PA_17_a_world_the_person_owns_is_a_legal_selection(rig_factory):
    rig = rig_factory(decider=ScriptedDecider())
    body = _ok(rig.ask("Open this world", route=f"/world/{W_VENDOR}", record=W_VENDOR))
    assert body["ui_action"] == navigate_to("world", {"kind": "world", "id": W_VENDOR})


# ------------------------------------------------------------------- the people oracle, one org, once
def test_FR_PA_17_every_oracle_request_is_the_signed_in_person_reading_in_full_with_plain_data(
    rig_factory, monkeypatch
):
    from _ppl11b_lib import is_plain  # noqa: PLC0415

    spy = AccessSpy(monkeypatch)
    rig = rig_factory(decider=ScriptedDecider(model_decision("decline")))
    for q in [
        QUESTIONS[0]["text"],
        QUESTIONS[12]["text"],
        "Open the calendar",
        "Open the rate sheet task",
        "What is on Priya's plate?",
        UNMATCHED,
    ]:
        _ok(rig.ask(q))
    _ok(rig.ask("Open this", record="mt_samsync1"))
    assert spy.reads
    for request in [*spy.reads, *spy.decides]:
        assert (request.actor, request.action, request.now) == (SAM, "read_full", NOW)
        assert type(request.actor) is str and type(request.action) is str and is_plain(request.record)
        assert request.actor.startswith("u_") and request.actor != "system"
    assert PRIYA not in {r.record.get("owner") for r in spy.all_requests()}


def test_FR_PA_17_one_org_is_loaded_per_request_and_the_directory_is_built_once(rig_factory, monkeypatch):
    directory_spy = DirectorySpy(monkeypatch)
    rig = rig_factory(decider=ScriptedDecider(model_decision("decline")))
    for n, q in enumerate(
        (QUESTIONS[0]["text"], "Open the rate sheet task", UNMATCHED, "What is on Priya's plate?"), start=1
    ):
        rig.world.reset_log()
        _ok(rig.ask(q))
        assert directory_spy.calls == n, "Directory.of once per request, never per row (about 6 ms per person)"
        lists = [c for c in rig.world.log if c[:2] == ("person", "list")]
        assert len(lists) == 1, "the persons of the org are listed once per request"
        assert {c[2] for c in rig.world.log} == {ORG}, "no lookup names another org"


def test_FR_PA_17_the_panel_writes_no_people_record_and_creates_none(rig_factory):
    rig = rig_factory(decider=ScriptedDecider(model_decision("intent", intent="plate")))
    before = rig.world.snapshot()
    for q in [QUESTIONS[0]["text"], "Open the calendar", UNMATCHED, "What is on Priya's plate?", "Open this"]:
        _ok(rig.ask(q))
    assert rig.world.snapshot() == before
    assert not [c for c in rig.world.log if c[1] in {"create", "replace", "delete"}]
    assert not [e for e in rig.all_events() if not e["type"].startswith(("assistant.", "memory."))]


def test_FR_PA_17_a_failure_to_read_the_org_gives_a_failed_answer_never_an_unchecked_one(rig_factory):
    class Boom:
        kind = "person"

        def list(self, *a, **k):
            raise RuntimeError("PRIYA-PRIVATE-3 store down")

        def get(self, *a, **k):
            raise RuntimeError("PRIYA-PRIVATE-3 store down")

    rig = rig_factory(decider=ScriptedDecider())
    spied = rig.world.spied
    rig.world.spied = type(spied)(
        persons=Boom(),
        meetings=spied.meetings,
        work_items=spied.work_items,
        pins=spied.pins,
        mentions=spied.mentions,
        calendar=spied.calendar,
        world_shares=spied.world_shares,
    )
    body = _ok(rig.ask("What is on my plate?"))
    assert (body["outcome"], body["text"], body["sources"]) == ("failed", DECLINES["failed"], [])
    assert_no_leak(rig.surfaces(), ["PRIYA-PRIVATE-3", "store down"])
