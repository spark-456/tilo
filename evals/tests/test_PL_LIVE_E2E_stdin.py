"""CLI line ownership and approach recovery, without a live switch or provider calls."""

from __future__ import annotations

import io
from typing import Any

import pytest
from tilo_evals import live_topic


def offered() -> dict[str, Any]:
    return {
        "recommended": "first",
        "approaches": [
            {"id": key, "label": key, "summary": "A proposed plan", "credits": {"min": 1, "max": 2}}
            for key in ("first", "second")
        ],
    }


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_PL_LIVE_E2E_topic_and_each_prompt_consume_their_own_line(
    monkeypatch: pytest.MonkeyPatch,
    newline: str,
) -> None:
    stream = io.TextIOWrapper(io.BytesIO(newline.join(["A team note", "", "1", "", "2", "y", "", ""]).encode()))
    monkeypatch.setattr("sys.stdin", stream)
    seen: list[str] = []

    def fake_run(topic: str, **kwargs: Any) -> None:
        assert kwargs["mode"] == "dry-run"
        seen.append(topic)
        person = kwargs["person"]
        assert person.answer({"field": "deliverables", "text": "What?", "suggested_answers": ["A note"]}) == "A note"
        assert person.answer({"field": "constraints", "text": "Limits?"}) is None
        assert person.approach(offered()) == "second"
        assert person.log[-1] == "approach second: approved by the person (-)"
        assert stream.read() == ""

    monkeypatch.setattr(live_topic, "run_topic", fake_run)
    assert live_topic.main(["--topic-stdin", "--dry-run"], environ={}) == 0
    assert seen == ["A team note"]


@pytest.mark.parametrize("ending", ["", "\n", "\n\n"])
def test_PL_LIVE_E2E_piped_topic_ends_at_eof_or_blank(monkeypatch: pytest.MonkeyPatch, ending: str) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("A note\nfor the team" + ending))
    assert live_topic._typed(input) == "A note\nfor the team"


@pytest.mark.parametrize("number", ["2", "9"])
def test_PL_LIVE_E2E_number_at_confirmation_reasks_approach(number: str) -> None:
    answers = iter(["", number, "2", "y", "why", "next line"])
    prompts: list[str] = []

    def read(prompt: str) -> str:
        prompts.append(prompt)
        return next(answers)

    person = live_topic.TerminalPerson(read=read, write=lambda _: None)
    assert person.approach(offered()) == "second"
    assert sum(p.startswith("approach number") for p in prompts) == 2
    assert "'second'" in prompts[-2]
    assert person.log == ["approach second: approved by the person (why)"]
    assert next(answers) == "next line"


@pytest.mark.parametrize("confirmation,result", [("yes", "second"), ("no", None)])
def test_PL_LIVE_E2E_bad_confirmation_reprompts_without_consuming_reason(
    confirmation: str,
    result: str | None,
) -> None:
    answers = iter(["2", "maybe", confirmation, "because", "next line"])
    messages: list[str] = []
    person = live_topic.TerminalPerson(read=lambda _: next(answers), write=messages.append)
    assert person.approach(offered()) == result
    assert "answer y or n" in messages
    assert "because" in person.log[-1]
    assert next(answers) == "next line"


def test_PL_LIVE_E2E_closed_input_after_number_declines() -> None:
    answers = iter(["", "2"])

    def read(_: str) -> str:
        try:
            return next(answers)
        except StopIteration:
            raise EOFError from None

    person = live_topic.TerminalPerson(read=read, write=lambda _: None)
    assert person.approach(offered()) is None
    assert "input closed" in person.decline_reason
