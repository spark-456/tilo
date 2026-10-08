# Transcript ingest (FR-MTG-02)

The meet-bot package (`transcript.jsonl` and optional `state.json`) or an uploaded VTT, SRT or text file becomes a
safety-screened, versioned `Transcript` artifact (`contracts/transcript.schema.json`, ids `u0001` upward) with an
origin record. Code: `tilo_planning.transcript_ingest`; tests: `packages/planning/tests/test_FR_MTG_02_*`.

**Placement.** It lives in `tilo_planning`, next to `recording.normalise_segments` (the one cleaner shared with the
FR-MTG-17 recording path) and the upload limits and safety screen (FR-INT-02). `tilo_planning` now depends on
`tilo-memory` (a leaf that depends only on `tilo-contracts`, so no cycle) for `ArtifactStore`, `NewVersion`, `Scope`.

## Flow

1. `kind_for_filename(name)` maps `.vtt`, `.srt`, `.txt`/`.text`, `.jsonl` to `vtt`, `srt`, `text`, `meet-bot`; the
   caller (the upload route, not built here) may also pass the kind itself.
2. `parse_transcript(kind, data, state=None)` is pure and deterministic (no model, no provider, no network; nothing
   in the input is executed or followed). It refuses an empty file, more than 4,000,000 bytes, a NUL byte, input
   that is not strict UTF-8 and more than 100,000 lines; a BOM and CRLF, LF or CR are accepted. It returns
   `{speaker, start_ms, text}` segments, the shape the recording path produces.
   - VTT: header required; `NOTE`, `STYLE`, `REGION` blocks and cue ids skipped; cue settings ignored; `<v Name>`
     gives the speaker; other tags (`<c>`, `<i>`, timestamps, `<font>`), SRT/ASS `{\an8}` and entities are removed or
     decoded. SRT: same cue parser. Text: one utterance per non-empty line, optional `Name: text`.
   - meet-bot: one JSON row per line `{speaker, text, t}` with `t` in seconds; a bad line is skipped and counted
     (`origin.skipped_lines`). `state.json` only gives the cleaned `agenda_title`; every other field is ignored.
3. `recording.normalise_segments` cleans and orders (stable time sort, control, format and bidi characters removed,
   `://` never survives in a speaker, a blank speaker is "Speaker 1", at most 10,000 utterances) and validates with the
   generated `Transcript` model. A payload over the 2,000,000-byte text cap is refused with a reason.
4. The speaker and text lines (and the title) are screened with the injected `SafetyProvider` in chunks of at most
   20,000 characters. A flag is kept and marked, never dropped; a provider error propagates before anything is stored.
5. One `NewVersion` (`application/json`, origin kind `upload`) goes into the `ArtifactStore`; the store redacts secrets
   and sets `screening` from its own verdict on the stored bytes (AR-07).
6. One registered event is returned, unwritten (the harness is the single writer): `artifact.created`
   (`artifact.versioned` when `parent` is given), severity `fyi` and `trace.tool` `safety_provider` when flagged,
   `info` otherwise. That is "flagged in the Trace". No transcript text is in the event.

Nothing else happens: no tool call, no outbox entry, no send. What a flagged transcript may reach is the caller's rule
(ADR-0020 decision 4 withholds quotes unless the version is `clean`).

`TranscriptIngest` holds `artifact` ref, `content`, `origin` (`kind`, `size_bytes`, `sha256` of the upload,
`utterances`; never the upload), `safety_flagged`, `safety_reason`, `title` and `events`. Open points:
BQ-MTG02-1 to BQ-MTG02-3 in `docs/open-questions.md`.
