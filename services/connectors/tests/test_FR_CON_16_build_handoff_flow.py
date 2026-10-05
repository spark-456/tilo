"""FR-CON-16 (supplement s6): build handoff, end to end through the outbox and the deterministic policy engine.
Acceptance: "No outbox entry before an approving `approval.resolved`; the prompt sent equals the prompt shown, byte
for byte; a requirement the person did not accept never appears in the prompt."

Steps 1 to 10 of API_FR_CON_16_17_20.md "Ordered flow": accept, prepare, store the prompt, record, gate, approval,
`Outbox.enqueue`, `Outbox.dispatch_due` -> `LovableLinkAdapter.execute_side_effect`. The card is what
`handoff_gate` returns (the deterministic card builder copies it, CR-10 to CR-12).
"""

from __future__ import annotations

import copy
import json

import pytest
from _handoff_lib import (
    AGENT,
    ATTEMPT,
    GOOD_FRAMING,
    OWNER,
    PLANT,
    REPO_ROOT,
    RUN,
    STRANGER,
    UNIT,
    WORLD,
    accept,
    approved_brief,
    build_case,
    default_framing,
    enqueue,
    errs,
    everything_emitted,
    h,
    link_url,
    load_json,
    lv,
    make_env,
    oracle_link,
    oracle_prompt,
    planted_unaccepted,
    prepare,
    run_flow,
    settle,
    variant,
)
from tilo_connectors import OutboxRefused
from tilo_policy import SideEffectFacts, load_risk_table


def _card(gate: dict) -> dict:
    """The part of the gate card the acceptance test reads (API doc step 7): gate.action and gate.recipients."""
    return {
        "gate": {
            "action": {
                "type": gate["action_type"],
                "connector": gate["connector"],
                "exact": gate["exact"],
                "item": gate["item"],
                "destination": gate["destination"],
            },
            "recipients": gate["recipients"],
        }
    }


def _approve_and_dispatch(flow):
    enqueue(flow.env, flow.case)
    return flow.env.outbox.dispatch_due()


# --- acceptance (a): no outbox entry before an approving approval.resolved ---------------------------------


def test_FR_CON_16_no_outbox_entry_before_an_approving_approval_resolved():
    flow = run_flow(make_env())
    env, entry_id = flow.env, flow.case["entry"]["id"]

    # steps 1 to 7 done: prompt stored, record made, card built, approval requested but not answered
    assert env.outbox.get(entry_id) is None
    assert env.links.links == []
    assert env.emitted == []

    for answer in (
        {"option": "hold"},
        {"option": "edit"},
        {"authorised_by": None},
    ):
        with pytest.raises(OutboxRefused):
            enqueue(env, flow.case, **answer)
        assert env.outbox.get(entry_id) is None
        assert env.links.links == []
        assert env.emitted == []
        assert env.outbox.dispatch_due() == []


def test_FR_CON_16_an_approving_approval_resolved_stores_the_entry_and_one_dispatch_stores_one_link_and_one_transfer():
    flow = run_flow(make_env())
    env = flow.env
    stored = enqueue(env, flow.case, option="approve")
    assert stored["id"] == flow.case["entry"]["id"] and env.outbox.get(stored["id"]) is not None
    assert env.links.links == [] and env.emitted == [], "queued, not yet sent"

    settled = env.outbox.dispatch_due()

    assert [e["state"] for e in settled] == ["sent"]
    assert len(env.links.links) == 1
    transfers = env.transfers()
    assert len(transfers) == 1
    (transfer,) = transfers
    assert transfer["authz"] == flow.case["authorised_by"]["authz"], "the approval travels with the send (SEC-11)"
    assert transfer["data"]["artifact"] == _card(flow.gate)["gate"]["action"]["item"]
    assert transfer["data"]["direction"] == "out"
    assert (transfer["data"]["connector"], transfer["data"]["action_type"]) == ("lovable", "build_handoff")
    assert transfer["data"]["risk_tier"] == "T3"
    assert transfer["data"]["outbox_id"] == flow.case["entry"]["id"]


def test_FR_CON_16_a_direct_call_to_the_adapter_without_the_outbox_grant_raises_and_stores_nothing():
    from tilo_connectors.errors import MissingGrant

    flow = run_flow(make_env())
    env = flow.env
    entry = enqueue(env, flow.case)
    with pytest.raises(MissingGrant):
        env.adapter.execute_side_effect(entry, None)
    assert env.links.links == [] and env.emitted == []


def test_FR_CON_16_a_second_enqueue_of_the_same_step_sends_one_link_once():
    flow = run_flow(make_env())
    env = flow.env
    enqueue(env, flow.case)
    enqueue(env, flow.case)
    env.outbox.dispatch_due()
    env.outbox.dispatch_due()
    assert len(env.links.links) == 1 and len(env.transfers()) == 1


def test_FR_CON_16_a_build_handoff_approved_on_mobile_web_is_accepted():
    flow = run_flow(make_env())
    flow.case = build_case(flow.record, flow.gate, channel="mobile_web")
    assert [e["state"] for e in _approve_and_dispatch(flow)] == ["sent"]


def test_FR_CON_16_the_assigned_approver_may_approve_a_build_handoff():
    from _handoff_lib import APPROVER

    flow = run_flow(make_env())
    case = build_case(flow.record, flow.gate, approver=APPROVER)
    case["reserved_by"]["data"]["approver"] = {
        "user": APPROVER,
        "assigned_by": {"by": OWNER, "at": "2026-09-29T09:31:00.000Z"},
    }
    flow.case = case
    assert [e["state"] for e in _approve_and_dispatch(flow)] == ["sent"]
    assert flow.env.transfers()[0]["authz"] == case["entry"]["authz"]
    assert case["entry"]["authz"]["ref"] == APPROVER


def test_FR_CON_16_T3_a_person_who_is_neither_owner_nor_approver_cannot_approve():
    flow = run_flow(make_env())
    flow.case = build_case(flow.record, flow.gate, approver=STRANGER)
    with pytest.raises(OutboxRefused):
        enqueue(flow.env, flow.case)
    assert flow.env.outbox.dispatch_due() == [] and flow.env.links.links == []


def test_FR_CON_16_T3_a_policy_never_opens_a_build_handoff():
    """PI-07: a standing policy never authorises T3; the entry is refused at enqueue (OB-01)."""
    from _connectors_lib import evidence_from_case

    fixture = load_json(
        REPO_ROOT / "contracts" / "fixtures" / "outbox" / "crossref" / "valid" / "policy_l3_status_update_waiting.json"
    )
    flow = run_flow(make_env())
    entry = copy.deepcopy(fixture["entry"])
    entry.update(
        {
            "id": flow.case["entry"]["id"],
            "idempotency_key": flow.case["entry"]["idempotency_key"],
            "action_type": "build_handoff",
            "connector": "lovable",
            "recipients": [],
            "item": copy.deepcopy(flow.gate["item"]),
            "destination": None,
            "modifiers": ["external_sharing"],
            "risk_tier": "T3",
            "undo_window_s": 0,
            "state": "queued",
            "scheduled_at": entry["created_at"],
        }
    )
    applied = fixture["authorised_by"]
    applied["data"].update(
        {
            "outbox_id": entry["id"],
            "action_type": "build_handoff",
            "connector": "lovable",
            "destination": None,
            "risk_tier": "T3",
            "item": copy.deepcopy(flow.gate["item"]),
            "undo_window_s": 0,
        }
    )
    case = {**fixture, "entry": entry, "authorised_by": applied}
    with pytest.raises(OutboxRefused):
        flow.env.outbox.enqueue(entry, evidence_from_case(case))
    assert flow.env.outbox.dispatch_due() == [] and flow.env.links.links == []


def test_FR_CON_16_OB_05_an_entry_pinned_to_another_prompt_version_than_the_one_authorised_is_refused():
    flow = run_flow(make_env())
    case = flow.case
    case["entry"]["item"] = {**case["entry"]["item"], "version": case["entry"]["item"]["version"] + 1}
    with pytest.raises(OutboxRefused):
        enqueue(flow.env, case)
    assert flow.env.outbox.dispatch_due() == []


def test_FR_CON_16_OB_05_an_entry_whose_tier_differs_from_the_authorised_gate_is_refused():
    flow = run_flow(make_env())
    flow.case["entry"]["risk_tier"] = "T2"
    with pytest.raises(OutboxRefused):
        enqueue(flow.env, flow.case)


def test_FR_CON_16_OB_05_an_approval_of_another_gate_cannot_release_the_entry():
    flow = run_flow(make_env())
    flow.case["authorised_by"]["data"]["outbox_id"] = "01JB5VQ0000000000000009999"
    with pytest.raises(OutboxRefused):
        enqueue(flow.env, flow.case)


def test_FR_CON_16_policy_engine_adds_external_sharing_so_the_gate_and_the_entry_carry_it():
    flow = run_flow(make_env())
    assessed = load_risk_table().assess("build_handoff", SideEffectFacts(external_share=True))
    assert flow.gate["modifiers"] == list(assessed.modifiers) == ["external_sharing"]
    assert flow.gate["risk_tier"] == assessed.tier == "T3"
    assert flow.case["entry"]["modifiers"] == ["external_sharing"]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda c: c["entry"].update(recipients=["buyer@example.com"]),
        lambda c: c["entry"].update(destination="folder_1"),
        lambda c: c["entry"].update(
            attachments=[{"artifact_id": "art_extra", "version": 1}], modifiers=["attachments", "external_sharing"]
        ),
        lambda c: c["entry"].update(modifiers=[]),
    ],
)
def test_FR_CON_16_BH_09_an_entry_that_is_not_exactly_a_recipientless_destinationless_t3_handoff_never_sends(mutate):
    flow = run_flow(make_env())
    case = flow.case
    mutate(case)
    states = settle(flow.env, case)
    assert states in (["failed"], ["refused"]), states
    assert flow.env.links.links == [] and flow.env.transfers() == []


def test_FR_CON_16_BH_09_a_prompt_that_did_not_go_through_prepare_and_record_never_leaves():
    env = make_env()
    flow = run_flow(env)
    orphan = env.artifacts.put("art_hand_made", 1, "A prompt somebody typed into the store.", run_id=RUN)
    case = build_case(flow.record, flow.gate)
    case["entry"]["item"] = dict(orphan)
    case["reserved_by"]["data"]["item"] = dict(orphan)
    assert settle(env, case) in (["failed"], ["refused"])
    assert env.links.links == [] and env.transfers() == []


# --- acceptance (b): the prompt sent equals the prompt shown, byte for byte -----------------------------------


def test_FR_CON_16_the_prompt_sent_equals_the_prompt_shown_byte_for_byte():
    flow = run_flow(make_env(), framing=GOOD_FRAMING)
    env = flow.env
    card = _card(flow.gate)
    assert [e["state"] for e in _approve_and_dispatch(flow)] == ["sent"]

    url = link_url(env)
    record = json.loads(env.links.links[0].content.decode("ascii"))
    shown = env.artifacts.read(WORLD, card["gate"]["action"]["item"])
    assert lv().decode_link(url).encode("utf-8") == shown == flow.prepared.prompt.encode("utf-8")
    (transfer,) = env.transfers()
    entry = env.outbox.get(flow.case["entry"]["id"])
    assert (
        entry["item"]
        == card["gate"]["action"]["item"]
        == flow.case["reserved_by"]["data"]["item"]
        == transfer["data"]["artifact"]
        == record["prompt"]
    )


def test_FR_CON_16_the_prompt_sent_equals_the_prompt_shown_for_non_ascii_text():
    a = accept(brief=approved_brief(constraints=["Prices in ₹, café menu ☕", "100% & more # ?"]))
    flow = run_flow(make_env(), accepted=a)
    _approve_and_dispatch(flow)
    sent = lv().decode_link(link_url(flow.env))
    assert sent == flow.prepared.prompt
    assert sent.encode("utf-8") == flow.env.artifacts.read(WORLD, flow.gate["item"])


def test_FR_CON_16_a_prompt_version_replaced_after_record_fails_the_entry_and_no_link_is_made():
    flow = run_flow(make_env())
    env = flow.env
    env.artifacts.replace_bytes(WORLD, flow.record.prompt, b"Build something else entirely.\n")
    assert settle(env, flow.case) == ["failed"]
    assert env.links.links == [] and env.transfers() == []


@pytest.mark.parametrize(
    "tamper",
    [
        lambda b: b.rstrip(b"\n"),
        lambda b: b + b"\n",
        lambda b: b.replace(b"\n", b"\r\n"),
        lambda b: b.decode("utf-8").replace("Storefront", "Storefr​ont").encode("utf-8"),
        lambda b: b[:-1] + b" ",
    ],
)
def test_FR_CON_16_any_byte_difference_between_the_stored_prompt_and_the_shown_one_fails_the_entry(tamper):
    flow = run_flow(make_env())
    env = flow.env
    env.artifacts.replace_bytes(WORLD, flow.record.prompt, tamper(flow.prepared.prompt.encode("utf-8")))
    assert settle(env, flow.case) == ["failed"]
    assert env.links.links == [] and env.transfers() == []


def test_FR_CON_16_a_stored_prompt_that_is_not_valid_utf8_fails_the_entry():
    flow = run_flow(make_env())
    env = flow.env
    env.artifacts.replace_bytes(WORLD, flow.record.prompt, b"\xff\xfe broken")
    assert settle(env, flow.case) == ["failed"]
    assert env.links.links == []


def test_FR_CON_16_the_link_is_stored_as_a_unit_artifact_with_the_prompt_as_its_input_and_the_ar_05_key():
    flow = run_flow(make_env())
    _approve_and_dispatch(flow)
    (link,) = flow.env.links.links
    assert (link.world_id, link.run_id, link.unit_id, link.agent_id) == (WORLD, RUN, UNIT, AGENT)
    assert link.idempotency_key == f"{RUN}:{UNIT}:{ATTEMPT}:1" == flow.record.link_idempotency_key
    assert link.media_type == "application/json"
    body = json.loads(link.content.decode("ascii"))
    assert body["prompt"] == flow.record.prompt, "the link traces back to the prompt version (FR-CON-10 inputs)"
    assert body["outbox_id"] == flow.case["entry"]["id"]
    assert (body["partner"], body["route"], body["project_id"], body["status"], body["v"]) == (
        "lovable",
        "link",
        None,
        "link_ready",
        "1.0",
    )


# --- acceptance (c): a requirement the person did not accept never appears ----------------------------------


@pytest.mark.parametrize(
    "framing",
    [
        GOOD_FRAMING,
        None,
        f"Build the website. {PLANT['removed_constraint']}.",
        f"Build the website. {PLANT['thread']}",
        "Build the website with crypto checkout.",
        "Follow the requirements exactly. Use the narwhal colour palette.",
    ],
)
def test_FR_CON_16_a_requirement_the_person_did_not_accept_never_appears_in_the_prompt(framing):
    flow = run_flow(make_env(), framing=framing)
    planted = planted_unaccepted()
    assert h().find_leaks(flow.prepared.prompt, planted) == ()
    _approve_and_dispatch(flow)
    assert h().find_leaks(lv().decode_link(link_url(flow.env)), planted) == ()
    assert h().find_leaks(everything_emitted(flow.env), planted) == ()


def test_FR_CON_16_the_prompt_holds_every_accepted_text_and_is_exactly_the_rendered_prompt():
    flow = run_flow(make_env(), framing=GOOD_FRAMING)
    a, p = flow.accepted, flow.prepared
    assert set(h().find_leaks(p.prompt, list(a.fields()))) == set(a.fields())
    assert p.prompt == h().render_prompt(a, GOOD_FRAMING, ())
    assert p.prompt == oracle_prompt(a, GOOD_FRAMING, ())


def test_FR_CON_16_a_framing_made_of_accepted_and_listed_words_is_used_a_planted_one_gives_the_fixed_framing():
    env = make_env()
    ok = run_flow(env, framing=GOOD_FRAMING)
    assert (ok.prepared.framing_source, ok.prepared.framing_rule) == ("writer", None)
    bad = run_flow(make_env(), framing="Build the website with crypto checkout.")
    assert (bad.prepared.framing_source, bad.prepared.framing_rule) == ("default", "unknown_word")
    assert bad.prepared.prompt.startswith(h().DEFAULT_FRAMING.format(title="Storefront website"))
    assert bad.prepared.prompt == oracle_prompt(accept(), default_framing(accept()), ())


def test_FR_CON_16_nothing_but_the_one_deliverables_accepted_texts_reach_the_prompt():
    flow = run_flow(make_env())
    prompt = flow.prepared.prompt
    for never in ("2026-10-09", "art_quote_a", "Which language?", PLANT["risk"], PLANT["preference"]):
        assert never not in prompt, never


# --- HandoffStore.record (BH-07), get, handoff_gate (BH-09) ------------------------------------------------------


def _prepared_and_stored(env=None):
    env = env or make_env()
    prepared = prepare(env, accept())
    return env, prepared, env.artifacts.put_prompt(prepared)


def test_FR_CON_16_BH_07_record_keeps_the_prompt_ref_hash_exact_text_and_the_ar_05_link_key():
    env, prepared, stored = _prepared_and_stored()
    rec = env.handoffs.record(prepared, stored, unit_id=UNIT, agent_id=AGENT, attempt=ATTEMPT)
    assert rec.prompt == {"artifact_id": stored["artifact"]["artifact_id"], "version": stored["artifact"]["version"]}, (
        "two keys only: the label is not part of the ref"
    )
    assert (rec.world_id, rec.run_id, rec.unit_id, rec.agent_id, rec.attempt) == (WORLD, RUN, UNIT, AGENT, ATTEMPT)
    assert (rec.connector, rec.action_type, rec.prompt_sha256, rec.grant_id, rec.items, rec.exact) == (
        "lovable",
        "build_handoff",
        prepared.prompt_sha256,
        None,
        (),
        prepared.exact,
    )
    assert rec.link_idempotency_key == f"{RUN}:{UNIT}:{ATTEMPT}:1"


@pytest.mark.parametrize(
    "changes",
    [
        {"world_id": "w_other_world"},
        {"run_id": "r_other_run_9"},
        {"media_type": "text/plain"},
        {"media_type": "application/json"},
        {"content_sha256": "0" * 64},
        {"screening": "flagged"},
        {"screening": "unscreened"},
        {"origin_kind": "upload"},
        {"origin_unit": "U8"},
        {"origin_agent": "A_other"},
        {"idempotency_key": f"{RUN}:{UNIT}:{ATTEMPT}:1"},
        {"idempotency_key": f"{RUN}:{UNIT}:{ATTEMPT + 1}:0"},
        {"idempotency_key": f"{RUN}:U8:{ATTEMPT}:0"},
        {"idempotency_key": None},
    ],
)
def test_FR_CON_16_BH_07_record_refuses_a_stored_prompt_that_is_not_exactly_the_one_prepared(changes):
    env, prepared, stored = _prepared_and_stored()
    with pytest.raises(errs().HandoffRefused) as ei:
        env.handoffs.record(prepared, variant(stored, **changes), unit_id=UNIT, agent_id=AGENT, attempt=ATTEMPT)
    assert ei.value.rule == "BH-07"
    assert env.handoffs.get(WORLD, stored["artifact"]) is None


def test_FR_CON_16_BH_07_the_store_changing_the_text_through_its_own_redactor_is_refused():
    env, prepared, stored = _prepared_and_stored()
    redacted = variant(stored, content_sha256="a" * 64, redacted=True)
    with pytest.raises(errs().HandoffRefused) as ei:
        env.handoffs.record(prepared, redacted, unit_id=UNIT, agent_id=AGENT, attempt=ATTEMPT)
    assert ei.value.rule == "BH-07"


def test_FR_CON_16_BH_07_recording_the_same_version_again_returns_the_first_record_other_content_is_refused():
    env, prepared, stored = _prepared_and_stored()
    first = env.handoffs.record(prepared, stored, unit_id=UNIT, agent_id=AGENT, attempt=ATTEMPT)
    again = env.handoffs.record(prepared, copy.deepcopy(stored), unit_id=UNIT, agent_id=AGENT, attempt=ATTEMPT)
    assert again == first
    other = prepare(env, accept(brief=approved_brief(goal="Build a different shop site.")))
    assert other.prompt_sha256 != prepared.prompt_sha256
    clash = variant(stored, content_sha256=other.prompt_sha256)
    with pytest.raises(errs().HandoffRefused) as ei:
        env.handoffs.record(other, clash, unit_id=UNIT, agent_id=AGENT, attempt=ATTEMPT)
    assert ei.value.rule == "BH-07"
    assert env.handoffs.get(WORLD, stored["artifact"]) == first


def test_FR_CON_16_handoff_store_get_is_keyed_on_world_artifact_and_version_type_strictly():
    env, prepared, stored = _prepared_and_stored()
    rec = env.handoffs.record(prepared, stored, unit_id=UNIT, agent_id=AGENT, attempt=ATTEMPT)
    ref = dict(rec.prompt)
    assert env.handoffs.get(WORLD, ref) == rec
    assert env.handoffs.get(WORLD, {**ref, "label": "Build prompt"}) == rec
    assert env.handoffs.get("w_other_world", ref) is None, "another world's record reads as None"
    assert env.handoffs.get(WORLD, {**ref, "version": True}) is None
    assert env.handoffs.get(WORLD, {**ref, "version": float(ref["version"])}) is None
    assert env.handoffs.get(WORLD, {**ref, "version": str(ref["version"])}) is None
    assert env.handoffs.get(WORLD, {**ref, "version": ref["version"] + 1}) is None
    assert env.handoffs.get(WORLD, {**ref, "artifact_id": "art_other"}) is None


def test_FR_CON_16_handoff_gate_is_exactly_what_the_card_the_approval_and_the_entry_copy():
    env, prepared, stored = _prepared_and_stored()
    rec = env.handoffs.record(prepared, stored, unit_id=UNIT, agent_id=AGENT, attempt=ATTEMPT)
    assert h().handoff_gate(rec, env.declaration) == {
        "action_type": "build_handoff",
        "connector": "lovable",
        "risk_tier": "T3",
        "irreversible": True,
        "modifiers": ["external_sharing"],
        "recipients": [],
        "attachments": [],
        "item": rec.prompt,
        "destination": None,
        "exact": prepared.exact,
        "undo_window_s": 0,
    }


def test_FR_CON_16_handoff_gate_hands_out_copies_the_record_cannot_be_changed_through():
    env, prepared, stored = _prepared_and_stored()
    rec = env.handoffs.record(prepared, stored, unit_id=UNIT, agent_id=AGENT, attempt=ATTEMPT)
    gate = h().handoff_gate(rec, env.declaration)
    gate["item"]["version"] = 999
    gate["modifiers"].append("deletion")
    assert h().handoff_gate(rec, env.declaration)["item"] == rec.prompt
    assert env.handoffs.get(WORLD, rec.prompt) == rec


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d["actions"][0].update(risk_tier="T2"),
        lambda d: d["actions"][0].update(irreversible=False),
        lambda d: d["actions"][0].update(risk_tier="T1", gate_type="none"),
        lambda d: d.update(actions=[]),
    ],
)
def test_FR_CON_16_BH_09_handoff_gate_refuses_a_declaration_that_is_not_t3_approval_irreversible(change):
    env, prepared, stored = _prepared_and_stored()
    rec = env.handoffs.record(prepared, stored, unit_id=UNIT, agent_id=AGENT, attempt=ATTEMPT)
    decl = copy.deepcopy(env.declaration)
    change(decl)
    with pytest.raises(errs().HandoffRefused) as ei:
        h().handoff_gate(rec, decl)
    assert ei.value.rule == "BH-09"


def test_FR_CON_16_nothing_is_logged_or_emitted_that_holds_the_prompt_or_the_link(caplog):
    import logging

    caplog.set_level(logging.DEBUG)
    flow = run_flow(make_env())
    _approve_and_dispatch(flow)
    url = link_url(flow.env)
    emitted = everything_emitted(flow.env)
    logged = "\n".join(r.getMessage() + repr(r.args) for r in caplog.records)
    for secretish in (url, oracle_link(flow.prepared.prompt), flow.accepted.goal, flow.prepared.prompt):
        assert secretish not in emitted
        assert secretish not in logged
