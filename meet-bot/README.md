# Tilo Meet bot (prototype)

For the Cloud Run guest path, use [the operator rehearsal](docs/CLOUD_RUN.md) and
`agy-bridge/tasks/MEETING-GO-LIVE-13OCT.md` in the coordination checkout. They track
current image certification, deployment and human acceptance prerequisites. The
local prototype commands below do not establish cloud readiness.

A bot that joins a Google Meet like a person, reads the live captions, tracks your agenda with a model (through Tilo's provider layer), and occasionally asks a short question in the Meet chat.

Cloud transcript ingestion assigns utterance ids in speech-start timestamp order,
keeping capture order for ties and preserving repeated speech. Overlapping captions
may finalize out of order; this keeps stored notes chronological without changing
their text or speaker labels.

The signed-in path requires `BOT_GOOGLE_EMAIL` to match the dedicated bot account exactly. Set it yourself in the
environment; replace the old account example when preparing your configuration. An unreadable or different account
refuses to join. Sign in manually; the bot never types credentials. Signed-in Chromium runs with its sandbox enabled.

`BOT_JOIN_MODE=guest` uses a fresh ephemeral browser context with no stored profile or account. Set
`BOT_DISPLAY_NAME` for the name shown when requesting admission; a human host admits it. Cloud Run refuses
signed-in mode before launching Chromium. Guest mode disables the Chromium sandbox for the Cloud Run runtime;
it never holds a signed-in browser session. The dedicated signed-in profile remains the local fallback.

The bot joins an existing approved meeting and never creates a call or admits participants. It posts its disclosure
before starting audio or captions; a failed disclosure leaves without capture. Any participant can say or type
`Tilo leave` to stop it. Browser screenshots and DOM dumps are disabled because they can contain account information
or the Meet capability. Meet links are removed from local transcript text, events and formatted logs.

> **Test meetings only.** Meeting content goes nowhere except local files (`out/`) and the Google models the provider layer calls. Until Google's data terms for that use have been reviewed, do not use real or sensitive meetings.
>
> **Terms note.** Automated browser clients for Google Meet may have terms-of-service implications. Review them before any commercial use.

## How it works, in plain language

Think of a spare laptop in a cupboard that only this bot uses:

- **Docker container = the laptop.** Inside it: a virtual screen (Xvfb), virtual sound (PulseAudio) and a real, visible Chromium browser driven by Playwright.
- **The dedicated bot Google account** (currently `tilotesting@gmail.com`; confirm before login) is signed in once, by you, by hand for the local fallback. Never reuse the owner's profile. The browser remembers it in a Docker volume. Cloud guest mode has no signed-in profile. The code never sees or stores a password.
- **The script does what a person would**: opens Meet, joins with camera and mic off, turns on captions, reads them, and every 45 seconds sends the last few minutes to the model. The model fills in a small JSON form (agenda status, decisions, action items, open questions). The code, not the model, decides whether the bot may speak.
- **noVNC** lets you watch and click inside that browser from a normal tab at http://localhost:6080. Used for the one-time login and for debugging.

Proactive chat nudges are limited to at most 4 messages per meeting, at least 5 minutes apart. Direct replies can also use configured voice with a chat mirror. Disclosure must succeed before capture starts.

## Setup

1. Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) (on Windows: WSL2 backend). Install Python 3.12 on the host (the CLI uses only the standard library).
2. Copy `.env.example` to `.env`. Copy `agenda.example.md` to `agenda.md` and edit it.
3. Cap WSL2 memory (Windows, recommended, see below).
4. `python -m bot.main login`, then open http://localhost:6080 and sign in as the bot account.
5. Models and speech: see Providers below. Without them the bot still joins and transcribes with fake providers (`bot/providers.py`); only the answers are canned.

## Commands

Run from the `meet-bot/` folder. On Windows use `python`, on Mac/Linux `python3`.

| Command | What it does |
|---|---|
| `python -m bot.main doctor [--watch]` | Checks Docker, `.env`, login state; prints container CPU/RAM while a meeting runs |
| `python -m bot.main login` | Starts the container with a plain browser for the one-time manual sign-in |
| `python -m bot.main start [--agenda FILE] [--duration MIN]` | Not used with the bot account until MTG09-c (ADR-0024 decision 7 and amendment 3(c)/(d): the bot never hosts or admits, and `start` is disabled for the persistent profile) |
| `python -m bot.main join URL` | Joins an existing meeting |
| `python -m bot.main run-mock` | Replays a recorded 30-minute transcript through the brain, offline, no key needed |

Local outputs per meeting, in `out/<timestamp>/`: `transcript.jsonl`, `events.jsonl`, `state.json`, `summary.md`. Browser screenshots and DOM dumps are disabled.

`start` and `join` need `LIVE=1` (set by you only): without it the providers are dev fakes, and a fake transcript never
reaches a real meeting, so both commands refuse and tell you so. `run-mock` works offline without it. The bot never
clicks Admit (ADR-0024 decision 7): `--auto-admit` and `start` are not used with the bot account until MTG09-c's preconditions are met, with no prototype exception.

Press Ctrl+C in the terminal to make the bot leave cleanly and write the summary.

## Checking what the bot heard (audio, playback, timing)

Start with `--record-audio` (or `RECORD_AUDIO=1`). The bot then says in chat that audio is recorded locally. Per run, in `out/<time>/`:

- `audio.wav`: exactly what the bot receives from Meet. Play it in any media player.
- `playback.html`: open in a browser; click a transcript line to hear that moment. Rebuild with `python -m bot.main playback`.
- `transcript_audio.md`: a second transcript made by the speech provider from the audio (`python -m bot.main retranscribe`), to compare with Meet's captions in `transcript.jsonl`.
- `latency.jsonl`: per question, time from caption visible to detected, model call, chat typing, total.
- `turns.jsonl`: one row per question with every stage (heard, model first token, first sound, chat posted) timed from the end of the human turn. Read it with `python -m bot.main report [out/<time>]`: a per-turn waterfall and p50/p90 per stage.
- `connections.jsonl`: model attempts (outcome, code, first-token time), and prewarms, so a slow answer can be explained.
- `bot.wav` (voice replies on): what the bot actually sent into the meeting, recorded next to `audio.wav` (`audio_clock.json` holds both start times). `python -m bot.main audit [out/<time>]` measures end of question to first bot sound from the recordings, to about 10 ms, and compares it with the log.

Talking to Tilo: address it by name or type in the chat. Replies are limited to the recorded meeting agenda, minutes so far and your own recorded meeting items; unrelated requests receive a scope refusal. For example, ask "Tilo, meeting agenda" or "Tilo, minutes so far". Wake/follow-up behavior is controlled by meeting configuration.

Tuning: `DIRECT_REPLY_GAP_SECONDS` (default 6), `MAX_DIRECT_REPLIES` (40), `BRAIN_INTERVAL_SECONDS` (20), `ANSWER_MODE` (`questions` or `addressed`). A throttled project hits quota errors if these are pushed too hard.

## Transcript sources and project knowledge

`--stt captions` (default) uses Meet's captions. `--stt gemini` (or `--hybrid`) sends each detected speech segment to the speech provider as batch audio; captions only supply speaker names. Streaming speech-to-text is a later ticket (FR-MTG-16). Audio modes are announced in the intro chat line.

The optional Gemini Live voice adapter is wired through `packages/providers` behind
`voice.live.enabled: false`; Chirp remains the default. Fake and recorded Live
responses pass the offline meeting lifecycle. Real Live additionally requires
price approval and the SEC-16 meter; without that meter the bot retains Chirp.
This is not human-heard Live acceptance. The standalone probe in
[LIVE_TRIAL.md](docs/LIVE_TRIAL.md) is separate from meeting capture.

The local prototype can load `context/` and explicit `--context` inputs, but these do not widen the meeting reply scope. Cloud guest capture disables context URLs. Typed chat requests still obey the same recorded-meeting scope.

## Providers (FR-MTG-11): models, speech and voice are Tilo's config

The bot names no model, vendor or key. `bot/providers.py` is the one module that talks to Tilo's provider layer
(`packages/providers`); everything else asks it for a role:

| What | Role or config | Used by |
|---|---|---|
| Agenda analysis (JSON in, JSON out) | role `meeting` in `config/models.yaml` | `Brain` through `ProviderLLM` |
| Direct answers, streamed with a first-token deadline | role `meeting_fast` | `FastLLM` through `ProviderFastClient` |
| Audio to text (`--stt gemini`, `retranscribe`) | `config/speech.yaml` (`SpeechProvider.transcribe`) | `ProviderSpeech` |
| The bot's voice | `config/voice.yaml` (`SpeechProvider.synthesize`, PCM) with the local espeak voice as backup | `ProviderTTS` / `make_tts` |

- **Vendor, model, voice and caps are config.** Speech accepts `google` or `fake`; voice also accepts `google-cloud-tts` (the Chirp default);
  anything else, or a denylisted model id, fails start-up. The voice name and sample rate are in `config/voice.yaml`.
- **Offline by default.** Without the live switch the bot reads `config/models.dev.yaml`, `config/speech.dev.yaml` and
  `config/voice.dev.yaml`, whose providers are deterministic fakes: canned answers, a tone for a voice, no network, no paid
  call. Only the user sets `LIVE` to `1` (then the real files are read and the Google adapters are built; they need
  `GOOGLE_CLOUD_PROJECT` and Google application default credentials). There is no API key in `.env`.
- **If your `meet-bot/.env` is older, delete these lines and revoke the keys.** The prototype's `.env` may still hold
  the prototype's model key (Gemini or AI Studio) and its third-party voice key. Nothing reads them now, but
  `env_file: .env` in `docker-compose.yml` loads the whole file into the container. Remove every `*_API_KEY` line from
  `.env`, then revoke each key in the console of the service that issued it.
- **Credentials for a live meeting (BQ-MTG11-4).** The local signed-in fallback uses a dedicated bot identity and sandboxed Chromium. Guest mode disables Chromium's sandbox and uses an ephemeral context; Cloud Run refuses signed-in mode. Never mount the owner's profile or gcloud credentials into either image. The cloud service uses its reviewed service identity; local noVNC/profile use still needs separate hardening review.
- **A cap per meeting.** `config/meeting.yaml` bounds the provider calls of one meeting (200 model calls, 400 speech
  calls; one model call is one router call, so a call that tries the primary and then the fallback counts once). At the
  cap the bot logs one warning and carries on without them: no more answers, the local voice (for the rest of that
  meeting only, nothing is remembered for the next), the transcript still written. Captions stay the transcript only
  outside hybrid mode: in hybrid mode (`--stt gemini`) the audio transcript is the transcript, so once the speech cap is
  reached no further speech is transcribed (`captions.jsonl` keeps the caption text, but the audio transcript no longer uses it for words). The
  config is checked when the session starts, before the bot joins: a bad `config/meeting.yaml`, or a role, speech or voice
  config that resolves to the dev fake provider, stops the start with a clear error. SEC-16 spend caps are not wired for
  the bot (BQ-MTG11-9).
- **No recording.** The bot refuses to start with `TILO_RECORD` set: it would write what people said into `fixtures/`.
- **Tests** run offline with the repo's venv: `just meet-bot-test` (also part of `just test`).
- **Docker.** The image carries the provider layer, so the build context is the repository root: `docker compose build`
  from `meet-bot/` uses `context: ..` and `docker/Dockerfile`; `docker/Dockerfile.dockerignore` whitelists what is copied
  (`meet-bot/bot`, `packages/providers/src`, `packages/contracts-py/src`, and only the config and prompts the provider layer
  reads: `config/models*`, `prices*`, `speech*`, `voice*`, `meeting*` and `prompts/router`, `prompts/speech`; key files at any
  depth are excluded). The layout is kept under `/opt/tilo` (`TILO_REPO_ROOT`). `docker/requirements.txt` pins the provider
  layer's dependencies to the versions in `uv.lock` (a test compares them). How credentials reach the container is not wired
  (open question BQ-MTG11-4).

## Meeting events (for later use inside a bigger system)

`events.jsonl` holds one JSON object per line: `{"v":1,"type":...,"ts":...,"meeting_id":...}` with types `meeting.joined`, `transcript.utterance`, `agenda.update`, `chat.posted`, `summary.ready`, `meeting.ended`. Input is a meeting URL plus an agenda file. Voice (`speaker.py`) and co-host control (`cohost.py`) are interfaces only.

## Debugging with noVNC

For the local fallback, open http://localhost:6080/vnc.html?autoconnect=true&resize=scale. You can inspect the browser manually. Selector definitions live in `bot/selectors.py`; browser screenshots and DOM dumps are disabled even if an inherited log mentions `debug/`. Cloud Run has no noVNC endpoint.

To capture real caption HTML for parser tests, set `SAVE_CAPTION_SNAPSHOTS=1` in `.env`; snapshots land in `debug/caption_snapshots/`.

## Laptop friendliness

- Container limits: 2 CPUs, 3 GB RAM (`BOT_CPUS`, `BOT_MEM_LIMIT` in `.env`).
- 1280x720 virtual screen, VNC refresh throttled, GPU/extensions/background networking disabled in Chromium, no camera stream.
- Run **short 10-15 minute test meetings first** and watch `doctor --watch`.

### Capping WSL2 memory (Windows)

Create `C:\Users\<you>\.wslconfig`:

```ini
[wsl2]
memory=5GB
processors=4
swap=2GB
```

Then run `wsl --shutdown` and restart Docker Desktop.

## Tests

```
just meet-bot-test            # from the repository root
uv run pytest meet-bot/tests   # the same
```

No live meeting, browser, network or key is needed. Caption fixtures in `tests/fixtures/` are synthetic (see the README there).

## Least certain parts

See `PROGRESS.md` (handoff section) for what could not be verified without a live Meet.
