"""E-BUILD (PRD supplement 2026-10-05 s6, 8 cases; the evals ticket wires them into `evals/`): the assertions the
API doc pins, run here as acceptance tests of FR-CON-16, FR-CON-17 and FR-CON-20.

- 4 handoffs: `prepare_handoff` succeeds, `prompt == render_prompt(...)` and `find_leaks(prompt, declined) == ()`
  (100%).
- 2 planted cases (unaccepted text; an ungranted file): `find_leaks(prompt + decode_link(url), planted) == ()` and
  no read of the ungranted ref (0 leaks).
- 2 over-long briefs: `BriefTooLong` with the MCP offer and `truncated is False` (no truncation without saying so).

No scenario-specific code: the four handoffs differ in their data, never in the code path (PRD 4.3).
"""

from __future__ import annotations

import pytest
from _handoff_lib import (
    PLANT,
    accept,
    approaches,
    approved_brief,
    declined,
    enqueue,
    errs,
    everything_emitted,
    excerpts_for,
    g,
    h,
    link_url,
    lv,
    make_env,
    planted_unaccepted,
    prepare,
    run_flow,
)


def _framing(accepted) -> str:
    return f"Build the {accepted.deliverable_title} described below. Follow the requirements exactly."


def _standard():
    return {"accepted": accept(), "grant": ()}


def _second_deliverable_with_a_granted_excerpt():
    brief = approved_brief(
        deliverables=[
            {"title": "Storefront website", "format": "in_app"},
            {"title": "Admin console", "format": "in_app"},
        ],
        constraints=["Staff sign in with their own company login", "List open orders first"],
    )
    return {
        "accepted": accept(brief=brief, deliverable_index=1),
        "grant": (("art_ops_notes", 1, "Ops notes"),),
        "texts": {("art_ops_notes", 1): "Orders are packed in the afternoon.\nReturns go to bay two."},
    }


def _non_ascii_and_reserved_characters():
    brief = approved_brief(
        goal="Bouwen: een winkel voor één merk & zijn fans (100% handmatig).",
        constraints=["Prijzen in ₹ en €", "Zoeken met # en ? werkt", "Tekst met 日本語 blijft staan"],
    )
    return {"accepted": accept(brief=brief), "grant": ()}


def _nothing_but_the_goal():
    chosen = next(a for a in approaches() if a["id"] == "balanced")
    chosen["skips"] = []
    brief = approved_brief(constraints=[], assumptions=[])
    return {"accepted": accept(brief=brief, approach_list=[chosen]), "grant": ()}


FOUR_HANDOFFS = {
    "standard": _standard,
    "second_deliverable_with_a_granted_excerpt": _second_deliverable_with_a_granted_excerpt,
    "non_ascii_and_reserved_characters": _non_ascii_and_reserved_characters,
    "nothing_but_the_goal": _nothing_but_the_goal,
}


@pytest.mark.parametrize("case", list(FOUR_HANDOFFS))
def test_FR_CON_16_E_BUILD_a_handoff_prompt_holds_only_accepted_requirements(case):
    spec = FOUR_HANDOFFS[case]()
    accepted = spec["accepted"]
    env = make_env()
    flow = run_flow(
        env, accepted=accepted, framing=_framing(accepted), grant_specs=spec["grant"], texts=spec.get("texts")
    )
    prompt = flow.prepared.prompt

    assert flow.prepared.framing_source == "writer"
    assert prompt == h().render_prompt(accepted, _framing(accepted), flow.excerpts)
    assert h().find_leaks(prompt, list(declined())) == (), "100%: nothing the owner did not accept"
    assert set(h().find_leaks(prompt, list(accepted.fields()))) == set(accepted.fields())

    enqueue(env, flow.case)
    assert [e["state"] for e in env.outbox.dispatch_due()] == ["sent"]
    assert lv().decode_link(link_url(env)) == prompt


def test_FR_CON_16_E_BUILD_planted_unaccepted_text_has_zero_leaks_in_the_prompt_the_link_and_the_events():
    env = make_env()
    flow = run_flow(env, framing=f"Build the website. {PLANT['removed_constraint']}. {PLANT['thread']}")
    planted = planted_unaccepted()
    enqueue(env, flow.case)
    env.outbox.dispatch_due()
    leaks = h().find_leaks(flow.prepared.prompt + "\n" + lv().decode_link(link_url(env)), planted)
    assert leaks == ()
    assert h().find_leaks(everything_emitted(env), planted) == ()


def test_FR_CON_20_E_BUILD_a_planted_ungranted_file_has_zero_leaks_and_is_never_read():
    env = make_env()
    env.artifacts.put("art_finance", 1, f"Quarterly margins. {PLANT['ungranted']}")
    env.artifacts.put("art_brand_guide", 1, "Use the shop logo.")
    flow = run_flow(env, grant_specs=(("art_brand_guide", 1, "Brand guide"),))

    with pytest.raises(errs().HandoffRefused) as ei:
        excerpts_for(env, flow.grant, [g().ExcerptRequest(ref="art_finance", version=1, text=None)])
    assert ei.value.rule == "DG-02"
    assert env.artifacts.touched("art_finance") == []

    enqueue(env, flow.case)
    env.outbox.dispatch_due()
    leaks = h().find_leaks(flow.prepared.prompt + "\n" + lv().decode_link(link_url(env)), [PLANT["ungranted"]])
    assert leaks == ()


def test_FR_CON_17_E_BUILD_an_over_long_brief_by_url_length_gives_brief_too_long_with_the_mcp_offer(tmp_path):
    base = prepare(make_env(), accept())
    env = make_env(tmp_path, max_url_length=base.link_length - 1)
    with pytest.raises(errs().BriefTooLong) as ei:
        prepare(env, accept())
    err = ei.value
    assert err.truncated is False
    assert err.alternatives == (errs().RouteOffer("mcp", False, "unavailable until FR-CON-18"),)
    assert env.links.links == [] and env.emitted == []


def test_FR_CON_17_E_BUILD_an_over_long_brief_by_prompt_characters_gives_brief_too_long_with_the_mcp_offer(tmp_path):
    base = prepare(make_env(), accept())
    env = make_env(tmp_path, max_prompt_chars=len(base.prompt) - 1)
    with pytest.raises(errs().BriefTooLong) as ei:
        prepare(env, accept())
    err = ei.value
    assert err.truncated is False
    assert err.alternatives == (errs().RouteOffer("mcp", False, "unavailable until FR-CON-18"),)
    assert err.prompt_chars == len(base.prompt) and err.max_prompt_chars == len(base.prompt) - 1
    assert env.links.links == [] and env.emitted == []


def test_FR_CON_17_E_BUILD_no_over_long_brief_is_ever_cut_to_fit(tmp_path):
    """No truncation without saying so: every limit either lets the whole prompt through or refuses the brief."""
    full = prepare(make_env(), accept()).prompt
    for max_chars in (len(full) - 1, len(full) // 2, 100):
        with pytest.raises(errs().BriefTooLong):
            prepare(make_env(tmp_path, max_prompt_chars=max_chars), accept())
    assert prepare(make_env(tmp_path, max_prompt_chars=len(full)), accept()).prompt == full
