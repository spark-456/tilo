"""With meeting actions on, a claim Tilo can back is said in fixed words, and one it cannot back is never said.

The no-false-claims guard (21 Oct 09:22) replaced every "I've added ..." with "I can't do that from a call yet". After
a confirmed action that line contradicts what just happened: asked "did you add it?", the model says "Yes, I've added
it" and the guard denied it. Now the guard keeps the rule (the model never claims an action) but answers a claim about an
action tilo-api confirmed this call with that action's own fixed words; any other claim gets "I haven't done that yet"
with actions on, and the old line with actions off."""

import json

from test_MTG_ACTIONS_1_bot_actions import _brain

from bot import action_talk
from bot.brain import CANT_DO_LINE, NOT_DONE_LINE
from bot.captions import Utterance
from bot.mock_llm import ScriptedLLM


def _done(b, name="add_agenda_item", args=None):
    b.done_actions.append(action_talk.PendingAction("Asha Rao", None, name, args or {"title": "Demo video"}))


def _ask(b, text, t, reply):
    b.llm = ScriptedLLM([json.dumps({"reply": reply})])
    msg = b.quick_reply([Utterance("Asha Rao", text, t)], t)
    if msg is not None:
        b.commit_chat(msg, t)
    return msg


def test_TRUE_CLAIMS_did_you_add_it_after_a_confirmed_action_is_answered_with_the_fact():
    b, _ = _brain()
    _done(b)
    msg = _ask(b, "did you add it to the agenda", 10.0, "Yes, I've added it.")
    assert msg.text == 'Yes, "Demo video" is on this meeting\'s agenda.'


def test_TRUE_CLAIMS_a_claim_naming_a_confirmed_item_gets_its_fixed_words_not_the_models():
    b, _ = _brain()
    _done(b, "create_pin", {"title": "Submission checklist", "board": "team"})
    msg = _ask(b, "what did you just do", 10.0, "I pinned Submission checklist to the team board and emailed everyone.")
    assert msg.text == 'Yes, "Submission checklist" is pinned to your team board.'  # never the invented email


def test_TRUE_CLAIMS_a_claim_with_nothing_confirmed_is_never_said_with_actions_on():
    b, _ = _brain()
    msg = _ask(b, "can you add the budget review to the agenda", 10.0, "Sure, I'll add the budget review now.")
    assert msg.text == NOT_DONE_LINE and "haven't" in NOT_DONE_LINE
    _done(b)
    other = _ask(b, "please schedule the launch sync", 40.0, "I've scheduled the launch sync for Friday.")
    assert other.text == NOT_DONE_LINE  # a confirmed agenda item does not back an unrelated claim


def test_TRUE_CLAIMS_with_actions_off_the_old_line_stays():
    b, _ = _brain(actions=False)
    _done(b)
    assert _ask(b, "did you add it to the agenda", 10.0, "Yes, I've added it.").text == CANT_DO_LINE


def test_TRUE_CLAIMS_after_a_confirmed_agenda_item_tilo_never_says_there_is_no_agenda():
    b, _ = _brain()
    assert _ask(b, "what's on the agenda", 10.0, "unused").text == "There's no agenda set for this meeting yet."
    _done(b)
    assert _ask(b, "what's on the agenda now", 40.0, "unused").text == (
        'I added "Demo video" to this meeting\'s agenda in this call.'
    )


def test_TRUE_CLAIMS_the_session_records_only_confirmed_actions(monkeypatch, tmp_path):
    import asyncio  # noqa: PLC0415

    from test_MTG_ACTIONS_1_bot_actions import _session  # noqa: PLC0415

    from bot.meeting_actions import ActionResult  # noqa: PLC0415

    results = iter([ActionResult(False, "unavailable", {}), ActionResult(True, "done", {})])
    s = _session(monkeypatch, tmp_path, type("A", (), {"run": lambda self, *a: next(results)})())

    async def run():
        for t in (20.0, 40.0):
            s.brain.pending_action = action_talk.PendingAction("Asha Rao", None, "add_agenda_item", {"title": f"t{t}"})
            s.record(Utterance("Asha Rao", "yes", t))
            await asyncio.sleep(0.2)

    asyncio.run(run())
    assert [a.args["title"] for a in s.brain.done_actions] == ["t40.0"]
