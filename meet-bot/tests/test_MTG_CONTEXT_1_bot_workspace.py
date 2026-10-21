"""Owner 21 Oct ~19:30 (relayed): Tilo answers from the call AND the owner's Tilo workspace ("what's on my board", "what
are we working on", "who's on the team"), read-only, through tilo-api's meeting actions route (action `context`).

The client keeps only the known fields, each cut short, so a large or odd answer never reaches the model. The model
sees the workspace only when it was fetched for the call as it is now: a one-on-one answer (personal items) is never
used once someone else has joined. The session refreshes it in the background, never on the answer path."""

import asyncio
import json
import logging

import httpx
from test_MTG_ACTIONS_1_bot_actions import _brain, _session

from bot.brain import QUICK_PROMPT, QUICK_PROMPT_ACTIONS
from bot.captions import Utterance
from bot.meeting_actions import MeetingActions

FULL = {
    "you": "Sacheev",
    "role": "member",
    "teams": [{"name": "Launch", "lead": True, "secret": "x"}],
    "teammates": [{"name": "Priya Nair", "lead": False}],
    "pins": [{"title": "Unfinished demo video", "board": "personal", "body": "never sent on"}],
    "meetings": [{"title": "Launch review", "start": "2026-10-22T09:00:00.000Z", "status": "scheduled"}],
    "worlds": [{"title": "Launch plan", "status": "completed"}],
    "email": "someone@example.com",
}


def _client(handle):
    return MeetingActions(
        "https://tilo-api.example.run.app",
        "mt_x",
        "c" * 32,
        token_for=lambda aud: "id.token.x",
        transport=httpx.MockTransport(handle),
    )


def test_CONTEXT_the_client_asks_for_the_owners_context_and_keeps_only_known_fields(caplog):
    asked = []

    def handle(request):
        body = json.loads(request.content)
        asked.append((body["action"], body["args"], body["speaker"]))
        return httpx.Response(200, json={"outcome": "done", "action": "context", "context": FULL})

    with caplog.at_level(logging.WARNING, logger="bot.cloud_run"):
        got = _client(handle).context(True)
    assert asked == [("context", {"one_on_one": True}, None)]  # never a speaker: always the owner's view
    assert set(got) == {"you", "role", "teams", "teammates", "pins", "meetings", "worlds"}  # no "email"
    assert got["teams"] == [{"name": "Launch", "lead": True}] and "body" not in got["pins"][0]
    assert [r.getMessage() for r in caplog.records] == ["stage workspace scope=one_on_one ok=True"]


def test_CONTEXT_a_refused_or_failed_read_gives_nothing():
    assert _client(lambda r: httpx.Response(409, json={"outcome": "not_attending"})).context(False) is None
    assert _client(lambda r: httpx.Response(503, json={"outcome": "unavailable"})).context(True) is None
    assert _client(lambda r: httpx.Response(200, json={"outcome": "done", "context": "nope"})).context(True) is None


def test_CONTEXT_the_model_sees_the_workspace_only_for_the_call_as_it_is_now():
    b, llm = _brain({"reply": "Your board has the unfinished demo video."}, {"reply": "Nothing I can share."})
    b.workspace = (True, {"pins": [{"title": "Unfinished demo video", "board": "personal"}]})
    b.quick_reply([Utterance("Sacheev", "what's on my board right now", 10.0)], 10.0)
    assert "Unfinished demo video" in llm.calls[0][1]
    b.sole_human = False  # someone joined: the one-on-one answer is not used
    b.quick_reply([Utterance("Sacheev", "Tilo, what's on my board right now?", 40.0)], 40.0)
    assert "Unfinished demo video" not in llm.calls[1][1]


def test_CONTEXT_the_prompt_says_what_the_workspace_is_in_both_modes():
    for prompt in (QUICK_PROMPT, QUICK_PROMPT_ACTIONS):
        assert "workspace" in prompt


def test_CONTEXT_the_session_refreshes_in_the_background_and_again_when_the_call_changes(monkeypatch, tmp_path):
    asked = []

    class Actions:
        def run(self, *a):
            return None

        def context(self, one_on_one):
            asked.append(one_on_one)
            return {"pins": [], "teams": [], "teammates": []}

    s = _session(monkeypatch, tmp_path, Actions())
    s.gate_at = 0.0

    async def run():
        s._maybe_refresh_workspace(100.0)
        await asyncio.sleep(0.2)
        s._maybe_refresh_workspace(101.0)  # fresh and same call: no second read
        await asyncio.sleep(0.1)
        s.brain.sole_human = False
        s._maybe_refresh_workspace(102.0)  # someone joined: read again, group scope
        await asyncio.sleep(0.2)

    asyncio.run(run())
    assert asked == [True, False] and s.brain.workspace[0] is False
