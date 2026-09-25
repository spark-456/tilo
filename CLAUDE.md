# Tilo — root rules for Claude Code

Tilo is an agentic work platform for the Google Cloud AI Builder Cup 2026 (submit 17 Oct 2026). People describe work; a Director plans it; agent teams run it; the work is shown as a living isometric world with Story and Trace lenses; people approve from web, phone, WhatsApp or email.

## Sources of truth (in this order)
1. `contracts/` (JSON Schemas, event registry, fixtures). Contracts win over prose.
2. `docs/prd/tilo-prd-v2.md`: the spec. **Read-only.** Requirement IDs (FR-*, NFR-*, SEC-*, PL-*, EFF-*) are ticket IDs; each acceptance test is the definition of done.
3. `docs/adr/`, then code comments.
4. `design/source/` (read-only design exports; map in `design/source/INDEX.md`) and `design/tokens.json`. Where exports do not cover a screen, use neutral role tokens; never invent brand colours or copy third-party assets.

Ambiguity: apply the PRD's stated default, log it in `docs/open-questions.md`, keep going. Never invent requirements.

## Hard rules
- Models are configuration. Every model, search, safety, speech and render call goes through `packages/providers`. No model id outside `config/` and `packages/providers` (PL-01).
- Dev and CI make no paid calls: record-and-replay or fake providers only. Only the user sets `LIVE=1` (EFF-01).
- Every side effect goes through the outbox and the deterministic policy engine. T3 always needs a person. A model never decides authorisation.
- Nothing animates without a recorded event (honesty rules HR-1 to HR-7, PRD 9.4).
- No scenario-specific code. A scenario that needs code becomes a pillar requirement first.
- No secrets in code, prompts, logs or fixtures. Fake secrets for tests are assembled at runtime. Tilo never handles passwords.
- Fresh code only: nothing copied from other projects (including `design/source/support.js`, Claude Design's runtime). Record every dependency's licence in `docs/licences.md`.
- Deploy on Cloud Run and Firebase, region `asia-southeast1`. English everywhere.

## Environment (native Windows, see ADR-0001)
- The repo path contains spaces: always quote paths. Use forward slashes in code and scripts.
- Task runner is `just` (not make). Every recipe calls `uv`, `pnpm`, Python or Node; no bash-only or PowerShell-only scripts. CI runs on Linux.
- Line endings are LF (`.gitattributes`). The Bash tool collapses `\\` inside heredocs: write files with the Write tool, not heredocs.
- Hooks: `.claude/hooks/guard.py` blocks edits to read-only paths, `.env` files, secret-looking content, `git push`, `terraform apply`, `tilo-demo` deploys and `LIVE=1`. Do not work around it; report instead.

## Ticket loop
- One ticket = one requirement ID or a small related group. Branch `feat/<ID>-<slug>`; acceptance tests on `tests/<ID>` written first by test-writer and failing before implementation.
- Test names contain the requirement ID (e.g. `test_FR_WLD_02_generated_types_match_schemas`).
- Commit trailer `Req: <ID>`. Diff under 400 hand-written lines (generated types, fixtures and lockfiles excluded; say so in the summary).
- Run `just check` before finishing. Emitted events must be registered and fixtured.
- Definition of done (PRD 20.4): acceptance test green with the ID in its name; events registered and fixtured; docs updated; no new console errors; deployed to `tilo-dev` once infrastructure exists.

### Builders
Work only in your worktree. Create `feat/<ID>-<slug>` from `main`, merge `tests/<ID>` if it exists, make its tests pass without weakening them. Never edit `contracts/` or `docs/prd/`; if a contract must change, stop and report "needs contract change: …". Keep code simple and deterministic where the PRD says so. Finish with: branch, worktree path, commit ids, `just check` result, hand-written line count, anything left undone. Do not describe your reasoning to reviewers.

### Reviewers
You get the ticket, the PRD sections, the branch and the worktree path. You never see the builder's reasoning; do not trust summaries. Read `git diff main...<branch>` and run the tests yourself. Never edit files or commit.
Automatic FAIL: any console error, layout shift, failing test, unregistered event type, schema drift, honesty-rule violation (PRD 9.4), model id outside config, secret in the diff, paid call without `LIVE=1`.
Reply in exactly this form, no scores, no praise:
```
VERDICT: PASS | FAIL
BIGGEST PROBLEM: <one problem: file:line, what is wrong, what done looks like> | none
EVIDENCE: <commands you ran and what they showed, at most 5 lines>
```
Save recurring defects, codebase patterns and PRD rules that keep being missed to your project memory.

## Ask the user before
Changing a frozen contract (ADR first); applying infrastructure or spending money; sending any real email or WhatsApp message; merging anything security-reviewer flagged; deploying to `tilo-demo`; the first push to any remote.

## Layout (PRD 20.3)
`docs/prd` `docs/adr` `contracts/` `config/` `prompts/` `skills/` `templates/` `packages/providers` `packages/contracts-py` `packages/contracts-ts` `apps/web` `services/{api,harness,channels,connectors,browser,render,sandbox-web}` `evals/` `infra/` `.github/workflows/` `design/`. Each service has its own `CLAUDE.md`.

## Commands
- `just setup` — `uv sync` + `pnpm install` for every workspace member
- `just dev` — run the `apps/web` dev server; `just dev-api` — run the `tilo-api` dev server (run both in separate terminals for a full local stack)
- `just tokens` — regenerate `apps/web`'s design-token CSS/TS from `design/tokens.json`
- `just check` — format check + lint + typecheck + all tests (the full gate; run before finishing a ticket)
- `just check-fast` — format + lint + tests, used by `.claude/hooks/stop_check.py`, under 2 minutes
- `just test` — all Python and JS test suites
- `just fmt` / `just lint` / `just typecheck` — individual gate steps
- `just eval` — run the eval harness (not built yet; prints a message and exits 0 until P3)
- `just skills-test` — run `skills/` tests (FR-AGT-04); passes with none present
- `just deploy dev` — refuses anything but `dev`, and infra isn't applied yet either way (ticket P0-07)
