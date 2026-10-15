# Skill Replay Plan

## Goal and constraints

Teach a repeatable browser task by observing one person-led session, then replay it against changed pages by observing, choosing, acting, and verifying each step. Browser only; the Chrome extension is phase 2. No credentials or password values are recorded or replayed. A person handles sign-in. Every browser/model action uses the existing worker and provider interfaces. Any download, form submission, or other external side effect pauses for explicit approval; policy decisions remain deterministic and T3 always requires a person.

## Recorder

- Phase 1 uses the isolated `BrowserWorker` session and a recording adapter around its existing `HandsProvider`; the user performs each action. Persist only an append-only local-first session record, scoped to its owner, with explicit start/stop and worker/session identity. Do not persist cookies, raw screenshots, field values, credentials, or unmasked page text.
- Phase 2 is a Chrome/Edge extension that emits the same event model from the user's signed-in browser, with per-site grants and a visible recording banner. It does not export cookies or password-field content.
- Events have monotonic sequence, timestamp, kind (`navigate`, `click`, `type`, `scroll`, `download`, `submit`, `sign_in_pause`), sanitized URL, role-based target description, safe selector candidates, masked non-sensitive input value only when needed, and masked before/after page observations. Secure fields store only a redacted marker and no value or selector that exposes their contents. File paths are user-chosen local destinations and are never inferred from sensitive page text.
- Storage is isolated by owner and recording id; writes are atomic, capped, and reject malformed sequences. Deletion removes the recording and derived drafts. A recording is never executable code.

## Recording to skill

- Deterministic preprocessing masks through the browser worker's masker, drops credential and secure-field events, and reduces repeated low-value observations. Preserve event order and source ids for traceability.
- Send only the minimized masked event sequence and page observations to a configured provider role through `packages/providers`; never call a model SDK or search directly. The model proposes intent text, target semantics, selector alternatives, and verification conditions in a closed schema. Code validates bounds, origins, selectors, and allowed worker actions; invalid output fails closed.
- A skill step contains intent, action, target role/name, selector candidates with evidence, expected page change, and risk tier. The draft retains recording provenance and confidence. No model output grants permission or invents connector scopes.

## Replay loop and safety

1. Open a fresh isolated worker; apply the allowlist and pause for the person at any login wall. Never read or restore cookies or type passwords.
2. Observe the current URL, masked accessibility tree, and masked page text. Compare to the step's expected page and target evidence.
3. Choose one next step using a configured provider role through `packages/providers`; validate its structured choice deterministically against the skill and current observation.
4. Execute only a `HandsProvider` action, then observe again and verify the expected state. On mismatch, retry with refreshed observations within a bounded budget, ask the person when ambiguous, or stop safely. Never blindly advance.
5. Before a download, form submit, or any action that leaves or changes data, request a person approval through the existing deterministic policy/outbox gate. Revalidate page, destination, and action after approval; deny by default and record the decision. Do not implement an approval bypass in the browser worker.

## Contracts and demo slice

- No contract change for the local deterministic demo: recorder events and replay drafts remain private internal models and storage, with no new public event types or API payloads. Existing `HandsProvider`, skill, card, and policy contracts remain authoritative. If durable cross-service skill provenance or approval events become necessary, the exact frozen-contract proposal is `contracts/taught_skill.schema.json`: add an optional `replay` object with source recording id, ordered intent/action steps, bounded selector evidence, and verification conditions; obtain owner approval before any contract edit.
- Demo slice for Fri 16 Oct 18:00 IST: fake driver on a `services/sandbox-web` seeded page; record navigation, search typing, result click and page verification; compile through a deterministic fake provider; replay after a benign label/layout change using accessible-role/intent fallback; mask a planted password field; pause at login; and prove download/submit waits for explicit approval. Deterministic `SKILL_REPLAY` tests only; no paid calls, live sites, or Playwright unless the worker's own tests already use it.
- Implementation order: add event model/store and masking tests; add compiler and fake-provider tests; add bounded observe/choose/act/verify runner and approval tests; wire only through new API modules/routes if needed. Avoid existing web app files and all contract/PRD edits.
