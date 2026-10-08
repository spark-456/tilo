# Tilo Meet bot (prototype)

A bot that joins a Google Meet like a person, reads the live captions, tracks your agenda with a model (through Tilo's provider layer), and occasionally asks a short question in the Meet chat.

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
| `python -m bot.main start [--agenda FILE] [--duration MIN]` | Opens `meet.google.com/new`, prints `MEETING_URL ...`, joins as host |
| `python -m bot.main join URL` | Joins an existing meeting |
| `python -m bot.main run-mock` | Replays a recorded 30-minute transcript through the brain, offline, no key needed |

Outputs per meeting, in `out/<timestamp>/`: `transcript.jsonl`, `events.jsonl`, `state.json`, `summary.md`. Screenshots go to `debug/`.

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
  `GOOGLE_CLOUD_PROJECT` and the user's Google application default credentials). There is no API key in `.env`.
- **Tests** run offline with the repo's venv: `just meet-bot-test` (also part of `just test`).
- **Docker.** The image carries the provider layer, so the build context is the repository root: `docker compose build`
  from `meet-bot/` uses `context: ..` and `docker/Dockerfile`; `docker/Dockerfile.dockerignore` whitelists what is copied
  (`meet-bot/bot`, `packages/providers/src`, `packages/contracts-py/src`, `config/`, `prompts/`). The layout is kept under
  `/opt/tilo` (`TILO_REPO_ROOT`). How the user's credentials reach the container is not wired (open question BQ-MTG11-4).

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
