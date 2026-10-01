"""FR-HIL-01 / FR-HIL-02 round-1 review findings (GitHub issue #32), one test per finding: identity
and channel come only from the verified principal and an authenticated tilo-channels caller
(PRD 10.1, PI-02, SEC-06); submit is idempotent and never reopens a resolved record; a merged
card keeps its own question; held gate and consent timeouts do not close the card; consent
answers emit connection.consented; CR-01 and CR-02; hostile dates and timeouts never raise.
"""

from __future__ import annotations

import pytest
from _cards_lib import (
    OWNER_P,
    FakeClock,
    FakeEventWriter,
    add_seconds,
    answer_client,
    clone_card,
    load_valid_card,
    new_ulid,
    principal,
)
from tilo_api.cards import CardStore

START = "2026-09-29T09:30:00.000Z"
APPROVER = "u_approver"
W = "w_01"


def _store(**kw) -> tuple[CardStore, FakeClock, FakeEventWriter]:
    clock, writer = FakeClock(START), FakeEventWriter()
    return CardStore(clock=clock, writer=writer, world_owners={W: "u_owner"}, **kw), clock, writer


def _answer(client, card, option="approve", **body):
    return client.post(f"/worlds/{W}/cards/{card['id']}/answer", json={"option": option, **body})


def _gate(store, **companion):
    card = load_valid_card("gate_send_reply")
    assert store.submit(card, outbox_id=new_ulid("ob"), **companion).outcome == "accepted"
    return card


# -- identity comes from the verified principal -------------------------------------------------


def test_FR_HIL_01_a_body_that_names_an_actor_is_refused_and_writes_nothing():
    store, _clock, writer = _store()
    card = _gate(store)

    resp = _answer(answer_client(store, OWNER_P), card, actor="u_owner")

    assert resp.status_code == 422
    assert writer.parts == []


def test_FR_HIL_01_a_stranger_cannot_answer_as_the_owner():
    store, _clock, writer = _store()
    card = _gate(store)
    for who in (
        principal("owner", "u_stranger"),
        principal("owner", "u_owner", world_id="w_other"),
        principal(world_id=None),
    ):
        assert _answer(answer_client(store, who), card).status_code == 404
    assert writer.parts == []


def test_FR_HIL_01_PRD_10_1_a_viewer_gets_403_and_the_gate_stays_open():
    store, _clock, writer = _store()
    card = _gate(store)

    resp = _answer(answer_client(store, principal("viewer", "u_viewer")), card)

    assert resp.status_code == 403
    assert writer.parts == []
    assert [c["id"] for c in store.list_for_world(W, principal=OWNER_P)] == [card["id"]]


def test_FR_HIL_01_PRD_10_1_an_approver_answers_only_assigned_cards():
    store, _clock, writer = _store()
    card = _gate(store, assignee=APPROVER)
    other = clone_card(card, id_="01J8Z3K4M5N6P7Q8R9S0T1V2WA")
    store.submit(other, outbox_id=new_ulid("ob2"))
    who = principal("approver", APPROVER)

    assert _answer(answer_client(store, who), other).status_code == 404
    assert writer.parts == []
    ok = _answer(answer_client(store, who), card, channel="mobile_web")
    assert ok.status_code == 200
    [part] = writer.of_type("approval.resolved")
    assert part["authz"]["ref"] == APPROVER
    assert [c["id"] for c in store.list_for_world(W, principal=who)] == []


def test_FR_HIL_01_PRD_10_1_a_team_lead_answers_questions_in_their_districts_only():
    store, _clock, writer = _store()
    mine = load_valid_card("needs_you_blocked")
    store.submit(mine, district="D1")
    lead = principal("team_lead", "u_lead", districts=("D1",))
    elsewhere = principal("team_lead", "u_lead2", districts=("D2",))

    assert _answer(answer_client(store, elsewhere), mine, "per_kwh").status_code == 404
    assert writer.parts == []
    assert _answer(answer_client(store, lead), mine, "per_kwh").status_code == 200
    assert len(writer.of_type("question.answered")) == 1


def test_FR_HIL_01_a_team_lead_does_not_open_a_gate_here_and_a_refused_approve_leaves_it_open():
    store, _clock, writer = _store()
    card = _gate(store, district="D1")
    lead = principal("team_lead", "u_lead", districts=("D1",))

    assert _answer(answer_client(store, lead), card).status_code == 403
    assert writer.parts == []
    assert _answer(answer_client(store, OWNER_P), card).status_code == 200
    assert len(writer.of_type("approval.resolved")) == 1


def test_FR_HIL_09_a_team_leads_card_list_hides_other_districts_and_names_no_count():
    store, _clock, _writer = _store()
    visible = load_valid_card("needs_you_blocked")
    hidden = clone_card(visible, id_="01J8Z3K4M5N6P7Q8R9S0T1V2WB", building="B4")
    store.submit(visible, district="D1")
    store.submit(hidden, district="D2")
    lead = principal("team_lead", "u_lead", districts=("D1",))

    resp = answer_client(store, lead).get(f"/worlds/{W}/cards")

    assert [c["id"] for c in resp.json()] == [visible["id"]]
    assert answer_client(store, principal("viewer", "u_v")).get(f"/worlds/{W}/cards").status_code == 403
    assert answer_client(store, principal(world_id="w_other")).get(f"/worlds/{W}/cards").status_code == 404


def test_FR_HIL_01_an_invalid_principal_id_is_never_written_into_authz():
    clock, writer = FakeClock(START), FakeEventWriter()
    store = CardStore(clock=clock, writer=writer, world_owners={W: "not a user id"})
    card = _gate(store)

    result = store.answer(W, card["id"], option="approve", channel="web", principal=principal(user_id="not a user id"))

    assert (result.outcome, result.reason) == ("rejected", "card_not_found")
    assert writer.parts == []


# -- channel and PIN only from an authenticated tilo-channels caller ----------------------------


def test_FR_HIL_01_SEC_06_a_web_session_cannot_claim_whatsapp_or_a_verified_pin():
    store, _clock, writer = _store()
    card = _gate(store)
    client = answer_client(store, OWNER_P)

    assert _answer(client, card, channel="whatsapp", pin_verified=True).status_code == 403
    assert _answer(client, card, channel="web", pin_verified=True).status_code == 403
    assert writer.parts == []


def test_FR_HIL_01_SEC_06_a_whatsapp_t3_approve_needs_the_pin_from_tilo_channels():
    store, _clock, writer = _store()
    card = _gate(store)
    client = answer_client(store, OWNER_P, from_channels=True)

    no_pin = _answer(client, card, channel="whatsapp")
    assert (no_pin.status_code, no_pin.json()["reason"]) == (400, "pin_required")
    assert writer.parts == []
    assert _answer(client, card, channel="whatsapp", pin_verified=True).status_code == 200
    assert writer.of_type("approval.resolved")[0]["data"]["pin_verified"] is True


# -- gate answers follow CR-07 and CR-13 -----------------------------------------------------------


def test_FR_HIL_01_CR_07_edit_and_hold_write_nothing_and_leave_the_gate_open():
    store, _clock, writer = _store()
    card = _gate(store)

    for option in ("edit", "hold"):
        assert store.answer(W, card["id"], option=option, channel="web", principal=OWNER_P).outcome == "answered"
    assert writer.parts == []
    assert store.answer(W, card["id"], option="approve", channel="web", principal=OWNER_P).emitted != ()


def test_FR_HIL_01_CR_13_only_connect_grants_a_connection_and_emits_connection_consented():
    store, _clock, writer = _store()
    card = load_valid_card("consent_drive_folder")
    store.submit(card)

    held = store.answer(W, card["id"], option="hold", channel="web", principal=OWNER_P)
    assert (held.outcome, held.emitted, writer.parts) == ("answered", (), [])
    granted = store.answer(W, card["id"], option="connect", channel="web", principal=OWNER_P)

    [part] = granted.emitted
    assert part["type"] == "connection.consented"
    assert part["data"] == {"connector": "google_drive", "card_id": card["id"], "scopes": card["consent"]["scopes"]}
    assert part["authz"] == {"by": "person", "ref": "u_owner", "at": START}
    assert store.answer(W, card["id"], option="connect", channel="web", principal=OWNER_P).reason == "already_resolved"


def test_FR_HIL_01_a_non_owner_never_answers_a_consent_card():
    store, _clock, writer = _store()
    card = load_valid_card("consent_drive_folder")
    store.submit(card, assignee=APPROVER)

    resp = _answer(answer_client(store, principal("approver", APPROVER)), card, "connect")

    assert resp.status_code == 403
    assert writer.parts == []


# -- submit: idempotent, never reopens ------------------------------------------------------------


def test_FR_HIL_01_a_same_content_resubmit_is_idempotent_and_never_reopens_a_resolved_gate():
    store, _clock, writer = _store()
    card = load_valid_card("gate_send_reply")
    ob = new_ulid("ob")
    first = store.submit(card, outbox_id=ob)
    assert store.answer(W, card["id"], option="approve", channel="web", principal=OWNER_P).outcome == "answered"

    again = store.submit(card, outbox_id=ob)

    assert again == first
    assert store.list_for_world(W, principal=OWNER_P) == []
    assert store.answer(W, card["id"], option="approve", channel="web", principal=OWNER_P).reason == "already_resolved"
    assert len(writer.of_type("approval.resolved")) == 1


def test_FR_HIL_01_different_content_under_a_used_id_is_rejected_and_the_original_stands():
    store, _clock, _writer = _store()
    card = load_valid_card("needs_you_blocked")
    store.submit(card)
    changed = clone_card(card)
    changed["what_happened"] = "Something else entirely."

    assert store.submit(changed).outcome == "rejected"
    assert store.get(W, card["id"]) == card
    assert store.submit(card, assignee=APPROVER).outcome == "rejected"


def test_FR_HIL_01_stored_cards_cannot_be_changed_through_the_callers_dict():
    store, _clock, _writer = _store()
    card = load_valid_card("needs_you_blocked")
    store.submit(card)

    card["options"].clear()
    store.get(W, card["id"])["options"].clear()

    assert len(store.get(W, card["id"])["options"]) == 2


# -- CR-01, CR-02 and hostile numbers -------------------------------------------------------------


def test_FR_HIL_01_CR_01_a_safe_default_that_names_no_option_is_rejected():
    store, _clock, _writer = _store()
    card = load_valid_card("needs_you_blocked")
    card["safe_default"] = "not_an_option"

    result = store.submit(card)

    assert result.outcome == "rejected"
    assert any("CR-01" in e for e in result.errors)


def test_FR_HIL_01_CR_02_a_repeated_option_id_is_rejected():
    store, _clock, _writer = _store()
    card = load_valid_card("needs_you_blocked")
    card["options"][1]["id"] = card["options"][0]["id"]

    result = store.submit(card)

    assert result.outcome == "rejected"
    assert any("CR-02" in e for e in result.errors)


@pytest.mark.parametrize("field,value", [("created_at", "2026-02-30T09:30:00.000Z"), ("timeout", 10**15)])
def test_FR_HIL_02_an_impossible_date_or_huge_timeout_is_rejected_not_raised(field, value):
    store, clock, writer = _store()
    ok = load_valid_card("needs_you_blocked")
    store.submit(ok)
    bad = clone_card(ok, id_="01J8Z3K4M5N6P7Q8R9S0T1V2WD")
    bad[field] = value

    assert store.submit(bad).outcome == "rejected"
    clock.advance(ok["timeout"])
    assert [r.card_id for r in store.tick()] == [ok["id"]]
    assert len(writer.of_type("question.answered")) == 1


# -- FR-HIL-02: merged cards keep their own question, submit is not a scan ------------------------


def test_FR_HIL_02_a_merged_card_keeps_its_own_question_and_options():
    store, _clock, writer = _store()
    base = load_valid_card("needs_you_compare_basis")
    second = clone_card(base, id_="01J8Z3K4M5N6P7Q8R9S0T1V2WE", created_at=add_seconds(START, 10))
    second["what_happened"] = "A different question."
    second["options"][0]["id"] = second["safe_default"] = "second_a"
    store.submit(base)
    assert store.submit(second).outcome == "merged"

    assert store.get(W, second["id"])["what_happened"] == "A different question."
    assert store.answer(W, second["id"], option="per_kwh", channel="web", principal=OWNER_P).reason == "invalid_option"
    assert store.answer(W, second["id"], option="second_a", channel="web", principal=OWNER_P).outcome == "answered"
    assert [c["id"] for c in store.list_for_world(W, principal=OWNER_P)] == [base["id"]]
    assert store.answer(W, base["id"], option="per_kwh", channel="web", principal=OWNER_P).outcome == "answered"
    assert store.list_for_world(W, principal=OWNER_P) == []
    assert len(writer.of_type("question.answered")) == 2


def test_FR_HIL_02_cards_for_different_districts_or_assignees_never_merge():
    store, _clock, _writer = _store()
    base = load_valid_card("needs_you_compare_basis")
    results = [
        store.submit(clone_card(base, id_=f"01J8Z3K4M5N6P7Q8R9S0T1V2X{n}"), district=d, assignee=a)
        for n, (d, a) in enumerate([("D1", None), ("D2", None), ("D1", APPROVER), ("D1", None)])
    ]

    assert [r.outcome for r in results] == ["accepted", "accepted", "accepted", "merged"]


def test_FR_HIL_02_a_merged_cards_own_timeout_applies_its_own_default():
    store, clock, writer = _store()
    base = load_valid_card("needs_you_compare_basis")
    store.submit(base)
    store.submit(clone_card(base, id_="01J8Z3K4M5N6P7Q8R9S0T1V2WF", created_at=add_seconds(START, 30)))

    clock.advance(base["timeout"])
    assert [r.card_id for r in store.tick()] == [base["id"]]
    clock.advance(30)
    assert [r.card_id for r in store.tick()] == ["01J8Z3K4M5N6P7Q8R9S0T1V2WF"]
    assert len(writer.of_type("question.answered")) == 2


def test_FR_HIL_01_every_emitted_part_is_a_registered_event_with_valid_data(registry, repo_root):
    import jsonschema
    from _cards_lib import load_json

    store, clock, writer = _store()
    gate, consent, question = (
        _gate(store),
        load_valid_card("consent_drive_folder"),
        load_valid_card("needs_you_blocked"),
    )
    store.submit(consent)
    store.submit(question)
    clock.advance(question["timeout"])
    store.tick()  # alert.raised for the held gate and consent; question.answered (default) for the question
    store.answer(W, gate["id"], option="approve", channel="web", principal=OWNER_P)
    store.answer(W, consent["id"], option="connect", channel="web", principal=OWNER_P)

    assert {p["type"] for p in writer.parts} == {
        "alert.raised",
        "question.answered",
        "approval.resolved",
        "connection.consented",
    }
    for part in writer.parts:
        schema = load_json(repo_root / "contracts" / "events" / "data" / f"{part['type']}.schema.json")
        jsonschema.Draft202012Validator(schema, registry=registry).validate(part["data"])
