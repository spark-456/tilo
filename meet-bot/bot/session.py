"""One live meeting from join to leave.

Inputs: Meet captions (who/when), the meeting audio (what, in hybrid mode), typed chat, and project knowledge.
Outputs: transcript, agenda tracking, answers in chat, latency log, summary.

The meeting "starts" for the bot (intro, clock, brain, chat) only once the required people are present.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import Counter
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from .audio_out import Player, WavTap, setup_virtual_mic
from .brain import CHAT_SUFFIX, Agenda, Brain, _norm, chat_utterance
from .browser import MeetBrowser
from .captions import CaptionMerger, CaptionReader, TranscriptStore, Utterance
from .chat import ChatPoster, intro_text
from .clock import SystemClock
from .config import ROOT, Config
from .events import EventSink
from .hybrid import (
    AudioBuffer,
    CaptionSpans,
    LiveRecorder,
    SpeechSegmenter,
    VoiceActivity,
    assign_speaker,
    to_wav,
)
from .knowledge import KnowledgeBase
from .llm_fast import FastLLM
from .people import gate_open, missing_required
from .playback import write_playback
from .providers import ProviderFastClient, ProviderLLM, ProviderSpeech, make_router, make_tts, start_up_check
from .speaker import NullSpeaker, VoiceSpeaker
from .timing import Timeline
from .trace import Turn, TurnTrace
from .tts import STT_END_AT

log = logging.getLogger("bot.session")
STATUS_EVERY_S = 3.0  # how often to check who is here before the meeting has started for the bot


def build_knowledge(cfg: Config, routes: list[str]) -> KnowledgeBase:
    kb = KnowledgeBase()
    if cfg.context_dir.is_dir():
        kb.add_dir(cfg.context_dir)
    for route in cfg.context_urls + routes:
        kb.add_route(route, ROOT)
    log.info("project knowledge loaded: %s", kb.describe())
    return kb


def build_brain(cfg: Config, agenda_path: Path | None, duration: float | None, kb: KnowledgeBase) -> Brain | None:
    """None (transcript only) when there is no agenda. The bot still joins and transcribes."""
    path = agenda_path or cfg.agenda_path
    if not path.is_file():
        log.warning("no agenda at %s: transcript only, no brain (copy agenda.example.md to agenda.md)", path)
        return None
    agenda = Agenda.load(path)
    return Brain(
        agenda,
        ProviderLLM(),
        agenda.resolve_duration(duration or cfg.meeting_minutes),
        bot_name=cfg.bot_display_name or "tilo",
        answer_mode=cfg.answer_mode,
        max_direct=cfg.max_direct_replies,
        direct_gap_s=cfg.direct_reply_gap_s,
        knowledge=kb,
    )


async def run_live(
    cfg: Config,
    mode: str,
    url: str | None,
    agenda_path: Path | None,
    duration: float | None,
    auto_admit: bool = False,
    require: list[str] | None = None,
    record_audio: bool = False,
    hybrid: bool = False,
    context: list[str] | None = None,
    stt: str | None = None,
    reply: str | None = None,
) -> None:
    await LiveSession(
        cfg, mode, url, agenda_path, duration, auto_admit, require, record_audio, hybrid, context or [], stt, reply
    ).run()


class _MicSwitch:
    """Adapts the browser to the speaker's MicControl interface."""

    def __init__(self, browser: MeetBrowser) -> None:
        self.b = browser

    async def set(self, on: bool) -> bool:
        return await self.b.set_mic(on)


class LiveSession:
    def __init__(
        self,
        cfg: Config,
        mode: str,
        url: str | None,
        agenda_path: Path | None,
        duration: float | None,
        auto_admit: bool,
        require: list[str] | None,
        record_audio: bool,
        hybrid: bool,
        context: list[str],
        stt: str | None = None,
        reply: str | None = None,
    ) -> None:
        self.cfg, self.mode, self.url = cfg, mode, url
        self.clock = SystemClock()
        self.run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.out_dir = cfg.out_dir / self.run_id
        self.events = EventSink(self.out_dir / "events.jsonl", self.run_id, echo=True)
        self.store = TranscriptStore(self.out_dir / "transcript.jsonl")
        self.captions_store = TranscriptStore(self.out_dir / "captions.jsonl")
        self.timeline = Timeline(self.out_dir / "latency.jsonl")
        self.kb = build_knowledge(cfg, context)
        self.brain = build_brain(cfg, agenda_path, duration, self.kb)
        self.fast = self._build_fast()
        if self.brain:
            self.brain.fast = self.fast
        self.required = list(
            dict.fromkeys((require or []) + cfg.required + (self.brain.agenda.required if self.brain else []))
        )
        self.auto_admit = auto_admit or cfg.auto_admit
        self.record_audio = record_audio or cfg.record_audio
        self.stt_mode = stt or ("gemini" if (hybrid or cfg.hybrid) else cfg.stt)
        if self.stt_mode == "gemini" and self.brain is None:
            log.warning("--stt gemini needs an agenda: falling back to captions")
            self.stt_mode = "captions"
        self.hybrid = self.stt_mode != "captions"  # audio is the transcript source; captions give names and timing
        self.merger = CaptionMerger(ignore_speakers=("you", cfg.bot_display_name))
        self.queue: asyncio.Queue = asyncio.Queue()
        self.start = self.clock.now()
        self.gate_at: float | None = None
        self.ignore = {"you", (cfg.bot_display_name or "").lower()}
        self.first_seen: dict[str, float] = {}
        self.stt_final: dict[str, float] = {}  # FR-MTG-11: question -> clock time its STT result came back
        self.own_texts: set[str] = set()
        self.spans = CaptionSpans()
        self.buffer = AudioBuffer()
        self.seg_q: asyncio.Queue = asyncio.Queue()
        self.recorder: LiveRecorder | None = None
        self.chat_seen: Counter = Counter()
        self.reply_mode = reply or cfg.reply_mode  # chat | voice | both
        self.voice = False
        self.partial_idle_s = 1.0  # how long a finished question must sit still
        self.tts = None
        self.speaker: Any = NullSpeaker()
        self.activity: VoiceActivity | None = None
        self._out_q: asyncio.Queue = asyncio.Queue()  # replies waiting to be spoken and posted, in order
        self._out_task: asyncio.Task | None = None
        self.next_status_at: float | None = None
        self.next_brain_at = 0.0
        self.last_question_at = -1e9  # when a question was last put to the assistant
        self.delivering = False  # a reply is being spoken or typed right now
        self.conns = Timeline(self.out_dir / "connections.jsonl")  # model attempts and prewarms
        self.trace = TurnTrace(self.out_dir / "turns.jsonl", self.clock, self.start)
        self.bot_tap: WavTap | None = None
        self.others_seen, self.alone_since = False, None
        self.last_wait_msg, self.intro_sent = None, False

    def _build_fast(self) -> FastLLM:
        """One long-lived async client for direct answers; every attempt lands in latency.jsonl."""
        router = make_router()
        return FastLLM(
            lambda: ProviderFastClient(router),
            self.cfg.fast_thinking,
            first_token_s=self.cfg.fast_first_token_s,
            on_attempt=lambda row: self.conns.record("prewarm" if row["outcome"] == "prewarm" else "attempt", **row),
        )

    def _prewarm(self) -> None:
        """Open the model connection because a question is likely (rate limited inside FastLLM)."""
        if self.fast is None:
            return
        try:
            asyncio.get_running_loop().create_task(self.fast.prewarm())
        except RuntimeError:  # no running loop (offline tools): nothing to warm
            pass

    def _on_admitted(self, name: str) -> None:
        """Someone just came in: check at once whether the meeting can start, so their first words are not lost."""
        self.events.emit("participant.admitted", name=name)
        self.next_status_at = min(self.next_status_at or 0.0, self.clock.now())

    @staticmethod
    def analysis_allowed(now: float, quick_running: bool, last_question_at: float) -> bool:
        """The meeting-notes loop shares one small, throttled quota with the answers: it stays quiet while a question is
        being answered and for 30 s after the last one, so a conversation is not starved by the notes."""
        return not quick_running and now - last_question_at > 30.0

    @staticmethod
    def idle_needed(text: str, base: float) -> float:
        """How long a live partial must sit still before it counts as finished: a question mark says it is complete,
        a statement ("Tilo tell me a joke") could still be mid-sentence, so it waits a little longer."""
        return base if text.rstrip().endswith("?") else base + 0.8

    # -- time ------------------------------------------------------------------------------------------------------
    def elapsed(self) -> float:  # seconds since joining (also the audio clock)
        return self.clock.now() - self.start

    def brain_elapsed(self) -> float:  # seconds since the meeting started for the bot
        return self.elapsed() - (self.gate_at or 0.0)

    def _shift(self, u: Utterance) -> Utterance:
        return Utterance(u.speaker, u.text, max(0.0, u.t - (self.gate_at or 0.0)), u.ts)

    # -- recording of transcript lines -----------------------------------------------------------------------------
    def record(self, u: Utterance, heard_at: float | None = None, stt_final_at: float | None = None) -> None:
        u.t = round(u.t, 1)
        self.store.append(u)
        self.events.emit("transcript.utterance", speaker=u.speaker, text=u.text, t=u.t)
        self.timeline.record(
            "utterance",
            speaker=u.speaker,
            text=u.text[:120],
            first_visible_at_s=u.t,
            finalized_after_s=round(self.elapsed() - u.t, 1),
        )
        if self.brain:
            q = self.brain.question_in(u)
            if q and self.brain.is_fresh(q):
                self.first_seen.setdefault(_norm(q.text), heard_at if heard_at is not None else self.clock.now())
                if stt_final_at is not None:
                    self.stt_final.setdefault(_norm(q.text), stt_final_at)
                self._prewarm()

    def record_caption(self, u: Utterance) -> None:
        u.t = round(u.t, 1)
        if self.hybrid:  # the audio transcript is the source of truth; captions only supply names and timing
            self.captions_store.append(u)
        else:
            self.record(u)

    # -- main ------------------------------------------------------------------------------------------------------
    async def run(self) -> None:
        start_up_check()  # before anything is opened or joined: the call cap and the resolved providers (FR-MTG-11)
        log.info(
            "required participants: %s | auto-admit: %s | transcript: %s | record audio: %s",
            self.required or "(anyone)",
            self.auto_admit,
            self.stt_mode,
            self.record_audio,
        )
        self._setup_voice()
        async with MeetBrowser(self.cfg, voice=self.voice) as br:
            self.br = br
            try:
                if self.mode == "start":
                    self.url = await br.open_new_meeting()
                    print(f"MEETING_URL {self.url}", flush=True)
                else:
                    await br.open_meeting(self.url or "")
                asked = await br.join()
                if self.voice:
                    self.speaker = VoiceSpeaker(
                        self.tts, Player(), _MicSwitch(br), self.activity, mic_policy=self.cfg.mic_policy
                    )
                    await br.set_mic(False)  # a virtual microphone exists, so Meet may have joined unmuted
                self.start = self.clock.now()
                self.trace.audio_start = self.start
                self.merger.t0 = self.start
                if br.account_name:
                    self.merger.add_ignored(br.account_name)
                await self._start_audio()
                self.events.emit(
                    "meeting.joined",
                    url=self.url,
                    asked_to_join=asked,
                    required=self.required,
                    auto_admit=self.auto_admit,
                )
                self.chat = ChatPoster(br)
                self._prewarm()
                if not await br.enable_captions():
                    log.error("captions could not be enabled: no speaker names, and no transcript without audio")
                snap = self.cfg.debug_dir / "caption_snapshots" if self.cfg.save_caption_snapshots else None
                reader = CaptionReader(
                    br.page, lambda blocks, now: self.queue.put_nowait((blocks, now)), self.clock, snap
                )
                await reader.start()
                await self._loop()
            finally:
                await self._shutdown()

    async def _start_audio(self) -> None:
        if not (self.hybrid or self.record_audio or self.voice):
            return
        loop = asyncio.get_running_loop()
        wav = self.out_dir / "audio.wav" if self.record_audio else None
        self.recorder = LiveRecorder(
            wav,
            self.buffer,
            SpeechSegmenter(),
            (lambda a, b: loop.call_soon_threadsafe(self.seg_q.put_nowait, (a, b)))
            if self.stt_mode == "gemini"
            else (lambda a, b: None),
            activity=self.activity,
        )
        if not self.recorder.start():
            self.recorder, self.hybrid = None, False
            return
        self.trace.audio_start = self.recorder.started_at  # time zero of audio.wav
        if self.voice:
            self.bot_tap = WavTap(self.out_dir / "bot.wav")
            if self.bot_tap.start():
                clock = {"audio_start": self.recorder.started_at, "bot_start": self.bot_tap.started_at}
                (self.out_dir / "audio_clock.json").write_text(json.dumps(clock), encoding="utf-8")
            else:
                self.bot_tap = None
        if self.record_audio:
            self.events.emit("audio.recording", path=str(wav), starts_at_s=0)
        if self.stt_mode == "gemini":
            self.stt_task = asyncio.create_task(self._stt_worker())

    # -- hybrid speech-to-text (Gemini, batch) -----------------------------------------------------------------------
    async def _stt_worker(self) -> None:
        speech = ProviderSpeech()
        last_failure = ""  # the same failure (the speech cap, an outage) is warned about once, not for every segment
        while True:
            a, b = await self.seg_q.get()
            try:
                pcm = self.buffer.slice(a, b)
                t0 = time.monotonic()
                text = (await asyncio.to_thread(speech.text, to_wav(pcm))).strip()
                stt_s = time.monotonic() - t0
                final_at = (
                    self.clock.now()
                )  # FR-MTG-11: the STT final result is in; the voice logs STT end -> first audio
                if not text:
                    self.timeline.record("segment_empty", start_s=a, end_s=b, stt_s=round(stt_s, 2))
                    continue
                speaker, others = assign_speaker((a, b), self.spans.as_tuples())
                if speaker is None:  # captions can trail the audio by a moment: look once more
                    await asyncio.sleep(1.5)
                    speaker, others = assign_speaker((a, b), self.spans.as_tuples())
                self.timeline.record(
                    "segment",
                    start_s=a,
                    end_s=b,
                    stt_s=round(stt_s, 2),
                    speaker=speaker,
                    also_active=others,
                    text=text[:160],
                    end_to_text_s=round(self.elapsed() - b, 2),
                )
                self.record(Utterance(speaker or "Speaker", text, a), heard_at=self.start + b, stt_final_at=final_at)
                last_failure = ""
            except Exception as e:
                level = logging.DEBUG if str(e) == last_failure else logging.WARNING
                last_failure = str(e)
                log.log(level, "segment %.1f-%.1f could not be transcribed: %s", a, b, e)

    # -- typed chat -----------------------------------------------------------------------------------------------
    @staticmethod
    def _clean_chat_text(text: str) -> str:
        """Drop Meet's own UI lines (pin buttons) that come along with a message's text."""
        junk = {"keep", "pin message", "unpin message", "pin", "more_vert", "push_pin"}
        lines = [ln.strip() for ln in text.splitlines() if ln.strip() and ln.strip().lower() not in junk]
        return " ".join(lines).strip()

    async def _read_chat(self) -> None:
        msgs = await self.br.read_chat()
        if not msgs:
            return
        seen_now: Counter = Counter()
        for sender, text in msgs:
            text = self._clean_chat_text(text)
            if not text:
                continue
            key = (sender, text)
            seen_now[key] += 1
            if seen_now[key] <= self.chat_seen[key]:
                continue
            self.chat_seen[key] += 1
            if (
                sender.lower() in self.ignore
                or text in self.own_texts
                or any(text.startswith(o) for o in self.own_texts)
            ):
                continue
            if sender == "?":  # Meet did not tag the sender; our own messages were filtered above, so it is a person
                sender = "Participant"
            bot = self.brain.bot_name if self.brain else ""
            addressed = text.lstrip("@ ").lower().startswith(bot.lower()) if bot else False
            asked = text.rstrip().endswith("?") or addressed
            log.info("chat from %s: %s", sender, text[:120])
            if not asked and len(text) >= 20:
                self.kb.add_chat(sender, text)  # pasted notes/links become answerable context
            self.record(chat_utterance(sender, text, self.elapsed()), heard_at=self.clock.now())

    # -- answering ---------------------------------------------------------------------------------------------------
    async def _post(self, text: str, kind: str) -> bool:
        self.own_texts.add(text)
        ok = await self.chat.send(text)
        if ok:
            self.events.emit("chat.posted", kind=kind, text=text)
            await self.br.shot(f"chat_{kind}")
        return ok

    def _setup_voice(self) -> None:
        """Voice replies need a TTS provider and a virtual microphone; without them the bot stays chat-only."""
        if self.reply_mode == "chat":
            return
        self.tts = make_tts()
        if self.tts is None:
            log.warning("no voice provider available: replies will be chat only")
        elif not setup_virtual_mic():
            log.warning("could not create the virtual microphone: replies will be chat only")
        else:
            self.voice = True
            self.activity = VoiceActivity()
            log.info("voice replies on (%s)", self.tts.name)

    async def _deliver(self, msg, turn: Turn | None = None) -> tuple[bool, dict]:
        """Send a reply out loud and in chat. Returns (delivered anywhere, timing info).

        The chat copy follows the first sound, so typing never delays the voice (and never competes with it for the UI)."""
        want_voice = self.voice and (msg.kind == "direct_reply" or (self.cfg.voice_nudges and msg.kind != "intro"))
        t0 = self.clock.now()
        first_sound = asyncio.Event()

        def mark(name: str, at: float | None = None) -> None:
            if turn is not None:
                turn.mark(name, at)

        def heard_first() -> None:
            first_sound.set()
            mark("first_sample")

        if want_voice:
            mark("tts_request", t0)
        speak = None
        if want_voice:
            token = STT_END_AT.set(turn.marks.get("stt_final") if turn is not None else None)  # the task copies it
            try:
                speak = asyncio.create_task(self.speaker.say(msg.text, on_first_sound=heard_first))
            finally:
                STT_END_AT.reset(token)
        chat_ok, chat_s, first_out = False, 0.0, None
        if self.reply_mode != "voice" or not want_voice:
            if speak:
                waiter = asyncio.ensure_future(first_sound.wait())
                await asyncio.wait({speak, waiter}, return_when=asyncio.FIRST_COMPLETED)
                waiter.cancel()
            t1 = self.clock.now()
            chat_ok = await self._post(msg.text, msg.kind)
            chat_s, first_out = self.clock.now() - t1, self.clock.now() - t0
            if chat_ok:
                mark("chat_posted")
        res = await speak if speak else None
        if res is not None:
            mark("playback_end")
            if res.first_audio_s is not None:
                mark("tts_first_pcm", t0 + res.first_audio_s)
            if res.interrupted:
                mark("barge_stop")
        if (
            speak and not (res and res.spoken) and not chat_ok
        ):  # voice-only mode and the voice failed: chat is the backup
            t1 = self.clock.now()
            chat_ok = await self._post(msg.text, msg.kind)
            chat_s, first_out = self.clock.now() - t1, (self.clock.now() - t0)
            if chat_ok:
                mark("chat_posted")
        if res is not None:
            self.timeline.record(
                "speech",
                text=msg.text[:120],
                spoken=res.spoken,
                interrupted=res.interrupted,
                error=res.error,
                waited_for_pause_s=round(res.waited_s, 2),
                first_audio_s=None if res.first_audio_s is None else round(res.first_audio_s, 2),
                total_s=round(res.total_s, 2),
            )
            if res.error:
                log.warning("voice reply not spoken: %s (chat is the fallback)", res.error)
            elif res.spoken:
                log.info(
                    "spoke reply%s: first sound %.1fs after the reply was ready",
                    " (interrupted)" if res.interrupted else "",
                    res.first_audio_s or 0.0,
                )
        cands = [
            x
            for x in (first_out, res.first_audio_s if res and res.spoken and res.first_audio_s else None)
            if x is not None
        ]
        status = "off" if res is None else ("spoken" if res.spoken else f"failed: {res.error}")
        if res is not None and res.spoken:
            outcome = "interrupted" if res.interrupted else "spoken"
        else:
            outcome = "chat_only" if chat_ok else "failed"
        return (chat_ok or bool(res and res.spoken)), {
            "chat_typing_s": round(chat_s, 2),
            "first_output_s": round(min(cands), 2) if cands else 0.0,
            "voice_status": status,
            "outcome": outcome,
        }

    def _queue_delivery(self, msg, done: Callable[[bool, dict], None] | None = None, turn: Turn | None = None) -> None:
        """Replies go out one at a time from their own task, so speaking never holds up the main loop."""
        self._out_q.put_nowait((msg, done, turn))
        if self._out_task is None or self._out_task.done():
            self._out_task = asyncio.create_task(self._delivery_worker())

    async def _delivery_worker(self) -> None:
        while True:
            msg, done, turn = await self._out_q.get()
            self.delivering = True
            try:
                ok, info = await self._deliver(msg, turn)
                if done:
                    done(ok, info)
            except Exception as e:  # one failed reply must not stop the next
                log.exception("delivering a reply crashed: %s", e)
                if done:
                    done(False, {"outcome": "failed"})
            finally:
                self.delivering = False

    async def _keep_mic_open(self) -> None:
        """MIC_POLICY=open: once the meeting has started the bot's mic stays on (it carries only synthesised speech,
        silence otherwise), so no answer waits for an unmute. Someone muting it is undone at the next status check."""
        if self.voice and self.gate_at is not None and self.cfg.mic_policy == "open":
            await self.br.set_mic(True)

    async def _timed_quick(self, recent: list[Utterance], meta: dict[str, Any]):
        t = time.monotonic()
        msg = await self.brain.aquick_reply(recent, self.brain_elapsed())
        turn = meta.get("turn")
        if turn is not None and self.brain.last_quick_source == "model":
            call = self.fast.last_call if self.fast else {}
            fresh = call.get("request_at", 0.0) >= t  # this call's times, not an earlier one's
            turn.mark("llm_request", call["request_at"] if fresh else t)
            if fresh:
                turn.mark("llm_first_token", call["first_token_at"])
        return msg, time.monotonic() - t, meta

    def _new_turn(self, q, meta: dict[str, Any]) -> Turn:
        """A trace row for one question. The end of the human turn is the last loud audio frame when the meeting audio
        is captured, the moment the chat message was read for typed chat, and an estimate otherwise."""
        last_loud = self.activity.last_loud_at() if self.activity else None
        if q.speaker.endswith(CHAT_SUFFIX):
            end, source = meta["first_seen"], "chat"
        elif last_loud is not None and 0 <= meta["detected"] - last_loud < 15:
            end, source = last_loud, "audio"
        else:
            end, source = meta["detected"] - self.partial_idle_s, "estimate"
        turn = self.trace.new_turn(q.speaker, q.text, end, source)
        turn.mark("addressed", meta["first_seen"])
        turn.mark("confirmed_end", meta["detected"])
        if meta.get("stt_final") is not None:
            turn.mark("stt_final", meta["stt_final"])
        return turn

    async def _finish_quick(self, task: asyncio.Task) -> None:
        try:
            msg, model_s, meta = task.result()
        except Exception as e:
            log.exception("quick reply crashed: %s", e)
            return
        turn = meta.get("turn")
        if turn is not None:
            turn.route = "instant" if self.brain.last_quick_source == "local" else "model"
        if not msg:
            if turn is not None:
                self.trace.finish(turn, "no_reply")
            self.timeline.record("question_no_reply", question=meta["question"], model_s=round(model_s, 2))
            log.info("no reply to %r (not answerable from the meeting/project info, %.1fs)", meta["question"], model_s)
            return
        reply_ready = self.clock.now()
        self.brain.commit_chat(msg, self.brain_elapsed())  # booked now: a second question cannot slip past the gap

        def done(ok: bool, info: dict) -> None:
            if turn is not None:
                self.trace.finish(turn, info.get("outcome", "failed"))
            if not ok:
                log.warning("the reply to %r could not be delivered anywhere", meta["question"])
                return
            row = {
                "question": meta["question"],
                "reply": msg.text,
                "heard_to_detected_s": round(meta["detected"] - meta["first_seen"], 2),
                "model_s": round(model_s, 2),
                "source": self.brain.last_quick_source,
                **info,
                "total_from_speech_end_s": round(self.clock.now() - meta["first_seen"], 2),
                "first_output_from_speech_end_s": round(reply_ready - meta["first_seen"] + info["first_output_s"], 2),
            }
            self.timeline.record("question_answered", **row)
            log.info(
                "LATENCY heard->detected %.1fs | model %.1fs | first sound/text %.1fs after speech end | chat %.1fs | voice %s",
                row["heard_to_detected_s"],
                model_s,
                row["first_output_from_speech_end_s"],
                info["chat_typing_s"],
                info.get("voice_status", "off"),
            )

        self._queue_delivery(msg, done, turn)

    # -- loop -------------------------------------------------------------------------------------------------------
    async def _loop(self) -> None:
        cfg, br, brain = self.cfg, self.br, self.brain
        base_interval = cfg.brain_interval_s
        interval = base_interval
        brain_task = quick_task = status_task = None
        if self.next_status_at is None:
            self.next_status_at = self.clock.now() + 3
        next_admit = next_chat = 0.0
        try:
            while True:
                await asyncio.sleep(0.1)
                while not self.queue.empty():
                    blocks, now = self.queue.get_nowait()
                    for b in blocks:
                        self.spans.touch(b.speaker, now - self.start)
                    for u in self.merger.feed(blocks, now):
                        self.record_caption(u)
                for u in self.merger.tick(self.clock.now()):
                    self.record_caption(u)
                now = self.clock.now()

                # --- fast path: answer questions (spoken or typed) now, not at the next analysis interval --------
                if quick_task and quick_task.done():
                    await self._finish_quick(quick_task)
                    quick_task = None
                if brain and self.gate_at is not None:
                    gate = self.gate_at
                    opens = [] if self.hybrid else self.merger.open_utterances(now)
                    base = [self._shift(u) for u in self.store.window(self.elapsed(), 3)]
                    q_any = brain.pending_question(base + [self._shift(u) for u, _ in opens])
                    if q_any:
                        self.first_seen.setdefault(_norm(q_any[1]), now)
                    if quick_task is None:
                        ready = base + [
                            Utterance(u.speaker, u.text, max(0.0, u.t - gate))
                            for u, idle in opens
                            if idle >= self.idle_needed(u.text, self.partial_idle_s)
                        ]
                        q = brain.pending_question(ready)
                        if q:
                            meta = {
                                "question": q[1],
                                "detected": now,
                                "first_seen": self.first_seen.get(_norm(q[1]), now),
                                "stt_final": self.stt_final.get(_norm(q[1])),
                            }
                            meta["turn"] = self._new_turn(q, meta)
                            self.last_question_at = now
                            quick_task = asyncio.create_task(self._timed_quick(ready, meta))

                # --- periodic analysis ---------------------------------------------------------------------------
                if brain_task and brain_task.done():
                    try:
                        res = brain_task.result()
                    except Exception as e:  # a bug in one cycle must not end the meeting
                        log.exception("brain step crashed: %s", e)
                        res = None
                    brain_task = None
                    if res is not None:
                        interval = (
                            min(base_interval * 4, interval * 2)
                            if not res.ok and "quota" in (res.error or "")
                            else base_interval
                        )
                        if res.chat:
                            chat = res.chat
                            if chat.kind == "direct_reply":  # booked now, like a quick reply
                                brain.commit_chat(chat, self.brain_elapsed())
                                self._queue_delivery(chat)
                            else:
                                self._queue_delivery(
                                    chat, lambda ok, _: ok and brain.commit_chat(chat, self.brain_elapsed())
                                )
                        brain.write_outputs(self.out_dir, self.brain_elapsed())
                        self.events.emit("agenda.update", state=brain.state.to_dict())
                if (
                    brain
                    and self.gate_at is not None
                    and brain_task is None
                    and now >= self.next_brain_at
                    and self.analysis_allowed(now, quick_task is not None, self.last_question_at)
                ):
                    self.next_brain_at = now + interval
                    window = [self._shift(u) for u in self.store.window(self.elapsed(), cfg.window_minutes)]
                    brain_task = asyncio.create_task(asyncio.to_thread(brain.step, window, self.brain_elapsed()))

                # --- typed chat (about every 1.5 s once the meeting has started) ---------------------------------
                if self.gate_at is not None and now >= next_chat:
                    next_chat = now + 1.5
                    await self._read_chat()

                # --- admitting (frequent, cheap) -----------------------------------------------------------------
                if self.auto_admit and now >= next_admit:
                    next_admit = now + 3.0
                    for name in await br.admit_waiting(cfg.admit_allowed):
                        self._on_admitted(name)

                # --- people, gate, exit conditions: a task, because the People panel takes over a second to open --
                if status_task and status_task.done():
                    try:
                        leave = status_task.result()
                    except Exception as e:
                        log.exception("status check crashed: %s", e)
                        leave = False
                    status_task = None
                    self.next_status_at = self.clock.now() + (STATUS_EVERY_S if self.gate_at is None else 15.0)
                    if leave:
                        return
                if status_task is None and now >= self.next_status_at:
                    status_task = asyncio.create_task(self._status_step())
        finally:
            if status_task:
                status_task.cancel()

    async def _status_step(self) -> bool:
        """Meeting ended? Who is here? Has the meeting started for the bot? True means leave."""
        cfg, br, brain = self.cfg, self.br, self.brain
        now = self.clock.now()
        if await br.meeting_ended():
            log.info("meeting ended")
            return True
        # Reading the People panel opens it over the chat, so it waits until nothing is being spoken or typed.
        info = None if self.delivering else await br.participants()
        if info is not None:
            if info["self"]:
                self.ignore.add(info["self"].lower())
                self.merger.add_ignored(info["self"])
                if brain and not cfg.bot_display_name:
                    brain.bot_name = info["self"]
            others = info["others"]
            spoke = [
                s
                for s in dict.fromkeys(u.speaker for u in list(self.store.items) + list(self.captions_store.items))
                if s.lower() not in self.ignore and not s.endswith("(chat)") and s != "Speaker"
            ]
            present = list(dict.fromkeys(others + spoke))
            others_count = len(others)
            if brain:
                brain.sole_human = others_count == 1
        else:  # panel unreadable: fall back to the head count
            count = await br.people_count()
            others_count = (count - 1) if count is not None else None
            if brain and others_count is not None:
                brain.sole_human = others_count == 1
            present = [u.speaker for u in self.store.items if u.speaker.lower() not in self.ignore]
        if self.gate_at is not None:
            await br.show_chat()  # the People read replaced the chat panel
        if others_count:
            self.others_seen, self.alone_since = True, None
        elif others_count == 0 and self.others_seen:
            self.alone_since = self.alone_since or now
            if now - self.alone_since >= cfg.alone_grace_s:
                log.info("everyone else left; leaving")
                return True
        if brain:
            brain.present = present

        if self.gate_at is None:
            if gate_open(self.required, present):
                self.gate_at = self.elapsed()
                self.next_brain_at = now + cfg.brain_interval_s
                self.events.emit("meeting.started", present=present, required=self.required)
                log.info("required people are here (%s): starting", ", ".join(present))
                await self._keep_mic_open()
                if not self.intro_sent and await self._post(
                    intro_text(self.record_audio, self.hybrid, self.voice), "intro"
                ):
                    self.intro_sent = True
            else:
                wait_msg = f"waiting for: {', '.join(missing_required(self.required, present)) or 'anyone to join'}"
                if wait_msg != self.last_wait_msg:
                    log.info(wait_msg)
                    self.last_wait_msg = wait_msg
        else:
            await self._keep_mic_open()  # re-check every status cycle: someone may have muted the bot
        if self.gate_at is None and self.elapsed() > cfg.empty_timeout_s:
            log.info("required people did not arrive within %.0fs; leaving", cfg.empty_timeout_s)
            return True
        if self.elapsed() > cfg.max_meeting_minutes * 60:
            log.info("hit MAX_MEETING_MINUTES; leaving")
            return True
        return False

    # -- shutdown ---------------------------------------------------------------------------------------------------
    async def _shutdown(self) -> None:
        if self._out_task:
            self._out_task.cancel()
        if self.bot_tap:
            self.bot_tap.stop()
        try:
            if self.recorder:
                self.recorder.stop()  # flushes the last speech segment
                if self.stt_mode == "gemini":
                    for _ in range(40):  # let the transcriber finish what is queued (about 20 s at most)
                        if self.seg_q.empty():
                            break
                        await asyncio.sleep(0.5)
                    await asyncio.sleep(2.5)
                    self.stt_task.cancel()
            for u in self.merger.flush(self.clock.now()):
                self.record_caption(u)
            if self.brain and self.gate_at is not None:
                try:
                    window = [self._shift(u) for u in self.store.window(self.elapsed(), 10)]
                    await asyncio.to_thread(self.brain.step, window, self.brain_elapsed())
                except Exception as e:  # final pass is best effort
                    log.warning("final brain pass failed: %s", e)
                self.brain.write_outputs(self.out_dir, self.brain_elapsed())
                self.events.emit("summary.ready", path=str(self.out_dir / "summary.md"))
            await self.br.leave()
        finally:
            self.events.emit("meeting.ended", seconds=round(self.elapsed()))
            page = write_playback(self.out_dir)
            if page:
                log.info("playback page: %s", page)
            log.info("outputs in %s", self.out_dir)
