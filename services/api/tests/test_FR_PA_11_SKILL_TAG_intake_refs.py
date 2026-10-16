"""SKILL-TAG (FR-PA-11, FR-AGT-03; mentions.rules.md MN-01, MN-02, MN-05, MN-06, MN-09): `POST /intake` takes the `refs`
form field, a JSON array of mention refs, and a tagged skill is kept on the task.

Pinned interface:
  * Thinking: a `skill` ref (library) or `taught_skill` ref (one the caller may use) is resolved as the sender before
    any world, upload or model call. The 201 body then also has `skill` {id, kind, scope, name, version, score 1.0,
    source "tagged"}; the task keeps it and the approaches answer it; the matcher never replaces it.
  * A ref that fails any check, does not exist, is another kind (resolved by M1/M1b, not yet) or is malformed in
    itself is 422 {"error": "ref_unavailable", "index": n}: the same body whatever the cause. A refs field that is not
    a list of at most 10 different refs is 422 {"error": "<sentence>"}; two skill tags are refused the same way.
    Nothing is stored.
  * Quick with a tagged skill answers the switch offer with reason `refs` and `skill`, with no model call, no record.
"""

from __future__ import annotations

import json

import pytest

SKILL = {"kind": "skill", "id": "competitor-scan"}
OTHER = {"kind": "skill", "id": "one-page-plan"}


def post(flow, refs, text="Compare our top rivals this week.", mode=None):
    data = {"text": text, "refs": refs if isinstance(refs, str) else json.dumps(refs)}
    if mode:
        data["mode"] = mode
    return flow.client.post("/intake", data=data)


def test_FR_PA_11_SKILL_TAG_a_library_skill_ref_is_kept_on_the_task_and_returned(clear_flow):
    response = post(clear_flow, [SKILL])
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["skill"]["id"] == "competitor-scan" and body["skill"]["kind"] == "library"
    assert body["skill"]["source"] == "tagged" and body["skill"]["score"] == 1.0
    assert set(body["skill"]) == {"id", "kind", "scope", "name", "version", "score", "source"}
    assert clear_flow.store.tasks[body["task_id"]].skill == body["skill"]


def test_FR_PA_11_SKILL_TAG_no_refs_or_an_empty_list_changes_nothing(clear_flow):
    for refs in (None, "", "[]", "  "):
        data = {"text": "Compare our top rivals this week."}
        if refs is not None:
            data["refs"] = refs
        response = clear_flow.client.post("/intake", data=data)
        assert response.status_code == 201 and "skill" not in response.json()


def test_FR_PA_11_SKILL_TAG_the_approaches_keep_the_tag_over_what_the_matcher_would_pick(clear_flow):
    from test_FR_SKL_04_ROUTE_skill_routing import Embedder, vec  # noqa: PLC0415

    goal = clear_flow.provider.brief["goal"].lower()
    embedder = Embedder({"one page plan": vec(i1=1.0), goal: vec(i1=1.0)})  # the matcher would choose one-page-plan
    clear_flow.provider.embed = embedder.embed
    task_id = post(clear_flow, [SKILL]).json()["task_id"]
    answer = clear_flow.approaches(task_id).json()
    assert answer["skill"]["id"] == "competitor-scan" and answer["skill"]["source"] == "tagged"
    assert clear_flow.store.tasks[task_id].skill["source"] == "tagged"


@pytest.mark.parametrize(
    "ref",
    [
        {"kind": "skill", "id": "no-such-skill"},
        {"kind": "taught_skill", "id": "tsk_not_yours"},
        {"kind": "taught_skill", "id": "competitor-scan"},  # a library id under the wrong kind
        {"kind": "skill", "id": "tsk_not_yours"},
        {"kind": "skill", "id": "BAD ID"},  # malformed in itself
        {"kind": "file", "id": "art_x", "version": 1},  # resolved by M1b, not yet: closed
        {"kind": "mystery", "id": "x"},
    ],
)
def test_FR_PA_11_SKILL_TAG_a_ref_that_cannot_be_used_is_one_422_and_nothing_is_stored(clear_flow, ref):
    response = post(clear_flow, [ref])
    assert response.status_code == 422 and response.json() == {"error": "ref_unavailable", "index": 0}
    later = post(clear_flow, [OTHER, ref])
    assert later.status_code == 422 and later.json() == {"error": "ref_unavailable", "index": 1}
    assert clear_flow.store.tasks == {} and clear_flow.store.worlds == {}
    assert clear_flow.provider.calls == []  # before any model call (MN-09)


def test_FR_PA_11_SKILL_TAG_a_refs_field_that_is_not_a_list_of_refs_is_refused_with_a_sentence(clear_flow):
    many = [{"kind": "skill", "id": f"s-{n}"} for n in range(11)]
    for refs in ("not json", "{}", json.dumps(many), json.dumps([SKILL, SKILL]), '"skill"', "null"):
        response = post(clear_flow, refs)
        assert response.status_code == 422 and set(response.json()) == {"error"}, refs
    two = post(clear_flow, [SKILL, OTHER])
    assert two.status_code == 422 and set(two.json()) == {"error"}  # one skill at a time
    assert clear_flow.store.tasks == {} and clear_flow.provider.calls == []


def test_FR_PA_11_SKILL_TAG_an_extra_key_or_a_label_in_a_ref_is_refused(clear_flow):
    response = post(clear_flow, [{**SKILL, "label": "Competitor scan"}])
    assert response.status_code == 422 and response.json() == {"error": "ref_unavailable", "index": 0}  # MN-08


def test_FR_PA_11_SKILL_TAG_quick_with_a_tag_answers_the_switch_offer_with_reason_refs_and_the_skill(quick_rig):
    response = quick_rig.client.post(
        "/intake", data={"text": "What is the capital of France?", "mode": "quick", "refs": json.dumps([SKILL])}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["mode"], body["outcome"], body["reason"]) == ("quick", "switch_to_thinking", "refs")
    assert body["skill"]["id"] == "competitor-scan" and body["skill"]["source"] == "tagged"
    assert quick_rig.calls == []  # no model call, and Quick keeps no record
    quick_rig.assert_nothing_stored()


def test_FR_PA_11_SKILL_TAG_quick_with_an_unusable_tag_is_the_same_422(quick_rig):
    bad = json.dumps([{"kind": "skill", "id": "no-such-skill"}])
    response = quick_rig.client.post(
        "/intake", data={"text": "What is the capital of France?", "mode": "quick", "refs": bad}
    )
    assert response.status_code == 422 and response.json() == {"error": "ref_unavailable", "index": 0}
    assert quick_rig.calls == []


def test_FR_PA_11_SKILL_TAG_a_taught_skill_the_caller_may_use_resolves_and_another_persons_does_not(repo_root):
    from test_FR_SKL_04_ROUTE_skill_routing import Embedder, context, taught  # noqa: PLC0415
    from tilo_api.intake_refs import RefsRefused, tagged_skill  # noqa: PLC0415

    mine = taught("tsk_mine", "u_priya", "Weekly digest")
    ctx = context(repo_root, Embedder({}), taught=[mine])  # the store read is already the caller's view
    found = tagged_skill([{"kind": "taught_skill", "id": "tsk_mine"}], ctx)
    assert found["id"] == "tsk_mine" and found["kind"] == "taught" and found["scope"] == "mine"
    for ref in ({"kind": "taught_skill", "id": "tsk_sams"}, {"kind": "skill", "id": "tsk_mine"}):
        with pytest.raises(RefsRefused) as caught:
            tagged_skill([ref], ctx)
        assert caught.value.index == 0
