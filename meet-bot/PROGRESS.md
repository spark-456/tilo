# Progress

## Status: M1, M2, M3 code and tests done. Waiting on a live Meet test (Handoff below).

| Milestone | State |
|---|---|
| M1 Join and stay (Dockerfile, compose, noVNC, CLI: doctor/login/start/join/run-mock, waiting-room timeout, clean leave) | Code written. Image built and container stack smoke-tested. Not run against real Meet. |
| M2 Live transcript (captions on, MutationObserver, parser, merger, transcript.jsonl, rolling window) | Parser and merger unit-tested on synthetic fixtures. Live path written, not run. |
| M3 Brain and chat (agenda, JSON schema + retry, chat policy in code, summary.md/state.json) | Done and tested with fake clock and stub model. No live model smoke test: live calls need the user's `LIVE=1`. |
| Stretch `--api-create` | Not implemented, on purpose (needs Google Cloud OAuth). Flag exists and says so. |

## Verified

- `just meet-bot-test`: the offline suite (no network, fakes only).
- `python -m bot.main run-mock`: 30-minute replay gives 3 chat messages (missing owner, 10-minute warning, untouched "Hiring plan"), all at least 5 minutes apart.
- `python -m bot.main doctor` runs on the host without dependencies.
- Docker image builds. In the container: Xvfb, openbox, PulseAudio (null sink `tilo_out`), x11vnc and noVNC (HTTP 200 on 127.0.0.1:6080) all start; Playwright launches headed Chromium and reaches Google's sign-in page; `start` without a login stops cleanly with "profile is not signed in".
- `doctor` detects the missing login through the container.

## Not verified (needs a live Meet or a key)

See Handoff item 4 in the final message. Short version: every Meet selector, the caption DOM shape, the pre-join dialogs, Google sign-in inside Chromium, and real Gemini behaviour.

## Session end, 2026-09-30 (stopped by the user; nothing is running)

State: 121 tests pass. Live pieces working: auto-admit (prototype only; never used for bot-hosted meetings, ADR-0024), "start only when required people are in", hybrid/streaming transcript,
knowledge base, chat reading, voice replies (local espeak fallback), audio recording, latency log.
The third-party streaming speech and voice clients were removed by FR-MTG-11 (Google only). Google streaming ears and the
native-audio voice are FR-MTG-16.

Open problems seen in the last live run (fix first next time):
1. **Model calls still 12 s in the meeting despite the keep-warm task** (in isolation, pings every 5 s gave 0.4-0.8 s). Log ping
   durations in `_keep_warm`; suspect overlapping pings or a cold connection per worker thread. Consider one dedicated long-lived
   client/thread for replies, or streaming responses.
2. **Typed chat questions without a "?" are ignored** ("When does the beta ship"). Treat every typed chat message as addressed to
   the assistant.
3. **"Can't take more than one question"**: later questions returned "no reply" (model said not answerable, 12 s) and the recogniser misheard
   ("beta ship" -> "leadership meet"). Check `direct_reply` gap/attempt bookkeeping and add a short "I didn't catch that" spoken reply
   instead of silence for unanswerable-but-addressed questions.
4. Instant local answers work (source: local, model 0.0 s) but first sound was still ~3.9 s after speech end: ~1.6 s detection,
   ~1.8 s to first sound (mic unmute + espeak). Measure unmute time; consider keeping the mic unmuted while speaking soon.
5. Speaker names come from caption-name voting; multi-speaker is not yet tested.
6. `account_button` selector still misses (harmless).

## Voice plan v2 tickets (docs/VOICE_ARCHITECTURE.md section 5)

Branches `feat/VA-<nn>-<slug>` are cut from `chore/meet-bot-baseline` and merged back into it by PR. Nothing goes to `phase0-stack` or `main` until the VA-INT ticket.

| Ticket | State |
|---|---|
| VA-01 fast-path model client | Merged (PR 75). Not yet measured live: the 12 s cold-call fix is unproven until a live run shows `model_attempt` rows and `model_s` in `latency.jsonl`. |
| VA-02 question bookkeeping and chat | Merged (PR 76). Two older assertions were updated because the ticket changes the behaviour they pinned (an addressed question with no answer now gets a fallback line instead of silence). Live check pending. |
| VA-03 voice never waits for the UI | Code and 16 offline tests done (176 pass overall). Fake-page mic wait 0 to 30 ms behind a slow chat post. Not yet measured live: needs a live run for unmute and first-sound numbers. |
| VA-04 turn trace, report, two-channel audio | Code and 16 offline tests done (192 pass overall). `report` and `audit` commands, `turns.jsonl`, `connections.jsonl`, `bot.wav`. Not yet run on a live meeting: the marks the v1 pipeline cannot produce (`probable_end`, `stt_final`, `first_sentence`, `barge_duck`) stay empty until Phase 2. |

## Session end, 2026-10-01: Phase 1 (VA-01 to VA-04) merged into chore/meet-bot-baseline

All four Phase 1 tickets are merged (PRs 75 to 78) and green offline (192 pass, 1 skipped). **None of it has been run in a live meeting yet**, so the 12 s cold-call fix, the unmute wait and the first-sound numbers are unproven until the live test below.

### Next (in order)
1. **Live test with the user (blocks everything else).** Needs Docker running, the user's `LIVE=1` and Google project settings (README, Providers), and the user in the meeting. Suggested command: `python -m bot.main join <link the user created> --agenda agenda.md --stt gemini --record-audio --reply both`. The bot never clicks Admit and `start` (meet.google.com/new) is disabled for the persistent profile (ADR-0024 decision 7, amendment 3(c) and 3(d)); the hosted-meeting live test waits for MTG09-c's preconditions.
   Ask 5 spoken questions (2 with the name, 1 repeated twice), type 3 chat questions (one without "?", one gibberish), then end the meeting. Then run `python -m bot.main report` and `python -m bot.main audit` and compare with the budget in VOICE_ARCHITECTURE section 4 (model path p50 1.3 s / p90 2.0 s, instant p50 0.8 s). Look in `connections.jsonl` for `timeout` or `busy` attempts and in `latency.jsonl` for `model_s`.
   Voice: the cloud voice is `config/voice.yaml`; if it cannot speak, the local espeak voice does.
2. **Choose the voice order** (FR-MTG-16, a later ticket): the Live probe was removed with FR-MTG-11 (it spoke a vendor protocol directly); a probe through the provider layer replaces it. Until then the cascade order applies (VA-05 to VA-13).
3. **Meeting features**: the four draft specs are in `docs/specs/` (MF-01 team pinboard, MF-02 personal pinboards, MF-03 responsibilities, MF-04 effort tracker). Nothing is built; each lists open questions. MF-04 needs the user to say which "effort tracker" they mean. Agenda tracking needs no spec (built and tested).
4. **Experiment probes** (X1 net-probe, X2, X3, X5) are not built yet; build them when their decision is due (X1 explains any slow model calls the live test still shows).
5. **VA-INT**: done as FR-MTG-11 (model ids in `config/`, every call through `packages/providers` via `bot/providers.py`).

### Things to know
- Per ticket: branch `feat/VA-<nn>-<slug>` from `chore/meet-bot-baseline`, commit through `uv run --no-project --with pre-commit git commit` (delete the empty `<worktree>/.venv` first, or the ruff hook fails), push, PR, merge with `gh pr merge --merge`.
- Existing assertions changed on purpose: an addressed question with no answer now gets a fallback line (VA-02), so `test_quick_reply_is_one_small_call...` and `test_VA_01_a_busy_or_down_model...` assert the line, not silence.
- `Config.from_env()` reads the developer's `.env`; tests that call it patch `bot.config.load_dotenv` to a no-op.
- Ticket sizes ran over the ~400-line guide for VA-03 and VA-04 (about 800 lines each with tests); the session.py loop refactor is most of it.

### CV-01 conversation mode (2026-10-02, user request)
Tilo answers ordinary questions and small talk when spoken to (by name, in typed chat, or as a follow-up within 15 s), with no keywords or question mark needed. 209 tests pass. The live quality of the answers, and the 0.8 s extra wait for statements, are unmeasured: check in the next live meeting.

- The 2026-10-02 handoff and the architect brief named removed third-party providers; they are replaced by short notes (`docs/HANDOFF-2026-10-02.md`, `docs/ARCHITECT_BRIEF.md`). The originals are on `chore/meet-bot-baseline` (c2991182).
