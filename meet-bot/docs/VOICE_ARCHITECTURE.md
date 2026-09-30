# Meet bot voice architecture (v2)

Answer to `docs/ARCHITECT_BRIEF.md`. Date: 2026-09-30. Status: proposed; **revised the same day after your answers**
(section 8): the bot is part of the Builder Cup submission, a Gemini-native voice is wanted if it can be instant, and
free-tier data use is fine.
Numbers marked **measured** come from the brief or from `out/20260929-*/latency.jsonl`. Numbers marked **est.** are
estimates to confirm with the experiment named next to them (section 7).

---

## 0. Decision in brief

### Revised decision (after Q1 = yes, Q2 = yes)

**Target: Gemini Live native audio as the bot's voice, behind our own floor controller, provided experiment X4 shows it
is instant. Until then, and whenever Live fails, the streaming pipeline below is the voice.** Everything outside the
voice is the same in both cases (about 80% of the tickets): Scribe as the ears, Silero end-of-turn, the floor
controller, the UI fixes, the player and the trace.

"Instant" in numbers: first sound **heard in Meet at p50 ≤ 1.5 s and p90 ≤ 2.0 s** after the person stops talking.

**Live's trick is an early activityEnd.** We send `activityEnd` at `probable_end` (0.25 s of silence) instead of at the
confirmed end (0.45 s). We hold the model's audio until the end is confirmed, and interrupt with `activityStart` if the
person keeps talking. With x = our activityEnd → Live's first audio chunk:

`heard ≈ max(0.45, 0.25 + x) + 0.04 (player) + 0.25 (Meet)`

So Live meets "instant" if **x ≤ ~0.95 s at p50 and ≤ ~1.4 s at p90**. Artificial Analysis measures 0.96 s for
`gemini-3.1-flash-live-preview` and 1.18 s for `gemini-3.8-live` (with their own end-of-turn, so ours may do better).
That puts Live right at the edge. It is decidable in 15 minutes, and the probe is built: `python -m bot.main live-probe`
(section 7, X4).

- **If X4 passes:** VA-16 (Live responder) comes right after the orchestrator (VA-11). The cascade responder (VA-08,
  VA-10) becomes the fallback.
- **If X4 fails:** the plan below stands unchanged, and Live is re-probed whenever Google ships a faster Live model. The
  probe is one command.

The original analysis follows; its numbers and reasoning still hold.

### Original decision

**Keep this stack. Rebuild the reply path as a streaming pipeline, and own turn-taking in our own code.** Scribe v2 Realtime
stays as the ears. A local VAD decides when a turn has ended. A deterministic floor controller decides who may speak.
Gemini Flash streams text over a connection that is already warm, a streaming TTS voices it sentence by sentence, and a
long-lived, paced player feeds the virtual mic, with the Meet mic already open. The Playwright layer stays as it is.

Why this and not a speech-to-speech model:

1. **Today's latency comes from our plumbing, not the vendors.** The logs show that 3.9 s and 12-24 s break down into
   fixable local causes (section 1). With those fixed and every hop streaming, the estimate is about 1.1-1.3 s to the
   first sample at the bot and about 1.4-1.6 s heard in Meet (section 4). That is inside the ~1.5 s target.
2. **Speech-to-speech is not faster today, and it does not remove the hard part.** Artificial Analysis measures time to
   first audio at 1.18 s for `gemini-3.8-live`, 0.96 s for `gemini-3.1-flash-live-preview` and 0.81-0.97 s for OpenAI
   realtime. Our budget from confirmed end of turn to first sample is 0.65-0.85 s. Their method differs from ours, but
   none of them is clearly faster. The only faster model (2.5 native audio, 0.63 s) is now closed to new users. Deciding
   who is addressed, crosstalk, barge-in and echo are multi-party problems, and all these products are built for one
   person talking to one bot, so we would build the same floor controller in front of any of them.
3. **Text first keeps the product rules easy to meet.** The chat backup is exactly what was spoken. Grounding in
   documents is ordinary retrieval. Tests are record-and-replay of text and PCM. Everything runs on today's free keys,
   plus an optional $6/month voice.

**When to revisit:** add Gemini Live as a second `Responder` (ticket VA-16, already allowed for by the interfaces) only if
experiment X4 shows *our activityEnd → first audio chunk* at p50 ≤ 500 ms and p90 ≤ 800 ms from this laptop. The
cascade path from confirmed end of turn to first sample is ≈ 0.65 s with speculation and ≈ 0.85 s without (section 4).
Live needs to beat that clearly, mainly on p90 (one network hop instead of three), to be worth a second code path. If
the bot must showcase Gemini-native voice for the Builder Cup (question Q1), VA-16 moves up to right after VA-11. About
80% of the tickets are the same either way.

---

## 1. Where today's time goes (diagnosis from the logs)

| Symptom | Evidence | Cause (in code) |
|---|---|---|
| Model calls take 12 s | `model_s` is **bimodal**: 10 calls at 0.37-2.31 s, 4 calls at **11.94-12.28 s**. All four slow calls are in the **last two runs** (20:44 and 20:58, which had keep-warm pings and Scribe streaming). Easy questions were slow too ("What is on the agenda today?" 12.18 s), while the same kinds of question took 0.78-2.31 s in the earlier runs. | It is not model compute. That varies with the prompt, and easy questions would be fast. It is a fixed stall plus a retry. `GeminiLLM._invoke` treats any network error (`code is None`) as retryable and **sleeps 2 s, then 4 s**. Three candidates, all with this signature: **H1** a pooled HTTPS connection that Docker Desktop's NAT dropped silently hangs until an error, then 2 s backoff; **H2** slow DNS in the container on each new connection (resolver timeouts); **H3** a 429 caused by our own traffic (keep-warm ping every 5 s = 12 RPM, plus analysis, plus replies, on a tightly limited free key), then 2 s + 4 s backoff. The isolated ping test used one connection and no competing calls, which is why it looked fine. X1 says which cause it is; VA-01 fixes all three. Check the console log of that run for `retrying in`. There is also a latent bug: with `GEMINI_MODEL` empty, the model is the newest plain `gemini-N-flash` in the list, but thinking is disabled only when the name contains "2.5". 3.x Flash models think at medium by default. |
| ~1.6 s from speech end to "question detected" | `heard_to_detected_s` 1.6; Scribe `end_to_text_s` 1.16-1.9 **measured** | Scribe's server VAD waits 0.6 s of silence and then commits. On top of that: `partial_idle_s` 0.5 s, a 0.5 s main-loop tick, 100 ms capture frames, and `parec` with no `--latency-msec` (unknown capture delay; X5 measures it). |
| First sound ~1.8 s after the reply was ready | `first_audio_s` 1.77 ≈ `chat_typing_s` 1.75 | `_deliver` starts voice and chat together. `ChatPoster.send` and `set_mic` share `browser.lock`, and chat holds it for ~1.75 s (including a fixed `sleep(0.8)`), so **the unmute waits behind chat typing**. On top of that, `FallbackTTS` tries ElevenLabs (402) before espeak, and espeak renders the whole text before yielding. |
| "Takes only one question" | "When does the leadership meet?" was attempted (12 s, no answer). The repeat "I lose. When does the leadership meet?" was **silently dropped** | `Brain._attempted` removes duplicates by *normalised text*, so a repeated question after a failed attempt is never tried again. There is no spoken fallback, so the failure is silent. Scribe misheard "beta ship" (keyterms are only the bot name and agenda titles). |
| Nothing else happens while the bot talks | The main loop awaits `_finish_quick → _deliver` for the whole utterance (12.6 s in the log) | Captions, chat reads, question detection and admitting all stop during speech. The People-panel read (every 15 s) also blocks the loop. |
| Typed chat without "?" ignored | `session._read_chat` treats a message as a question only if it ends in "?" or starts with the bot name | Policy bug. |

**What this means:** none of these causes is intrinsic to Scribe, Gemini or Meet. Fixing them (Phase 1, four small
tickets) should bring the model path from 15-24 s to about 2.5-3 s, and the instant path from 3.9 s to about 2 s,
**before** any new architecture.

---

## 2. Options compared (A)

Latency means end of the human's question → first sound **heard by a human in Meet**. It includes about 0.25 s of Meet
transport (est., X5), which every option pays.

Assumptions for cost: a busy real meeting has about 40 min of human speech per hour and about 3 min of bot speech (30
answers). Today's test meetings send only 5-15% of audio. Prices are vendor list prices checked on 30 Sep 2026 (sources in
the research notes at the end of this section).

| Option | Heard latency p50 (est.) | Cost per meeting-hour | Free tier | Multi-party fit | Risk | Verdict |
|---|---|---|---|---|---|---|
| **1. This stack as a streaming pipeline:** Scribe, local end-of-turn, Gemini Flash stream, ElevenLabs Flash WS, paced player | **1.3-1.55 s** (1.05-1.3 s at the bot, section 4) | Test meetings: $0.02-0.10 (Gemini free on Express; Scribe $0.39/h × 5-15%). Busy meeting, all paid: about $0.5-0.9 (Scribe ~$0.26, Flash-Lite answers + analysis ~$0.3-0.5, TTS ~$0.1) | **Yes.** Express key, Scribe on free credits, local voice. A natural voice is ElevenLabs Starter at $6/month (30k credits) | Full control with our own floor controller | **Low.** Every hop is measured except TTS first byte (X3) | **Fallback voice, and the voice until X4 passes** |
| 2a. Gemini Live (`gemini-3.8-live`, AI Studio key) with the Playwright layer | 1.4-1.9 s: third-party time to first audio 1.18 s (3.1 Live 0.96 s), plus our end-of-turn and transport; served from US/EU | About $0.6-0.9 if only addressed turns go in as audio plus a text card (the whole context is billed every turn), plus Scribe for the transcript. About $3 if it hears everything without a sliding window | Yes on an AI Studio key (Google may use free-tier data; limits unpublished). **Not** on Express | Manual activity detection gives us the floor. 3.8 has proactive audio always on (it may choose silence), which cannot be turned off | **High.** Slower than option 1 today; 15-min sessions without compression, ~10-min connections; the fast 2.5 model is closed to new users; no Asian Vertex region | **Target voice if X4 passes** (VA-16); an early activityEnd makes 1.3-1.5 s heard plausible |
| 2b. GCP billing for Cloud STT + Chirp 3 HD TTS | ≈ option 1. TTS might be faster, since Chirp 3 HD streams from asia-southeast1 | TTS $30 per 1M characters with 1M free per month (unverified) | Needs billing | Same as 1 | Medium: billing and IAM set-up, no gain in end-of-turn detection | Test Chirp 3 HD in X3 if billing is enabled; it is a TTS swap, not an architecture |
| 3. OpenAI Realtime (`gpt-realtime-2.1` or mini) | 1.3-1.7 s (third-party 0.81-0.97 s, plus end-of-turn and transport) | About $1-1.5 full or $0.4 mini (audio $32/$64 per 1M tokens, 600 in and 1,200 out per minute, conversation re-sent every turn), plus Scribe | No | 1:1 design; needs the same floor controller | Medium; off the Google stack | Rejected |
| 4a. ElevenLabs Agents (custom LLM) | ~1-1.5 s (not published) | $0.08 per session minute, so about $4.80/h if connected all meeting, plus LLM | 15 free minutes | 1:1 turn-taking model that would compete with our floor rules | Medium; cost | Rejected |
| 4b. Scribe + streaming TTS on a paid ElevenLabs plan | = option 1 | = option 1 | Starter $6/month | = option 1 | = option 1 | This is option 1's voice |
| 5. Hosted bot API (Recall.ai) with our models | Adds ~0.3-0.6 s (audio round-trips through their cloud in 200 ms chunks, est.) | $0.50/h (+$0.15 for transcripts), 5 h free, plus models | Partly | Output Media renders a web page as the bot's video. Signed-in bots need a paid Workspace, not consumer Gmail | **Breaks "meeting content goes only to local files and model/speech providers"**; the bot joins as a guest | Rejected. Revisit only if Meet UI automation becomes the main failure |

**End-of-turn contingency:** Deepgram Flux claims ~260 ms semantic end-of-turn. Its `EagerEndOfTurn` and `TurnResumed`
events map one-to-one onto our `probable_end` and `resume` (~$0.46/h). It is the drop-in upgrade if X6 shows our
silence-plus-lexical rule cuts people off or waits too long. `stt_stream` stays behind an interface so an adapter fits.
AssemblyAI Universal-Streaming ($0.15/h) bills idle session time, which conflicts with "never spend on silence".

**Scribe facts that shape the design** (vendor docs, Sep 2026):
- Manual commit is the default mode, with an automatic commit at about 36 s.
- VAD mode's default silence threshold is 1.5 s (we use 0.6 s).
- Up to 50 keyterms are allowed; our code caps them at 10.
- **There is no realtime diarization.** Speaker names come from caption voting (`SpeakerNames` and `assign_speaker`, which
  already work), and brief item 5 is settled that way.

Research notes (all accessed 30 Sep 2026):
- Gemini pricing and models: ai.google.dev/gemini-api/docs/pricing, /models, /live-guide, /live-session
- Time to first audio: artificialanalysis.ai/speech-to-speech
- Express mode reference: docs.cloud.google.com/vertex-ai/generative-ai/docs/start/express-mode/vertex-ai-express-mode-api-reference
- ElevenLabs: elevenlabs.io/pricing/api, /pricing/agents, /docs/eleven-api/guides/how-to/speech-to-text/realtime/transcripts-and-commit-strategies
- OpenAI: developers.openai.com/api/docs/pricing, /guides/realtime-costs
- Recall.ai: recall.ai/pricing, docs.recall.ai/docs/stream-media, docs.recall.ai/docs/google-meet-login-getting-started
- Deepgram and AssemblyAI: deepgram.com/pricing, assemblyai.com/pricing

---

## 3. Architecture (B)

### 3.1 Components

```
 container: one asyncio loop (control + all network I/O) + 1 capture thread + subprocesses (parec x2, pacat)

 Meet audio -> tilo_out.monitor -> parec(20 ms) -> AudioIn thread: 32 ms frames -> Silero VAD -> VadStart/VadEnd --+
                                                    |  ring buffer 30 s, audio.wav                                     |
                                                    +-> AudioGate (VAD-driven) -> ScribeStream WS (manual commit) --+
                                                                                  Partial / Final(words, speaker)   |
 Meet captions -> CaptionReader -> speaker spans, CaptionActivity (who is talking) -------------------------------+
 Meet chat -----> ChatReader -> ChatMessage (every human message is addressed) -----------------------------------+
                                                                                                                  v
                                                            FloorController (pure, deterministic)  <-- Tick (every VAD frame)
                                                                                  | Actions
            +--------------------------------- Orchestrator (async) -------------+---------------------------------+
            | Responder:  InstantResponder (notes, 0 ms)  ->  GeminiResponder (streamed text, warm client)       |
            | TTS:        sentence chunker -> ElevenLabs WS (stream-input) | local voice | phrase cache (PCM in RAM) |
            | Player:     one long-lived pacat, 20 ms paced writes, <=100 ms in flight -> tilo_mic_sink -> tilo_mic |
            | UI:         priority scheduler over MeetBrowser: mic > chat post > chat read > admit > People panel     |
            +--------------------------------------------------------------------------------------------------------+
 Brain analysis (every 20 s, paused while a turn is active) -> meeting card (agenda, decisions, actions, topic) -> Responder
 Trace: turns.jsonl, connections.jsonl, audio.wav + bot.wav (tilo_mic_sink.monitor)  ->  `report`, `audit`
```

### 3.2 Process, thread and async model

- **One asyncio loop** owns everything that decides or talks to the network: FloorController steps, Orchestrator, Scribe
  WS, Gemini (`client.aio`, streaming), TTS WS, Playwright. **No `asyncio.to_thread` in the voice path.**
- **One capture thread** (today's `LiveRecorder`, kept) reads `parec` and runs VAD on each 32 ms frame (Silero ONNX is
  about 1 ms per frame on one core, est.). It posts `(frame, t)` and VAD events to the loop with `call_soon_threadsafe`.
  VAD stays off the loop so Playwright stalls cannot delay barge-in detection.
- **Subprocesses:** `parec` for meeting audio, a second `parec` for the bot's own mic monitor (`bot.wav`, observability
  only), and one long-lived `pacat` for playback.
- **FloorController is a pure object:** `step(event) -> list[Action]`, with no I/O, no awaits and an injected clock.
  All concurrency lives in the Orchestrator, which runs the actions as cancellable tasks, at most one response task per
  turn.
- **The UI scheduler** serialises Playwright actions through one priority queue, so a mic toggle never waits behind a
  chat post or a People-panel read. The main loop never awaits delivery; delivery runs as tasks.

### 3.3 Audio flows

**In:** Meet → `tilo_out` (default sink) → `parec --latency-msec=20` → 32 ms frames on the audio clock → (a) VAD events,
(b) ring buffer and `audio.wav`, (c) `AudioGate` → Scribe. Only frames the VAD marks as speech, plus 300 ms of lead-in and
a 500 ms tail, are sent, and only while the gate is open and humans are present. **Never spend on silence** still holds,
and it improves: the VAD does not open on keyboard noise the way the energy gate does.

**Out:** response PCM (24 kHz s16le: Gemini Live's native rate and ElevenLabs `pcm_24000`; the local voices are
resampled once per phrase) → Player → `pacat
--device=tilo_mic_sink --latency-msec=30` → `tilo_mic` (remap of `tilo_mic_sink.monitor`) → Chromium's default source →
Meet. The player writes 20 ms chunks paced by the clock, with at most 100 ms queued, so a stop is audible within about
130 ms. Ducking is done by scaling samples in the writer.

### 3.4 Turn-taking and barge-in state machine

States: `IDLE` → `CAPTURE` (an addressed human turn in progress) → `THINK` (turn confirmed, answer not yet audible) →
`SPEAK` → `FOLLOWUP` → `IDLE`. Humans always win. The bot never starts while any human is speaking.

Timers (all in `FloorConfig`, defaults shown):

| Name | Default | Meaning |
|---|---|---|
| `probable_end_s` | 0.25 | Silence after the addressed turn: start the answer **speculatively** (audio is held back). |
| `confirm_end_s` | 0.45 / 0.80 | Silence that confirms the end of the turn: 0.45 s if the text looks complete (question or imperative, no trailing "and/so/um/the/to"), else 0.80 s. A Scribe final also confirms. |
| `resume_s` | 0.70 | A voice within this time after confirming means the same person was not finished: cancel and merge. |
| `floor_free_s` | 0.20 | The bot may start only after this much silence from everyone. |
| `one_moment_s` | 1.50 | No audio yet: play the cached "One moment." once, if the floor is free. |
| `stale_s` | 4.0 | Answer ready but the floor stayed busy: chat only, no voice. |
| `duck_after_s` / `stop_after_s` | 0.25 / 0.60 | Human voice while the bot speaks: duck to 30%, then stop. Also stop at once if a partial shows 2 or more non-backchannel words. |
| `followup_s` | 8.0 | After the bot speaks, a question from anyone counts as addressed without the wake word. |

Transitions (the ticket VA-09 implements exactly this table):

| State | Event / condition | Actions | Next |
|---|---|---|---|
| IDLE / FOLLOWUP | `Partial` or `Final` text is addressed (3.5) | `OpenMic` (if policy = conversation), `Prewarm` (LLM + TTS), `PrepareTurn` | CAPTURE |
| IDLE / FOLLOWUP | `ChatMessage` from a human | `StartResponse(text, spec=False)`, `Confirm` | THINK |
| FOLLOWUP | `followup_s` passed | `CloseMic` later (policy) | IDLE |
| CAPTURE | silence ≥ `probable_end_s`, no speculation running | `StartResponse(text, spec=True)` | CAPTURE |
| CAPTURE | `VadStart` (speaker continues) | `Cancel(spec)` | CAPTURE |
| CAPTURE | silence ≥ `confirm_end_s` or `Final` | `CommitSTT`; if the speculative text still matches (≥ 90% same tokens) `Confirm`, else `Cancel` + `StartResponse(final text)` + `Confirm` | THINK |
| THINK | audio ready and floor free | `StartPlayback`; after the first sample, `PostChat(full text)` | SPEAK |
| THINK | `VadStart` within `resume_s` of confirming | `Cancel`, keep the turn text | CAPTURE |
| THINK | `VadStart` later | hold (floor busy) | THINK |
| THINK | `one_moment_s` passed, no audio, floor free | `SpeakPhrase(one_moment)` (once per turn) | THINK |
| THINK | `stale_s` passed with the floor busy | `PostChat(answer)` when ready, drop voice | FOLLOWUP |
| THINK | `ResponseFailed(kind)` | `SpeakPhrase(kind)` + `PostChat(line)` | FOLLOWUP |
| SPEAK | human voice ≥ `duck_after_s` (not echo, 3.7) | `Duck(0.3)` | SPEAK |
| SPEAK | human voice ends before `stop_after_s` (backchannel) | `Duck(1.0)` | SPEAK |
| SPEAK | human voice ≥ `stop_after_s`, or 2+ real words | `StopPlayback`, `Cancel`; the interrupter's turn counts as addressed | CAPTURE |
| SPEAK | `PlaybackDone` | set `followup_until` | FOLLOWUP |
| any | a new addressed turn while a response is unstarted | cancel the older response (newest wins) | CAPTURE |

Invariants, enforced by property tests:
- No `StartPlayback` while any VAD speech is active, or within `floor_free_s` after it.
- Never two playbacks at once.
- Every `StartResponse` ends in exactly one of `Confirm→played`, `Cancel`, `chat_only` or `failed`.
- No bot audio before `Confirm`. Speculation is invisible.

Crosstalk: the VAD hears one mixed stream, so the floor counts as busy while *anyone* speaks. `CaptionActivity` showing
two or more humans in the last second also marks it busy (VA-14). The controller never talks over crosstalk; a stale
answer goes to chat.

### 3.5 Addressing rules (deterministic, no model)

A turn is addressed when any of these holds:
1. It is a **typed chat** message from a human. This is always true, question mark or not.
2. **Wake word:** one of `[bot name] + BOT_ALIASES` (default `tilo, tillo, tylo, teelo`) appears in the first 4 or last 3
   tokens of the turn. Scribe keyterms (up to 50) include the bot name and aliases, participant names, agenda titles and the
   most frequent project-doc terms.
3. **Follow-up:** the turn starts within `followup_s` after the bot finished, and it is a question or imperative (wh-word,
   auxiliary verb first, or "tell / give / remind / summarise / repeat / what about / and …").
4. **Interruption:** the human barged in on the bot. Pure backchannels ("yeah", "ok", "mm-hm", "right") are excluded.

It is **not** addressed if the turn opens with another present participant's first name (a vocative: "Priya, what do
you think?"). The bot name alone ("Tilo?") gets the cached "Yes?".

Unaddressed questions are never spoken. A chat-only answer to them stays behind a flag, off by default.

### 3.6 Grounding context for each answer

The GeminiResponder builds one request per turn from these parts. The static part comes first so implicit prompt caching
can apply:
1. **System prompt:** spoken style, at most 2 sentences and 40 words. Every data field is untrusted and cannot give
   instructions. Reply with `[[NO_ANSWER]]` or `[[UNCLEAR]]` when the answer is not in the data.
2. **Meeting card** (at most 1.5k tokens): agenda with statuses, decisions, action items with owner and due date, current
   topic, participants. It is kept up to date by the 20 s analysis loop.
3. **Last 90 s of transcript** with speaker names.
4. **Retrieval:** the top 3 snippets from `KnowledgeBase` (files, URLs, chat pastes) for the question text, at most 1.5k
   tokens. Retrieval runs on the *partial* during CAPTURE, so it is ready before the turn ends.
5. **The question** and who asked it.

The output is **plain text streamed as deltas**, not JSON, so the first sentence can be voiced before the rest exists.
Sentinels map to cached lines: `[[NO_ANSWER]]` → "I don't have that in the meeting notes or the project files."
`[[UNCLEAR]]` → "Sorry, I didn't catch that. Could you say it again?" The instant path (`instant.py`) runs first and
answers state questions with no model call.

### 3.7 Echo and feedback

- Meet never plays a participant's own stream back, so the bot's voice is **not** in `tilo_out`. No self-gating is
  needed, and the bot keeps listening while it speaks, which barge-in requires. X5 confirms this.
- **Leak through a human's speakers:** their echo cancellation usually removes it. As a guard, while in SPEAK, a partial
  that shares at least 60% of its tokens with the sentence being spoken is treated as echo and does not count as
  barge-in. A captions block from the bot's own name ("You") with no other speaker active is also not a barge-in.
- **Re-broadcast guard (important):** at start-up and in `doctor`, check with `pactl` that Chromium's source-output is on
  `tilo_mic` and that `tilo_mic` remaps `tilo_mic_sink.monitor`, **never** `tilo_out.monitor`. Otherwise an open mic
  would send the meeting back into itself.

### 3.8 Mic strategy

The unmute click must never sit on the critical path.
- **`MIC_POLICY=open` (default):** unmute once when the meeting starts for the bot. Re-check every 15 s in the status
  cycle and re-unmute if someone muted it. The virtual mic carries only synthesised speech and is digital silence
  otherwise, so an open mic sends nothing. This is the only policy with zero added latency.
- **`MIC_POLICY=conversation`:** unmute when a turn becomes *addressed*, which overlaps the rest of the question (the
  toggle takes ≤ 0.5 s, est.). Mute after 20 s of `IDLE`.
- Toggling uses Meet's Ctrl+D through the UI scheduler at top priority, followed by an aria check that runs *after*
  playback has started. Whether Ctrl+D works while the chat box has focus is checked in X5.

### 3.9 Connections: warm on intent, deadlines, heartbeats

- **Warm on intent:** the moment a turn becomes addressed (usually 0.5-2 s before it ends), the Orchestrator (a) sends a
  non-generating request (`models.get`) on the fast Gemini client, which warms DNS, TCP and TLS without using generation
  quota, and (b) opens the TTS WebSocket. Scribe stays connected while humans are present: no audio sent means no cost.
- **No generation keep-warm pings.** They use up the free RPM (hypothesis H3).
- **Deadlines on the fast path:** Gemini first token ≤ 2.5 s, then one *immediate* retry on a fresh client, then a
  fallback line. A 429 is never retried on the fast path. TTS first PCM ≤ 1.2 s, else the local voice for this turn.
  **No sleeping backoff on the fast path, ever.** The analysis path keeps its backoff and yields to the fast path, which
  has its own token bucket.
- **Heartbeats:** every WebSocket pings every 10-15 s. HTTP `keepalive_expiry` is set below the NAT idle limit measured in
  X1 (4 s until measured). Every connect, stall, retry and reconnect goes to `connections.jsonl`.

### 3.10 Failure modes and fallbacks

| Failure | Detection | Fallback |
|---|---|---|
| Scribe down or quota | WS fatal message or reconnects failing | Captions become the transcript (exists). Voice answers continue, but addressing can use only captions (worse). Logged once. |
| Gemini slow | no first token by `one_moment_s` | "One moment." then wait until the 2.5 s deadline, retry once, then the `[[NO_ANSWER]]`-style line "I couldn't get that just now." and chat. |
| Gemini 429 | status code | Instant answers only for this turn; the analysis interval doubles. |
| TTS plan or key error | 401/402/403 | Local voice for the rest of the meeting (exists in `FallbackTTS`). |
| TTS slow | first PCM > 1.2 s | Local voice for this turn. |
| Mic toggle fails | aria check | Chat only for the answer; `selector_miss` screenshot. |
| Playback process dies | pacat exit | Restart; the turn falls back to chat. |
| UI stuck | UI task over 5 s | Voice continues if the mic is open; chat posts queue up. |
| Everything voice-related down | health = down | `--reply chat` behaviour: answers in chat only. |

### 3.11 Observability

- `turns.jsonl`: one row per turn with the route (instant, model, chat), outcome (spoken, interrupted, chat_only, failed,
  cancelled), text, asker, and marks relative to `speech_end` (the VAD end of the human turn, on the audio clock):
  `addressed, probable_end, confirmed_end, stt_final, llm_request, llm_first_token, first_sentence, tts_request,
  tts_first_pcm, first_sample, barge_duck, barge_stop, playback_end, chat_posted`.
- `connections.jsonl`: connect, prewarm, attempt (with code and durations), stall, reconnect.
- **Two-channel audio:** `audio.wav` (meeting) and `bot.wav` (from `tilo_mic_sink.monitor`) on one clock.
  `python -m bot.main audit out/<run>` measures *speech end → first bot sample* from the waveforms (±20 ms), which checks
  the log marks against the audio.
- `python -m bot.main report out/<run>` prints a per-turn waterfall and p50/p90 per stage:

```
turn 7  route=model  outcome=spoken  asked_by=John  "Tilo, when does the beta ship?"
  addressed       -1.21   wake word in partial
  probable_end     0.25   speculative LLM start
  confirmed_end    0.45
  llm_first_token  0.71
  first_sentence   0.79
  tts_first_pcm    1.08
  first_sample     1.11   (budget 1.30)   audit 1.13
  chat_posted      1.64
summary  n=18  first_sample p50 1.12 p90 1.71 | llm_ttft p50 0.41 | tts_ttfb p50 0.29 | barge stop p50 0.19 | retries 1
```

### 3.12 Gemini Live as the voice (VA-16, if X4 passes)

Live replaces only the Responder and TTS box in 3.1. It implements `AudioResponder`: it takes a turn and yields PCM
plus text. The floor controller, player, trace and fallbacks do not change.

- **Session life:**
  - One session per meeting, opened when the meeting starts for the bot (the gate), so no turn pays the setup cost.
  - Manual activity detection (`automaticActivityDetection.disabled`).
  - Context-window compression with a sliding window, which is mandatory: sessions otherwise stop at 15 min, and the
    whole context is billed every turn.
  - Session resumption on `goAway`: connections last about 10 min, and we reconnect in the background before the
    current one ends.
  - A WebSocket ping every 10-15 s. An idle session costs nothing.
- **What goes in:**
  - Only addressed turns are sent as audio. The floor controller already decided the turn was addressed; the audio
    starts from the turn's first frame, taken from the ring buffer, so a wake word at the start is included. It is sent
    between `activityStart` and `activityEnd`.
  - Unaddressed speech is never sent as audio. The model hears it only as text: Scribe finals are batched every ~20 s
    into `clientContent` with `turnComplete: false`, which adds context without triggering an answer.
  - The meeting card goes in the system instruction at start and as a `clientContent` update when the analysis loop
    changes it.
  - Retrieval snippets for the question (from the partial) are sent as `clientContent` just before `activityEnd`, on
    the same socket, so no extra round trip.
- **Early activityEnd (speculation):**
  - `activityEnd` is sent at `probable_end`. Audio chunks are buffered and released to the player at `Confirm`.
  - If the person resumes before `Confirm`, send `activityStart` (which interrupts the model), keep streaming their
    audio, and send `activityEnd` again at the next probable end. The model sees one turn split in two, which is
    harmless.
- **What comes out:**
  - Model audio (24 kHz) goes to the player. The player's rate becomes 24 kHz for all providers, including the cascade.
  - The output transcription is posted as the chat mirror after speech ends. It is the model's own speech recognised
    as text, so it is close to, but not guaranteed identical to, what was said. Section 0's "exactly what was spoken"
    holds only for the cascade.
  - The system prompt says every audio turn is addressed and must be answered, because `gemini-3.8-live` has proactive
    audio always on and may otherwise stay silent. X4 counts silent answers.
- **Barge-in:** `StopPlayback` locally (≤ 130 ms), then `activityStart` for the interrupter's turn, which also cancels
  the model's generation.
- **Per-turn fallback:** no audio chunk within 1.5 s of `Confirm`, a closed socket or a 429 → this turn goes to the
  cascade responder (its TTS WebSocket is already warm) and Live reconnects in the background. Two failures in 5 minutes
  → cascade for the rest of the meeting. Logged in `connections.jsonl`.
- **Typed chat questions:** sent as `clientContent` with `turnComplete: true`, answered in voice and mirrored to chat.
- **Model ids:** `LIVE_MODELS` in config only (already done for the probe in `bot/config.py`).

### 3.13 Builder Cup implications (Q1 = yes)

- **Tilo's PRD has no requirement for a meeting bot yet.** Tilo's rules say a feature needs a requirement ID before it
  becomes Tilo code, and the PRD is read-only for builders. So `meet-bot/` stays a standalone prototype until you add a
  requirement (for example as a channel in P5).
- **When it moves into Tilo:**
  - Every model and speech call (Gemini text, Live, Scribe, TTS) moves behind `packages/providers` with ids in
    `config/` (PL-01).
  - Tests stay record-and-replay (EFF-01).
  - The container runs as a Cloud Run job per meeting in `asia-southeast1`. The Live endpoint itself is global, served
    from US/EU.
- **Until then:** every new module is written provider-shaped: `Responder`, `AudioResponder`, `TTSProvider` and
  `SttStream` interfaces with config-only model ids. That makes the port mechanical.

---

## 4. Latency budget (C)

**Targets** (end of the human's question → first sample written to the virtual mic; add about 0.25 s of Meet transport
for "heard"):
**model path p50 ≤ 1.3 s, p90 ≤ 2.0 s; instant path p50 ≤ 0.8 s; fixed phrases ≤ 0.5 s; barge-in stop ≤ 0.3 s after the
human starts.**

| Stage | Today (measured) | Target p50 | How |
|---|---|---|---|
| Capture delay (parec) | unknown | ≤ 0.03 | `--latency-msec=20`, 32 ms frames (X5 measures today's value) |
| End-of-turn decision | 1.16-1.9 (Scribe VAD commit + 0.5 idle + 0.5 tick) | 0.45 (0.80 if the text looks incomplete) | local Silero VAD + lexical completeness; Scribe manual commit |
| Retrieval + prompt | inside `model_s` | 0 on the critical path | done on partials during CAPTURE |
| LLM first token | 0.4-0.9 warm, 12 cold | 0.40 (starts ~0.2 s early when speculation hits) | `client.aio` streaming, warm on intent, thinking minimal, Flash-Lite (X1) |
| First sentence complete | n/a (JSON, whole reply) | +0.10 | plain-text streaming, short first clause |
| TTS first PCM | espeak whole-text + failed ElevenLabs call first | 0.30 | ElevenLabs Flash WS opened on intent (X3); cached phrases 0 |
| Mic | ~1.75 (waits behind chat) | 0 | open-mic policy |
| Player to virtual mic | new `paplay` each time | 0.04 | long-lived pacat, paced writes |
| **First sample at the bot** | **3.9 instant / 15-24 model** | **≈1.3 serial, ≈1.1 with speculation; instant ≈0.8** | |
| Meet transport | not measured | ~0.25 | X5 (a phone recording, once) |

Serial model path: 0.45 + 0.40 + 0.10 + 0.30 + 0.04 = 1.29 s. With speculation from 0.25 s, the LLM and part of the
TTS run before the turn is confirmed, which gives ≈1.05-1.15 s. Instant path: 0.45 + 0.30 + 0.04 = 0.79 s.

---

## 5. Build plan (D)

Ticket ids are `VA-nn`. Test names contain the id (`test_VA_09_barge_in_stops_within_one_tick`). Each ticket is at most
~400 hand-written lines including tests (fixtures excluded), runs `python -m pytest` green, and makes **no paid calls**:
only fakes, synthetic fixtures (espeak-voiced speech, tones, noise) and fake servers. Real meeting recordings in `out/`
are gitignored and are **never** copied into `tests/fixtures`; `replay` runs on them locally as a developer tool only.

**Model column:** Sonnet is enough for plumbing with a clear spec. Opus is for the concurrency-critical pieces (the state
machine, speculation and cancellation, and the session integration). An Opus reviewer is recommended on VA-07 and VA-12.

### Phase 0: experiments (about 1 hour of your time, a few cents; section 7)
**X4 first** (the probe is built: `python -m bot.main live-probe`), then X1, X2, X3 and X5 before Phase 2. X6 runs
after VA-09, on recordings.

### Phase 1: fix the bleeding in v1 (ships value in days; all four can run in parallel)

| Id | Ticket | Acceptance tests (offline) | Size | Model |
|---|---|---|---|---|
| VA-01 | **Fast-path model client.** `bot/llm_fast.py`: `FastLLM` on `client.aio.models.generate_content_stream`, one client per purpose (`fast`, `analysis`), first-token deadline 2.5 s, one immediate retry on a fresh client, a 429 raises `Busy` with no sleep, `prewarm()` = `models.get` rate-limited to once per 10 s. Thinking comes from config (`FAST_THINKING`), not from the model name (today only names containing "2.5" get `thinking_budget=0`). Fast model from config (`FAST_MODEL`): `gemini-2.5-flash-lite` while the key still has it (thinking off by default, $0.10/$0.40), else `gemini-3.1-flash-lite` with minimal thinking (on 3.x, "minimal" is not guaranteed to be off). X1 picks. The analysis loop keeps `GEMINI_MODEL`. Delete `_keep_warm`. Every attempt logged. | A fake client that hangs → a retry that succeeds within deadline + 50 ms. 429 → `Busy` with no sleep call. Connection reset → immediate retry. Deltas arrive in order. The attempt log has outcome, code and first-token time. No model-id literal outside config. | ~250 | Sonnet |
| VA-02 | **Question bookkeeping and chat.** Every human chat message is addressed. Attempts are tracked by utterance or message id, not by text. Addressed but unanswerable or unclear gets a spoken and chat fallback line (sentinels). Scribe keyterms (cap raised to 50) add participant names and the most frequent project-doc terms. | Replay of the 29 Sep sequence: the repeated "When does the leadership meet?" is attempted again. "When does the beta ship" (no ?) in chat → answered. `[[NO_ANSWER]]` → the fallback line in voice and chat. | ~200 | Sonnet |
| VA-03 | **The voice never waits for the UI.** A priority UI scheduler (mic > chat post > chat read > admit > People). The chat critical section has no `sleep(0.8)` inside the lock (poll the box instead). `MIC_POLICY=open` with a 15 s re-check. `_deliver` and People reads run as tasks, and the main loop tick drops to 0.1 s. The chat mirror is posted after the first sample. | A fake browser with a 2 s chat post: mic toggle starts ≤ 50 ms after the request. During a 10 s fake utterance, the loop keeps processing captions and chat. With the open policy there are no mic calls per answer. | ~250 | Sonnet |
| VA-04 | **Turn trace, report, two-channel audio.** `bot/trace.py` (marks as in 3.11), `connections.jsonl`, `bot.wav` from `tilo_mic_sink.monitor`, `report` and `audit` CLI commands. `parec --latency-msec=20`. | Synthetic `turns.jsonl` → exact p50/p90. Synthetic WAVs with tones at known offsets → `audit` within ±20 ms. The report prints the waterfall. | ~300 | Sonnet |

### Phase 2: the streaming pipeline (v2, behind `--voice-engine v2`)

| Id | Ticket | Acceptance tests (offline) | Size | Model |
|---|---|---|---|---|
| VA-05 | **Replay harness and fakes.** `ReplaySource` (WAV → frames on a virtual clock). Record raw Scribe messages with audio-clock time to `stt.jsonl` and replay them. `FakeLLM` (scripted deltas and delays), `FakeTTS` (tone with a set TTFB), `FakePlayer` (sample timestamps), `FakeUI`. `replay out/<run> --fake-latency llm=0.45,tts=0.30`. | A 20 s synthetic fixture replays deterministically (same `turns.jsonl` twice). Virtual clock: a 60 s replay runs in under 2 s. | ~350 | Sonnet |
| VA-06 | **AudioIn with Silero VAD.** 32 ms frames, Silero via onnxruntime (MIT; model file pinned by hash at image build), hysteresis 0.6/0.35, min speech 120 ms. Emits `VadStart/VadEnd(t)`. `AudioGate` driven by the VAD. Energy VAD fallback if the model is missing. Licences in `docs/licences.md`. | espeak speech + noise + silence fixtures: event times within ±40 ms. Noise alone → no `VadStart`. Model missing → energy fallback with a warning. | ~250 | Sonnet |
| VA-07 | **Paced persistent player.** `bot/voice_out.py`: long-lived pacat at 24 kHz, 20 ms paced writes with ≤ 100 ms lead, `play/duck/stop`, `first_sample` and `end` marks, restart on crash. Replaces `audio_out.Player`. | Fake sink process: in-flight audio never above 100 ms; after `stop`, no bytes within 25 ms; `duck(0.3)` scales samples; a killed process is restarted and the next `play` works. | ~200 | Sonnet (Opus review) |
| VA-08 | **Streaming TTS and phrase cache.** ElevenLabs stream-input WebSocket (`pcm_24000`), local voices resampled to 24 kHz, `open_on_intent()`, sentence chunker (first chunk cut at the first `.?!` or at a comma after 60 characters). Fixed phrases rendered once at start-up and kept as PCM. Local fallback voice (Piper if its licence passes review, else espeak). `FallbackTTS` semantics kept. | Fake WS server: first audio is requested right after the first sentence; a cached phrase returns in ≤ 5 ms; 402 → local voice for the meeting; the key never appears in logs. | ~350 | Sonnet |
| VA-09 | **FloorController and addressing.** `bot/floor.py` (table 3.4) and `bot/addressing.py` (3.5). Pure and clock-injected. | 15 scenarios on a virtual clock: wake first; wake last; unaddressed question; follow-up inside and outside 8 s; chat while idle and while a human talks; resume after probable end (speculation cancelled); resume after confirm (merge); backchannel (duck then resume); real barge-in (stop in one tick); crosstalk → stale → chat only; two addressed turns (newest wins); vocative to another person; "Tilo?" → "Yes?". Property tests for the 3.4 invariants. | ~400 (split a/b if over) | **Opus** |
| VA-10 | **Streaming responder.** `bot/responder.py`: `InstantResponder` (wraps `instant.py`), `GeminiResponder` (VA-01 client, prompt as in 3.6, plain-text deltas, 40-word cap, sentinels), and the `Responder` protocol (`stream(req) -> AsyncIterator[str]`). | The prompt holds card, transcript and retrieval as JSON data under `untrusted`. Sentinel → phrase key. Instant beats model. Length cap. Markdown stripped. | ~250 | Sonnet |
| VA-11 | **Orchestrator: speculation, cancellation, warm on intent.** It runs FloorController actions over Responder, TTS, Player and UI, and accepts both a text `Responder` (then TTS) and an `AudioResponder` (PCM straight to the player) from the start, so VA-16 plugs in without changes. Speculative start with audio held until `Confirm`, cancel on resume or text drift, prewarm on `addressed`, "One moment" and stale handling, chat mirror once per answer, trace marks. | With fakes (LLM TTFT 0.45 s, TTS 0.30 s, confirm at 0.45 s): first sample ≤ 1.20 s + 30 ms overhead; with speculation from 0.25 s ≤ 1.00 s + 30 ms. No sample before `Confirm`. After cancel, no task is left running. Barge-in → `player.stop` within one frame. LLM hang → "One moment" at 1.5 s, then the fallback line. The chat mirror is posted exactly once with the full text. | ~400 | **Opus** |
| VA-12 | **Scribe manual commit.** `commit_strategy=manual` (the vendor default; server auto-commit at ~36 s), keyterm cap raised from 10 to 50, `commit()` on confirmed end and on pauses ≥ 0.8 s in unaddressed speech, forced every 25 s of continuous speech. The connection stays open while humans are present, with a WS ping every 15 s. `stt.jsonl` recording. VAD commit remains a config fallback. | Fake server: commit sent at the right audio time; finals mapped to session time; ping sent; no audio sent during silence (credit test). | ~200 | Sonnet (Opus review) |
| VA-13 | **Session integration behind a flag.** `--voice-engine v1\|v2`, default v1. v2 wires AudioIn, Scribe, Chat and captions into the Orchestrator. Analysis pauses while a turn is active. The old path stays untouched for v1. | `run-mock --voice-engine v2` end to end with fakes gives ≥ 3 answered turns and a report. All existing tests pass. | ~300 | **Opus** |

**Live acceptance gate** (you plus at least one other person, 3 test meetings): 20 or more addressed questions (5 typed),
5 barge-ins, 5 unaddressed questions. Pass means: model-path first sample p50 ≤ 1.3 s and p90 ≤ 2.0 s; instant p50 ≤
0.8 s; zero spoken answers to unaddressed questions; barge-in stop ≤ 0.3 s in at least 90% of cases; no addressed
question left unanswered and silent. Then make v2 the default.

### Phase 3: hardening and clean-up

| Id | Ticket | Acceptance tests (offline) | Size | Model |
|---|---|---|---|---|
| VA-14 | **Barge-in guards:** echo similarity, captions "You" rule, backchannel lexicon, crosstalk from `CaptionActivity`. | Scripted scenarios: an echoed partial does not stop playback; two caption speakers → floor busy; "yeah" → duck only. | ~200 | Sonnet |
| VA-15 | **Health and degradation ladder** (table 3.10). WS heartbeats and jittered reconnects. Meet receive resolution set to "audio only" to save CPU (if the setting exists for this account). CPU samples every 5 s into the trace. | Each fake failure → the expected mode switch, logged once. Recovery switches back. | ~300 | Sonnet |
| VA-17 | **Delete v1** after the acceptance gate (list in section 6). | Test suite green; no references left to the removed modules. | ~-600 | Sonnet |
| VA-16 | *Gated by X4; if it passes, built right after VA-11 (design in 3.12):* **Gemini Live responder.** An `AudioResponder` with a persistent session, manual activity detection, early `activityEnd` with audio held until `Confirm`, and per-turn fallback to the cascade. The turn audio comes from the ring buffer (from turn start), the meeting card is injected as client content, `activityEnd` is sent on `Confirm`, output transcription goes to the chat mirror, session resumption on GoAway (connections last ~10 min), and context-window compression, which is mandatory: sessions otherwise stop at 15 min, and the whole context is billed every turn. The model id comes from config. Choose with `--responder cascade\|live`. | Fake Live WS server: audio is only ever sent between `activityStart` and `activityEnd`; card injected; resumption works; the same trace marks are written. | ~400 | **Opus** |

Order if X4 passes (Live is the voice): X4, X1, X5 → VA-01..04 (in parallel) → VA-05, 06, 07, 12 (in parallel) →
VA-09 → VA-11 → **VA-16** → VA-13 → acceptance gate → VA-08 + VA-10 (the cascade, now the fallback), VA-14, VA-15 →
VA-17.

Order if X4 fails (the cascade is the voice): X1-X3, X5 → VA-01..04 → VA-05, 06, 07, 08, 12 → VA-09, VA-10 → VA-11 →
VA-13 → acceptance gate → VA-14, VA-15 → VA-17. Re-run `live-probe` whenever a new Live model ships.

---

## 6. Keep, replace, delete, and the migration path (E)

**Keep as is:** Docker image and PulseAudio layout, `browser.py`, `selectors.py`, `captions.py` (speaker names and
timing), `people.py` gate and auto-admit, `chatread.py`, `knowledge.py`, `instant.py`, `brain.py` analysis and
`ChatPolicy` nudges, `events.py`, `retranscribe.py`, `playback.py`, `probe.py`, `main.py` CLI, `audio_out.setup_virtual_mic`,
`hybrid.AudioBuffer`, `assign_speaker` and `LiveRecorder` (becomes the AudioIn thread), `stt_stream.py` (extended with
manual commit), the `tts.py` providers and `FallbackTTS` (extended).

**Replace (v2 path):** `speaker.VoiceSpeaker` → FloorController + Orchestrator + Player. `audio_out.Player` (a new paplay
per reply) → `voice_out.Player`. The session fast path (`pending_question`, `partial_idle_s`, `_timed_quick`,
`_finish_quick`, `_keep_warm`) → Orchestrator. `Brain.quick_reply` JSON → `GeminiResponder` streaming text
(`instant_answer` kept). Energy `VoiceActivity` and `SpeechSegmenter` → Silero AudioIn (energy kept as fallback). Sync
`GeminiLLM` in `to_thread` for replies → `FastLLM` (the analysis loop can move to it later).

**Delete (VA-17, after the gate):** the `--stt gemini` batch path in the live session (2-4 s per clip, 13-16 s when
limited; Scribe replaces it; `retranscribe` stays for offline use). `ANSWER_MODE=questions` (answering unaddressed
questions). Keep-warm pings. The v1 fast path and `VoiceSpeaker`. Tests for deleted code go with it.

**Migration:**
1. Phase 1 fixes land **in v1**. You feel them at once, and v1 stays the safe default.
2. v2 is built beside v1 behind `--voice-engine v2`. Both share the browser, captions, chat, Scribe and brain.
3. After the acceptance gate, v2 becomes the default and v1 stays one more week as a fallback flag.
4. VA-17 then deletes v1.

The 121 existing tests stay green at every step. The `run-mock` path keeps working in both engines.

---

## 7. Riskiest assumptions and the cheapest experiment for each (F)

| # | Assumption | Cheapest experiment | Decision it drives |
|---|---|---|---|
| X1 | The 12 s calls are connection or quota behaviour (H1/H2/H3), not model speed, and a warm streaming Flash-Lite call has TTFT ≤ 0.5 s from this laptop. | `net-probe` (to add to `probe.py`, ~80 lines): inside the container, curl timing (DNS, connect, TLS, first byte) to the Gemini and ElevenLabs hosts on unauthenticated requests (no quota) after idle gaps of 5, 10, 20, 30 and 60 s. Then 20 streaming calls each for Flash and Flash-Lite with a real 3k-token answer prompt, spaced 15-40 s apart, logging every exception. Also grep the 29 Sep console log for `retrying in`. 10 min, free. | The `keepalive_expiry` value, whether a DNS fix (`options single-request-reopen` or a static resolver) is needed, and the fast model choice. |
| X2 | Scribe manual commit returns the final ≤ 300 ms after `commit`, and partials trail the audio by ≤ 300 ms. | Stream 3 minutes of a recorded `audio.wav` through Scribe with manual commits at the VAD ends; log commit → final and audio time → partial time. About 2 cents. | Whether `confirm_end` can rely on the final or must use partials alone. |
| X3 | ElevenLabs Flash first PCM ≤ 350 ms on an open WS from India, with a voice your plan allows. | 20 short sentences over stream-input WS and over HTTP stream, with a voice from `GET /v1/voices` (category premade, or one you own). Time the local Piper/espeak voice on the container while Meet runs. About 1k characters. If a GCP billing project exists, also stream Chirp 3 HD from asia-southeast1. | The voice provider; whether the $6 Starter plan is needed. |
| X4 | Gemini Live, with manual activity detection, answers fast enough for "instant": our `activityEnd` → first audio at p50 ≤ ~0.95 s and p90 ≤ ~1.4 s (which gives heard p50 ≤ 1.5 s and p90 ≤ 2.0 s with the early activityEnd of section 0). It accepts text context mid-session and rarely stays silent on a real question. | **Built:** add `GEMINI_LIVE_API_KEY` (AI Studio) to `.env`, start Docker, run `python -m bot.main live-probe`. For each model in `LIVE_MODELS` (default: 3.1 flash live, 3.8 live, 2.5 native audio, which may be refused for new users), it opens one session with manual turns, injects `agenda.md` + `context/` as the card, and asks the phrases ending in "?" from your latest recorded run (else 5 espeak questions) at real-time speed. It prints per-question timings, what the model heard and said, and a PASS/FAIL summary per model, and saves every answer as WAV in `out/live-probe-*/` so you can judge the voice. Add `--burst` to test sending buffered audio at once. 15 min, free tier. | VA-16 yes or no, and which Live model. |
| X5 | Meet transport ≈ 0.25 s; `parec` capture delay is small; the bot's voice is not in `tilo_out`; Chromium does not garble TTS; Ctrl+D toggles the mic in ≤ 150 ms even with chat focused. | One test meeting with a phone as the second participant: record the phone's speaker while the bot plays a click (transport). `paplay` a click into `tilo_out` and time it in `parec` (capture). Record `tilo_out` while only the bot talks (should be silence). Time Ctrl+D against the aria state. 15 min, free. | The `parec` flags, the echo guard, the mic policy. |
| X6 | Addressing and barge-in hold up with 3 real people: addressed recall ≥ 90% with keyterms, false barge-ins < 1 per 10 min with a speakerphone user, and caption-vote speaker names right on ≥ 90% of segments (Scribe has no realtime diarization). | A 10-minute scripted 3-person meeting recorded with `--record-audio`, then `replay` through VA-09 and VA-05 offline with the recorded `stt.jsonl`. You can tune thresholds offline without paying again. | Timer defaults, alias list, whether to rely on caption names only. |

---

## 8. Questions and answers

**Q1. Will this bot be part of the Builder Cup submission (Tilo)?**
**Answer (30 Sep):** yes, and a Gemini-native voice is wanted if it can be instant. As a result, section 0 was revised,
X4 moved to the front, 3.12 and 3.13 were added, and VA-16 moves up if X4 passes. Tilo's PRD still needs a
requirement for the bot (3.13).

**Q2. May test-meeting audio go to the Gemini Developer API free tier, where Google may use it to improve its
products?**
**Answer (30 Sep):** yes. X4 runs on a free AI Studio key; no billing project is needed. The intro chat line must still
disclose that audio goes to Google's AI services.

Decisions that do not change the architecture (defaults in brackets):
- A natural voice: ElevenLabs Starter at $6/month, or GCP billing for Chirp 3 HD [local voice until you choose;
  recommended: Starter, after X3 confirms the first byte].
- Chat-only answers to unaddressed questions [off].
- Mic policy [open].
