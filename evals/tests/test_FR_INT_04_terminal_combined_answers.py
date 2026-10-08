"""FR-INT-04 (PRD 7.1), live-run refusal of 8 Oct 2026: at the terminal a person typed "1 and 2" for the deliverables
question and the run ended `refused`. The terminal now reads "1 and 2", "1,2" or "1 2" as both options, and answers the
brief refuses (422) are asked again, a bounded number of times, instead of ending the run. Fakes only, no network.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from tilo_evals import bank_run
from tilo_evals.bank import BankCase
from tilo_evals.live_topic import TerminalPerson

OPTIONS = ["Report (pdf)", "A PDF report", "A slide deck"]
QUESTION = {"field": "deliverables", "text": "What should Tilo deliver?", "suggested_answers": OPTIONS}


def _person(said: list[str]) -> tuple[TerminalPerson, list[str]]:
    shown: list[str] = []
    queue = list(said)

    def read(_prompt: str) -> str:
        if not queue:
            raise EOFError
        return queue.pop(0)

    return TerminalPerson(read=read, write=shown.append, tty=lambda: False), shown


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("1 and 2", "Report (pdf); A PDF report"),
        ("1,2", "Report (pdf); A PDF report"),
        ("1, 3", "Report (pdf); A slide deck"),
        ("1 2", "Report (pdf); A PDF report"),
        ("2 & 3", "A PDF report; A slide deck"),
        ("1 and 1", "Report (pdf)"),
        ("1", "Report (pdf)"),
        ("a slide deck", "a slide deck"),
        ("", "Report (pdf)"),
    ],
)
def test_FR_INT_04_the_terminal_reads_several_numbers_as_several_options(typed, expected):
    person, _ = _person([typed])

    assert person.answer(QUESTION) == expected


def test_FR_INT_04_a_number_outside_the_list_asks_again_instead_of_guessing():
    person, shown = _person(["1 and 9", "1 and 2"])

    assert person.answer(QUESTION) == "Report (pdf); A PDF report"
    assert any("pick numbers from 1 to 3" in line for line in shown)


def test_FR_INT_04_only_a_question_that_can_name_several_takes_a_list():
    person, _ = _person(["1 and 2"])

    goal = {"field": "goal", "text": "What should this achieve?", "suggested_answers": ["Win", "Describe"]}
    assert person.answer(goal) == "1 and 2", "a goal is one thing: the words go through and the brief decides"


def test_FR_INT_04_a_long_joined_answer_is_cut_on_a_part_boundary():
    long_current = "x" * 295
    person, _ = _person(["1 and 2"])

    question = {"field": "deliverables", "text": "?", "suggested_answers": [long_current, "A PDF report"]}
    assert person.answer(question) == long_current, (
        "the second part would pass the route's 300 limit: it is dropped whole"
    )


def _app(statuses: list[int], seen: list[Any]) -> FastAPI:
    from tilo_api import deps

    app = FastAPI()

    @app.post("/intake")
    def intake() -> dict[str, Any]:
        return {"world_id": "w_1", "task_id": "t_1", "questions": [QUESTION]}

    @app.post("/tasks/t_1/answers")
    async def answers(request: Request) -> JSONResponse:
        seen.append((await request.json())["answers"][0]["answer"])
        status = statuses.pop(0) if statuses else 200
        body = {"detail": "That change does not fit the brief: Name the format."} if status == 422 else {"brief": {}}
        return JSONResponse(body, status_code=status)

    @app.get("/tasks/t_1/approaches")
    def approaches() -> JSONResponse:
        return JSONResponse({"detail": "stop here"}, status_code=502)

    store = SimpleNamespace(events={}, runs={})
    app.dependency_overrides[deps.get_store] = lambda: store
    app.dependency_overrides[deps.get_connector_adapters] = lambda: {}
    return app


def _case() -> BankCase:
    return BankCase(
        id="T-1", title="t", domain="d", shapes=(), brief="a brief", director={}, expect={"outcome": "refused"},
        path=Path("none"),
    )  # fmt: skip


def test_FR_INT_04_answers_the_brief_refuses_are_asked_again_not_the_end_of_the_run():
    seen: list[Any] = []
    person, shown = _person(["banana", "1 and 2"])
    obs = bank_run.Observation(_case())

    bank_run.drive(_case(), obs, 10.0, _app([422], seen), person=person)

    assert seen == ["banana", "Report (pdf); A PDF report"], "asked again, and the second answer went through"
    assert any("did not fit the brief" in line and "Please answer again" in line for line in shown)
    assert [h[2] for h in obs.http if h[1].endswith("/answers")] == [422, 200]
    assert obs.reason == "stop here", "the run went on to the approaches, which is where this fake stops"


def test_FR_INT_04_a_person_who_keeps_giving_answers_the_brief_refuses_is_stopped_after_a_bounded_number_of_asks():
    seen: list[Any] = []
    person, _ = _person(["banana"] * 10)
    obs = bank_run.Observation(_case())

    bank_run.drive(_case(), obs, 10.0, _app([422] * 10, seen), person=person)

    assert len(seen) == bank_run.MAX_REASKS + 1
    assert obs.outcome == "refused" and "does not fit the brief" in str(obs.reason)


def test_FR_INT_04_a_scripted_run_without_a_person_is_refused_once_as_before():
    seen: list[Any] = []
    obs = bank_run.Observation(_case())
    case = _case()
    case = BankCase(**{**case.__dict__, "answers": {"deliverables": "banana"}})

    bank_run.drive(case, obs, 10.0, _app([422], seen))

    assert seen == ["banana"] and obs.outcome == "refused"


@pytest.mark.parametrize(
    "typed",
    [" " * 3_000, "1" + " " * 3_000 + "x", "1 " * 1_500],
    ids=["spaces", "digit-then-spaces", "digit-space-pairs"],
)
def test_FR_INT_04_a_long_run_of_spaces_at_the_terminal_is_read_quickly(typed):
    import time

    started = time.perf_counter()
    person, _ = _person([typed, ""])
    person.answer(QUESTION)
    assert time.perf_counter() - started < 1.0


def test_FR_INT_04_digits_separated_by_more_than_one_space_are_still_a_list():
    person, _ = _person(["1   2"])

    assert person.answer(QUESTION) == "Report (pdf); A PDF report"


def test_FR_INT_04_a_declined_approach_with_a_reason_asks_for_one_revised_set():
    calls: list[tuple[str, dict[str, Any]]] = []
    person, _ = _person(["", "n", "It does not cover old papers"])
    offered = {
        "approaches": [{"id": "a1", "label": "A", "summary": "s", "credits": {"min": 1, "max": 2}}],
        "recommended": "a1",
    }
    assert person.approach(offered) is None
    assert person.decline_reason == "It does not cover old papers"

    def call(method: str, path: str, **kw: Any) -> Any:
        calls.append((path, kw.get("json", {})))
        return SimpleNamespace(status_code=200, json=lambda: {"brief": {"constraints": ["x"]}})

    assert bank_run._revise(call, {"task_id": "t"}, person) is True
    edits = calls[-1][1]["brief_edits"]["constraints"]
    assert edits == ["x", "Must address: It does not cover old papers"]


def test_FR_INT_04_a_declined_approach_without_a_reason_is_not_revised():
    person = SimpleNamespace(decline_reason="")

    assert bank_run._revise(lambda *a, **k: 1 / 0, {"task_id": "t"}, person) is False
