"""FR-PA-10 slice s2, the `assistant` role as the fallback (API_FR_PA_10.md section 5): only when the rules cannot
decide, the role is asked once; its reply is a closed document (`update`: `mark_done` or `snooze` of one work item,
the day as a phrase code resolves) that code validates against the same schema, the same offered menu and the same
oracle as a rule's proposal. A model-decided update is a proposal the person confirms (PE-10): `decided_by` is
`model`. A model never writes, never mints an id, never supplies a date and never decides authorisation.

The model is a REAL `ModelDecider` over a REAL `Router` and a scripted provider that replays the recorded replies of
`fixtures/assistant/updates.json`: no network, no paid call, no LIVE. Strict xfails until the builder removes `s2`
from `SLICE_PENDING`.
"""

from __future__ import annotations

import json

import pytest
from _fr_pa_10_lib import (
    BUDGET,
    MODEL_PHRASES,
    RATE,
    SAM,
    TRAVEL,
    ask,
    assert_declined,
    assert_nothing_written,
    assert_proposal,
    decline_text,
    expected_action,
    fuzz_update_replies,
    new_rig,
    pending,
    replay,
    request_text,
    update_reply,
)
from _ppl11b_lib import (
    PRIYA_TITLES,
    assert_events_valid,
    assert_no_leak,
)
from _ppl11b_lib import rig_factory as rig_factory  # noqa: PLC0414  (the fixture)

pytestmark = pending("s2")


@pytest.mark.parametrize("phrase", MODEL_PHRASES, ids=lambda p: f"n{p['n']:02d}")
def test_FR_PA_10_s2_when_no_rule_decides_the_recorded_model_reply_becomes_a_confirmable_proposal(
    phrase, rig_factory, tmp_path
):
    """Given an update no rule reads, then the role is asked once and its recorded reply is validated into the same
    typed action a rule would have made (the day computed by code from the model's `when` phrase), marked
    `decided_by: model` so the web asks for the confirm chip (PE-10). Nothing is written."""
    mr, rig = new_rig(rig_factory, tmp_path, default=replay())
    before = rig.world.snapshot()
    rig.world.reset_log()
    body = ask(rig, phrase["text"], record=phrase["select"])
    assert_proposal(body, expected_action(phrase), by="model")
    assert len(mr.main.calls) == 1
    assert_nothing_written(rig, before)
    asked, replied = rig.events()
    assert replied["actor"] == "A_assistant" and replied["data"]["decided_by"] == "model"
    assert replied["data"]["ui_action"] == body["ui_action"] and replied["data"]["outcome"] == "answered"
    assert replied["trace"]["model_role"] == "assistant" and replied["trace"]["tokens_in"] is not None
    assert_events_valid(rig.events())


def test_FR_PA_10_s2_an_unmatched_title_is_the_models_to_resolve_and_code_still_vets_the_item(rig_factory, tmp_path):
    """'done with the quarterly review' names nothing on the plate, so the rules cannot decide; the model may point
    at one offered item, and only an offered, readable, open item of the person's is accepted."""
    reply = update_reply("mark_done", BUDGET)
    mr, rig = new_rig(rig_factory, tmp_path, default=reply)
    body = ask(rig, "done with the quarterly review", record=RATE)
    assert_proposal(body, {"kind": "mark_done", "work_item_id": BUDGET}, by="model")
    assert len(mr.main.calls) == 1


def test_FR_PA_10_s2_the_model_is_not_asked_when_a_rule_decided_or_the_rules_asked_a_question(rig_factory, tmp_path):
    """Rules first, in this order: a clear update, an ambiguous title, a date the code cannot resolve: zero calls."""
    mr, rig = new_rig(rig_factory, tmp_path, default=replay())
    for text, record in (
        ("done", RATE),
        ("move it to friday", RATE),
        ("done with the share", RATE),
        ("snooze it to the weekend", RATE),
        ("done", None),
    ):
        ask(rig, text, record=record)
    assert mr.main.calls == [] and mr.safety.calls == []


def test_FR_PA_10_s2_the_request_holds_only_the_persons_own_rows_and_the_closed_reply_shapes(rig_factory, tmp_path):
    """FR-PA-17: the model sees the signed-in person's own plate rows as delimited data, never another person's
    record, and is told only the two update kinds and the day phrase (never a timestamp to produce)."""
    mr, rig = new_rig(rig_factory, tmp_path, default=replay())
    ask(rig, "I wrapped up the travel booking")
    [call] = mr.main.calls
    sent = request_text(call)
    assert_no_leak({"request": sent}, [*PRIYA_TITLES.values(), *PRIYA_TITLES.keys(), "wi_priya_1", "OTHER-ORG"])
    for needle in (TRAVEL, RATE, "I wrapped up the travel booking", "mark_done", "snooze", "work_item_id", "when"):
        assert needle in sent, needle
    assert "u_priya" not in sent, "no other person's id is ever put in a request"
    assert sent.count("I wrapped up the travel booking") == 1, "the utterance appears once, inside the data block"
    assert call.json_mode is True


def test_FR_PA_10_s2_130_fuzzed_model_replies_execute_nothing(rig_factory, tmp_path):
    """Selectors, urls, scripts, timestamps, other people's ids, kinds outside the closed set, extra keys, bad
    dates: each is dropped with the fixed `dropped` text; no action, no source, no write, two events per ask."""
    replies = fuzz_update_replies()
    assert len(replies) >= 120
    texts = iter([text for _, text in replies] + [update_reply("mark_done", TRAVEL)])
    mr, rig = new_rig(rig_factory, tmp_path, default=lambda request: next(texts))
    before = rig.world.snapshot()
    rig.world.reset_log()
    for n, (category, _) in enumerate(replies):
        body = ask(rig, f"the offsite budget thing number {n}")
        assert_declined(body, "dropped", by="model")
        assert body["cost"]["model_calls"] == 1, category
    assert len(mr.main.calls) == len(replies)
    assert_nothing_written(rig, before)
    assert [e["type"] for e in rig.events()] == ["assistant.asked", "assistant.replied"] * len(replies)
    control = ask(rig, "the offsite budget thing, once more")  # the same rig accepts a valid reply
    assert_proposal(control, {"kind": "mark_done", "work_item_id": TRAVEL}, by="model")


def test_FR_PA_10_s2_the_model_may_not_name_an_item_the_menu_did_not_offer_or_that_is_no_longer_open(
    rig_factory, tmp_path
):
    """Sam owns `wi_inject1` and it is open, but the plate the model saw did not list it; and the travel item was
    marked done after the plate was built. Both are dropped: code checks the offered menu and the record now. The
    control: the same reply for the open, offered travel item is a proposal."""
    mr, rig = new_rig(rig_factory, tmp_path, default=update_reply("mark_done", TRAVEL))
    control = ask(rig, "the offsite budget thing")
    assert_proposal(control, {"kind": "mark_done", "work_item_id": TRAVEL}, by="model")
    mr1, rig1 = new_rig(rig_factory, tmp_path, default=update_reply("mark_done", "wi_inject1"), world=rig.world)
    assert_declined(ask(rig1, "the offsite budget thing"), "dropped", by="model")
    stored = rig.world.stores.work_items.get("org_tilo", TRAVEL)
    record = json.loads(json.dumps(dict(stored.record)))
    record["status"] = "done"
    record["history"].append({"at": "2026-10-06T09:00:00.000Z", "by": SAM, "change": "done", "status": "done"})
    rig.world.replace_record("work_items", record)
    mr2, rig2 = new_rig(rig_factory, tmp_path, default=update_reply("mark_done", TRAVEL), world=rig.world)
    assert_declined(ask(rig2, "the offsite budget thing"), "dropped", by="model")


def test_FR_PA_10_s2_the_day_is_the_codes_not_the_models(rig_factory, tmp_path):
    """A reply may say 'monday' and code makes 09:00 local of the next Monday; the same reply with a timestamp of
    its own is dropped; a phrase that resolves to a day outside the next 30 days is dropped."""
    mr, rig = new_rig(rig_factory, tmp_path, default=update_reply("snooze", RATE, when="monday"))
    good = ask(rig, "the offsite budget thing")
    assert good["ui_action"] == {"kind": "snooze", "work_item_id": RATE, "until": "2026-10-12T03:30:00.000Z"}
    for reply in (
        update_reply("snooze", RATE, when="monday", until="2026-10-13T03:30:00.000Z"),
        update_reply("snooze", RATE, when="20 nov"),
        update_reply("snooze", RATE, when="2026-10-12T03:30:00.000Z"),
    ):
        mr2, rig2 = new_rig(rig_factory, tmp_path, default=reply)
        assert_declined(ask(rig2, "the offsite budget thing"), "dropped", by="model")


@pytest.mark.parametrize("failure", ["safety_outage", "provider_error"])
def test_FR_PA_10_s2_rules_keep_working_when_the_model_is_unavailable(failure, rig_factory, tmp_path):
    """FR-PA-19 and NFR-22: a safety outage or a failing provider costs only the fallback. A rule phrase still
    proposes; a phrase only the model could read is declined with the `rules_only` text."""

    def provider_down(request):
        raise RuntimeError("provider down (test double)")

    mr, rig = new_rig(
        rig_factory,
        tmp_path,
        default=provider_down if failure == "provider_error" else None,
        safety_raises=failure == "safety_outage",
    )
    ok = ask(rig, "snooze it to friday")
    assert ok["ui_action"] == {"kind": "snooze", "work_item_id": RATE, "until": "2026-10-09T03:30:00.000Z"}
    assert ok["decided_by"] == "rules"
    gone = ask(rig, "I wrapped up the travel booking")
    assert gone["outcome"] == "declined" and gone["ui_action"] is None
    assert gone["text"] in (decline_text("rules_only"), decline_text("failed"))
