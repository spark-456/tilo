# Open questions (build log)

Questions found while building. Each has the default we build on until the user answers. PRD-level open questions (OQ-01 to OQ-15) stay in PRD 22.1; these use `BQ-` ids.

| ID | Question | Default until answered | Source | Raised |
| --- | --- | --- | --- | --- |
| BQ-01 | PRD 9.3: the `authz` row was cut off by the Markdown export (a `|` inside the cell broke the table: "`{by: user |`"). What is the exact shape? | `authz: {by: "person" \| "policy" \| "team_lead", ref: string, at: RFC 3339}` from PRD 10.4 "Audit" and the glossary; architect records it in an ADR | PRD 9.3, 10.4 | 2026-09-25 |
| BQ-02 | PRD 9.2: layout validation rules WE-01 to WE-16 "carry over from v1", but v1 is not in the repo; only a one-sentence summary exists. Can we get the v1 list? | Derive the rules from the 9.2 summary sentence and number them in `contracts/layout.rules.md`; mark gaps | PRD 9.2 | 2026-09-25 |
| BQ-03 | PRD 14.2 counts Email Autopilot units `reply_handled` and `mail_triaged`, but no event type in 9.5 carries them. | `building.completed` with `data.unit_type` in {`reply_handled`, `mail_triaged`} | PRD 9.5, 14.2 | 2026-09-25 |
| BQ-04 | Card merge and "timed-out card applies its default and posts a Nudge" (10.3, FR-HIL-02) have no registered event type. | `question.answered` with `data.answered_by = "default"` and `severity = "nudge"`; gates never time out to go | PRD 9.5, 10.3 | 2026-09-25 |
| BQ-05 | CP0 needs "first deploy" and "the provider router serves one real call". Both need the user: Google Cloud projects and billing, `gcloud auth`, applying Terraform, and one `LIVE=1` call. | Build and test everything locally on record-and-replay; hand over the plan and commands | PRD 5.4, 25 | 2026-09-25 |
| BQ-06 | May the design prototypes' JavaScript (`tilo-world.js`, `tilo-kit.js`, `tilo-player.js`, made in Claude Design during the programme) be ported into `apps/web`, or only used as a visual reference? The inventory found all world art is programmatic inline SVG in these files, so porting would save most of the world-art work. `support.js` is Claude Design's runtime and is never copied. | Visual reference only; the app is re-implemented fresh | Brief "fresh code only", PRD 4.4 | 2026-09-25 |
| BQ-07 | `design/source/worlds/k1.events.json`: real recorded run or generator-made? **Found:** hand-scripted by `k1-generator.js`, with authored decision branches; it also uses 4 types not in the 9.5 registry (`world.created`, `user.joined`, `user.commented`, `alert.batched`). | Dev fixture only; never shown as a replay of a real run (SC-07 needs a real recorded run) | PRD 4.3, 9.4 | 2026-09-25 |
| BQ-10 | The design exports and PRD 18.2 disagree: buttons 16 px radius and 56 px tall on mobile, camera pans 650 ms in the exports, versus 12 px, 52 px and 320 ms in the PRD. Which wins? | PRD 18.2 values (the spec); the design-critic judges everything else against the exports | design/source/INDEX.md, PRD 18.2 | 2026-09-25 |
| BQ-11 | Colour roles `signal.gate`, `policy` and `ink.3` have no value in the exports. `policy` is needed for HR-7 (policy-authorised actions must look different). | Structural work uses neutral fallbacks marked `status: missing`; no brand colour is invented. Visual polish for gates and policy stamps waits for the user | design/tokens.json, PRD 9.4 | 2026-09-25 |
| BQ-08 | FR-WLD-10 perf budget is "on the reference laptop" (integrated graphics). CI cannot run that hardware. | CI uses Playwright with CPU throttling and software rendering as a proxy; a manual run on a real mid-range laptop before CP1 and CP4 | PRD 9.7 | 2026-09-25 |
| BQ-09 | PRD 20.4 says humans own every merge; the kickoff brief says the orchestrator merges and asks only for security-flagged items and contract changes. | The brief wins (it is the user's later instruction) | PRD 20.4 | 2026-09-25 |

## Answered

| ID | Answer | Date |
| --- | --- | --- |
| BQ-05 | Google Cloud billing is temporarily unavailable. Build local-first on emulators; live model tests may use NVIDIA NIM through the OpenAI-compatible adapter; apply `infra/` later (ADR-0003). | 2026-09-25 |
| BQ-06 | Yes: Tilo's own design prototypes may be ported; `support.js` never (ADR-0003). | 2026-09-25 |
| BQ-10 | PRD 18.2 values win (user go-ahead on the default). | 2026-09-25 |
| BQ-11 | Colours taken from the exports' own palette: `policy` #0E8A87 (lip #0A6664), `signal.gate` #5A5768, `ink.3` #66717A. User may override (ADR-0003). | 2026-09-25 |
| Repo | Private GitHub repository `spark-456/tilo`; not public for now. | 2026-09-25 |
