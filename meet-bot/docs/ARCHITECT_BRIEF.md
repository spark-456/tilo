# Brief for the architect: a fast, conversational voice agent inside Google Meet

You are a senior real-time systems architect. I want your architecture and a build plan for a talking meeting agent that feels
instantaneous. Below is what exists, what I measured, what failed, and what I need from you. Be concrete and decisive: pick one
approach, justify it with the numbers below, and give me tickets that a cheaper model (Claude Sonnet) can implement safely.

## 1. The product

A bot joins a Google Meet as a normal participant (own Google account, consumer Gmail, no Workspace) and acts as a colleague:

- Listens to everyone, transcribes accurately with speaker names, tracks an agenda, decisions, action items, per-person notes.
- **Speaks back** in the meeting (voice is the main output) and writes the same text in Meet chat as a backup. It must also
  accept questions typed in chat.
- Answers from: the live meeting state, project documents, URLs, and text pasted into chat (all treated as untrusted data).
- Feels like ChatGPT/Gemini voice mode: sub-second to ~1.5 s from the end of a question to the first sound.
- Multi-party: several humans, sometimes talking over each other. Speaks only when addressed or clearly asked; stops instantly
  when a human talks over it (barge-in).
- Starts (intro, clock, brain, speech) only when required people have joined; can auto-admit from the waiting room.
- Honest disclosure: intro chat line says audio is transcribed by an AI service / recorded / bot may speak.
- Test meetings only for now; meeting content may go only to local files and the model/speech providers.

## 2. Hard constraints

- Runs on a Windows 11 laptop: Docker Desktop (WSL2), 2 CPUs / 3 GB RAM for the container. Must remain portable to Linux/Mac.
- Python 3.12, asyncio. Host CLI is stdlib-only; everything real runs in one Linux container.
- No secrets in code/logs/fixtures. Keys live only in `meet-bot/.env` (I add them; never write that file). Redact in logs.
- Free tiers today: Gemini via **Vertex AI Express Mode API key** (no GCP project, no billing), ElevenLabs free plan.
  Paid upgrades are possible if you can justify them with numbers (billing on a Google Cloud project is possible).
- Tests must not make paid calls: record-and-replay or fakes; a live test needs a human joining a real Meet.
- Never spend credits on silence: audio is only streamed while someone speaks and only while people are in the meeting.

## 3. Current architecture (works end to end; 121 unit tests pass)

Repo: `meet-bot/` (standalone inside the Tilo monorepo). One Docker image: Xvfb + PulseAudio + openbox + x11vnc/noVNC +
headed Chromium driven by Playwright, signed in once by a human through noVNC (profile in a named volume).

Audio plumbing (PulseAudio): Meet plays into null sink `tilo_out` (default sink); we record `tilo_out.monitor` with `parec`
(16 kHz mono s16le, 100 ms frames). For speech out: virtual mic = null sink `tilo_mic_sink` + `module-remap-source tilo_mic`
(default source); `paplay --device=tilo_mic_sink` plays TTS PCM; the bot unmutes/mutes its Meet mic by clicking the button
(`--use-fake-ui-for-media-stream` so no permission prompt).

Modules (`bot/`): `browser.py` (Playwright, all UI actions, one lock), `selectors.py` (all Meet selectors, aria/role/text
only), `captions.py` (Meet captions -> parser -> merger; used for speaker names/timing), `hybrid.py` (AudioBuffer, energy VAD
SpeechSegmenter, caption spans -> speaker assignment, LiveRecorder, VoiceActivity), `stt_stream.py` (ElevenLabs Scribe v2
Realtime WebSocket client, AudioGate, lazy connect/idle close, timestamp remapping across skipped silence), `brain.py`
(agenda + JSON-schema state tracking with Gemini, ChatPolicy, quick_reply fast path, Gemini client with backoff),
`instant.py` (state questions answered from notes with no model call), `knowledge.py` (keyword retrieval over files/URLs/chat),
`tts.py` (TTSProvider interface: ElevenLabsTTS streaming HTTP, LocalTTS espeak-ng, FallbackTTS), `speaker.py` (VoiceSpeaker:
wait for pause, unmute, stream, barge-in, re-mute; injected mic/activity/player), `audio_out.py`, `session.py` (LiveSession:
one asyncio loop coordinating everything), `chatread.py`, `playback.py`, `retranscribe.py`, `probe.py`, `timing.py`
(latency.jsonl), `events.py` (JSON event stream), `main.py` (CLI: doctor/login/start/join/run-mock/stt-probe/retranscribe/...).
Flags: `--stt captions|gemini|elevenlabs`, `--reply chat|voice|both`, `--auto-admit`, `--require`, `--record-audio`, `--context`.

Data flow today (elevenlabs mode): parec -> AudioGate (speech only) -> Scribe WebSocket -> partial/committed transcripts ->
question detection -> `quick_reply` (instant local answer OR one Gemini `generate_content` call returning JSON) -> reply is typed
into chat AND spoken (TTS -> paplay -> virtual mic) in parallel. A separate 20 s Gemini "analysis" call updates agenda state.

## 4. Measurements (this laptop, this network)

| Stage | Result |
|---|---|
| Meet live captions | Poor: "agenda"->"architecture"/"accent", "Tilo"->"Tyler/Heart"; only useful for speaker names/timing |
| Gemini batch audio STT per short clip | 2-4 s normally, 13-16 s when rate-limited (429 backoff) on free Express key |
| ElevenLabs Scribe v2 Realtime | Accurate ("What is on the agenda today?"); final text arrives **1.6-1.8 s after the phrase ends** (server VAD 0.6 s); no speaker ids returned for a single speaker (multi-speaker untested); keyterms supported; ~$0.39/h; 5-15% of audio actually sent thanks to gating |
| Gemini `generate_content` (Vertex Express key) | **Cold call after ~30 s idle = ~12 s** (8 s idle = 3 s); warm = 0.4-0.9 s. A separate isolated test with a 1-token ping every 5 s kept it at 0.4-0.8 s, but in the live meeting the model calls were still ~12 s (unexplained; suspect overlapping pings / per-thread connections / sync client in `asyncio.to_thread`) |
| Gemini Live API (native audio) | **Not available on the Express key**: every model name fails with `1007 Invalid resource field value`; needs a GCP project (billing) |
| ElevenLabs TTS | Free plan: `402 paid_plan_required` for library voices (default voice). Needs a voice owned by the account or a paid plan. Not yet measured |
| Local TTS (espeak-ng) | Works, robotic; first sound ~1.6-1.8 s after reply ready (includes Meet mic unmute click) |
| Meet chat typing (Playwright) | ~1.7 s per message |
| Question-to-first-sound, best path today | ~3.9 s (instant local answer: ~1.6 s detection + ~1.8 s unmute/TTS). Model path: 15-24 s in the meeting |

Other findings: Meet's host-via-`/new` skips the pre-join screen; the People panel and chat panel share one side panel (reading
one hides the other); Meet chat message DOM has `data-message-id` nodes without sender attribute and with "keep / Pin message"
UI text; bot's own messages must be filtered from typed-chat input.

## 5. Known bugs / gaps

1. Model calls still ~12 s in-meeting despite keep-warm (see above).
2. Typed chat messages without "?" are ignored; should all be treated as addressed to the agent.
3. After one answer, later questions were unanswered: model said "not answerable" (12 s), Scribe mishears ("beta ship" ->
   "leadership meet"); no spoken "I didn't catch that" fallback; check attempt/answered bookkeeping.
4. First sound still slow: mic unmute + TTS start; consider keeping the mic open while a conversation is active.
5. Speaker identity: rely on Scribe speaker ids (untested multi-party) vs caption-name voting.
6. Turn-taking is heuristic (energy VAD; wait for 0.6 s pause; barge-in after 0.5 s of continuous loud audio).

## 6. What I need from you

A. **Decision**: choose the target architecture and defend it against these alternatives with a latency budget per stage, cost
   per meeting-hour, free-tier viability and risk:
   1. Stay on this stack and optimise (persistent async connections, streamed LLM tokens -> sentence-level TTS, speculative
      answering from partial transcripts, dedicated async Gemini client instead of `to_thread`, keep the mic open).
   2. Enable billing on a GCP project: Gemini Live (native audio, server VAD, barge-in) or Google Cloud streaming STT + TTS.
   3. OpenAI Realtime (speech-to-speech) fed from the virtual audio devices.
   4. ElevenLabs Agents/Conversational AI (custom LLM, knowledge base) or Scribe + streaming TTS on a paid plan.
   5. A hosted meeting-bot API (e.g. Recall.ai-style) for audio in/out and transcripts.
   Consider a hybrid: a realtime speech model for the *conversation* plus my existing Playwright layer for joining, admitting,
   chat, and speaker names from captions.
B. **Architecture**: components, process/thread/async model, how audio flows in both directions, the turn-taking and barge-in
   state machine (who may speak when; addressed vs unaddressed; multiple humans; crosstalk), how grounding context (agenda,
   state, documents, chat) is supplied to a realtime model, echo/feedback avoidance, mic unmute strategy, failure modes and
   fallbacks (chat-only, local voice), and observability (per-stage latency log I can read after each meeting).
C. **Latency budget**: target numbers for end-of-question -> first sound, and where each ms goes.
D. **Build plan**: ordered tickets, each <= ~400 lines, with acceptance tests that run without paid calls (record/replay of
   `out/<run>/audio.wav` and `latency.jsonl`, fake servers), and for each ticket say whether **Claude Sonnet is enough or Opus
   is needed** (e.g. concurrency-critical realtime pipeline and the turn-taking state machine vs plumbing/UI/tests).
E. **What to keep, what to delete** from the current code, and the migration path so nothing that works today regresses.
F. The 3-5 riskiest assumptions and the cheapest experiment to test each before building (e.g. does my key/plan support X,
   measure X for 10 minutes of a real meeting).

Do not write the full implementation. Give the design, the decision rationale, the experiments and the ticket list.
Ask me at most 5 questions, only if the answer changes the architecture.
