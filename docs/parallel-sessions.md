# Parallel sessions charter

Several Claude Code sessions build Tilo at the same time. Each owns a slice of the repo, runs the same ticket loop (root `CLAUDE.md`) with the registered agents in `.claude/agents/`, and integrates through pull requests into `phase0-stack` on the private GitHub repo `spark-456/tilo`. Session S0 (the orchestrator) owns contracts, the provider layer, `docs/progress.md` and `main`.

## Sessions

| Session | Owns (only these paths, plus its own tests) | Tickets, in order | Main agents |
| --- | --- | --- | --- |
| S0 Orchestrator | `contracts/`, `config/`, `packages/providers/`, `packages/contracts-*`, `docs/progress.md`, `docs/adr/`, `docs/open-questions.md`, `CLAUDE.md`, `.claude/`, `main` | P0-03 event contract, P0-05 adapters, P0-06 router; contract requests; merges to `main`; checkpoint audits | architect, intelligence-builder, checkpoint-auditor |
| SW World and web | `apps/web/`, `design/tokens.json` | P0-08b camera rework + fixture player; P0-08c design-art port + ADR-0003 colours; FR-WLD-04, -06, -07, -08, -09, -10, -11; screens S-04, S-05, S-10, S-11, S-14 | world-builder, design-critic, qa-breaker |
| SH Harness and memory | `services/harness/`, `skills/`, `packages/archive/` (new), `packages/memory/` (new) | P0-09 harness skeleton; FR-AGT-01..10, -12, -13; FR-AGT-04 (10 v0 skills); FR-MEM-01..09 | intelligence-builder |
| ST Trust and reach | `packages/policy/` (new), `services/api/` (cards, approvals, policies modules), `services/connectors/`, `services/channels/`, `services/browser/`, `services/render/` | Policy engine FR-HIL-03, -04, -05, -07, -08, -09 with `docs/security/p4-policy-invariants.md`; outbox FR-AGT-11 / FR-CHN-13; FR-CON-01, -02, -03, -06, -13; FR-CHN-02, -03, -06, -07; FR-CON-07, -08, -09; SEC-03, -06, -08 | reach-builder, security-reviewer |
| SE Evidence | `packages/metering/` (new), `evals/`, `services/sandbox-web/`, `docs/evidence.md` | FR-MTR-01..09; eval harness and the 170 case skeletons (PRD 19.2) with deterministic checks; EFF-06, EFF-07; Sandbox Web sites; EV-G2 timing protocol | evidence-builder, cost-reviewer |
| SP Planning (after CP0) | `services/api/` (intake module), `packages/planning/` (new), `prompts/` | FR-INT-01..09, -11, -12; FR-WLD-01 layout generation + deterministic solver + WE rules | intelligence-builder |

## Prototype first until CP2 (ADR-0008)
Until one flow works end to end (target CP2, 3 Oct), every session builds only for that flow: type a task, answer questions, pick an approach and budget, watch the world, approve a "Needs you" card, get the result.
- Backend track: SH (agent runtime), SP (intake and planning), ST (policy engine, approval cards and outbox only).
- Frontend track: SW (merge the world view, then the screens along the flow).
- Paused: SE (evidence, metering, evals) after it parks its in-flight work cleanly, and ST's connectors, channels, browser and render tickets.
- S0 prioritises what the flow needs, such as the router, and holds contract work that only serves paused tickets.

The paused work resumes in Phase B (about 4 to 12 Oct).

## Protocol (every session except S0)

1. **Start.** Work in your own worktree. `git fetch origin`, then branch from `origin/phase0-stack`. Read `CLAUDE.md`, this file, `docs/progress.md`, `docs/open-questions.md`, the ADRs, and only the PRD sections your ticket names.
2. **Contract not merged yet.** Until P0-03 lands in `phase0-stack`, merge `origin/feat/P0-03-event-contract` into your branch when you need the event contract. SW starts from `origin/int/p0-08b-base` (web shell + event contract).
3. **Loop (speed mode, user 2026-09-26).** Per ticket: test-writer (failing tests first) → builder (own worktree, `feat/<ID>-<slug>`) → reviewers in parallel → fix every blocking problem in one pass → re-run only the reviewer that failed, on the fix. Reviewers:
   - code-reviewer: always.
   - security-reviewer: only if the diff touches policy or risk tiers, auth or tokens, the outbox, webhooks or signed links, redaction, secrets, IAM or infra, or a T3 action.
   - cost-reviewer: only for provider or router, metering or credit caps, CI or infra.
   - qa-breaker: once per ticket, only for running code with concurrency or UI.
   - design-critic: once per finished screen.

   Reviewers list every blocking problem in one round (root `CLAUDE.md`). Non-blocking findings go to a follow-up issue, never another round. Use the Agent tool with the registered agent types, or a Workflow.
4. **Limits.**
   - At most 2 agents running tests at once per session.
   - While iterating, run only the touched package's tests; run `just check` once before pushing.
   - After 3 failed rounds, redo from a tighter brief with a fresh builder, or split the ticket. If it still fails, open the PR with label `stuck` and say what is left.
   - Stop dev servers and emulators when done. No polling loops or crons.
   - Never set `LIVE=1`, never call Google Cloud, Meta or any paid API; build against emulators, fakes and recordings (ADR-0003).
5. **Paths.** Edit only the paths your session owns, plus tests for them. Never edit `contracts/`, `docs/prd/`, `design/source/`, `docs/progress.md`, `CLAUDE.md` or `.claude/` (except `.claude/agent-memory/`). Shared files (`justfile`, root `pyproject.toml`, `uv.lock`, `pnpm-lock.yaml`, `pnpm-workspace.yaml`, `docs/licences.md`, `.github/workflows/ci.yml`): smallest possible edits; on conflict regenerate lockfiles (`uv lock`, `pnpm install --lockfile-only`), never hand-merge them.
6. **Contracts and questions.** Need a contract change: open a GitHub issue labelled `contract-change` with the exact fields and the reason, keep going with a local stub, and pick up the change once S0 lands it. New ambiguity: open an issue labelled `question` with the PRD section and the default you are building on, then continue on that default.
7. **Integrate.** Push `feat/<ID>-<slug>` and open a PR into `phase0-stack` (`gh pr create --base phase0-stack`). The PR body lists: requirement IDs, a reviewer table (reviewer, rounds, final verdict), tests added, hand-written line count. Before merging, merge the latest `origin/phase0-stack` into the branch; `just check` and CI must be green.
   - Every reviewer passed and security-reviewer never failed the ticket: merge it yourself with `gh pr merge --merge --delete-branch`.
   - security-reviewer failed it in any round: label `needs-user-approval` and leave it open. The user approves; S0 merges.
   - Only S0 moves `main`.
8. **Agent memory.** Commit `.claude/agent-memory/` changes with your PRs; on conflict keep both sides.
9. **End of session.** Report: merged IDs, open PRs and their labels, tests added, recurring reviewer FAIL reasons, what is next, risks, questions.

## S0 duties
Triage `contract-change` issues (architect implements, reviewed, merged into `phase0-stack`), fold `question` issues into `docs/open-questions.md`, merge `needs-user-approval` PRs after the user approves, keep `docs/progress.md` current from merged PRs, fast-forward `main` after approvals, run checkpoint audits.
