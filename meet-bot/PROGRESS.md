# Progress

## Status: M1, M2, M3 code and tests done. Waiting on a live Meet test (Handoff below).

| Milestone | State |
|---|---|
| M1 Join and stay (Dockerfile, compose, noVNC, CLI: doctor/login/start/join/run-mock, waiting-room timeout, clean leave) | Code written. Image built and container stack smoke-tested. Not run against real Meet. |
| M2 Live transcript (captions on, MutationObserver, parser, merger, transcript.jsonl, rolling window) | Parser and merger unit-tested on synthetic fixtures. Live path written, not run. |
| M3 Brain and chat (agenda, JSON schema + retry, chat policy in code, summary.md/state.json) | Done and tested with fake clock and stub model. Real Gemini smoke test skipped (no key). |
| Stretch `--api-create` | Not implemented, on purpose (needs Google Cloud OAuth). Flag exists and says so. |

## Verified

- `python -m pytest`: 43 passed, 1 skipped (Gemini smoke test, no key).
- `python -m bot.main run-mock`: 30-minute replay gives 3 chat messages (missing owner, 10-minute warning, untouched "Hiring plan"), all at least 5 minutes apart.
- `python -m bot.main doctor` runs on the host without dependencies.
- Docker image builds. In the container: Xvfb, openbox, PulseAudio (null sink `tilo_out`), x11vnc and noVNC (HTTP 200 on 127.0.0.1:6080) all start; Playwright launches headed Chromium and reaches Google's sign-in page; `start` without a login stops cleanly with "profile is not signed in".
- `doctor` detects the missing login through the container.

## Not verified (needs a live Meet or a key)

See Handoff item 4 in the final message. Short version: every Meet selector, the caption DOM shape, the pre-join dialogs, Google sign-in inside Chromium, and real Gemini behaviour.

## Session end, 2026-09-30 (stopped by the user; nothing is running)

State: 121 tests pass. Live pieces working: auto-admit, "start only when required people are in", hybrid/streaming transcript,
knowledge base, chat reading, voice replies (local espeak fallback), audio recording, latency log.
ElevenLabs: key set in `.env`; Scribe STT works (gated, ~5-15% of audio sent, ~1.7 s lag). TTS blocked on the free plan for
library voices: needs `ELEVENLABS_VOICE_ID` of a voice the user owns, or key permission Voices: Read.
Gemini Live is NOT available on the Express key (every model name -> "1007 Invalid resource"); needs a GCP project with billing.

Open problems seen in the last live run (fix first next time):
1. **Model calls still 12 s in the meeting despite the keep-warm task** (in isolation, pings every 5 s gave 0.4-0.8 s). Log ping
   durations in `_keep_warm`; suspect overlapping pings or a cold connection per worker thread. Consider one dedicated long-lived
   client/thread for replies, or streaming responses.
2. **Typed chat questions without a "?" are ignored** ("When does the beta ship"). Treat every typed chat message as addressed to
   the assistant.
3. **"Can't take more than one question"**: later questions returned "no reply" (model said not answerable, 12 s) and Scribe misheard
   ("beta ship" -> "leadership meet"). Check `direct_reply` gap/attempt bookkeeping and add a short "I didn't catch that" spoken reply
   instead of silence for unanswerable-but-addressed questions.
4. Instant local answers work (source: local, model 0.0 s) but first sound was still ~3.9 s after speech end: ~1.6 s detection,
   ~1.8 s to first sound (mic unmute + espeak). Measure unmute time; consider keeping the mic unmuted while speaking soon.
5. Speaker names: Scribe returned no speaker ids for a single speaker; multi-speaker not yet tested.
6. `account_button` selector still misses (harmless).

## Voice plan v2 tickets (docs/VOICE_ARCHITECTURE.md section 5)

Branches `feat/VA-<nn>-<slug>` are cut from `chore/meet-bot-baseline` and merged back into it by PR. Nothing goes to `phase0-stack` or `main` until the VA-INT ticket.

| Ticket | State |
|---|---|
| VA-01 fast-path model client | Merged (PR 75). Not yet measured live: the 12 s cold-call fix is unproven until a live run shows `model_attempt` rows and `model_s` in `latency.jsonl`. |
| VA-02 question bookkeeping and chat | Merged (PR 76). Two older assertions were updated because the ticket changes the behaviour they pinned (an addressed question with no answer now gets a fallback line instead of silence). Live check pending. |
| VA-03 voice never waits for the UI | Code and 16 offline tests done (176 pass overall). Fake-page mic wait 0 to 30 ms behind a slow chat post. Not yet measured live: needs a live run for unmute and first-sound numbers. |
| VA-04 turn trace, report, two-channel audio | Queued. |
