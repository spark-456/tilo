# Recording upload and the speech provider (FR-MTG-17, FR-MTG-11)

An uploaded audio or video recording is transcribed through `SpeechProvider`, then follows the FR-MTG-02 ingest shape.

## Provider layer (`packages/providers`, the only place a speech vendor is named)

- `SpeechProvider.transcribe(audio, media_type=..., language=None)` returns exactly
  `{"segments": [{"speaker", "start_ms", "text"}]}` (`speech.as_speech_result`; anything else is a `ProviderError`).
- `config/speech.yaml` sets the vendor (`google` or the dev vendor `fake`; anything else fails start-up), the profile
  id, the model id (checked against `rules.deny` in `config/models.yaml`, PL-07) and the caps (`max_bytes`,
  `max_duration_ms`). `speech.build_speech_provider(load_speech_config(...), fixtures_dir=...)` builds it.
- `google` is `SpeechRecordReplayProvider` (EFF-01): replay by default from `<fixtures_dir>/speech-recordings/<key>.json`
  (key = profile, SHA-256 of the audio, media type, language; the audio is never stored), a miss is a
  `ReplayMissError`, `LIVE=1` goes live through `google_speech_adapter.GoogleSpeechProvider` (Gemini audio inline in
  one `generate_content` call, prompt `prompts/speech/transcribe.md`, reply validated or the call fails closed),
  `+TILO_RECORD=1` writes a redacted recording. Tests use a fake client and the committed recording only.
- `FakeSpeechProvider` is deterministic and refused when `LIVE=1` or deployed (`K_SERVICE`, `CLOUD_RUN_JOB`).

## The bot's voice (FR-MTG-11, `tilo_providers.voice`)

- `SpeechProvider.synthesize(text, *, voice=None)` returns raw 16-bit mono little-endian PCM. It is additive and not
  abstract: a provider that only transcribes raises `errors.NotConfigured`. The sample rate is not in the result, it is
  `config/voice.yaml` `sample_rate`.
- `config/voice.yaml` sets the vendor (`google`, or the dev vendor `fake`; anything else fails start-up), the profile id,
  the model id (checked against `rules.deny`, PL-07), the voice name, the sample rate and the caps (`max_chars` before the
  request, `max_audio_bytes` after it). `config/voice.dev.yaml` is the offline default the meet-bot reads without the live
  switch. `voice.build_voice_provider(load_voice_config(...))` builds it.
- `google` is Gemini speech output through the same client as `transcribe` (`GoogleSpeechProvider.synthesize`,
  `response_modalities: [AUDIO]`, a prebuilt voice name). It is built only with `LIVE=1`; without it the call raises
  `NotConfigured` (audio is not recorded for replay). `fake` is `FakeSpeechProvider.synthesize`: a deterministic
  sawtooth, 0.1 s per word, pitch from a digest of voice and text.
- Not metered: `config/prices.yaml` has no audio-output price (BQ-MTG11-3). Streaming the voice is FR-MTG-16.

## Ingest (`tilo_planning.recording.transcribe_recording`, pure)

Why `tilo_planning`: it already depends on `tilo-providers` and `tilo-contracts`, and owns the upload allowlists, size
caps and safety screen (FR-INT-02) that this path shares.

- Fails closed before any speech call: media type outside `audio/*`, `video/mp4`, `video/webm`; empty or oversized
  file; declared duration over the cap. After the call: no speech, more than 10,000 utterances, last offset over the
  duration cap.
- Normalises to `contracts/transcript.schema.json`: ids `u0001` upward in time order, one line of text (whitespace runs
  and newlines become a space; control, format and separator characters removed), text at most 4000, speaker at most
  80 with no `://`, a blank speaker becomes "Speaker 1"; checked with the generated `Transcript` model.
- Safety: the speaker and text lines are screened with the injected `SafetyProvider` in chunks of at most 20,000
  characters. A flag is kept and returned (`safety_flagged`, `safety_reason`), never dropped; a provider error
  propagates. What a flagged transcript may reach is the caller's rule (FR-MTG-02).
- Returns `RecordingTranscript(content, origin, safety_flagged, safety_reason)`. `origin` is the ingest origin record
  `{"kind": "recording-upload", "media_type", "size_bytes", "sha256", "utterances"}`; it never holds audio.

## Not built here

The upload route and the storing of a recording's transcript. The FR-MTG-02 ingest (VTT, SRT, text, the meet-bot
package, the stored artifact, the Trace event) is in `docs/transcript-ingest.md` and shares `normalise_segments` with
this path. See BQ-MTG17-1 and BQ-MTG17-2 in `docs/open-questions.md`.
