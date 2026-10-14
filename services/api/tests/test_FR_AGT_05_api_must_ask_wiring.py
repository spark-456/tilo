"""FR-AGT-05 through the API (PRD 8.3 "Must-ask rules", 8.6 "planted ambiguity raises a question; clear tasks raise
none", 10.2 Needs you; issue #292 items 2 and 5; BQ-198, BQ-199, BQ-201, BQ-212). The harness half is merged (#276):
`run_plan(must_ask=)` parks a unit that must ask. These tests pin that the API's run (`tilo_api.runs.Run`) uses it:
the planted ambiguity becomes a needs_you card in the run's CardStore plus the Specialist -> Lead -> Director -> person
chain, the unit does not start, and a run with a unit waiting for a person is neither completed nor failed. The wiring
and the new seam `deps.get_must_ask_providers` are in `_agt05_lib.py`. Scripted models, fake connector, in-process
app: no model, no network, no browser, no server.
"""

from __future__ import annotations

import pathlib
import re

import pytest
from _agt05_lib import (
    ASK,
    CLEAR,
    CLEAR_REPLY,
    FLOW_USER,
    QUESTION_TYPES,
    ScriptedProvider,
    build_ask_flow,
    needs_you_cards,
    question_events,
    spy_card_submit,
    start_and_approve,
    tasks_provider,
    worker_of,
)
from _clint2_lib import MOCK_ID, assert_stream_valid, schema_errors, wait_for

pytestmark = pytest.mark.usefixtures("must_ask_ask_mode")  # these suites pin the cards (BQ-ASSUME-1)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
RUN_TERMINAL = ("world.completed", "world.failed")


def _l3_send_policy() -> dict:
    """The owner's valid L3 policy for send_email on the mock connector."""
    stamp = {"by": FLOW_USER, "at": "2026-09-29T09:30:00.000Z"}
    return {
        "id": "pol_send_mock", "owner": FLOW_USER, "action_type": "send_email",
        "scope": {"connectors": [MOCK_ID], "recipients": [], "domains": [], "districts": []},
        "limits": {"per_day": 5, "credits": None},
        "conditions": {"no_attachments": True, "no_new_recipients": True, "no_safety_flags": True},
        "level": "L3", "undo_window_s": 60, "expiry": None, "notify_channel": "email", "team_lead_domains": [],
        "created_by": stamp, "changed_by": stamp, "history": [{**stamp, "change": "Raised to L3", "level": "L3"}],
    }  # fmt: skip


@pytest.fixture()
def asking(repo_root):
    """A run whose U1 plants an ambiguity (the recorded model asks) and whose U2 and U3 are clear; U2 depends on U1."""
    flows = []

    def build(**kwargs):
        provider = tasks_provider(ASK, *CLEAR[1:])
        flows.append(build_ask_flow(repo_root, provider, **kwargs))
        return flows[-1]

    yield build
    for rf in flows:
        rf.close()


def _asked(rf):
    """Starts the run and waits until it has asked; returns (events, the one needs_you card)."""
    start_and_approve(rf)
    wait_for(lambda: rf.events("question.routed"), what="question.routed")
    rf.quiet_stream()
    (card,) = needs_you_cards(rf)
    return rf.stream(), card


def test_FR_AGT_05_api_planted_ambiguity_raises_the_question_chain_and_a_needs_you_card(asking, registry):
    rf = asking()

    events, card = _asked(rf)

    assert rf.provider.misses == []
    chain = question_events(rf)
    assert {t: len(v) for t, v in chain.items()} == {t: 1 for t in QUESTION_TYPES}, "one chain, for U1 only"
    helped, escalated, routed = (chain[t][0] for t in QUESTION_TYPES)
    worker = worker_of(rf, "U1")
    semantic = rf.layouts[rf.world_id]["semantic"]
    assigned = next(e for e in events if e["type"] == "agent.assigned" and e["data"]["unit"] == "U1")
    lead = next(
        d["lead"] for level in semantic["levels"] for d in level["districts"] if d["id"] == assigned["district"]
    )
    director = next(a["id"] for a in semantic["agents"] if a["rank"] == "director")
    assert assigned["seq"] < helped["seq"] < escalated["seq"] < routed["seq"]
    assert (helped["actor"], helped["target"], helped["data"]["unit"]) == (worker, lead, "U1")
    assert helped["cause"] == assigned["id"]
    assert (escalated["actor"], escalated["target"], escalated["data"]["reason"]) == (lead, director, "ambiguous_brief")
    assert escalated["cause"] == helped["id"] and routed["cause"] == escalated["id"]
    assert (routed["actor"], routed["target"]) == (lead, FLOW_USER), "no Team Lead is configured: the owner is asked"
    assert routed["data"]["card_id"] == card["id"]

    # the card is the API CardStore's: the cards route lists it, the run's own store holds it
    assert schema_errors("card", card) == [], schema_errors("card", card)
    assert (card["kind"], card["rung"], card["world_id"]) == ("needs_you", "needs_you", rf.world_id)
    run = rf.store.runs[rf.world_id]
    assert card["run_id"] == run.run_id and run.cards.get(rf.world_id, card["id"]) is not None
    assert card["what_happened"] == ASK["model_reply"]["question"]
    assert [o["label"] for o in card["options"]] == ASK["model_reply"]["options"]
    assert card["header"]["agent"] == worker
    assert card["safe_default"] in {o["id"] for o in card["options"]}
    assert not any(o["irreversible"] for o in card["options"]), "a question's options can never authorise a send"
    assert_stream_valid(rf, registry)


def test_FR_AGT_05_api_the_unit_that_asks_does_not_start_and_hands_nothing_over(asking):
    rf = asking()

    events, _card = _asked(rf)

    worker = worker_of(rf, "U1")
    assert "U1" not in rf.runner.ran, "the ambiguous unit must not start its work until a person answers"
    assert [
        e
        for e in events
        if e["type"] in ("agent.working", "agent.handoff", "agent.retired") and worker in (e["actor"], e["target"])
    ] == []
    assert not [e for e in events if e["type"] == "artifact.created" and e["actor"] == worker]
    assert rf.provider.calls_about(ASK["title"]) == 1, "one judgement of the unit, one model call"


def test_FR_AGT_05_api_the_card_carries_the_units_district_so_a_team_lead_sees_only_theirs(asking):
    rf = asking()
    _events, card = _asked(rf)
    district = next(e for e in rf.events("agent.assigned") if e["data"]["unit"] == "U1")["district"]
    other = "D2" if district == "D1" else "D1"

    rf.as_member("u_lead_here", "team_lead", districts=(district,))
    assert [c["id"] for c in rf.cards().json()] == [card["id"]]
    rf.as_member("u_lead_elsewhere", "team_lead", districts=(other,))
    assert rf.cards().json() == [], "a district's question never reaches a Team Lead of another district"
    assert all(e["vis"] == [district] for e in question_events_flat(rf)), "the chain is that district's (PRD 10.1)"


def question_events_flat(rf):
    return [e for events in question_events(rf).values() for e in events]


@pytest.mark.parametrize("independent", [False, True], ids=["dependants_wait", "nothing_depends_on_it"])
def test_FR_AGT_05_api_a_run_with_a_unit_waiting_for_a_person_does_not_complete_or_fail(asking, independent):
    """Issue #292 item 5: `result.parked` is not a failure and not a completion. U1 waits for its answer; its
    dependants (if any) wait with it; neither `world.completed` nor `world.failed` may be written."""
    rf = asking(independent=independent)

    events, _card = _asked(rf)

    types = [e["type"] for e in events]
    assert not [t for t in types if t in RUN_TERMINAL], f"a parked run is still waiting: {types}"
    assert rf.delivery().status_code == 409, "nothing is delivered until the work is done"
    if independent:
        assert {"U2", "U3"} <= set(rf.runner.ran), "the units that do not depend on the asked one go on"
    else:
        assert rf.runner.ran == [], "U2 and U3 depend on the asked unit, so they wait"
    assert "U1" not in rf.runner.ran


def test_FR_AGT_05_api_clear_plan_raises_no_question_and_completes_as_before(repo_root):
    provider = tasks_provider(*CLEAR)
    rf = build_ask_flow(repo_root, provider, first=CLEAR[0])
    try:
        start_and_approve(rf)
        wait_for(lambda: rf.events("world.completed"), what="world.completed")
        rf.quiet_stream()

        # the rules ran for every unit (a clear task is judged clear, not skipped), and nothing asked
        assert provider.misses == []
        assert [provider.calls_about(t["title"]) for t in CLEAR] == [1, 1, 1], "each unit is judged once"
        assert question_events_flat(rf) == [] and rf.events("agent.help_requested") == []
        assert rf.cards().json() == []
        assert rf.runner.ran == ["U1", "U2", "U3"]
        assert len(rf.events("world.completed")) == 1 and rf.events("world.failed") == []
        assert rf.delivery().status_code == 200
    finally:
        rf.close()


def test_FR_AGT_05_api_an_uncovered_send_above_T1_asks_even_when_the_model_says_clear_with_no_model_call(repo_root):
    """PRD 8.3 "outside communication not covered by an autonomy policy" is a deterministic rule (BQ-198): the model
    here says {"ask": false} for everything, and the send unit (send_email is T2) still asks, without being asked."""
    provider = ScriptedProvider(default=CLEAR_REPLY)
    rf = build_ask_flow(repo_root, provider, send=True)
    try:
        start_and_approve(rf)
        routed = wait_for(lambda: rf.events("question.routed"), what="question.routed")[0]
        rf.quiet_stream()

        sender = rf.last_plan["units"][3]
        assert sender["actions"] == ["send_email"]
        assert provider.calls_about(sender["title"]) == 0, "the rule decides: zero model calls for the send unit"
        assert provider.calls_about(rf.last_plan["units"][0]["title"]) >= 1, "the other units were judged by the model"
        (escalated,) = rf.events("agent.escalated")
        assert escalated["data"]["reason"] == "sensitive_step"
        (card,) = needs_you_cards(rf)
        assert routed["data"]["card_id"] == card["id"]
        assert "U4" not in rf.runner.ran, "the send unit does not start until a person answers"
        assert rf.events("approval.requested") == [] and [c for c in rf.cards().json() if c["kind"] == "gate"] == []
        assert rf.outbox_store.all_entries() == [] and rf.adapter.sent == [], "nothing is sent or queued"
        assert not [e for e in rf.stream() if e["type"] in ("data.transfer", "artifact.delivered", *RUN_TERMINAL)]
    finally:
        rf.close()


def test_FR_AGT_05_api_a_send_covered_by_the_owners_autonomy_policy_asks_no_question_and_still_gates(repo_root):
    """The covered branch of the same rule: the owner's L3 policy for send_email covers the T2 action, so no question
    (the model says clear); the send still waits at its gate, because the recipient is new (T3, FR-HIL-04)."""
    provider = ScriptedProvider(default=CLEAR_REPLY)
    rf = build_ask_flow(repo_root, provider, send=True)
    try:
        policy = _l3_send_policy()
        rf.store.policies[policy["id"]] = policy
        requested, gate_card = rf.run_to_gate()

        assert requested["data"]["risk_tier"] == "T3"
        assert provider.calls_about(rf.last_plan["units"][3]["title"]) == 1, "judged by the model, which said clear"
        assert question_events_flat(rf) == [] and needs_you_cards(rf) == []
        assert gate_card["kind"] == "gate" and rf.runner.ran == ["U1", "U2", "U3", "U4"]
    finally:
        rf.close()


def test_FR_AGT_05_api_the_must_ask_models_are_the_router_roles_never_a_model_id_in_api_code(asking, monkeypatch):
    """PL-01: with no override of `get_must_ask_providers`, the default builds its role models from `deps.get_router()`
    (as `get_unit_runner` does), so the specialist unit's judgement reaches the Router and is served by a profile of
    the `specialist` role in config/models.yaml."""
    from _clint1_lib import seam  # noqa: PLC0415
    from tilo_api import deps  # noqa: PLC0415
    from tilo_providers.config import load_providers_config  # noqa: PLC0415
    from tilo_providers.router import Router  # noqa: PLC0415

    rf = asking()
    rf.app.dependency_overrides.pop(seam(deps, "get_must_ask_providers"), None)
    served: list[str] = []
    scripted = tasks_provider(ASK, *CLEAR[1:])

    def provider_for_profile(profile_id: str) -> ScriptedProvider:
        served.append(profile_id)
        return scripted

    config = load_providers_config(REPO_ROOT / "config" / "models.yaml", REPO_ROOT / "config" / "prices.yaml")
    router = Router(config, provider_for_profile=provider_for_profile)
    rf.start()  # intake and approaches use the flow's own scripted Director; only the run's must-ask models are checked
    monkeypatch.setattr(deps, "get_router", lambda: router)
    assert rf.approve().status_code == 200
    wait_for(lambda: rf.events("question.routed"), what="question.routed")
    rf.quiet_stream()
    (card,) = needs_you_cards(rf)

    roles = config.roles
    specialist, writer = roles["specialist"], roles["writer"]
    assert card["what_happened"] == ASK["model_reply"]["question"], "the question came from the Router's model"
    assert served, "the judgement did not go through the Router"
    assert set(served) <= {specialist.primary, specialist.fallback, writer.primary, writer.fallback} - {None}
    assert scripted.calls_about(ASK["title"]) == 1


def test_FR_AGT_05_api_src_names_no_model_id():
    """PL-01 guard for the new wiring: no model id from config/models.yaml, and no vendor model name, in the API."""
    import yaml

    profiles = yaml.safe_load((REPO_ROOT / "config" / "models.yaml").read_text(encoding="utf-8"))["profiles"]
    ids = {p["model"] for p in profiles.values()}
    vendor = re.compile(r"\b(gemini|gpt|claude|llama|mistral|nemotron)[-\w.]*\d", re.IGNORECASE)
    offenders = []
    for path in sorted((REPO_ROOT / "services" / "api" / "src").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        offenders += [f"{path.name}: {i}" for i in ids if i in text]
        offenders += [f"{path.name}: {m.group(0)}" for m in vendor.finditer(text)]
    assert offenders == [], offenders


def test_FR_AGT_05_api_the_card_is_stored_before_the_question_chain_is_emitted(asking, monkeypatch):
    """Issue #292 item 2: help_requested, escalated and question.routed come after the card reached the store, so
    question.routed never names a card that does not exist."""
    rf = asking()
    spy_card_submit(monkeypatch, rf)

    _asked(rf)

    timeline = rf.timeline
    assert timeline.count("card:submit") == 1, timeline
    stored = timeline.index("card:submit")
    for type_ in QUESTION_TYPES:
        assert stored < timeline.index(f"event:{type_}"), f"the card must be stored before {type_}: {timeline}"


def test_FR_AGT_05_api_a_card_the_store_cannot_take_emits_no_question_and_the_unit_never_starts(asking, monkeypatch):
    rf = asking()
    spy_card_submit(monkeypatch, rf, fail=RuntimeError("the card store is down"))

    start_and_approve(rf)
    wait_for(lambda: "card:submit" in rf.timeline, what="the card sink to be called")
    rf.quiet_stream(1.0)

    assert rf.events("question.routed") == [], "question.routed must not name a card that was never stored"
    assert "U1" not in rf.runner.ran
    assert rf.events("world.completed") == [], "a run that could not ask its question is not done"
