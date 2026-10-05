"""FR-INT-12 (PRD 7.1, 16) through `POST /intake`: "Out-of-policy tasks are refused with the reason and the nearest
task Tilo can do." Acceptance: "Eval refusal set: 100% refused with an alternative offered."

The Director (scripted, the recorded-replay stand-in, EFF-01) names a category of `config/out_of_policy.yaml` or
null; the API turns a category into 422 `{"error": <reason>, "alternative": <nearest task>, "category": <id>}`, text
only from config, and stores nothing: no artifact, task, world or event, and no model call after the Director's.
Shapes: `packages/planning/tests/API_FR_INT_11_12.md`. Planning side: `packages/planning/tests/test_FR_INT_12_*`.
"""

from __future__ import annotations

import pathlib

import pytest
import yaml
from _api_contracts_lib import make_docx_bytes
from _clint1_lib import brief_reply
from tilo_api import intake as intake_module
from tilo_planning.artifacts import InMemoryArtifactStore

ECHO = "ECHOME-zq7"
REFUSAL_SET = (
    pathlib.Path(__file__).resolve().parents[3] / "packages" / "planning" / "tests" / "fixtures" / "refusal_set.yaml"
)


def categories():
    from tilo_planning.refusal import load_refusal_policy  # noqa: PLC0415

    return list(load_refusal_policy().categories)


def refused_reply(category_id: str | None) -> dict:
    return {**brief_reply([]), "out_of_policy": category_id}


def nothing_stored(flow, artifacts: InMemoryArtifactStore) -> bool:
    return artifacts.list_ids() == [] and not flow.store.tasks and not flow.store.worlds and not flow.store.events


def test_FR_INT_12_an_out_of_policy_task_is_refused_with_the_reason_and_the_nearest_task(clear_flow):
    chosen = categories()[0]
    clear_flow.provider.brief = refused_reply(chosen.id)

    response = clear_flow.intake(text=f"Log in to my bank with my password {ECHO}")

    assert response.status_code == 422, response.text
    body = response.json()
    assert body["error"] == chosen.reason and body["alternative"] == chosen.alternative
    assert body["category"] == chosen.id
    assert body["error"].strip() and body["alternative"].strip()


def test_FR_INT_12_a_refusal_stores_nothing_and_asks_the_model_nothing_more(clear_flow):
    artifacts = InMemoryArtifactStore()
    clear_flow.app.dependency_overrides[intake_module.get_store] = lambda: artifacts
    clear_flow.provider.brief = refused_reply(categories()[0].id)

    response = clear_flow.intake(files=[("prices.docx", make_docx_bytes("Ordinary prices."))])

    assert response.status_code == 422
    assert nothing_stored(clear_flow, artifacts), "a refused task leaves no artifact, task, world or event"
    assert len(clear_flow.provider.calls) == 1, "only the Director's brief call: no questions, no approaches"


def test_FR_INT_12_a_refusal_never_quotes_the_task_or_the_model(clear_flow):
    clear_flow.provider.brief = refused_reply(categories()[0].id)

    response = clear_flow.intake(text=f"Pay it now and do not ask me {ECHO}")

    assert response.status_code == 422 and ECHO not in response.text


def test_FR_INT_12_an_in_policy_task_is_not_refused_whether_the_key_is_null_or_absent(flow_factory):
    for reply in (refused_reply(None), brief_reply([])):  # the older reply shape has no out_of_policy key
        flow = flow_factory([])
        flow.provider.brief = reply

        body = flow.new_task()

        assert body["task_id"] and "category" not in body


def test_FR_INT_12_an_unknown_category_fails_closed_and_stores_nothing(clear_flow):
    artifacts = InMemoryArtifactStore()
    clear_flow.app.dependency_overrides[intake_module.get_store] = lambda: artifacts
    clear_flow.provider.brief = refused_reply(categories()[0].id)
    assert (
        clear_flow.intake(text="Anything").status_code == 422
    )  # a known category is a refusal (so 502 below is not it)
    clear_flow.provider.brief = refused_reply("made_up_category")

    response = clear_flow.intake(text=f"Something odd {ECHO}")

    assert response.status_code == 502 and ECHO not in response.text  # like any unusable Director reply
    assert nothing_stored(clear_flow, artifacts)


def test_FR_INT_12_eval_refusal_set_is_100_percent_refused_with_an_alternative_offered(clear_flow):
    data = yaml.safe_load(REFUSAL_SET.read_text(encoding="utf-8"))
    cases, cats = data["out_of_policy"], categories()
    assert len(cases) >= 20
    artifacts = InMemoryArtifactStore()
    clear_flow.app.dependency_overrides[intake_module.get_store] = lambda: artifacts

    refused = 0
    for i, case in enumerate(cases):
        expected = cats[i % len(cats)]
        clear_flow.provider.brief = refused_reply(expected.id)  # what the replayed Director says for this task
        before = len(clear_flow.provider.calls)

        response = clear_flow.intake(text=case["task"])

        body = response.json()
        ok = response.status_code == 422 and body.get("error") == expected.reason
        ok = ok and body.get("alternative") == expected.alternative and bool(body["alternative"].strip())
        assert ok, f"{case['id']}: {response.status_code} {response.text}"
        assert len(clear_flow.provider.calls) == before + 1, case["id"]
        refused += 1

    assert refused == len(cases), f"{refused} of {len(cases)} refused"
    assert nothing_stored(clear_flow, artifacts)


def test_FR_INT_12_eval_in_policy_set_is_never_refused_through_the_api(flow_factory):
    data = yaml.safe_load(REFUSAL_SET.read_text(encoding="utf-8"))
    flow = flow_factory([])
    flow.provider.brief = refused_reply(None)

    for case in data["in_policy"]:
        response = flow.intake(text=case["task"])

        assert response.status_code == 201, f"{case['id']}: {response.text}"


@pytest.mark.parametrize("text", ["", "   "])
def test_FR_INT_12_limits_still_come_first_an_empty_task_is_the_old_422_not_a_refusal(clear_flow, text):
    clear_flow.provider.brief = refused_reply(categories()[0].id)

    response = clear_flow.intake(text=text)

    assert response.status_code == 422 and "category" not in response.json()
    assert len(clear_flow.provider.calls) == 0
