# CX-SKILL-REPLAY-03 — recorder/runner integration plan for Claude approval
Scope: plan only; no API, UI, schema, PRD or runtime changes are included.
Base: origin/live13-candidate at 625517b157653e84fa3efc5251a2bcbf315788c5.
Recorder/runner reference: cx/SKILL-REPLAY-extension at 1379ae62f662b51e6fd41886e14636ffdd614c99 (read-only).

Existing seams
- `services/browser/extension/README.md`: local extension capture/export, maximum 200 events; export is untrusted, never authorisation.
- `services/browser/src/tilo_browser/skill_recording.py`: `RecordingSession` checks typed fields with `BrowserWorker`; `JsonlRecordingStore` masks and partitions by owner.
- `services/browser/src/tilo_browser/skill_replay.py`: `compile_recording` retains recorded actions; `replay` observes, chooses current targets, verifies, and requires a `SideEffectGate`.
- `services/api/src/tilo_api/skills_capture.py`: capture/version routes currently accept only descriptions; `skills_routes.py` saves and reads taught skills.
- `apps/web/src/park/pages/Skills/TeachWizard.tsx` and `useTeach.ts`: example recording and Try it once are disabled because their routes do not exist.

Proposed minimal API surface, subject to the decisions below
1. `POST /v1/skills/recordings`: import a bounded extension export; return a server recording id and redacted captured-step preview, never replay automatically.
2. Extend `POST /v1/skills/captures/{capture_id}/version` to compile an approved recording reference; reuse `POST /v1/skills` for reviewed Save.
3. `POST /v1/skills/{skill_id}/runs`: owner-initiated real replay of a server-pinned version; return the recorded world/run identity, then use existing world/card reads and answers.
4. A separate `POST /v1/skills/{skill_id}/try-runs` may expose the contracted dry-run result only after a no-side-effect executor exists; never call real replay and label it a try-run.

Request, storage and execution boundaries
- API derives org/owner from `deps.get_current_principal`; reuse AccessGate, App Check, rate limits, work-mode/spend gates and `deps.get_router`; demo stays replay-only with ephemeral stores.
- Accept only closed, size-bounded event fields plus an idempotency key; reject caller owner/path, verified-input stamps, executable proposals and unknown/foreign recording ids.
- Browser service validates exports through `RecordingSession` against a bound isolated worker; never trust extension `safe_text` or JSON `input_verified`; reject unverifiable typed values and pause at sign-in.
- API owns business metadata, owner lookup and a pinned redacted artifact reference in the owner's Desk; browser keeps only scoped session data and cannot read business Firestore/Cloud Storage.
- `JsonlRecordingStore` is a local primitive, not an approved durable store: decide encrypted persistence, retention/deletion and retry/concurrent-import rules before production wiring.
- Add authenticated internal browser RPC following `services/browser/src/tilo_browser/app.py`'s fail-closed OIDC audience/caller pattern; bind each session to API-issued ownership and allowlisted egress.
- Implement `SideEffectGate` using deterministic policy and `services/connectors/src/tilo_connectors/outbox.py` `Outbox.enqueue/dispatch_due`; execute only with its grant, fresh approval and fresh target checks; T3 requires a person.
- Pin versions and use `services/api/src/tilo_api/skill_ledger.py` start/finish records; show progress only from recorded events. Existing replay is synchronous, so bounded job/resume semantics need agreement.

Skills entry and approval questions
- After backend approval, wire Show an example to import a recorder export through `park/api`, then review/version/Save via `useTeach`; show Record/Run controls only when the service supports them.
- `contracts/taught_skill.schema.json` defines method `record` as video only and `guided` as Tilo-browser interaction: which method covers external extension event JSON? Needs owner-approved contract clarification/change before implementation.
- The same schema requires registered connector tool/action plan steps; `config/connectors.yaml` has no browser action mapping. Claude must approve the browser action/risk mapping and replay-plan storage contract; do not squeeze selectors into plan text.
- Approve closed request/response schemas, artifact format/retention, RPC ownership claims, run lifecycle/idempotency and approval-resume events; any new events require registry/fixtures before code.
- Later implementation tests: fake provider/worker/RPC only; foreign owner, forged verification, secure fields, ordering/caps, duplicate imports, sign-in, target drift, denied/T3 approval, outbox retry and honest UI state; no paid calls.
