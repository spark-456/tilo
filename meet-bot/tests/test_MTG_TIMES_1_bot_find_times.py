"""Owner 21 Oct ~19:30 (relayed): Tilo finds suitable times for a follow-up, then books the one picked.

The model may ask for `find_times` (no read-back: it reads, it changes nothing). Tilo says "Let me check the
calendars", tilo-api answers up to three free starts, and Tilo offers them in fixed words, saying plainly when the
owner's Google Calendar is not connected and that teammates' Google Calendars are not visible (WT-01). The offered
times go back to the model, so "the second one" becomes an ordinary create_meeting proposal with its read-back and
the spoken yes."""

import asyncio
import json

import httpx
from test_MTG_ACTIONS_1_bot_actions import _brain, _session

from bot import action_talk
from bot.captions import Utterance
from bot.meeting_actions import MeetingActions

FOUND = {
    "outcome": "done",
    "action": "find_times",
    "slots": ["2026-10-22T08:30:00.000Z", "2026-10-23T03:30:00.000Z"],
    "zone": "Asia/Kolkata",
    "google": "ok",
    "teammates": ["Priya Nair"],
    "extra": "dropped",
}


def test_TIMES_the_client_asks_tilo_api_and_keeps_only_the_known_fields():
    asked = []

    def handle(request):
        asked.append(json.loads(request.content)["args"])
        return httpx.Response(200, json=FOUND)

    client = MeetingActions(
        "https://tilo-api.example.run.app",
        "mt_x",
        "c" * 32,
        token_for=lambda a: "t",
        transport=httpx.MockTransport(handle),
    )
    got = client.find_times(30, 7, True)
    assert asked == [{"minutes": 30, "days": 7, "with_team": True}]
    assert got == {k: FOUND[k] for k in ("slots", "zone", "google", "teammates")}
    refused = MeetingActions(
        "https://tilo-api.example.run.app",
        "mt_x",
        "c" * 32,
        token_for=lambda a: "t",
        transport=httpx.MockTransport(lambda r: httpx.Response(409, json={"outcome": "cap_reached"})),
    )
    assert refused.find_times(30, 7, False) is None


def test_TIMES_the_offer_is_in_fixed_words_and_says_what_was_not_checked():
    line = action_talk.times_line(FOUND, {"minutes": 30, "days": 7, "with_team": True})
    assert line.startswith("I can do Thu 22 Oct at 2:00 PM or Fri 23 Oct at 9:00 AM.")
    assert "Tilo calendars" in line and line.endswith("Which one should I schedule?")
    none = action_talk.times_line({**FOUND, "slots": []}, {"minutes": 45, "days": 7, "with_team": False})
    assert none == "I couldn't find a free 45-minute slot in the next 7 days."
    off = action_talk.times_line({**FOUND, "google": "not_connected"}, {"minutes": 30, "days": 7, "with_team": False})
    assert "Google Calendar isn't connected" in off
    alone = action_talk.times_line({**FOUND, "teammates": []}, {"minutes": 30, "days": 7, "with_team": True})
    assert "not on a team" in alone
    assert action_talk.times_line(None, {"minutes": 30, "days": 7, "with_team": False}) == (
        "I couldn't check calendars just now."
    )


def test_TIMES_a_find_times_request_is_checked_at_once_not_read_back():
    ask = {"reply": None, "action": {"name": "find_times", "args": {"minutes": 30, "with_team": True}}}
    b, _ = _brain(ask)
    msg = b.quick_reply([Utterance("Sacheev", "find us a time next week for a 30 minute follow up", 10.0)], 10.0)
    assert msg is not None and msg.text == action_talk.CHECKING_LINE and b.pending_action is None
    assert b.times_wanted == {"minutes": 30, "days": 7, "with_team": True}


def test_TIMES_the_session_offers_the_times_and_the_model_sees_them_next(monkeypatch, tmp_path):
    class Actions:
        def run(self, *a):
            return None

        def find_times(self, minutes, days, with_team):
            return {k: FOUND[k] for k in ("slots", "zone", "google", "teammates")}

    s = _session(monkeypatch, tmp_path, Actions())
    s.brain.times_wanted = {"minutes": 30, "days": 7, "with_team": True}

    async def run():
        s._start_times()
        await asyncio.sleep(0.3)

    asyncio.run(run())
    assert len(s.said) == 1 and s.said[0].startswith("I can do Thu 22 Oct")
    assert s.brain.times_wanted is None
    assert [o["start"] for o in s.brain.offered_times] == FOUND["slots"]
    b = s.brain
    b.llm = __import__("bot.mock_llm", fromlist=["ScriptedLLM"]).ScriptedLLM([json.dumps({"reply": "ok"})])
    b.quick_reply([Utterance("Sacheev", "let's do the second one please", 200.0)], 200.0)
    assert "2026-10-23T03:30:00.000Z" in b.llm.calls[0][1] and "offered_times" in b.llm.calls[0][1]
