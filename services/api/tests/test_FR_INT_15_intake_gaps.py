"""FR-INT-15 (supplement 2026-10-05 section 4, "Best effort before refusal") through `POST /intake` and
`GET /tasks/{id}/approaches`: "A safe request outside what Tilo can fully do gets best effort first: it does what it
can, says plainly what it could not do and offers alternatives. A hard refusal is only for safety or policy."

The Director (scripted, the recorded-replay stand-in, EFF-01) names the parts Tilo cannot do as `out_of_scope` gaps.
The API then answers 201 with `gaps` (configured reason and alternative beside the cleaned label), stores the gaps on
the task, and puts the same lines first in every approach's `skips`. With no possible part it answers 422
`{error, gaps}` (no `category`: it is not a refusal) and stores nothing. A refusal id anywhere is FR-INT-12's
unchanged 422. A bad gap config is 503 before any Director call. Shapes: `packages/planning/tests/API_FR_INT_15.md`.
Planning side: `packages/planning/tests/test_FR_INT_15_*`.
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
REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]


def gap_texts():
    import tilo_planning.gaps as module  # noqa: PLC0415

    return {c.id: c for c in module.load_gap_policy().categories}


def refusal_texts():
    import tilo_planning.refusal as module  # noqa: PLC0415

    return {c.id: c for c in module.load_refusal_policy().categories}


def gap_item(category: str, part: str) -> dict:
    return {"category": category, "part": part}


def gap_brief(gaps, *, ambiguous=(), deliverables=None, out_of_policy=None) -> dict:
    reply = {**brief_reply(list(ambiguous)), "out_of_policy": out_of_policy, "out_of_scope": gaps}
    if deliverables is not None:
        reply["deliverables"] = deliverables
    return reply


def expected_body(*items: tuple[str, str]) -> list[dict]:
    config = gap_texts()
    return [
        {"category": c, "part": p, "reason": config[c].reason, "alternative": config[c].alternative} for c, p in items
    ]


def nothing_stored(flow, artifacts: InMemoryArtifactStore) -> bool:
    return artifacts.list_ids() == [] and not flow.store.tasks and not flow.store.worlds and not flow.store.events


# --- 201: the possible part, with the gaps named ---


def test_FR_INT_15_a_partly_out_of_scope_task_is_201_with_each_gap_and_its_configured_text(clear_flow):
    clear_flow.provider.brief = gap_brief(
        [gap_item("money_movement", "Pay the \u200binvoice."), gap_item("calls_and_chat", "Phone the supplier")]
    )

    response = clear_flow.intake(text=f"Compare the quotes, pay the invoice and phone them {ECHO}")

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["gaps"] == expected_body(
        ("money_movement", "Pay the invoice"), ("calls_and_chat", "Phone the supplier")
    )
    assert "category" not in body and "out_of_scope" not in body["brief"] and "out_of_policy" not in body["brief"]
    assert body["brief"]["deliverables"] == brief_reply([])["deliverables"], "the possible part is the brief"
    assert {"task_id", "world_id", "run_id", "event", "brief", "questions", "files"} <= set(body), "old keys stay"
    assert len(clear_flow.provider.calls) == 1, "best effort costs no extra model call"


def test_FR_INT_15_gaps_is_always_present_and_empty_when_the_whole_task_is_possible(flow_factory):
    for reply in (gap_brief([]), brief_reply([])):  # an empty list and an older reply with no key at all
        flow = flow_factory([])
        flow.provider.brief = reply

        body = flow.new_task()

        assert body["gaps"] == []


def test_FR_INT_15_gap_lines_are_at_most_three_and_a_fourth_is_a_502_that_stores_nothing(clear_flow):
    artifacts = InMemoryArtifactStore()
    clear_flow.app.dependency_overrides[intake_module.get_store] = lambda: artifacts
    items = [gap_item(c, f"Part {i}") for i, c in enumerate(gap_texts()) if i < 4]
    clear_flow.provider.brief = gap_brief(items)

    response = clear_flow.intake(text=f"Do four things I cannot have {ECHO}")

    assert response.status_code == 502 and ECHO not in response.text, "never a truncated list"
    assert nothing_stored(clear_flow, artifacts)
    assert len(clear_flow.provider.calls) == 1, "no repair for a gap list"
    clear_flow.provider.brief = gap_brief([gap_item("physical_world", "Visit the site")])  # control: one gap is fine
    assert clear_flow.intake(text="Visit the site").status_code == 201


@pytest.mark.parametrize("category", ["made_up_category", "Money_Movement", "money_movement "])
def test_FR_INT_15_an_unknown_or_near_miss_gap_id_is_502_stores_nothing_and_is_not_a_refusal(clear_flow, category):
    artifacts = InMemoryArtifactStore()
    clear_flow.app.dependency_overrides[intake_module.get_store] = lambda: artifacts
    clear_flow.provider.brief = gap_brief([gap_item(category, f"Some part {ECHO}")])

    response = clear_flow.intake(text=f"Something odd {ECHO}")

    assert response.status_code == 502 and ECHO not in response.text
    assert "category" not in response.json()
    assert nothing_stored(clear_flow, artifacts)
    clear_flow.provider.brief = gap_brief([gap_item("physical_world", "Visit the site")])  # control: a known id is fine
    assert clear_flow.intake(text="Visit the site").status_code == 201


# --- the task record, and the approaches ---


def test_FR_INT_15_the_task_record_holds_the_gaps_and_answers_and_chip_edits_never_change_them(flow):
    flow.provider.brief = gap_brief([gap_item("physical_world", "Visit the site")], ambiguous=["audience", "deadline"])
    intake = flow.new_task()
    want = expected_body(("physical_world", "Visit the site"))
    assert intake["gaps"] == want
    assert [g.as_dict() for g in flow.store.tasks[intake["task_id"]].gaps] == want

    answers = [{"field": "audience", "answer": "The board of directors"}, {"field": "deadline", "answer": None}]
    edits = {"goal": "Compare three suppliers on landed price."}
    assert flow.answers(intake["task_id"], answers, brief_edits=edits).status_code == 200

    assert [g.as_dict() for g in flow.store.tasks[intake["task_id"]].gaps] == want, "set once, from the extraction"


def test_FR_INT_15_every_approach_starts_with_the_gap_lines_in_the_intake_bodys_order(clear_flow):
    clear_flow.provider.brief = gap_brief(
        [gap_item("money_movement", "Pay the invoice"), gap_item("unsupported_output", "Record a video")]
    )
    intake = clear_flow.new_task()
    lines = [f"Not done: {g['part']}. {g['reason']}" for g in intake["gaps"]]

    response = clear_flow.approaches(intake["task_id"])

    assert response.status_code == 200, response.text
    approaches = response.json()["approaches"]
    assert approaches and all(a["skips"][:2] == lines for a in approaches)
    assert all(len(a["skips"]) <= 5 and all(len(s) <= 200 for s in a["skips"]) for a in approaches)
    assert any("Warranty terms" in a["skips"][2:] for a in approaches), "the model's own skips follow the gap lines"
    assert len(clear_flow.provider.calls) == 2, "one brief call, one approaches call"


def test_FR_INT_15_a_re_proposal_after_a_chip_edit_adds_the_same_gap_lines(flow):
    flow.provider.brief = gap_brief([gap_item("desktop_apps", "Edit the file on my laptop")], ambiguous=["audience"])
    intake = flow.new_task()
    line = f"Not done: {intake['gaps'][0]['part']}. {intake['gaps'][0]['reason']}"
    answers = [{"field": "audience", "answer": None}]
    assert flow.answers(intake["task_id"], answers).status_code == 200
    before = flow.approaches(intake["task_id"]).json()["approaches"]
    assert flow.answers(intake["task_id"], answers, brief_edits={"goal": "A different goal."}).status_code == 200

    after = flow.approaches(intake["task_id"]).json()["approaches"]

    assert all(a["skips"][0] == line for a in before) and all(a["skips"][0] == line for a in after)


def test_FR_INT_15_a_task_with_no_gaps_has_its_approach_skips_unchanged(clear_flow):
    intake = clear_flow.new_task()

    approaches = clear_flow.approaches(intake["task_id"]).json()["approaches"]

    assert intake["gaps"] == [] and [a["skips"] for a in approaches] == [["Warranty terms"], []]


# --- 422: no possible part, and refusals ---


def test_FR_INT_15_no_possible_part_is_422_with_error_and_gaps_only_and_stores_nothing(clear_flow):
    import tilo_planning.gaps as module  # noqa: PLC0415

    artifacts = InMemoryArtifactStore()
    clear_flow.app.dependency_overrides[intake_module.get_store] = lambda: artifacts
    clear_flow.provider.brief = gap_brief([gap_item("calls_and_chat", "Phone my landlord")], deliverables=[])

    response = clear_flow.intake(
        files=[("prices.docx", make_docx_bytes("Ordinary prices."))], text=f"Phone my landlord for me {ECHO}"
    )

    assert response.status_code == 422, response.text
    body = response.json()
    assert set(body) == {"error", "gaps"}, "no category and no alternative key: it is not a refusal"
    assert body["error"] == module.load_gap_policy().nothing_possible
    assert body["gaps"] == expected_body(("calls_and_chat", "Phone my landlord"))
    assert ECHO not in response.text
    assert nothing_stored(clear_flow, artifacts)
    assert len(clear_flow.provider.calls) == 1, "no further model call"


def test_FR_INT_15_a_refusal_id_in_the_gap_list_is_fr_int_12s_unchanged_422(clear_flow):
    chosen = refusal_texts()["deception"]
    artifacts = InMemoryArtifactStore()
    clear_flow.app.dependency_overrides[intake_module.get_store] = lambda: artifacts
    clear_flow.provider.brief = gap_brief(
        [gap_item("money_movement", "Pay"), gap_item("deception", f"Fake reviews {ECHO}")], out_of_policy=None
    )

    response = clear_flow.intake(text=f"Write fake reviews {ECHO}")

    assert response.status_code == 422
    assert response.json() == {"error": chosen.reason, "alternative": chosen.alternative, "category": "deception"}
    assert ECHO not in response.text and nothing_stored(clear_flow, artifacts)
    assert len(clear_flow.provider.calls) == 1


def test_FR_INT_15_a_refusal_wins_over_a_safe_part_and_valid_gaps_in_the_same_reply(clear_flow):
    chosen = refusal_texts()["credential_handling"]
    clear_flow.provider.brief = gap_brief([gap_item("money_movement", "Pay")], out_of_policy="credential_handling")

    response = clear_flow.intake(text="Log in with my password and summarise the prices.")

    assert response.status_code == 422 and response.json()["category"] == "credential_handling"
    assert response.json()["error"] == chosen.reason and "gaps" not in response.json()


# --- 503: an unusable gap config ---


@pytest.mark.parametrize(
    "content",
    [None, "", "nothing_possible: ok\ncategories: []\n", "categories: [unclosed", "just: a mapping\n"],
    ids=["missing", "empty", "no categories", "bad yaml", "wrong keys"],
)
def test_FR_INT_15_an_unusable_gap_config_is_503_stores_nothing_and_asks_the_model_nothing(
    clear_flow, monkeypatch, tmp_path, content
):
    import tilo_planning.gaps as module  # noqa: PLC0415

    path = pathlib.Path(tmp_path) / "capability_gaps.yaml"
    if content is not None:
        path.write_text(content, encoding="utf-8")
    monkeypatch.setattr(module, "DEFAULT_GAP_CONFIG", path)
    artifacts = InMemoryArtifactStore()
    clear_flow.app.dependency_overrides[intake_module.get_store] = lambda: artifacts

    response = clear_flow.intake(text=f"Summarise the weekly supplier prices {ECHO}")

    assert response.status_code == 503 and ECHO not in response.text
    assert nothing_stored(clear_flow, artifacts)
    assert len(clear_flow.provider.calls) == 0, "a bad gap config is found before the Director is asked"


def test_FR_INT_15_a_gap_id_shared_with_a_refusal_id_is_503_before_any_director_call(clear_flow, monkeypatch, tmp_path):
    import tilo_planning.gaps as module  # noqa: PLC0415

    config = yaml.safe_load((REPO_ROOT / "config" / "capability_gaps.yaml").read_text(encoding="utf-8"))
    config["categories"][0]["id"] = "deception"  # also an out_of_policy id
    path = pathlib.Path(tmp_path) / "capability_gaps.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    monkeypatch.setattr(module, "DEFAULT_GAP_CONFIG", path)
    artifacts = InMemoryArtifactStore()
    clear_flow.app.dependency_overrides[intake_module.get_store] = lambda: artifacts

    response = clear_flow.intake(text=f"Summarise the weekly supplier prices {ECHO}")

    assert response.status_code == 503 and ECHO not in response.text
    assert nothing_stored(clear_flow, artifacts) and len(clear_flow.provider.calls) == 0


@pytest.mark.parametrize("text", ["", "   "])
def test_FR_INT_15_limits_still_come_first_an_empty_task_is_the_old_422_with_no_gaps_and_no_model_call(
    clear_flow, text
):
    clear_flow.provider.brief = gap_brief([gap_item("money_movement", "Pay")])

    response = clear_flow.intake(text=text)

    assert response.status_code == 422 and "gaps" not in response.json() and "category" not in response.json()
    assert len(clear_flow.provider.calls) == 0
