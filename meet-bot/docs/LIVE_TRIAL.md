# FR-MTG-16 synthetic native-audio probe

This is a standalone, one-turn experiment, separate from meeting capture. It does
not change the bot's Chirp responder or accept a meeting recording. No live result
exists yet. Tests inject a fake session, record synthetic PCM, then replay exactly
the same response while proving the SDK client stays unused.

Before a paid run, the user approves the current regional text-input/native-audio
output quote in `config/meeting-live-trial.yaml`: `price_status: set`, the two rates,
HTTPS source, region and ISO price date (within 30 days). Missing prices refuse
before SDK construction, even with the live switch. No rate is guessed. Use the
configured project and regional ADC environment; no service-account key file.

The **user** sets `LIVE=1` for this one experiment. From the repository root:

```powershell
uv run --no-sync python -m tilo_providers.live_trial --recordings work/live-trial --record-synthetic --wav work/live-trial/recorded.wav
# Replay never builds a network client, even if LIVE is still set:
uv run --no-sync python -m tilo_providers.live_trial --recordings work/live-trial --wav work/live-trial/replayed.wav
```

The prompt and model are config-only. One invocation sends one short synthetic text
turn, with at most 256 output tokens, 30 seconds of 24kHz mono PCM, and a 20-second
whole-session deadline. It records the PCM, redacted output transcription, time
to first audio, total duration and any reported token usage. Missing usage stays
unknown. These are resource caps; they are not a dollar reservation or a credit
charge. This experiment does not yet use a world budget or issue a billing event.
Listen to the WAV and compare its bytes against the replay. Keep both out of Git.

Latency includes cold session setup, not time until a Meet participant hears it.
Silent, interrupted, incomplete, odd-byte or over-cap audio is a failed experiment,
with awaited session cleanup and no success recording. No automatic retry occurs.

This probe establishes record/replay and native audio output only. The full X4
decision still needs addressed audio input, warm-session latency, barge-in,
manual activity detection, resumption/compression and real microphone playback.
Chirp remains the bot voice until that experiment passes architectural review.
