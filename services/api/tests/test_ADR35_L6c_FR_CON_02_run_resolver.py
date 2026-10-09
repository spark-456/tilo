"""ADR35_L6c / FR_CON_02: a whole run with the PRODUCTION resolver, asked and filled end to end.

A structured answer the person gave fills the recipients, so the gate card shows them; nothing is read from the brief's
text. A missing recipient or field is asked on a needs-you card (nothing enqueued), answered on the fields route,
and the approved document is what the real L5 route sends with Google faked. No network, no paid call, no live switch.
"""

from __future__ import annotations

import json

import pytest
from _clint2_lib import NEW_RECIPIENT, wait_for
from _mtg09b_lib import block_network
from test_ADR35_L6b_FR_CON_02_run_documents import SUBJECT, Live, mime_of
from tilo_api import side_effect_fields


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    block_network(monkeypatch)


class Production(Live):
    """The run of the L6b tests, but the action resolver is the shipped one and the answers are the person's."""

    def __init__(self, repo_root, answers=None, brief_text=None):
        super().__init__(repo_root)
        self.answers, self.brief_text = answers or {}, brief_text
        self.rf.resolve_action = side_effect_fields.make_resolver()

    def start(self):
        self.rf.start()
        task = self.rf.store.tasks[self.rf.task_id]
        task.answers = dict(self.answers)
        if self.brief_text:
            task.brief = {**task.brief, **self.brief_text}  # prose: the Director's own chips, not the person's answers
        self.as_user("u_flow_owner", "owner", full=True)
        assert self.rf.approve().status_code == 200

    def ask(self, field: str):
        def find():
            cards = self.rf.cards().json() if self.rf.cards().status_code == 200 else []
            return next((c for c in cards if c["kind"] == "needs_you" and f"needs {field}" in c["what_happened"]), None)

        return wait_for(find, what=f"the needs-{field} card")

    def asked(self, card_id: str):
        return self.rf.flow.client.get(f"/worlds/{self.rf.world_id}/cards/{card_id}/fields")


@pytest.fixture
def prod(repo_root):
    made = []

    def make(**kw):
        made.append(Production(repo_root, **kw))
        return made[-1]

    yield make
    for item in made:
        item.close()


def test_ADR35_L6c_FR_CON_02_a_structured_answer_gives_the_recipients_and_the_run_sends_through_the_real_route(prod):
    lv = prod(answers={"audience": NEW_RECIPIENT})
    lv.start()
    subject_card = lv.ask("subject")  # the brief has no subject answer: asked, never made from the text
    assert lv.rf.events("approval.requested") == [] and lv.google.reached() == 0
    assert lv.supply(subject_card["id"], {"subject": SUBJECT}).status_code == 200
    draft = lv.gate_card("create_draft")
    assert draft["gate"]["recipients"] == [NEW_RECIPIENT] and f"subject: {SUBJECT}" in draft["gate"]["action"]["exact"]
    assert NEW_RECIPIENT in draft["gate"]["action"]["exact"]
    assert lv.rf.answer(draft["id"], "approve").status_code == 200
    send = lv.gate_card("send_email")
    assert (
        send["gate"]["recipients"] == [NEW_RECIPIENT]
        and send["gate"]["action"]["item"] == draft["gate"]["action"]["item"]
    )
    assert lv.rf.answer(send["id"], "approve").status_code == 200
    wait_for(lambda: lv.rf.events("world.completed"), what="world.completed")
    assert len(lv.google.drafts) == 1 and len(lv.google.sent) == 1
    sent = mime_of(lv.google.sent[0]["raw"])
    assert sent["Subject"] == SUBJECT and sent["To"] == NEW_RECIPIENT and sent["Cc"] is None and sent["Bcc"] is None
    assert {tuple(e["recipients"]) for e in lv.rf.outbox_store.all_entries()} == {(NEW_RECIPIENT,)}


def test_ADR35_L6c_FR_CON_02_an_address_in_the_brief_text_is_not_an_answer_so_the_person_is_asked_who(prod):
    lv = prod(brief_text={"goal": "Email eve@example.org the note", "audience": "eve@example.org"})
    lv.start()
    card = lv.ask("recipient")
    assert card["gate"] is None and [o["id"] for o in card["options"]] == ["provide", "hold"]
    assert "eve@example.org" not in json.dumps(card) and lv.rf.outbox_store.all_entries() == []
    assert lv.google.reached() == 0 and lv.rf.events("approval.requested") == []


def test_ADR35_L6c_FR_CON_02_absent_answer_asks_then_the_fields_route_fills_it_and_it_is_sent(prod):
    lv = prod()
    lv.start()
    who = lv.ask("recipient")
    form = lv.asked(who["id"])
    assert form.status_code == 200 and form.json() == {"fields": side_effect_fields.describe(("recipient",))}
    assert form.json()["fields"][0]["label"] == "Send to" and "Cache-Control" in form.headers
    bad = lv.supply(who["id"], {"recipient": "Eve <eve@example.org>"})
    assert bad.status_code == 422 and "plain email address" in bad.json()["reason"]
    crlf = lv.supply(who["id"], {"recipient": "eve@example.org\r\nBcc: x@example.org"})
    assert crlf.status_code == 422 and "line breaks" in crlf.json()["reason"]
    assert lv.supply(who["id"], {"recipient": NEW_RECIPIENT, "subject": "x"}).status_code == 422  # only what is asked
    assert lv.supply(who["id"], {"recipient": f"{NEW_RECIPIENT}, ops@example.org"}).status_code == 200
    assert lv.asked(who["id"]).status_code == 404  # answered: the form is gone
    assert lv.supply(lv.ask("subject")["id"], {"subject": SUBJECT}).status_code == 200
    draft = lv.gate_card("create_draft")
    assert draft["gate"]["recipients"] == [NEW_RECIPIENT, "ops@example.org"]
    assert lv.rf.answer(draft["id"], "approve").status_code == 200
    send = lv.gate_card("send_email")
    assert lv.rf.answer(send["id"], "approve").status_code == 200
    wait_for(lambda: lv.rf.events("world.completed"), what="world.completed")
    sent = mime_of(lv.google.sent[0]["raw"])
    assert sent["To"] == f"{NEW_RECIPIENT}, ops@example.org" and sent["Subject"] == SUBJECT


def test_ADR35_L6c_FR_CON_02_an_answer_that_is_an_invalid_address_asks_again_and_says_why(prod):
    lv = prod(answers={"audience": "Eve <eve@example.org>"})
    lv.start()
    card = lv.ask("recipient")
    assert "plain email address" in card["why_it_matters"] and lv.google.reached() == 0


def test_ADR35_L6c_FR_CON_02_holding_the_recipient_question_sends_nothing(prod):
    lv = prod()
    lv.start()
    assert lv.rf.answer(lv.ask("recipient")["id"], "hold").status_code == 200
    failed = wait_for(lambda: lv.rf.events("world.failed"), what="world.failed")[0]
    assert "needs recipient" in failed["data"]["reason"]
    assert lv.rf.outbox_store.all_entries() == [] and lv.google.reached() == 0


def test_ADR35_L6c_FR_CON_02_the_form_route_is_the_owners_alone_and_open_cards_only(prod):
    lv = prod()
    lv.start()
    who = lv.ask("recipient")
    for user, role in (("u_viewer1", "viewer"), ("u_appr1", "approver")):
        lv.as_user(user, role, full=True)
        refused = lv.asked(who["id"])
        assert refused.status_code == 404 and "recipient" not in refused.text
    lv.as_user("u_flow_owner", "owner", full=False)
    assert lv.asked(who["id"]).status_code == 403
    lv.as_user("u_flow_owner", "owner", full=True)
    assert lv.asked("0" * 26).status_code == 404
    assert lv.asked(who["id"]).status_code == 200
