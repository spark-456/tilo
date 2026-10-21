"""ADR-0042 amendment 1 (owner decision 21 Oct, BQ-MTG-ACTIONS-1): the bot side of meeting actions.

The model only proposes one of three actions; Tilo reads it back in fixed words; only the same speaker's yes (anyone
one-on-one) within the window sends it to tilo-api; Tilo says "done" only when tilo-api confirmed it, and a failed or
refused call never yields a success claim. Off (no actions client), the old "I can't do that from a call yet" stays."""

import asyncio
import json
import time
from types import SimpleNamespace

import httpx

from bot import action_talk
from bot.brain import NO_ACTIONS_TEXT, QUICK_PROMPT, QUICK_PROMPT_ACTIONS, Agenda, Brain
from bot.captions import Utterance
from bot.meeting_actions import ActionResult, MeetingActions, actions_from_env
from bot.mock_llm import ScriptedLLM
from bot.wake import WakeSettings


def _brain(*replies, actions=True, sole=True):
    llm = ScriptedLLM([json.dumps(r) for r in replies])
    b = Brain(
        Agenda.parse("# Meeting\n1. Discussion and decisions (45 min)"),
        llm,
        45,
        max_direct=40,
        direct_gap_s=0,
        wake_settings=WakeSettings(),
    )
    b.sole_human, b.agenda_placeholder, b.actions_enabled = sole, True, actions
    return b, llm


def test_ACTIONS_the_prompt_offers_the_three_actions_only_when_actions_are_on():
    assert NO_ACTIONS_TEXT in QUICK_PROMPT and NO_ACTIONS_TEXT not in QUICK_PROMPT_ACTIONS
    assert all(name in QUICK_PROMPT_ACTIONS for name in ("create_pin", "add_agenda_item", "create_meeting"))


def test_ACTIONS_a_proposal_is_read_back_in_fixed_words_not_the_models():
    b, llm = _brain({"reply": "Done! I pinned it.", "action": {"name": "create_pin", "args": {"title": "Checklist"}}})
    msg = b.quick_reply([Utterance("Asha Rao", "pin the checklist to my board", 10)], 10)
    assert msg is not None and msg.text == 'Pin "Checklist" to your personal board?'
    assert b.pending_action is not None and b.pending_action.api_speaker is None  # one-on-one: the owner
    assert "now_local" in str(llm.calls[0])


def test_ACTIONS_in_a_group_call_the_speakers_name_goes_to_tilo_api():
    b, _ = _brain(
        {"reply": None, "action": {"name": "create_pin", "args": {"title": "x", "board": "team"}}}, sole=False
    )
    b.quick_reply([Utterance("Priya Nair", "Tilo, pin x to the team board", 10)], 10)
    assert b.pending_action.api_speaker == "Priya Nair" and b.pending_action.args["board"] == "team"


def test_ACTIONS_off_the_model_cannot_propose_and_a_claim_is_still_replaced():
    b, _ = _brain(
        {"reply": "I have pinned it.", "action": {"name": "create_pin", "args": {"title": "x"}}}, actions=False
    )
    msg = b.quick_reply([Utterance("Asha Rao", "please pin x to my board", 10)], 10)
    assert b.pending_action is None and msg.text == "I can't do that from a call yet."


def test_ACTIONS_a_malformed_or_unknown_action_is_not_read_back():
    for action in (
        {"name": "send_email", "args": {"title": "x"}},
        {"name": "create_pin", "args": {}},
        {"name": "create_meeting", "args": {"title": "x", "start": "friday", "minutes": 30}},
    ):
        assert action_talk.proposal(action, "Asha", one_on_one=True) is None


def test_ACTIONS_only_the_asked_speakers_yes_in_time_counts():
    pending = action_talk.PendingAction("Priya Nair", "Priya Nair", "create_pin", {"title": "x", "board": "personal"})
    assert action_talk.answer(pending, "Dev Menon", "yes", one_on_one=False) is None
    assert action_talk.answer(pending, "Priya Nair (chat)", "yes please", one_on_one=False) == "yes"
    assert action_talk.answer(pending, "Priya Nair", "no, wait", one_on_one=False) == "no"
    assert action_talk.answer(pending, "Priya Nair", "what time is it", one_on_one=False) is None
    pending.at = time.monotonic() - action_talk.CONFIRM_S - 1
    assert action_talk.answer(pending, "Priya Nair", "yes", one_on_one=False) is None


def test_ACTIONS_a_meeting_carries_the_spoken_recording_attestation():
    raw = {
        "name": "create_meeting",
        "args": {"title": "Follow-up", "start": "2026-10-23T15:00:00+05:30", "minutes": 30},
    }
    pending = action_talk.proposal(raw, "Asha", one_on_one=True)
    assert "right to record" in action_talk.readback(pending)
    assert action_talk.request_args(pending)["recording_attested"] is True


def test_ACTIONS_success_is_said_only_on_tilo_apis_confirmation():
    pending = action_talk.PendingAction("Asha", None, "create_pin", {"title": "x", "board": "personal"})
    assert action_talk.result_line(pending, True, "done", {"board": "personal"}).startswith("Done")
    for outcome in ("unavailable", "refused", "cap_reached", "unknown_person", "not_attending", "team_unclear"):
        line = action_talk.result_line(pending, False, outcome, {})
        assert not line.lower().startswith("done") and "pinned" not in line.lower()
    assert "can't find you in Tilo" in action_talk.result_line(pending, False, "unknown_person", {})


def _session(monkeypatch, tmp_path, actions):
    from bot.config import Config
    from bot.session import LiveSession

    monkeypatch.setattr("bot.config.load_dotenv", lambda path=None: None)
    monkeypatch.setenv("OUT_DIR", str(tmp_path / "out"))
    monkeypatch.setenv("CONTEXT_DIR", str(tmp_path / "ctx"))
    agenda = tmp_path / "agenda.md"
    agenda.write_text("# Meeting\n1. Discussion (45 min)", encoding="utf-8")
    s = LiveSession(
        Config.from_env(),
        "join",
        "https://meet.example/abc-defg-hij",
        agenda,
        30,
        False,
        [],
        False,
        False,
        [],
        actions=actions,
    )
    s.intro_sent = True
    s.brain.sole_human = True
    s._queue_delivery = lambda msg, *a, **k: s.said.append(msg.text)
    s.said = []
    return s


def _confirm(monkeypatch, tmp_path, result):
    calls = []

    class FakeActions:
        def run(self, name, args, speaker, key):
            calls.append((name, args, speaker))
            return result

    s = _session(monkeypatch, tmp_path, FakeActions())
    assert s.brain.actions_enabled
    s.brain.pending_action = action_talk.PendingAction(
        "Asha Rao", None, "create_pin", {"title": "x", "board": "personal"}
    )

    async def run():
        s.record(Utterance("Asha Rao", "yes", 20.0))
        await asyncio.sleep(0.2)

    asyncio.run(run())
    return s, calls


def test_ACTIONS_a_yes_sends_the_action_and_tilo_reports_the_confirmed_result(monkeypatch, tmp_path):
    s, calls = _confirm(monkeypatch, tmp_path, ActionResult(True, "done", {"board": "personal"}))
    assert calls == [("create_pin", {"title": "x", "board": "personal"}, None)]
    assert s.said == ["Done, I pinned it to your personal board."] and s.brain.pending_action is None


def test_ACTIONS_a_failed_api_call_yields_no_success_claim(monkeypatch, tmp_path):
    s, calls = _confirm(monkeypatch, tmp_path, ActionResult(False, "unavailable", {}))
    assert len(calls) == 1 and len(s.said) == 1
    assert not s.said[0].lower().startswith("done") and "nothing was changed" in s.said[0]


def test_ACTIONS_a_no_cancels_without_calling_tilo_api(monkeypatch, tmp_path):
    called = []
    s = _session(monkeypatch, tmp_path, SimpleNamespace(run=lambda *a: called.append(a)))
    s.brain.pending_action = action_talk.PendingAction(
        "Asha Rao", None, "create_pin", {"title": "x", "board": "personal"}
    )
    s.record(Utterance("Asha Rao", "no", 20.0))
    assert called == [] and s.said == ["Okay, I won't."]


def test_ACTIONS_the_client_reads_only_fixed_outcome_words_and_needs_live_and_the_claim():
    def handle(request):
        body = json.loads(request.content)
        assert set(body) == {"meeting_id", "claim", "key", "speaker", "action", "args"}
        if body["args"]["title"] == "boom":
            return httpx.Response(503, json={"outcome": "unavailable"})
        if body["speaker"] == "Mallory":
            return httpx.Response(404, json={"outcome": "unknown_person", "extra": "ignored"})
        return httpx.Response(200, json={"outcome": "done", "action": "create_pin", "board": "team"})

    client = MeetingActions(
        "https://tilo-api.example.run.app",
        "mt_x",
        "c" * 32,
        token_for=lambda aud: "id.token.x",
        transport=httpx.MockTransport(handle),
    )
    assert client.run("create_pin", {"title": "ok"}, None, "k1") == ActionResult(True, "done", {"board": "team"})
    assert client.run("create_pin", {"title": "ok"}, "Mallory", "k2") == ActionResult(False, "unknown_person", {})
    assert client.run("create_pin", {"title": "boom"}, None, "k3").ok is False
    assert client.run("send_email", {"title": "x"}, None, "k4") == ActionResult(False, "refused", {})
    assert actions_from_env("mt_x", "c" * 32, {"TILO_API_URL": "https://a.example.run.app"}) is None  # no LIVE
    assert actions_from_env("mt_x", None, {"LIVE": "1", "TILO_API_URL": "https://a.example.run.app"}) is None
