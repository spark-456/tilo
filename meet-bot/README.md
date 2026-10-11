# Tilo Meet bot (prototype)

A bot that joins a Google Meet like a person, reads the live captions, tracks your agenda with a model (through Tilo's provider layer), and occasionally asks a short question in the Meet chat.

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
- **The bot's Google account** (`tiloagent@gmail.com`) is signed in once, by you, by hand. The browser remembers it in a Docker volume. The code never sees or stores a password.
- **The script does what a person would**: opens Meet, joins with camera and mic off, turns on captions, reads them, and every 45 seconds sends the last few minutes to the model. The model fills in a small JSON form (agenda status, decisions, action items, open questions). The code, not the model, decides whether the bot may speak.
- **noVNC** lets you watch and click inside that browser from a normal tab at http://localhost:6080. Used for the one-time login and for debugging.

The bot speaks in chat only: at most 4 messages per meeting, at least 5 minutes apart, and only when (a) an agenda item is untouched after its fair share of time, (b) an action item lacks an owner or due date, or (c) once, with about 10 minutes left. Default is silence. Right after joining it posts one intro line ("Hi, I'm an AI assistant taking notes for this meeting.").

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

Outputs per meeting, in `out/<timestamp>/`: `transcript.jsonl`, `events.jsonl`, `state.json`, `summary.md`. Screenshots go to `debug/`.

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

Talking to Tilo: say its name at the start or end of what you say ("Tilo, tell me a joke", "what do you think, Tilo"), or type in the chat; no question mark and no special words are needed, and it answers any topic in a sentence or two. For about 15 s after it answers you can follow up without the name. People talking among themselves are never answered, except a question the meeting notes or project files can answer.

Tuning: `DIRECT_REPLY_GAP_SECONDS` (default 6), `MAX_DIRECT_REPLIES` (40), `BRAIN_INTERVAL_SECONDS` (20), `ANSWER_MODE` (`questions` or `addressed`). A throttled project hits quota errors if these are pushed too hard.

## Transcript sources and project knowledge

`--stt captions` (default) uses Meet's captions. `--stt gemini` (or `--hybrid`) sends each detected speech segment to the speech provider as batch audio; captions only supply speaker names. Streaming speech-to-text is a later ticket (FR-MTG-16). Audio modes are announced in the intro chat line.

Google's native-audio voice (Gemini Live) is not wired into meetings yet: it is FR-MTG-16, see `docs/VOICE_ARCHITECTURE.md`.

The bot answers project questions from `context/` (.md/.txt/.csv/.json), any `--context FILE|FOLDER|https://URL` (repeatable, or `CONTEXT_URLS`), and text people paste into the Meet chat. Typed chat questions work without any speech recognition.

## Providers (FR-MTG-11): models, speech and voice are Tilo's config

The bot names no model, vendor or key. `bot/providers.py` is the one module that talks to Tilo's provider layer
(`packages/providers`); everything else asks it for a role:

| What | Role or config | Used by |
|---|---|---|
| Agenda analysis (JSON in, JSON out) | role `meeting` in `config/models.yaml` | `Brain` through `ProviderLLM` |
| Direct answers, streamed with a first-token deadline | role `meeting_fast` | `FastLLM` through `ProviderFastClient` |
| Audio to text (`--stt gemini`, `retranscribe`) | `config/speech.yaml` (`SpeechProvider.transcribe`) | `ProviderSpeech` |
| The bot's voice | `config/voice.yaml` (`SpeechProvider.synthesize`, PCM) with the local espeak voice as backup | `ProviderTTS` / `make_tts` |

- **Vendor, model, voice and caps are config.** Speech and voice accept the vendor `google` (or the dev vendor `fake`);
  anything else, or a denylisted model id, fails start-up. The voice name and sample rate are in `config/voice.yaml`.
- **Offline by default.** Without the live switch the bot reads `config/models.dev.yaml`, `config/speech.dev.yaml` and
  `config/voice.dev.yaml`, whose providers are deterministic fakes: canned answers, a tone for a voice, no network, no paid
  call. Only the user sets `LIVE` to `1` (then the real files are read and the Google adapters are built; they need
  `GOOGLE_CLOUD_PROJECT` and Google application default credentials). There is no API key in `.env`.
- **If your `meet-bot/.env` is older, delete these lines and revoke the keys.** The prototype's `.env` may still hold
  the prototype's model key (Gemini or AI Studio) and its third-party voice key. Nothing reads them now, but
  `env_file: .env` in `docker-compose.yml` loads the whole file into the container. Remove every `*_API_KEY` line from
  `.env`, then revoke each key in the console of the service that issued it.
- **Credentials for a live meeting (BQ-MTG11-4).** The only default is a dedicated identity that has no project role
  (ADR-0024 amendment 3(a)); until you create one, make no live run. Running on the host is not an alternative: the bot starts
  Chromium with `--no-sandbox` everywhere (`bot/browser.py`), so a host run would put an unsandboxed browser on pages other
  people control next to your own gcloud credentials, until MTG09-c drops that flag outside the container. Never put your own gcloud credentials in the container: they are
  the project Owner's, and the container runs Chromium with `--no-sandbox` behind a VNC session with no password.
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

Start any command, then open http://localhost:6080/vnc.html?autoconnect=true&resize=scale. You see the bot's browser and can click in it (for example to dismiss a surprise dialog). When a Meet control cannot be found, the log names the selector (from `bot/selectors.py`) and a screenshot is saved to `debug/`. Fix the selector there; it is the only file that knows Meet's UI.

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
