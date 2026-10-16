"""MORNING-BRIEF-B1A, MO-10 and MO-11: the email copy, the owner vouching and the confirmed to-do; demo sessions.
Rig and fakes: `_morning_brief_lib`."""

from __future__ import annotations

# ruff: noqa: F811  (the shared `case` fixture is imported by name)
from datetime import UTC, datetime
from typing import Any

from _morning_brief_lib import BODY, DAY, case, desk_events, get, made, post, sweep, turn_on  # noqa: F401
from _ppl11a_lib import OWNER, PRIYA
from tilo_api import brief_routes, deps, morning_brief_doc, seams_store

# --- MO-10: the email copy -------------------------------------------------------------------------


def test_MORNING_BRIEF_B1A_MO10_the_email_copy_is_plain_text_from_the_stored_brief_and_only_for_a_scheduled_one(case):
    c = case
    c.monkeypatch.setenv(brief_routes.ENV_BRIEF, "1")
    made(c)  # on demand: never mailed
    assert c.mailer.sent == []
    turn_on(c, email_copy=True)
    sweep(c)
    assert len(c.mailer.sent) == 1
    user, text, kind = c.mailer.sent[0]
    assert (user, kind) == (OWNER, "morning_brief")
    assert "Standup" in text and "Invoice 1042 due" in text and "Finish the Q4 report" in text
    assert "http" not in text and "@" not in text and BODY not in text and "example.org" not in text


def test_MORNING_BRIEF_B1A_MO10_without_email_copy_nothing_is_mailed(case):
    c = case
    c.monkeypatch.setenv(brief_routes.ENV_BRIEF, "1")
    turn_on(c, email_copy=False)
    sweep(c)
    assert c.mailer.sent == []


def test_MORNING_BRIEF_B1A_MO10_a_failing_mailer_leaves_the_in_app_brief_as_it_is(case):
    c = case
    c.monkeypatch.setenv(brief_routes.ENV_BRIEF, "1")
    turn_on(c, email_copy=True)

    def boom(*a: Any, **k: Any) -> bool:
        raise RuntimeError("mail down")

    c.mailer.deliver_text = boom
    assert sweep(c) == 1 and get(c).status_code == 200


def test_MORNING_BRIEF_B1A_MO10_an_email_rule_that_is_not_ready_is_said_in_the_setting(case):
    c = case
    c.rig.app.dependency_overrides[brief_routes.get_brief_mailer] = lambda: None
    assert get(c, path="/v1/me/brief-settings").json()["email_rule_ready"] is False
    c.rig.app.dependency_overrides[brief_routes.get_brief_mailer] = lambda: c.mailer
    assert get(c, path="/v1/me/brief-settings").json()["email_rule_ready"] is True


def test_MORNING_BRIEF_B1A_MO10_the_rendered_copy_says_when_a_section_was_not_read(case):
    c = case
    c.rpc.outcome = {"read_events": "not_connected"}
    c.rpc.raises = {"search_email"}
    text = morning_brief_doc.render_email(made(c))
    assert "This section not connected." in text and "This section could not be read today." in text


# --- MO-11: a brief acts on nothing; a to-do needs the person --------------------------------------


def test_MORNING_BRIEF_B1A_MO11_making_and_reading_a_brief_writes_no_outbox_gate_card_or_decision(case):
    c = case
    made(c)
    get(c)
    kinds = {e["type"] for e in desk_events(c)}
    assert kinds <= {"data.transfer", "artifact.created", "artifact.versioned"}
    assert c.mailer.sent == []


def test_MORNING_BRIEF_B1A_MO11_the_source_owners_seam_vouches_for_a_message_of_the_persons_own_brief_only(case):
    c = case
    made(c)
    owners = seams_store.StoreSourceOwners(c.rig.event_store, c.briefs)
    assert owners.owner_of("mail", "m_invoice") == OWNER
    for foreign in ("m_visit", "m_bad", "m_old", "m_nothing", "bad id"):
        assert owners.owner_of("mail", foreign) is None  # read, flagged, too old, unknown: none was in the brief
    assert seams_store.StoreSourceOwners(c.rig.event_store, None).owner_of("mail", "m_invoice") is None


def test_MORNING_BRIEF_B1A_MO11_a_message_id_in_two_briefs_vouches_for_nobody_and_a_week_old_one_for_nobody(case):
    c = case
    c.briefs.index_mail(deps.ORG_ID, OWNER, ["m_shared"], DAY)
    c.briefs.index_mail(deps.ORG_ID, PRIYA, ["m_shared"], DAY)
    c.briefs.index_mail(deps.ORG_ID, OWNER, ["m_stale"], "2026-10-01")
    today = datetime(2026, 10, 16, tzinfo=UTC).date().isoformat()
    assert c.briefs.mail_owner(deps.ORG_ID, "m_shared", today) is None
    assert c.briefs.mail_owner(deps.ORG_ID, "m_stale", today) is None


def test_MORNING_BRIEF_B1A_MO11_a_confirmed_todo_is_a_work_item_with_the_mail_as_source_and_a_foreign_id_is_refused(
    case,
):
    c = case
    c.script.reply = {"needs_reply": [3], "suggestions": [],
                      "todos": [{"title": "Pay invoice 1042", "due_text": "by Friday", "item": 3}]}  # fmt: skip
    brief = made(c)
    todo = brief["todo_suggestions"][0]
    owners = seams_store.StoreSourceOwners(c.rig.event_store, c.briefs)
    c.rig.app.dependency_overrides[deps.get_source_owners] = lambda: owners
    body = {"title": todo["title"], "source": {"kind": "mail", "ref": todo["mail"]["source"]["id"]}}
    created = c.rig.client.post("/v1/work-items", json=body)
    assert created.status_code in (200, 201), created.text
    item = created.json()
    assert item["created_by"]["ref"] == OWNER and item["source"]["ref"] == "m_invoice"
    c.rig.as_user(PRIYA)
    refused = c.rig.client.post("/v1/work-items", json=body)
    assert refused.status_code == 422 and refused.json()["detail"] == "source_not_found"
    c.rig.as_user(OWNER)
    other = c.rig.client.post("/v1/work-items", json={"title": "x", "source": {"kind": "mail", "ref": "m_visit"}})
    assert other.status_code == 422


# --- demo sessions and the off switch --------------------------------------------------------------


def test_MORNING_BRIEF_B1A_MO01_a_demo_session_reads_no_account_and_gets_not_connected_sections(case):
    c = case
    c.rig.app.dependency_overrides[deps.get_current_principal] = lambda: deps.Principal(
        OWNER, "owner", demo_session=True
    )
    response = c.rig.client.post("/v1/me/brief", json={})
    assert response.status_code == 200, response.text
    brief = response.json()
    assert brief["meetings"]["status"] == "not_connected" and brief["mail_needing_reply"]["status"] == "not_connected"
    assert c.rpc.calls == [] and c.script.calls == [] and brief["model"] in ("skipped", "failed")
    assert c.rig.client.get("/v1/me/brief").json() == brief


def test_MORNING_BRIEF_B1A_MO01_the_whole_feature_is_off_by_default(case):
    assert brief_routes.ENV_BRIEF == "TILO_MORNING_BRIEF"
    turn_on(case)
    assert sweep(case) == 0
