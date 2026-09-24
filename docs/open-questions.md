# Open questions (build log)

Questions found while building. Each has the default we build on until the user answers. PRD-level open questions (OQ-01 to OQ-15) stay in PRD 22.1; these use `BQ-` ids.

| ID | Question | Default until answered | Source | Raised |
| --- | --- | --- | --- | --- |
| BQ-01 | PRD 9.3: the `authz` row was cut off by the Markdown export (a `|` inside the cell broke the table: "`{by: user |`"). What is the exact shape? | `authz: {by: "person" \| "policy" \| "team_lead", ref: string, at: RFC 3339}` from PRD 10.4 "Audit" and the glossary; architect records it in an ADR | PRD 9.3, 10.4 | 2026-09-25 |
| BQ-02 | PRD 9.2: layout validation rules WE-01 to WE-16 "carry over from v1", but v1 is not in the repo; only a one-sentence summary exists. Can we get the v1 list? | Derive the rules from the 9.2 summary sentence and number them in `contracts/layout.rules.md`; mark gaps | PRD 9.2 | 2026-09-25 |
| BQ-03 | PRD 14.2 counts Email Autopilot units `reply_handled` and `mail_triaged`, but no event type in 9.5 carries them. | `building.completed` with `data.unit_type` in {`reply_handled`, `mail_triaged`} | PRD 9.5, 14.2 | 2026-09-25 |
| BQ-04 | Card merge and "timed-out card applies its default and posts a Nudge" (10.3, FR-HIL-02) have no registered event type. | `question.answered` with `data.answered_by = "default"` and `severity = "nudge"`; gates never time out to go | PRD 9.5, 10.3 | 2026-09-25 |
| BQ-05 | CP0 needs "first deploy" and "the provider router serves one real call". Both need the user: Google Cloud projects and billing, `gcloud auth`, applying Terraform, and one `LIVE=1` call. | Build and test everything locally on record-and-replay; hand over the plan and commands | PRD 5.4, 25 | 2026-09-25 |
| BQ-06 | May the design prototypes' JavaScript (`tilo-world.js`, `tilo-kit.js`, `tilo-player.js`, made in Claude Design during the programme) be ported into `apps/web`, or only used as a visual reference? `support.js` is Claude Design's runtime and is never copied. | Visual reference only; the app is re-implemented fresh | Brief "fresh code only", PRD 4.4 | 2026-09-25 |
| BQ-07 | `design/source/worlds/k1.events.json`: is it a real recorded run or generator-made? SC-07 must be a "labelled replay of a real scoped run" (HR-4). | Use it only as a dev fixture; never present it as a real run | PRD 4.3, 9.4 | 2026-09-25 |
| BQ-08 | FR-WLD-10 perf budget is "on the reference laptop" (integrated graphics). CI cannot run that hardware. | CI uses Playwright with CPU throttling and software rendering as a proxy; a manual run on a real mid-range laptop before CP1 and CP4 | PRD 9.7 | 2026-09-25 |
| BQ-09 | PRD 20.4 says humans own every merge; the kickoff brief says the orchestrator merges and asks only for security-flagged items and contract changes. | The brief wins (it is the user's later instruction) | PRD 20.4 | 2026-09-25 |
