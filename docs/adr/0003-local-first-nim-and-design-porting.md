# ADR-0003: Local-first build, NVIDIA NIM for live tests, private repo, design-code porting

- Status: Accepted (2026-09-25, user decisions)
- Deciders: product owner, orchestrator

## Context
Google Cloud billing is temporarily unavailable to the team, so `tilo-dev` cannot be created or applied yet and CP0's "first deploy" and "one real call on the default profile" cannot happen on Google Cloud. The user asked to test with NVIDIA NIM if possible, or to build the shell so Google services plug in later; to keep the repository private for now; and gave a go-ahead on the open questions (BQ-06, BQ-10, BQ-11) and on merging the security-flagged P0-01 and P0-07.

## Decision
1. **Local-first.** Everything runs locally on emulators until billing is available: Firestore and Pub/Sub emulators under a `demo-tilo` project id (emulators need no Google account), local FastAPI services, the web app on Vite. The Terraform in `infra/` stays ready and tested with mock providers; the user applies it later.
2. **Providers.** The provider layer ships the `google` adapter (tested against mocks and recordings) and the generic OpenAI-compatible adapter. An example profile set for NVIDIA NIM (`https://integrate.api.nvidia.com/v1`, key from `NVIDIA_API_KEY` in the git-ignored `.env`) is added alongside the Google examples, preferring Gemma models where NIM hosts them so behaviour stays close to the hackathon's Google-model rule. Live calls still need `LIVE=1`, set by the user. The submitted build must route every role to Google models on Google Cloud (PRD 4.4); NIM is for testing only.
3. **Repository.** Private GitHub repository `spark-456/tilo`. Pushing branches is allowed; force pushes, making it public and deleting it need the user.
4. **Design code (BQ-06).** Tilo's own design prototypes made during the programme (`tilo-kit.js`, `tilo-world.js`, `tilo-player.js`, `worlds/k1-generator.js`) may be ported into `apps/web`. `support.js` is Claude Design's runtime and is never copied.
5. **Design values (BQ-10, BQ-11).** PRD 18.2 values win where they differ from the exports (12 px control radius, 52 px mobile buttons, 320 ms camera). Missing colour roles take colours that already exist in the exports: `policy` = `#0E8A87` (lip `#0A6664`, the Token card's "Tide · accent"), `signal.gate` = `#5A5768` (the exports' closed-gate grey), `ink.3` = `#66717A` (the "Neutral" swatch). The user can override any of these.
6. **Merges.** P0-01 and P0-07 are approved for `main`. Future security-flagged merges still need the user.

## Consequences
- CP0 cannot be fully GO: the deploy criterion stays NOT MET until billing works; "one real call" can be shown on NIM once the user adds a key.
- A later switch to Google Cloud is configuration: apply `infra/`, set Google profiles as defaults, record new responses.
- Live NIM responses recorded for replay must be re-recorded on Google models before submission evidence is produced.
