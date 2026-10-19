"""VA-03: the voice never waits for the UI. A fake Meet page drives the real MeetBrowser and ChatPoster code."""

import asyncio
import time
from types import SimpleNamespace

import pytest

from bot import selectors as S
from bot.brain import Agenda, Brain
from bot.browser import MeetBrowser
from bot.chat import ChatPoster
from bot.config import Config
from bot.mock_llm import ScriptedLLM
from bot.session import LiveSession
from bot.speaker import SpeakResult, VoiceSpeaker
from bot.ui import ADMIT, CHAT_POST, CHAT_READ, MIC, PEOPLE, UIScheduler

OP_S = 0.01  # one UI primitive (find, click, fill) on the fake page; real Playwright calls take 10-50 ms
BY_STRAT = {strat: sel.name for sel in S.ALL_SELECTORS for strat in sel.strategies}


def run(coro):
    return asyncio.run(coro)


# -- the scheduler ---------------------------------------------------------------------------------------------------
def test_VA_03_the_scheduler_serves_the_most_urgent_waiter_first_and_ties_in_order():
    async def go():
        ui, order = UIScheduler(), []

        async def job(name, prio):
            async with ui.section(prio):
                order.append(name)

        async with ui.section(PEOPLE):  # busy while everyone queues up
            tasks = [
                asyncio.create_task(job(n, p))
                for n, p in [("people", PEOPLE), ("admit", ADMIT), ("read", CHAT_READ), ("post2", CHAT_POST)]
            ]
            tasks.append(asyncio.create_task(job("mic", MIC)))
            tasks.append(asyncio.create_task(job("post1", CHAT_POST)))
            await asyncio.sleep(0.01)
        await asyncio.gather(*tasks)
        return order

    assert run(go()) == ["mic", "post2", "post1", "read", "admit", "people"]


def test_VA_03_a_cancelled_waiter_does_not_block_the_queue():
    async def go():
        ui = UIScheduler()
        async with ui.section(PEOPLE):
            doomed = asyncio.create_task(ui.acquire(MIC))
            await asyncio.sleep(0.01)
            doomed.cancel()
            await asyncio.sleep(0.01)
        async with asyncio.timeout(1.5):  # a hang guard, 3x for a starved laptop
            async with ui.section(CHAT_POST):
                return True

    assert run(go()) is True


def test_VA_03_the_scheduler_records_how_long_each_section_waited():
    async def go():
        ui = UIScheduler()
        async with ui.section(CHAT_POST):
            waiter = asyncio.create_task(_enter(ui, MIC))
            await asyncio.sleep(0.05)
        await waiter
        return ui.waits

    async def _enter(ui, prio):
        async with ui.section(prio):
            pass

    waits = run(go())
    assert [p for p, _ in waits][-1] == MIC and 0.04 <= waits[-1][1] < 0.9


# -- a fake Meet page -------------------------------------------------------------------------------------------------
class FakeMeet:
    """Visibility by selector name; every primitive costs OP_S. The chat box empties `settles_s` after Send."""

    def __init__(self, settles_s: float = 1.5) -> None:
        self.settles_s, self.mic_on, self.chat_open, self.people_open = settles_s, False, False, False
        self.box, self.sent_at, self.rows = "", None, []
        self.keyboard = SimpleNamespace(press=self._press)
        self.url = "https://meet.google.com/abc-defg-hij"

    async def _press(self, key):
        await asyncio.sleep(OP_S)

    def visible(self, name: str) -> bool:
        return {
            "mic_turn_off": self.mic_on,
            "mic_turn_on": not self.mic_on,
            "chat_open": True,
            "chat_input": self.chat_open,
            "chat_send": self.chat_open,
            "people_button": True,
            "people_panel_mark": self.people_open,
        }.get(name, False)

    def clicked(self, name: str) -> None:
        if name == "mic_turn_on":
            self.mic_on = True
        elif name == "mic_turn_off":
            self.mic_on = False
        elif name == "chat_open":
            self.chat_open, self.people_open = True, False
        elif name == "people_button":
            self.chat_open, self.people_open = False, True
        elif name == "chat_send":
            self.sent_at = time.monotonic()

    async def evaluate(self, js, *args):
        await asyncio.sleep(OP_S)
        return self.rows if self.people_open else []


class FakeLoc:
    def __init__(self, page: FakeMeet, name: str) -> None:
        self.page, self.name = page, name

    @property
    def first(self):
        return self

    async def is_visible(self):
        await asyncio.sleep(OP_S)
        return self.page.visible(self.name)

    async def click(self, timeout=None):
        await asyncio.sleep(OP_S)
        self.page.clicked(self.name)

    async def fill(self, text, timeout=None):
        await asyncio.sleep(OP_S)
        self.page.box = text

    async def press(self, key, timeout=None):
        await asyncio.sleep(OP_S)
        self.page.clicked("chat_send")

    async def input_value(self, timeout=None):
        await asyncio.sleep(OP_S)
        if self.page.sent_at and time.monotonic() - self.page.sent_at >= self.page.settles_s:
            self.page.box = ""
        return self.page.box

    async def count(self):
        return 1


@pytest.fixture
def meet(monkeypatch):
    monkeypatch.setattr("bot.config.load_dotenv", lambda path=None: None)
    monkeypatch.setattr("bot.browser.locate", lambda page, strat: FakeLoc(page, BY_STRAT[strat]))
    page = FakeMeet()
    br = MeetBrowser(Config.from_env())
    br.page = page

    async def no_shot(label):
        return None

    br.shot = no_shot
    return br, page


def test_VA_03_the_mic_toggle_is_not_blocked_by_a_slow_chat_post(meet):
    br, page = meet

    async def go():
        post = asyncio.create_task(ChatPoster(br).send("hello there"))
        await asyncio.sleep(0.3)  # the message is typed and sent; Meet is slow to clear the box
        assert not post.done()
        ok = await br.set_mic(True)
        mic_wait = [w for p, w in br.ui.waits if p == MIC][-1]
        return ok, mic_wait, post.done(), await post

    ok, mic_wait, post_running_done, posted = run(go())
    assert ok and page.mic_on and posted
    assert not post_running_done  # the mic did not wait for the post to end
    assert mic_wait <= 0.15, f"mic waited {mic_wait:.3f}s for the UI"


def test_VA_03_a_chat_post_returns_when_the_box_empties_not_after_a_fixed_sleep(meet):
    br, page = meet
    page.settles_s, page.chat_open = 0.1, True  # the panel is already open: only the wait after Send counts

    async def go():
        t = time.monotonic()
        ok = await ChatPoster(br).send("quick one")
        return ok, time.monotonic() - t

    ok, took = run(go())
    assert ok and took < 0.6  # the old code always slept 0.8 s inside the lock


def test_VA_03_a_people_read_lets_the_mic_through_while_the_panel_opens(meet):
    br, page = meet
    page.rows = [{"text": "Tilo (You)", "waiting": False}, {"text": "Sam", "waiting": False}]

    async def go():
        read = asyncio.create_task(br.participants())
        await asyncio.sleep(0.4)  # the People panel is opening (Meet needs about a second)
        await br.set_mic(True)
        mic_wait = [w for p, w in br.ui.waits if p == MIC][-1]
        return await read, mic_wait

    info, mic_wait = run(go())
    assert info and info["others"] == ["Sam"] and info["self"] == "Tilo"
    assert mic_wait <= 0.15


def test_VA_03_an_unreadable_people_panel_is_none_not_an_empty_room(meet):
    br, page = meet
    page.rows = []  # the panel was replaced by the chat panel meanwhile: no rows at all
    assert run(br.participants()) is None


# -- the mic policy and the speaker ----------------------------------------------------------------------------------
class MicLog:
    def __init__(self):
        self.calls = []

    async def set(self, on):
        self.calls.append(on)
        return True


class OneChunkTTS:
    name, sample_rate = "fake", 16000

    async def stream(self, text):
        yield b"\x00\x00" * 160


class FakePlayer:
    async def play(self, chunks, rate, should_stop):
        async for _ in chunks:
            pass
        return True


def speaker(mic, policy):
    return VoiceSpeaker(OneChunkTTS(), FakePlayer(), mic, None, mic_policy=policy, tail_s=0.0)


def test_VA_03_the_open_mic_policy_makes_no_mic_calls_per_answer():
    mic = MicLog()
    res = run(speaker(mic, "open").say("Hello."))
    assert res.spoken and mic.calls == []


def test_VA_03_the_conversation_policy_still_unmutes_and_mutes():
    mic = MicLog()
    res = run(speaker(mic, "conversation").say("Hello."))
    assert res.spoken and mic.calls == [True, False]


def test_VA_03_the_speaker_reports_the_first_sound_before_playback_ends():
    seen = []

    class SlowPlayer:
        async def play(self, chunks, rate, should_stop):
            async for _ in chunks:
                pass
            seen.append("played")
            return True

    sp = VoiceSpeaker(OneChunkTTS(), SlowPlayer(), MicLog(), None, mic_policy="open", tail_s=0.0)
    run(sp.say("Hello.", on_first_sound=lambda: seen.append("first")))
    assert seen == ["first", "played"]


def test_VA_03_the_mic_policy_is_configuration(monkeypatch):
    monkeypatch.setattr("bot.config.load_dotenv", lambda path=None: None)
    monkeypatch.delenv("MIC_POLICY", raising=False)
    assert Config.from_env().mic_policy == "open"
    monkeypatch.setenv("MIC_POLICY", "conversation")
    assert Config.from_env().mic_policy == "conversation"
    monkeypatch.setenv("MIC_POLICY", "sometimes")
    with pytest.raises(SystemExit):
        Config.from_env()


# -- the session: nothing in the loop waits for the voice or the People panel ------------------------------------------
class FakeSpeaker:
    def __init__(self, speak_s=2.5, first_s=0.05):
        self.speak_s, self.first_s, self.busy, self.said = speak_s, first_s, False, []

    async def say(self, text, on_first_sound=None):
        self.busy = True
        self.said.append(text)
        await asyncio.sleep(self.first_s)
        if on_first_sound:
            on_first_sound()
        await asyncio.sleep(self.speak_s - self.first_s)
        self.busy = False
        return SpeakResult(True, first_audio_s=self.first_s, total_s=self.speak_s)

    async def stop(self):
        return None


class FakeBrowser:
    def __init__(self, chats, people_s=0.0):
        self.chats, self.people_s = chats, people_s
        self.reads, self.posted, self.mic_calls = 0, [], []

    async def read_chat(self):
        self.reads += 1
        return self.chats[min(self.reads, len(self.chats)) - 1]

    async def participants(self):
        await asyncio.sleep(self.people_s)
        return {"others": ["Sam"], "waiting": [], "self": "Tilo"}

    async def meeting_ended(self):
        return False

    async def people_count(self):
        return 2

    async def show_chat(self):
        return None

    async def set_mic(self, on):
        self.mic_calls.append(on)
        return True

    async def shot(self, label):
        return None


@pytest.fixture
def session(tmp_path, monkeypatch):
    monkeypatch.setattr("bot.config.load_dotenv", lambda path=None: None)
    monkeypatch.setenv("OUT_DIR", str(tmp_path / "out"))
    monkeypatch.setenv("CONTEXT_DIR", str(tmp_path / "ctx"))
    agenda = tmp_path / "agenda.md"
    agenda.write_text("# Sync\n1. Roadmap (10 min)\n2. Hiring (5 min)\n", encoding="utf-8")
    s = LiveSession(
        Config.from_env(), "join", "https://meet.google.com/abc-defg-hij", agenda, 30, False, [], False, False, []
    )
    s.brain = Brain(Agenda.load(agenda), ScriptedLLM(['{"reply": null}']), 30, bot_name="Tilo")
    s.gate_at, s.voice, s.reply_mode = 0.0, True, "both"
    s.chat = SimpleNamespace(send=_fake_send(s))
    return s


def _fake_send(s):
    async def send(text):
        s.br.posted.append((time.monotonic(), text))
        return True

    return send


async def _until(pred, timeout):
    t = time.monotonic()
    while not pred():
        if time.monotonic() - t > timeout:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.02)


def test_VA_03_the_loop_keeps_reading_chat_while_a_reply_is_spoken(session):
    s = session
    ask = ("Sam", "What is on the agenda today?")
    later = ("Priya", "Budget check is tomorrow")
    s.br = FakeBrowser([[ask], [ask, later]])
    s.speaker = FakeSpeaker(speak_s=2.5)

    async def go():
        loop_task = asyncio.create_task(s._loop())
        try:
            await _until(lambda: s.speaker.busy, 3)
            await _until(lambda: any(u.speaker == "Priya (chat)" for u in s.store.items), 3)
            return s.speaker.busy
        finally:
            loop_task.cancel()

    assert run(go()) is True  # Priya's message was read and recorded while the first reply was still being spoken


def test_VA_03_a_slow_people_read_does_not_stall_the_loop(session):
    s = session
    s.br = FakeBrowser([[("Sam", "hello everyone")]], people_s=2.0)
    s.next_status_at = 0.0

    async def go():
        loop_task = asyncio.create_task(s._loop())
        try:
            await asyncio.sleep(1.9)  # the People read is still pending
            return s.br.reads
        finally:
            loop_task.cancel()

    assert run(go()) >= 2  # chat is read about every 1.5 s regardless


def test_VA_03_the_chat_mirror_is_posted_after_the_first_sound(session):
    s = session
    s.br = FakeBrowser([[]])
    s.speaker = FakeSpeaker(speak_s=0.6, first_s=0.3)
    msg = SimpleNamespace(kind="direct_reply", text="Kickoff is in progress.")

    async def go():
        t0 = time.monotonic()
        ok, info = await s._deliver(msg)
        return ok, info, t0

    ok, info, t0 = run(go())
    ((posted_at, text),) = s.br.posted
    assert ok and text == "Kickoff is in progress." and posted_at - t0 >= 0.29  # not before the voice had started


def test_VA_03_chat_is_posted_at_once_when_the_voice_fails(session):
    s = session
    s.br = FakeBrowser([[]])

    class Broken(FakeSpeaker):
        async def say(self, text, on_first_sound=None):
            return SpeakResult(False, error="voice service down")

    s.speaker = Broken()
    ok, info = run(s._deliver(SimpleNamespace(kind="direct_reply", text="Fallback in chat.")))
    assert ok and [t for _, t in s.br.posted] == ["Fallback in chat."]


def test_VA_03_the_mic_is_opened_when_the_meeting_starts_and_rechecked(session):
    s = session
    s.br = FakeBrowser([[]])
    run(s._keep_mic_open())
    assert s.br.mic_calls == [True]
    s.cfg = SimpleNamespace(**{**s.cfg.__dict__, "mic_policy": "conversation"})
    run(s._keep_mic_open())
    assert s.br.mic_calls == [True]  # the conversation policy unmutes per answer instead
    s.voice = False
    s.cfg = SimpleNamespace(**{**s.cfg.__dict__, "mic_policy": "open"})
    run(s._keep_mic_open())
    assert s.br.mic_calls == [True]  # no voice, no mic


def test_FR_MTG_11_the_stt_final_time_of_a_question_is_kept_and_marked_on_its_turn(session):
    from bot.brain import _norm
    from bot.captions import Utterance
    from bot.chat import intro_text

    s = session
    s.br = FakeBrowser([[]])
    assert run(s._post(intro_text(False, False, True), "intro"))
    s.intro_sent = True
    u = Utterance("Ana", "Tilo, what is the plan for Hiring?", 5.0)
    s.record(u, heard_at=40.0, stt_final_at=41.2)
    (q,) = [s.brain.question_in(u)]
    assert s.stt_final[_norm(q.text)] == 41.2  # the moment the transcript came back, on the bot clock
    turn = s._new_turn(q, {"first_seen": 40.0, "detected": 42.0, "stt_final": s.stt_final[_norm(q.text)]})
    assert turn.marks["stt_final"] == 41.2


def test_FR_MTG_11_the_speak_call_sees_the_turns_stt_final_time_and_a_chat_reply_sees_none(session):
    from bot.tts import STT_END_AT

    s = session
    s.br = FakeBrowser([[]])
    seen: list = []

    class Spy(FakeSpeaker):
        async def say(self, text, on_first_sound=None):
            seen.append(STT_END_AT.get())
            return await super().say(text, on_first_sound)

    s.speaker = Spy(speak_s=0.05, first_s=0.01)
    msg = SimpleNamespace(kind="direct_reply", text="Hiring is next.")
    turn = s.trace.new_turn("Ana", "Tilo, what is next?", 1.0)
    turn.mark("stt_final", 12.5)
    run(s._deliver(msg, turn))
    run(s._deliver(msg))
    assert seen == [12.5, None]
