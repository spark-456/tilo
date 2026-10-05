"""FR-HIL-10, issue #338 (Opus review of PR #336; PRD 10.3 "Every card has a timeout and a safe default; the
Director applies the default", 10.6 "answering resumes the agent in <= 2 s", 8.3). Harness half; the API half (merged
cards, a commit-then-raise followed by another answer, a tick failure after a committed default) is
services/api/tests/test_FR_HIL_10_merged_cards_and_claim_races.py.

QuestionWait claims a card's resolution before it writes it. (a) A person's answer claims the card, the deadline
passes while that write is in flight (the deadline task sees the claim and ends), then the write FAILS and the claim
is released: nothing is left to apply the default, so the waiting unit would wait for ever for an answer that never
came. The default must still fire (the deadline is the card's own safe net, PRD 10.3).

Option ids: `Ask.confirms` and `MustAsk.confirmation` both read the answer's option id. "o01" is not the id "o1":
`confirms` reads it as a choice other than the suggested one, `confirmation` reads it as the first option, so the
model's suggested option (which holds the unit) asks for a confirmation when written "o01". Default applied (the PRD
names no id format; the card builder emits o1, o2, o3): an id is exactly "o<n>" or it is not an option at all. These
tests allow either fix for "o01" (rejected by both, or read as "o1" by both) and require that both agree.
"""

from __future__ import annotations

import asyncio
import threading

import pytest
from conftest import make_memory_writer
from hil_wait_support import (
    DIRECTOR,
    DISTRICT,
    LEAD,
    WORLD,
    FakeAsyncClock,
    answered_part,
    events_of,
    layout,
    make_card,
    settle,
    until,
)
from tilo_harness.config import load_agents_config
from tilo_harness.must_ask import Ask, MustAsk
from tilo_harness.question_wait import Answer, QuestionWait

# --------------------------------------------------------------------------------------------------------------------
# (a) a person's answer claims the card, its write fails after the deadline: the default must still fire


class _FailingPersonWriter:
    """The real writer, except that a person's answer blocks inside `emit` until released and then fails (nothing
    committed). Every other event (the harness's own default) goes through."""

    def __init__(self, inner):
        self._inner = inner
        self.entered, self.release = threading.Event(), threading.Event()

    def emit(self, **kwargs):
        if kwargs["data"]["answered_by"] == "person":
            self.entered.set()
            self.release.wait(timeout=10)
            raise RuntimeError("the write failed")
        return self._inner.emit(**kwargs)

    def __getattr__(self, name):
        return getattr(self._inner, name)


def test_FR_HIL_10_a_failed_answer_write_that_outlived_the_deadline_still_gets_the_default() -> None:
    async def go():
        inner, store = make_memory_writer(layout(), world_id=WORLD)
        writer, clock = _FailingPersonWriter(inner), FakeAsyncClock()
        wait = QuestionWait(writer, clock=clock)
        card = make_card(timeout=3600, safe_default="per_kwh")
        task = asyncio.ensure_future(wait.wait_for(card, lead=LEAD, director=DIRECTOR, district=DISTRICT))
        await until(lambda: clock.pending_sleepers() >= 1 or task.done())

        write = asyncio.ensure_future(
            asyncio.to_thread(wait.write, answered_part(card, by="person", option="per_pack"))
        )
        await until(writer.entered.is_set)  # the person's answer holds the claim
        clock.advance(3600)  # the deadline passes while that write is in flight
        await settle()
        writer.release.set()
        with pytest.raises(RuntimeError):
            await write  # the person's write failed and nothing was committed
        for _ in range(300):  # up to 3 s of real time for the default to fire
            if task.done():
                break
            await asyncio.sleep(0.01)
        done = task.done()
        outcome = task.result() if done and not task.exception() else None
        if not done:
            task.cancel()
        return done, outcome, store, card

    done, outcome, store, card = asyncio.run(go())

    assert done, "the card's deadline passed and its only answer failed: the default must still resume the unit"
    assert outcome == Answer(card_id=card["id"], option="per_kwh", answered_by="default")
    answered = events_of(store, "question.answered")
    assert [(e["data"]["answered_by"], e["severity"], e["actor"], e["target"]) for e in answered] == [
        ("default", "nudge", DIRECTOR, LEAD)
    ], "one question.answered, the Director's default nudge; the failed person's write left no event"


# --------------------------------------------------------------------------------------------------------------------
# Ask.confirms and MustAsk.confirmation read option ids the same way


def _must_ask() -> MustAsk:
    return MustAsk({}, config=load_agents_config(), card_sink=lambda card: None)


def _ask(suggested: int) -> Ask:
    return Ask(
        "sensitive_step",
        "Pay the outstanding invoice?",
        ("Hold the payment", "Pay the full amount"),
        suggested,
        "Hold first.",
    )


def _answer(option: str) -> Answer:
    return Answer(card_id="c1", option=option, answered_by="person")


@pytest.mark.parametrize("suggested", [0, 1])
@pytest.mark.parametrize("option", ["o1", "o2", "o01", "o02", "o001"])
def test_FR_HIL_10_confirms_and_confirmation_agree_on_every_option_id(suggested, option) -> None:
    ask, answer = _ask(suggested), _answer(option)

    confirmation = _must_ask().confirmation(ask, answer)

    assert ask.confirms(answer) == (confirmation is not None), (
        f"option {option!r} (suggested o{suggested + 1}): confirms() says {ask.confirms(answer)}, "
        f"confirmation() says {confirmation is not None}"
    )


@pytest.mark.parametrize(("suggested", "option"), [(0, "o01"), (1, "o02"), (0, "o001"), (1, "o0002")])
def test_FR_HIL_10_an_option_id_with_leading_zeros_never_turns_the_suggested_hold_into_a_confirmation(
    suggested, option
) -> None:
    """ "o01" names the suggested option "o1" (or nothing): either way the model's suggestion holds the unit, so no
    confirmation card is raised and `confirms` is false. It must never read as a different choice than "o1"."""
    ask, answer = _ask(suggested), _answer(option)

    assert ask.confirms(answer) is False, (
        f"{option!r} must not be treated as a choice other than the suggested o{suggested + 1}"
    )
    assert _must_ask().confirmation(ask, answer) is None
    assert ask.runs(answer) is False, "a model-raised sensitive_step answer never runs the unit on its own"


def test_FR_HIL_10_the_plain_ids_still_behave_as_pinned() -> None:
    """Regression guard: the suggested option holds (no card); the other one asks code's confirmation."""
    ask = _ask(0)
    assert ask.confirms(_answer("o1")) is False and _must_ask().confirmation(ask, _answer("o1")) is None
    assert ask.confirms(_answer("o2")) is True
    card = _must_ask().confirmation(ask, _answer("o2"))
    assert card is not None and card.reason == "sensitive_step" and "Pay the full amount" in card.question
