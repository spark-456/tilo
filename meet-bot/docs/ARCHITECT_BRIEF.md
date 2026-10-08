# Architect brief, 2026-09-30 (replaced)

The original brief compared third-party voice and speech vendors with Google's. FR-MTG-11 (Google only) makes that
comparison moot, so the text is not kept in this tree; it is on `chore/meet-bot-baseline` (commit c2991182). What it
established and still holds:

- The bot joins Meet as a normal participant with a Chromium profile in a named Docker volume, signed in once by hand
  (ADR-0017); it never handles a password.
- Everything real runs in one Linux container: Playwright, a virtual screen, virtual audio.
- Captions give speaker names and timing; audio gives the accurate text.
- Honest disclosure: the intro chat line says the audio is transcribed by an AI service, recorded, and that the bot may speak.

The current design is `docs/VOICE_ARCHITECTURE.md` (Google voice, FR-MTG-16) and `DECISIONS.md`.
