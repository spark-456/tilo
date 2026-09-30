# Tilo Meet bot (prototype)

A bot that joins a Google Meet like a person, reads the live captions, tracks your agenda with Gemini, and occasionally asks a short question in the Meet chat.

> **Test meetings only.** Meeting content goes nowhere except local files (`out/`) and Gemini. Until Google's data terms for that use have been reviewed, do not use real or sensitive meetings.
>
> **Terms note.** Automated browser clients for Google Meet may have terms-of-service implications. Review them before any commercial use.

## How it works, in plain language

Think of a spare laptop in a cupboard that only this bot uses:

- **Docker container = the laptop.** Inside it: a virtual screen (Xvfb), virtual sound (PulseAudio) and a real, visible Chromium browser driven by Playwright.
- **The bot's Google account** (`tiloagent@gmail.com`) is signed in once, by you, by hand. The browser remembers it in a Docker volume. The code never sees or stores a password.
- **The script does what a person would**: opens Meet, joins with camera and mic off, turns on captions, reads them, and every 45 seconds sends the last few minutes to Gemini. Gemini fills in a small JSON form (agenda status, decisions, action items, open questions). The code, not Gemini, decides whether the bot may speak.
- **noVNC** lets you watch and click inside that browser from a normal tab at http://localhost:6080. Used for the one-time login and for debugging.

The bot speaks in chat only: at most 4 messages per meeting, at least 5 minutes apart, and only when (a) an agenda item is untouched after its fair share of time, (b) an action item lacks an owner or due date, or (c) once, with about 10 minutes left. Default is silence. Right after joining it posts one intro line ("Hi, I'm an AI assistant taking notes for this meeting.").

## Setup

1. Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) (on Windows: WSL2 backend). Install Python 3.12 on the host (the CLI uses only the standard library).
2. Copy `.env.example` to `.env`. Copy `agenda.example.md` to `agenda.md` and edit it.
3. Cap WSL2 memory (Windows, recommended, see below).
4. `python -m bot.main login`, then open http://localhost:6080 and sign in as the bot account.
5. Later, put `GEMINI_API_KEY` in `.env` (a Vertex AI Express Mode key). Without it the bot still joins and transcribes; only the brain is off.

## Commands

Run from the `meet-bot/` folder. On Windows use `python`, on Mac/Linux `python3`.

| Command | What it does |
|---|---|
| `python -m bot.main doctor [--watch]` | Checks Docker, `.env`, login state; prints container CPU/RAM while a meeting runs |
| `python -m bot.main login` | Starts the container with a plain browser for the one-time manual sign-in |
| `python -m bot.main start [--agenda FILE] [--duration MIN]` | Opens `meet.google.com/new`, prints `MEETING_URL ...`, joins as host |
| `python -m bot.main join URL` | Joins an existing meeting |
| `python -m bot.main run-mock` | Replays a recorded 30-minute transcript through the brain, offline, no key needed |
| `python -m bot.main list-models` | Lists models your Gemini key can use |

Outputs per meeting, in `out/<timestamp>/`: `transcript.jsonl`, `events.jsonl`, `state.json`, `summary.md`. Screenshots go to `debug/`.

Press Ctrl+C in the terminal to make the bot leave cleanly and write the summary.

## Checking what the bot heard (audio, playback, timing)

Start with `--record-audio` (or `RECORD_AUDIO=1`). The bot then says in chat that audio is recorded locally. Per run, in `out/<time>/`:

- `audio.wav`: exactly what the bot receives from Meet. Play it in any media player.
- `playback.html`: open in a browser; click a transcript line to hear that moment. Rebuild with `python -m bot.main playback`.
- `transcript_audio.md`: a second transcript made by Gemini from the audio (`python -m bot.main retranscribe`), to compare with Meet's captions in `transcript.jsonl`.
- `latency.jsonl`: per question, time from caption visible to detected, model call, chat typing, total.
- `turns.jsonl`: one row per question with every stage (heard, model first token, first sound, chat posted) timed from the end of the human turn. Read it with `python -m bot.main report [out/<time>]`: a per-turn waterfall and p50/p90 per stage.
- `connections.jsonl`: model attempts (outcome, code, first-token time), prewarms and Scribe connections, so a slow answer can be explained.
- `bot.wav` (voice replies on): what the bot actually sent into the meeting, recorded next to `audio.wav` (`audio_clock.json` holds both start times). `python -m bot.main audit [out/<time>]` measures end of question to first bot sound from the recordings, to about 10 ms, and compares it with the log.

Tuning: `DIRECT_REPLY_GAP_SECONDS` (default 6), `MAX_DIRECT_REPLIES` (12), `BRAIN_INTERVAL_SECONDS` (20), `ANSWER_MODE` (`questions` or `addressed`). Free-tier Gemini keys hit 429 limits if these are pushed too hard.

## Transcript sources and project knowledge

`--stt captions` (default) uses Meet's captions. `--stt gemini` (or `--hybrid`) sends each detected speech segment to Gemini; captions only supply speaker names. `--stt elevenlabs` streams audio to ElevenLabs Scribe v2 Realtime (partial text while people speak, speaker ids, `ELEVENLABS_API_KEY` in `.env`); run `python -m bot.main stt-probe` on a recorded run first to measure it on your plan. Audio modes are announced in the intro chat line.

Gemini Live (native voice) is not wired into meetings yet; see `docs/VOICE_ARCHITECTURE.md`. `python -m bot.main live-probe` measures it first. It needs `GEMINI_LIVE_API_KEY`, a Google AI Studio key. For each model in `LIVE_MODELS`, it asks the questions from your latest recorded run (or espeak-voiced ones with `--espeak`) and times our end-of-turn signal to the first audio. It prints PASS/FAIL against the "instant" target and saves every answer as a WAV in `out/live-probe-*/`.

The bot answers project questions from `context/` (.md/.txt/.csv/.json), any `--context FILE|FOLDER|https://URL` (repeatable, or `CONTEXT_URLS`), and text people paste into the Meet chat. Typed chat questions work without any speech recognition.

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
pip install pytest
python -m pytest
```

No live meeting, browser or API key is needed. `tests/test_gemini_smoke.py` runs only when `GEMINI_API_KEY` is set. Caption fixtures in `tests/fixtures/` are synthetic (see the README there).

## Least certain parts

See `PROGRESS.md` (handoff section) for what could not be verified without a live Meet.
