# AppSpec rules beyond the schema (appspec.schema.json v1)

ADR-0029 decision 9, FR-AGT-16 (Could; BQ-LW-3 asks the user to promote it). `appspec.schema.json` checks
one spec on its own. The rules below need other records, the renderer or the run, so they have no invalid
fixture; the tests of the ticket named in each row cover them. The generated pydantic models drop the
schema's `dependentSchemas` and `dependentRequired`, so every writer and reader validates a spec against the
JSON Schema itself. Rule ids are stable.

| Rule | Rule | Checked by | Source |
| --- | --- | --- | --- |
| AS-01 | Question ids are unique within a spec. | writer before the put (LW-10); player refuses a spec that breaks it (LW-14) | ADR-0029 9 |
| AS-02 | Every `source.artifact` names a version recorded in the spec's own world (EV-15) whose `origin.kind` is `fetch` or `upload`, and `page`, when present, is within that PDF's page count. The Verifier checks each `answer` against that page before `app.tested` (FR-AGT-12, BQ-LW-4); a question it cannot confirm is dropped or the unit fails, never shipped unchecked. | Verifier (LW-12); tilo-api when serving (LW-13) | 13.3, FR-AGT-12, FR-CON-10 |
| AS-03 | Fixed web code renders the spec. Every string (title, stem, option, artifact label) is shown as plain text: never parsed as HTML, Markdown or maths markup, never turned into a link, never fetched. The route is owner-only (the world's Scope, SEC-07). The "from <publisher>" line is the host of the cited version's cleaned source URL, read server side from its manifest (BQ-104), never from the spec. `theme` is checked by shape only until `config/themes/` exists (BQ-202). In phase 1 attempts stay on the person's device (BQ-LW-3). Showing the spec to anyone but the owner is a share and T3 (BQ-LW-3). | apps/web player (LW-14); tilo-api route (LW-13) | 9.4, 16.1, 16.3; BQ-LW-3, BQ-LW-5 |
| AS-04 | A spec is a unit's `application/json` output (origin `unit`, ADR-0018) that passed this schema before the store put; one that fails fails the unit (FR-AGT-13). Events reuse the `app` family: `app.spec` names the stored version, `app.tested` records the Verifier's answer-key check (`passed`), and `app.deployed` is written when the owner-only route first serves that version. No other `app.*` event is written for a quiz, and nothing animates without one (HR-1). | harness (LW-10); tilo-api (LW-13) | 9.4, 9.5, FR-AGT-13, FR-AGT-16 |
