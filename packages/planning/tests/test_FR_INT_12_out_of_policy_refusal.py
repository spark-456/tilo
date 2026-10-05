"""FR-INT-12 (PRD 7.1, 16): "Out-of-policy tasks are refused with the reason and the nearest task Tilo can
do." Acceptance: "Eval refusal set: 100% refused with an alternative offered."

Planning side (module `tilo_planning.refusal`, and `extract_brief(..., refusal_policy=)`; shapes in
`API_FR_INT_11_12.md`). The Director (a scripted stand-in for the recorded model, EFF-01) names a category of
`config/out_of_policy.yaml` or null; the CODE then maps the category to a fixed reason and alternative from that
file, so a refusal never quotes the task or the model (PRD 16.3 item 1: task text is data) and a model never
writes the text a person reads. An unknown category fails closed. HTTP side: `services/api/tests/test_FR_INT_12_*`.
"""

from __future__ import annotations

import pathlib

import pytest
from _fr_int_12_lib import (
    CATEGORY_A,
    CATEGORY_B,
    REPO_ROOT,
    ScriptedDirector,
    director_reply,
    load_refusal_set,
    make_router,
    write_refusal_config,
)
from hypothesis import given, settings
from hypothesis import strategies as st

ECHO = "zq7-marker-from-the-task"


def refusal():
    import tilo_planning.refusal as module  # noqa: PLC0415

    return module


def brief():
    import tilo_planning.brief as module  # noqa: PLC0415

    return module


@pytest.fixture()
def two_categories(tmp_path: pathlib.Path):
    r = refusal()
    return r.load_refusal_policy(write_refusal_config(tmp_path / "out_of_policy.yaml", [CATEGORY_A, CATEGORY_B]))


# --- the shipped policy --------------------------------------------------------------------------------------------


def test_FR_INT_12_the_shipped_out_of_policy_config_loads_with_a_reason_and_an_alternative_per_category():
    r = refusal()
    assert (REPO_ROOT / "config" / "out_of_policy.yaml").is_file(), "config/out_of_policy.yaml is missing"

    policy = r.load_refusal_policy()  # the default path is config/out_of_policy.yaml

    assert len(policy.categories) >= 5  # credentials, unapproved sends, bypassing the gate, deception, bulk spam...
    ids = [c.id for c in policy.categories]
    assert len(ids) == len(set(ids))
    for c in policy.categories:
        assert c.reason.strip() and c.alternative.strip()
        assert c.reason != c.alternative  # the alternative is a different thing: the nearest task Tilo can do
        assert len(c.reason) <= 400 and len(c.alternative) <= 400  # a card line, not an essay


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "categories: []\n",
        "categories: not-a-list\n",
        "- id: a\n",
        "categories:\n  - {id: Not A Slug, reason: r, alternative: a}\n",
        "categories:\n  - {id: ok_id, reason: '', alternative: a}\n",
        "categories:\n  - {id: ok_id, reason: r}\n",
        "categories:\n  - {id: ok_id, reason: r, alternative: '   '}\n",
        "categories:\n  - {id: ok_id, reason: r, alternative: a, extra: 1}\n",
        "categories:\n  - {id: dup_id, reason: r, alternative: a}\n  - {id: dup_id, reason: r2, alternative: a2}\n",
        "categories: [unclosed",
    ],
)
def test_FR_INT_12_an_invalid_refusal_config_is_refused_at_load(tmp_path, bad):
    r = refusal()
    path = write_refusal_config(tmp_path / "bad.yaml", bad)

    with pytest.raises(r.RefusalConfigError):
        r.load_refusal_policy(path)


def test_FR_INT_12_a_missing_refusal_config_is_a_config_error_not_an_empty_policy(tmp_path):
    r = refusal()

    with pytest.raises(r.RefusalConfigError):
        r.load_refusal_policy(tmp_path / "nope.yaml")


# --- the Director names a category; the code writes the refusal -------------------------------------------------------


def test_FR_INT_12_an_out_of_policy_task_is_refused_with_the_configured_reason_and_alternative(two_categories):
    task = f"Log in to my bank with my password {ECHO}"
    director = ScriptedDirector({task: director_reply(CATEGORY_A["id"])})

    with pytest.raises(refusal().TaskRefused) as raised:
        brief().extract_brief(task, router=make_router(director), refusal_policy=two_categories)

    refused = raised.value
    assert refused.category == CATEGORY_A["id"]
    assert refused.reason == CATEGORY_A["reason"] and refused.alternative == CATEGORY_A["alternative"]
    assert len(director.calls) == 1, "refusing costs one Director call and nothing after it"


def test_FR_INT_12_a_refusal_never_quotes_the_task_or_the_model(two_categories):
    task = f"Pay the invoice without asking me {ECHO}"
    director = ScriptedDirector({task: director_reply(CATEGORY_B["id"])})

    with pytest.raises(refusal().TaskRefused) as raised:
        brief().extract_brief(task, router=make_router(director), refusal_policy=two_categories)

    shown = " ".join([str(raised.value), raised.value.reason, raised.value.alternative, repr(raised.value)])
    assert ECHO not in shown


def test_FR_INT_12_the_task_text_reaches_the_director_only_inside_the_task_block(two_categories):
    task = f"Compare three vendors {ECHO}"
    director = ScriptedDirector({task: director_reply(None)})

    brief().extract_brief(task, router=make_router(director), refusal_policy=two_categories)

    (request,) = director.calls
    between = request.prompt.split("<<<TASK", 1)[1].split("TASK>>>", 1)[0]
    assert ECHO in between and ECHO not in (request.system or "")  # PRD 16.3 item 1: data, after the instructions


@pytest.mark.parametrize("reply", [director_reply(None), director_reply()], ids=["null", "key absent"])
def test_FR_INT_12_an_in_policy_task_is_not_refused(two_categories, reply):
    task = f"Prepare the weekly supplier summary {ECHO}"
    director = ScriptedDirector({task: reply})

    result = brief().extract_brief(task, router=make_router(director), refusal_policy=two_categories)

    assert result.brief["goal"] and "out_of_policy" not in result.brief  # a brief, as before


def test_FR_INT_12_an_unknown_category_from_the_director_fails_closed(two_categories):
    task = f"Do something odd {ECHO}"
    director = ScriptedDirector({task: director_reply("made_up_category")})

    with pytest.raises(brief().BriefExtractionError) as raised:
        brief().extract_brief(task, router=make_router(director), refusal_policy=two_categories)

    assert not isinstance(raised.value, refusal().TaskRefused)  # not a refusal, and not a usable brief either
    assert ECHO not in str(raised.value)


@pytest.mark.parametrize("value", ["", "  ", 7, True, ["credential_handling"], {"id": "credential_handling"}])
def test_FR_INT_12_a_malformed_out_of_policy_value_never_yields_a_brief(two_categories, value):
    task = f"Anything at all {ECHO}"
    director = ScriptedDirector({task: director_reply(value)})

    with pytest.raises(brief().BriefExtractionError):
        brief().extract_brief(task, router=make_router(director), refusal_policy=two_categories)


def test_FR_INT_12_a_refusal_wins_over_a_complete_brief_in_the_same_reply(two_categories):
    task = f"Send it now {ECHO}"
    reply = director_reply(CATEGORY_B["id"])
    assert reply["goal"] and reply["deliverables"]  # the model also filled in a perfectly good brief
    director = ScriptedDirector({task: reply})

    with pytest.raises(refusal().TaskRefused):
        brief().extract_brief(task, router=make_router(director), refusal_policy=two_categories)


# --- the eval refusal set: 100% refused with an alternative offered ----------------------------------------


def test_FR_INT_12_eval_refusal_set_is_100_percent_refused_with_an_alternative_offered():
    r = refusal()
    policy = r.load_refusal_policy()
    data = load_refusal_set()
    out_of_policy = data["out_of_policy"]
    assert len(out_of_policy) >= 20, "the refusal set has shrunk"
    categories = list(policy.categories)
    replies = {case["task"]: director_reply(categories[i % len(categories)].id) for i, case in enumerate(out_of_policy)}
    director = ScriptedDirector(replies)
    router = make_router(director)

    refused = []
    for i, case in enumerate(out_of_policy):
        try:
            brief().extract_brief(case["task"], router=router)  # default policy: the shipped config
        except r.TaskRefused as exc:
            expected = categories[i % len(categories)]
            refused.append((case["id"], exc.reason, exc.alternative, expected.reason, expected.alternative))

    assert len(refused) == len(out_of_policy), f"{len(refused)} of {len(out_of_policy)} refused"
    for case_id, reason, alternative, want_reason, want_alternative in refused:
        assert reason.strip() and alternative.strip(), case_id
        assert (reason, alternative) == (want_reason, want_alternative), case_id


def test_FR_INT_12_eval_in_policy_set_is_never_refused():
    """The guard that keeps 100% refused honest: refusing everything would pass the test above."""
    data = load_refusal_set()
    ordinary = data["in_policy"]
    director = ScriptedDirector({case["task"]: director_reply(None) for case in ordinary})
    router = make_router(director)

    for case in ordinary:
        result = brief().extract_brief(case["task"], router=router)
        assert result.brief["goal"], case["id"]


@settings(max_examples=40, deadline=None)
@given(
    text=st.text(min_size=1, max_size=300).filter(lambda t: t.strip() and "\x00" not in t),
    pick=st.sampled_from([None, CATEGORY_A["id"], CATEGORY_B["id"]]),
)
def test_FR_INT_12_property_the_verdict_follows_the_director_and_the_text_comes_from_config(text, pick):
    """Invariant: null means a brief; a category means exactly that category's configured text, whatever the
    task says, and the refusal never contains the task text."""
    r = refusal()
    import tempfile  # noqa: PLC0415

    with tempfile.TemporaryDirectory() as tmp:
        policy = r.load_refusal_policy(write_refusal_config(pathlib.Path(tmp) / "p.yaml", [CATEGORY_A, CATEGORY_B]))
    director = ScriptedDirector({}, default=director_reply(pick))
    router = make_router(director)

    if pick is None:
        assert brief().extract_brief(text, router=router, refusal_policy=policy).brief["goal"]
        return
    with pytest.raises(r.TaskRefused) as raised:
        brief().extract_brief(text, router=router, refusal_policy=policy)
    chosen = CATEGORY_A if pick == CATEGORY_A["id"] else CATEGORY_B
    assert (raised.value.reason, raised.value.alternative) == (chosen["reason"], chosen["alternative"])
