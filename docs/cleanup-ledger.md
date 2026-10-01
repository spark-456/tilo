# Repo cleanup ledger

Repo-hygiene pass before feature work resumes. Started 2026-09-30 after `git fetch --prune`. One row per open PR, per worktree, and per local branch. "p0s" = `origin/phase0-stack` (e19885e at inventory time). Decisions follow the user's delegation and speed-mode rules; each can be overridden.

## Inventory, 2026-09-30 (before any change)

- Local `phase0-stack` c351361: 1 ahead (agent-memory notes), 46 behind `origin/phase0-stack` (e19885e: #37, #50, #61 merges). `origin/phase0-stack` is 79 ahead of `origin/main` (3a94287), main 0 ahead.
- Main checkout: only `meet-bot/` untracked (72 files; stray ignored `meet-bot/C:/`).
- Orphan directories under `.claude/worktrees/` that are no longer registered worktrees (no git state; leftover `node_modules`): `agent-a02268635cfdc7d63`, `se-feat-P8-01b-treasury`, `se-feat-P8-01c-kill-switch`, `se-feat-P8-07-sandbox-web`, plus `sw-*.log` files. Not touched (see "Needs the user").

### Open PRs

| name | base | ahead/behind | upstream state | CI state | ticket | decision | evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| #53 `feat/FR-HIL-07-idempotent-append` | phase0-stack | +2/-63 | pushed, in sync | pass (6cc237c) | FR-HIL-07 (#46) | merge | code-reviewer PASS, CLEAN; merge was only blocked by an SH-session classifier denial (pause note SH) |
| #62 `feat/P0-08b-camera` | phase0-stack | +19/-0 | pushed, in sync | FAIL: SEC-13 audit only (vitest <3.2.6, GHSA-5xrq-8626-4rwp) | P0-08b (FR-WLD-04) | fix-then-merge | code + qa PASS (pause note SW); fix = bump vitest in apps/web |
| #66 `feat/P0-08b-player` | feat/P0-08b-camera | +38/-0 vs p0s | pushed; worktree `sw-player` has an interrupted, untested vitest bump | FAIL: same SEC-13 audit | P0-08b (FR-WLD-04/10) | fix-then-merge (after #62) | code PASS, qa PASS on 14124c5; size waiver by the user (pause note SW) |
| #60 `feat/FR-AGT-01-roles-parallel-skills` | phase0-stack | +3/-131 local; remote 3f31176 +8/-46 | local is 90 behind remote | pass (3f31176) | FR-AGT-01/02/03 | merge (after one code-review of the merged head) | code r2 PASS on fix delta; qa r2 never ran (paused) |
| #24 `feat/FR-AGT-04-v0-skills` | phase0-stack | remote 51c3eb7; local 586aad1 is 5 ahead | local re-scope not pushed | pass (old head 51c3eb7) | FR-AGT-04 | park | `stuck`: 5 rounds all FAIL, re-scope r3 all FAIL; deferred to Phase B by ADR-0008 (pause note SH) |
| #54 `feat/FR-HIL-09-redaction` | phase0-stack | +3/-46 | pushed; worktree mid-merge of e19885e, conflicts already resolved and staged | pass (a0f3941) but CONFLICTING | FR-HIL-09, SEC-07 | fix-then-merge | code r2 PASS, security r1 PASS (pause note ST) |
| #52 `feat/P8-06b-checks` | phase0-stack | +5/-57 | pushed | no checks reported; CONFLICTING | P8-06b (EFF-07) | fix-then-merge, else park | "parked, needs code review": built, `just check` green locally, never reviewed (PR body) |

### Worktrees

| name | base | ahead/behind | upstream state | CI state | ticket | decision | evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| main checkout (`phase0-stack`) | - | +1/-46 | not pushed | n/a | - | keep | - |
| `agent-a3d4197de3c2bba0b` (`work/FR-AGT-01-a3d4`) | phase0-stack | +5/-70 | none | n/a | FR-AGT-01 | fold memory edit into phase0-stack, then remove | uncommitted security-reviewer memory (MEMORY.md, archive-redactor-gaps.md) from the #37 review (pause note SH) |
| `agent-a6ae34c1da332263e` (`worktree-agent-a6ae…` @3a94287) | main | 0 | none | n/a | - | delete-safe | 3a94287 is `origin/main`; only untracked item is the nested worktree |
| `agent-a6ae…/nested-tests-P8-06b` (`tests/P8-06b`) | phase0-stack | +2/-63 | origin/phase0-stack | n/a | P8-06b | remove worktree, keep branch until #52 decided | clean |
| `agent-aae1d4cd456e97655` (`feat/FR-HIL-07-kill-switches`) | phase0-stack | +3/-63 | tracks the wrong branch (origin/feat/FR-HIL-09-redaction) | n/a | FR-HIL-07 | park: commit WIP, push backup under own name | uncommitted half-built kill-switch redo (pause note ST) |
| `agent-abb8b5e5e07239b59` (`feat/FR-HIL-09-redaction`) | phase0-stack | +3/-46 | in sync | n/a | FR-HIL-09 | finish merge (PR #54) | `MERGE_HEAD` = e19885e, "All conflicts fixed but you are still merging" |
| `lucid-kilby-06f5a8` (detached 26bed7c) | phase0-stack | 0 | n/a | n/a | SEC-13 | delete-safe | 26bed7c contained in p0s (`git branch --contains`), clean |
| `sw-player` (`feat/P0-08b-player`) | feat/P0-08b-camera | see #66 | in sync | n/a | P0-08b | keep until #66 merges | uncommitted vitest bump in package.json + pnpm-lock (pause note SW: discard here, redo in camera) |

### Local branches (128)

"delete-safe" = every commit is already in `origin/phase0-stack`. "park" = unmerged commits, all already reachable from an `origin` ref; kept, re-checked in task 6 after PR merges. "park (push backup)" = has commits on no remote; pushed to `origin/<same name>` in task 6.

| name | base | ahead/behind | upstream state | CI state | ticket | decision | evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `claude/lucid-kilby-06f5a8` | phase0-stack | +0/-244 vs p0s | none | n/a | - | delete-safe | `git log origin/phase0-stack..claude/lucid-kilby-06f5a8` empty |
| `feat/CC-SE-contracts-se` | phase0-stack | +0/-65 vs p0s | none | n/a | CC-SE- | delete-safe | `git log origin/phase0-stack..feat/CC-SE-contracts-se` empty |
| `feat/CC-SH-contracts-sh` | phase0-stack | +0/-226 vs p0s | none | n/a | CC-SH- | delete-safe | `git log origin/phase0-stack..feat/CC-SH-contracts-sh` empty |
| `feat/CC-SP-47-safety-provider` | phase0-stack | +2/-46 vs p0s | none | n/a | CC-SP-47 | park | 2 unmerged; all reachable from an origin ref (`git rev-list feat/CC-SP-47-safety-provider --not --remotes` empty) |
| `feat/CC-SP-64-grant-budget-tier` | phase0-stack | +1/-46 vs p0s | none | n/a | CC-SP-64 | park | 1 unmerged; all reachable from an origin ref (`git rev-list feat/CC-SP-64-grant-budget-tier --not --remotes` empty) |
| `feat/FR-AGT-01-roles-parallel-skills` | phase0-stack | +3/-131 vs p0s | origin/feat/FR-AGT-01-roles-parallel-skills [behind 90] | n/a | FR-AGT-01 | see PR #60 | open PR head |
| `feat/FR-AGT-04-v0-skills` | phase0-stack | +11/-270 vs p0s | origin/feat/FR-AGT-04-v0-skills [ahead 5] | n/a | FR-AGT-04 | see PR #24 | open PR head |
| `feat/FR-AGT-11-outbox` | phase0-stack | +0/-99 vs p0s | origin/feat/FR-AGT-11-outbox [gone] | n/a | FR-AGT-11 | delete-safe | `git log origin/phase0-stack..feat/FR-AGT-11-outbox` empty |
| `feat/FR-HIL-01-cards` | phase0-stack | +3/-202 vs p0s | origin/feat/FR-HIL-01-cards | n/a | FR-HIL-01 | park | 3 unmerged; all reachable from an origin ref (`git rev-list feat/FR-HIL-01-cards --not --remotes` empty) |
| `feat/FR-HIL-07-idempotent-append` | phase0-stack | +2/-63 vs p0s | origin/feat/FR-HIL-07-idempotent-append | n/a | FR-HIL-07 | see PR #53 | open PR head |
| `feat/FR-HIL-07-kill-switch-redaction` | phase0-stack | +38/-70 vs p0s | origin/feat/FR-HIL-07-kill-switch-redaction | n/a | FR-HIL-07 | park | 38 unmerged; all reachable from an origin ref (`git rev-list feat/FR-HIL-07-kill-switch-redaction --not --remotes` empty) |
| `feat/FR-HIL-07-kill-switches` | phase0-stack | +3/-63 vs p0s | origin/feat/FR-HIL-09-redaction [ahead 1, behind 18] | n/a | FR-HIL-07 | park (push backup) | 3 unmerged, 1 on no remote |
| `feat/FR-HIL-09-redaction` | phase0-stack | +3/-46 vs p0s | origin/feat/FR-HIL-09-redaction | n/a | FR-HIL-09 | see PR #54 | open PR head |
| `feat/FR-INT-01-intake` | phase0-stack | +0/-8 vs p0s | origin/feat/FR-INT-01-intake [gone] | n/a | FR-INT-01 | delete-safe | `git log origin/phase0-stack..feat/FR-INT-01-intake` empty |
| `feat/FR-INT-03-brief` | phase0-stack | +0/-1 vs p0s | origin/feat/FR-INT-03-brief [gone] | n/a | FR-INT-03 | delete-safe | `git log origin/phase0-stack..feat/FR-INT-03-brief` empty |
| `feat/FR-INT-06-approaches` | phase0-stack | +3/-0 vs p0s | origin/feat/FR-INT-06-approaches | n/a | FR-INT-06 | park | 3 unmerged; all reachable from an origin ref (`git rev-list feat/FR-INT-06-approaches --not --remotes` empty) |
| `feat/FR-INT-09-plangraph` | phase0-stack | +3/-0 vs p0s | origin/feat/FR-INT-09-plangraph | n/a | FR-INT-09 | park | 3 unmerged; all reachable from an origin ref (`git rev-list feat/FR-INT-09-plangraph --not --remotes` empty) |
| `feat/FR-MEM-04-raw-archive` | phase0-stack | +0/-22 vs p0s | origin/feat/FR-MEM-04-raw-archive [gone] | n/a | FR-MEM-04 | delete-safe | `git log origin/phase0-stack..feat/FR-MEM-04-raw-archive` empty |
| `feat/P0-01-scaffold` | phase0-stack | +0/-304 vs p0s | none | n/a | P0-01 | delete-safe | `git log origin/phase0-stack..feat/P0-01-scaffold` empty |
| `feat/P0-02-core-contracts` | phase0-stack | +0/-295 vs p0s | none | n/a | P0-02 | delete-safe | `git log origin/phase0-stack..feat/P0-02-core-contracts` empty |
| `feat/P0-02b-provider-endpoint-fields` | phase0-stack | +0/-267 vs p0s | none | n/a | P0-02b | delete-safe | `git log origin/phase0-stack..feat/P0-02b-provider-endpoint-fields` empty |
| `feat/P0-03-event-contract` | phase0-stack | +0/-233 vs p0s | none | n/a | P0-03 | delete-safe | `git log origin/phase0-stack..feat/P0-03-event-contract` empty |
| `feat/P0-04-provider-config` | phase0-stack | +0/-274 vs p0s | none | n/a | P0-04 | delete-safe | `git log origin/phase0-stack..feat/P0-04-provider-config` empty |
| `feat/P0-05-provider-adapters` | phase0-stack | +0/-252 vs p0s | none | n/a | P0-05 | delete-safe | `git log origin/phase0-stack..feat/P0-05-provider-adapters` empty |
| `feat/P0-06-role-router` | phase0-stack | +0/-183 vs p0s | none | n/a | P0-06 | delete-safe | `git log origin/phase0-stack..feat/P0-06-role-router` empty |
| `feat/P0-08a-web-shell` | phase0-stack | +6/-301 vs p0s | none | n/a | P0-08a | park | 6 unmerged; all reachable from an origin ref (`git rev-list feat/P0-08a-web-shell --not --remotes` empty) |
| `feat/P0-08b-camera` | phase0-stack | +19/-0 vs p0s | origin/feat/P0-08b-camera | n/a | P0-08b | see PR #62 | open PR head |
| `feat/P0-08b-player` | phase0-stack | +38/-0 vs p0s | origin/feat/P0-08b-player | n/a | P0-08b | see PR #66 | open PR head |
| `feat/P0-09-harness-skeleton` | phase0-stack | +1/-177 vs p0s | origin/feat/P0-09-harness-skeleton [gone] | n/a | P0-09 | park (push backup) | 1 unmerged, 1 on no remote |
| `feat/P4-01-policy-engine` | phase0-stack | +0/-132 vs p0s | origin/feat/P4-01-policy-engine [gone] | n/a | P4-01 | delete-safe | `git log origin/phase0-stack..feat/P4-01-policy-engine` empty |
| `feat/P8-01a-price-book` | phase0-stack | +0/-237 vs p0s | origin/feat/P8-01a-price-book [gone] | n/a | P8-01a | delete-safe | `git log origin/phase0-stack..feat/P8-01a-price-book` empty |
| `feat/P8-01b-treasury` | phase0-stack | +0/-192 vs p0s | origin/feat/P8-01b-treasury [gone] | n/a | P8-01b | delete-safe | `git log origin/phase0-stack..feat/P8-01b-treasury` empty |
| `feat/P8-06-eval-harness` | phase0-stack | +10/-253 vs p0s | origin/feat/P8-06-eval-harness | n/a | P8-06 | park | 10 unmerged; all reachable from an origin ref (`git rev-list feat/P8-06-eval-harness --not --remotes` empty) |
| `feat/P8-06a-eval-cases` | phase0-stack | +1/-226 vs p0s | origin/feat/P8-06a-eval-cases [gone] | n/a | P8-06a | park (push backup) | 1 unmerged, 1 on no remote |
| `feat/P8-06b-checks` | phase0-stack | +5/-57 vs p0s | origin/feat/P8-06b-checks | n/a | P8-06b | see PR #52 | open PR head |
| `feat/P8-07-sandbox-web` | phase0-stack | +0/-73 vs p0s | origin/feat/P8-07-sandbox-web [gone] | n/a | P8-07 | delete-safe | `git log origin/phase0-stack..feat/P8-07-sandbox-web` empty |
| `feat/SEC-13-google-aq-key-pattern` | phase0-stack | +0/-243 vs p0s | none | n/a | SEC-13 | delete-safe | `git log origin/phase0-stack..feat/SEC-13-google-aq-key-pattern` empty |
| `fix/FR-MEM-05-split-keys` | phase0-stack | +0/-59 vs p0s | none | n/a | FR-MEM-05 | delete-safe | `git log origin/phase0-stack..fix/FR-MEM-05-split-keys` empty |
| `int/p0-08b-base` | phase0-stack | +8/-260 vs p0s | none | n/a | - | park | 8 unmerged; all reachable from an origin ref (`git rev-list int/p0-08b-base --not --remotes` empty) |
| `main` | phase0-stack | +0/-79 vs p0s | origin/main | n/a | - | keep | long-lived branch |
| `phase0-stack` | phase0-stack | +1/-46 vs p0s | none | n/a | - | keep | long-lived branch |
| `phase0-stack-local` | phase0-stack | +0/-264 vs p0s | none | n/a | - | delete-safe | `git log origin/phase0-stack..phase0-stack-local` empty |
| `sh/base` | phase0-stack | +1/-258 vs p0s | origin/phase0-stack [ahead 1, behind 258] | n/a | - | park (push backup) | 1 unmerged, 1 on no remote |
| `split/FR-MEM-04` | phase0-stack | +0/-56 vs p0s | origin/feat/FR-MEM-04-raw-archive [gone] | n/a | FR-MEM-04 | delete-safe | `git log origin/phase0-stack..split/FR-MEM-04` empty |
| `tests/CC-SE` | phase0-stack | +0/-196 vs p0s | none | n/a | CC-SE | delete-safe | `git log origin/phase0-stack..tests/CC-SE` empty |
| `tests/CC-SP-47` | phase0-stack | +1/-46 vs p0s | none | n/a | CC-SP-47 | park | 1 unmerged; all reachable from an origin ref (`git rev-list tests/CC-SP-47 --not --remotes` empty) |
| `tests/CC-SP-64` | phase0-stack | +1/-46 vs p0s | origin/phase0-stack [ahead 1, behind 46] | n/a | CC-SP-64 | park | 1 unmerged; all reachable from an origin ref (`git rev-list tests/CC-SP-64 --not --remotes` empty) |
| `tests/FR-AGT-01` | phase0-stack | +1/-176 vs p0s | origin/phase0-stack [ahead 1, behind 176] | n/a | FR-AGT-01 | park | 1 unmerged; all reachable from an origin ref (`git rev-list tests/FR-AGT-01 --not --remotes` empty) |
| `tests/FR-AGT-04` | phase0-stack | +2/-270 vs p0s | origin/phase0-stack [ahead 2, behind 270] | n/a | FR-AGT-04 | park (push backup) | 2 unmerged, 1 on no remote |
| `tests/FR-HIL-01` | phase0-stack | +1/-248 vs p0s | none | n/a | FR-HIL-01 | park | 1 unmerged; all reachable from an origin ref (`git rev-list tests/FR-HIL-01 --not --remotes` empty) |
| `tests/FR-HIL-07` | phase0-stack | +4/-257 vs p0s | none | n/a | FR-HIL-07 | park (push backup) | 4 unmerged, 1 on no remote |
| `tests/FR-HIL-07-idempotent-append` | phase0-stack | +1/-63 vs p0s | origin/phase0-stack [ahead 1, behind 63] | n/a | FR-HIL-07 | park | 1 unmerged; all reachable from an origin ref (`git rev-list tests/FR-HIL-07-idempotent-append --not --remotes` empty) |
| `tests/FR-HIL-07-r2` | phase0-stack | +6/-257 vs p0s | none | n/a | FR-HIL-07 | park (push backup) | 6 unmerged, 1 on no remote |
| `tests/FR-HIL-07-r3` | phase0-stack | +6/-257 vs p0s | none | n/a | FR-HIL-07 | park | 6 unmerged; all reachable from an origin ref (`git rev-list tests/FR-HIL-07-r3 --not --remotes` empty) |
| `tests/FR-HIL-07-r4` | phase0-stack | +8/-257 vs p0s | none | n/a | FR-HIL-07 | park | 8 unmerged; all reachable from an origin ref (`git rev-list tests/FR-HIL-07-r4 --not --remotes` empty) |
| `tests/FR-HIL-07-r5` | phase0-stack | +10/-257 vs p0s | none | n/a | FR-HIL-07 | park | 10 unmerged; all reachable from an origin ref (`git rev-list tests/FR-HIL-07-r5 --not --remotes` empty) |
| `tests/FR-HIL-07-r6` | phase0-stack | +13/-257 vs p0s | none | n/a | FR-HIL-07 | park | 13 unmerged; all reachable from an origin ref (`git rev-list tests/FR-HIL-07-r6 --not --remotes` empty) |
| `tests/FR-HIL-07-r7` | phase0-stack | +15/-257 vs p0s | none | n/a | FR-HIL-07 | park | 15 unmerged; all reachable from an origin ref (`git rev-list tests/FR-HIL-07-r7 --not --remotes` empty) |
| `tests/FR-HIL-07-r8` | phase0-stack | +39/-70 vs p0s | origin/tests/FR-HIL-07-r8 | n/a | FR-HIL-07 | park | 39 unmerged; all reachable from an origin ref (`git rev-list tests/FR-HIL-07-r8 --not --remotes` empty) |
| `tests/FR-INT-01` | phase0-stack | +0/-77 vs p0s | origin/phase0-stack [behind 77] | n/a | FR-INT-01 | delete-safe | `git log origin/phase0-stack..tests/FR-INT-01` empty |
| `tests/FR-INT-03` | phase0-stack | +0/-64 vs p0s | none | n/a | FR-INT-03 | delete-safe | `git log origin/phase0-stack..tests/FR-INT-03` empty |
| `tests/FR-INT-06` | phase0-stack | +1/-48 vs p0s | none | n/a | FR-INT-06 | park | 1 unmerged; all reachable from an origin ref (`git rev-list tests/FR-INT-06 --not --remotes` empty) |
| `tests/FR-INT-09` | phase0-stack | +1/-48 vs p0s | none | n/a | FR-INT-09 | park | 1 unmerged; all reachable from an origin ref (`git rev-list tests/FR-INT-09 --not --remotes` empty) |
| `tests/FR-MEM-04` | phase0-stack | +0/-262 vs p0s | origin/phase0-stack [behind 262] | n/a | FR-MEM-04 | delete-safe | `git log origin/phase0-stack..tests/FR-MEM-04` empty |
| `tests/P0-08a` | phase0-stack | +1/-301 vs p0s | none | n/a | P0-08a | park | 1 unmerged; all reachable from an origin ref (`git rev-list tests/P0-08a --not --remotes` empty) |
| `tests/P0-08b-camera` | phase0-stack | +10/-260 vs p0s | origin/int/p0-08b-base [ahead 2] | n/a | P0-08b | park | 10 unmerged; all reachable from an origin ref (`git rev-list tests/P0-08b-camera --not --remotes` empty) |
| `tests/P0-08b-player` | phase0-stack | +10/-260 vs p0s | origin/int/p0-08b-base [ahead 2] | n/a | P0-08b | park | 10 unmerged; all reachable from an origin ref (`git rev-list tests/P0-08b-player --not --remotes` empty) |
| `tests/P8-01` | phase0-stack | +1/-265 vs p0s | origin/phase0-stack [ahead 1, behind 265] | n/a | P8-01 | park (push backup) | 1 unmerged, 1 on no remote |
| `tests/P8-06` | phase0-stack | +2/-254 vs p0s | origin/phase0-stack [ahead 2, behind 254] | n/a | P8-06 | park | 2 unmerged; all reachable from an origin ref (`git rev-list tests/P8-06 --not --remotes` empty) |
| `tests/P8-06b` | phase0-stack | +2/-63 vs p0s | origin/phase0-stack [ahead 2, behind 63] | n/a | P8-06b | park | 2 unmerged; all reachable from an origin ref (`git rev-list tests/P8-06b --not --remotes` empty) |
| `tests/P8-07` | phase0-stack | +0/-234 vs p0s | origin/phase0-stack [behind 234] | n/a | P8-07 | delete-safe | `git log origin/phase0-stack..tests/P8-07` empty |
| `work/FR-AGT-01-a3d4` | phase0-stack | +5/-70 vs p0s | none | n/a | FR-AGT-01 | park | 5 unmerged; all reachable from an origin ref (`git rev-list work/FR-AGT-01-a3d4 --not --remotes` empty) |
| `work/FR-AGT-01-b` | phase0-stack | +7/-46 vs p0s | none | n/a | FR-AGT-01 | park | 7 unmerged; all reachable from an origin ref (`git rev-list work/FR-AGT-01-b --not --remotes` empty) |
| `work/FR-AGT-01-fix1` | phase0-stack | +8/-46 vs p0s | origin/feat/FR-AGT-01-roles-parallel-skills | n/a | FR-AGT-01 | park | 8 unmerged; all reachable from an origin ref (`git rev-list work/FR-AGT-01-fix1 --not --remotes` empty) |
| `work/FR-HIL-07-a46f` | phase0-stack | +38/-70 vs p0s | origin/feat/FR-HIL-07-kill-switch-redaction | n/a | FR-HIL-07 | park | 38 unmerged; all reachable from an origin ref (`git rev-list work/FR-HIL-07-a46f --not --remotes` empty) |
| `worktree-agent-a07d26c72e3ea049c` | phase0-stack | +0/-287 vs p0s | none | n/a | - | delete-safe | `git log origin/phase0-stack..worktree-agent-a07d26c72e3ea049c` empty |
| `worktree-agent-a200af44d20b9b898` | phase0-stack | +0/-79 vs p0s | none | n/a | - | delete-safe | `git log origin/phase0-stack..worktree-agent-a200af44d20b9b898` empty |
| `worktree-agent-a2c47c63a901fe631` | phase0-stack | +0/-79 vs p0s | none | n/a | - | delete-safe | `git log origin/phase0-stack..worktree-agent-a2c47c63a901fe631` empty |
| `worktree-agent-a3bbaea2214eff6fc` | phase0-stack | +0/-79 vs p0s | none | n/a | - | delete-safe | `git log origin/phase0-stack..worktree-agent-a3bbaea2214eff6fc` empty |
| `worktree-agent-a3d4197de3c2bba0b` | phase0-stack | +0/-79 vs p0s | none | n/a | - | delete-safe | `git log origin/phase0-stack..worktree-agent-a3d4197de3c2bba0b` empty |
| `worktree-agent-a46f445d1497dadf1` | phase0-stack | +0/-79 vs p0s | none | n/a | - | delete-safe | `git log origin/phase0-stack..worktree-agent-a46f445d1497dadf1` empty |
| `worktree-agent-a529e48c19fdaa47b` | phase0-stack | +0/-79 vs p0s | none | n/a | - | delete-safe | `git log origin/phase0-stack..worktree-agent-a529e48c19fdaa47b` empty |
| `worktree-agent-a686113f82622348b` | phase0-stack | +0/-79 vs p0s | none | n/a | - | delete-safe | `git log origin/phase0-stack..worktree-agent-a686113f82622348b` empty |
| `worktree-agent-a6ae34c1da332263e` | phase0-stack | +0/-79 vs p0s | none | n/a | - | delete-safe | `git log origin/phase0-stack..worktree-agent-a6ae34c1da332263e` empty |
| `worktree-agent-a7d388777d4265254` | phase0-stack | +0/-79 vs p0s | none | n/a | - | delete-safe | `git log origin/phase0-stack..worktree-agent-a7d388777d4265254` empty |
| `worktree-agent-a8e8db588238c061e` | phase0-stack | +0/-287 vs p0s | none | n/a | - | delete-safe | `git log origin/phase0-stack..worktree-agent-a8e8db588238c061e` empty |
| `worktree-agent-a91daad4aad12f322` | phase0-stack | +0/-79 vs p0s | none | n/a | - | delete-safe | `git log origin/phase0-stack..worktree-agent-a91daad4aad12f322` empty |
| `worktree-agent-a97a83623dbaf006a` | phase0-stack | +0/-79 vs p0s | none | n/a | - | delete-safe | `git log origin/phase0-stack..worktree-agent-a97a83623dbaf006a` empty |
| `worktree-agent-a99448f1e1081a438` | phase0-stack | +0/-79 vs p0s | none | n/a | - | delete-safe | `git log origin/phase0-stack..worktree-agent-a99448f1e1081a438` empty |
| `worktree-agent-a9b675d4d9753bdc0` | phase0-stack | +0/-248 vs p0s | none | n/a | - | delete-safe | `git log origin/phase0-stack..worktree-agent-a9b675d4d9753bdc0` empty |
| `worktree-agent-aa4b1f15ba3585e90` | phase0-stack | +0/-79 vs p0s | none | n/a | - | delete-safe | `git log origin/phase0-stack..worktree-agent-aa4b1f15ba3585e90` empty |
| `worktree-agent-aa734d1baec1d8218` | phase0-stack | +0/-79 vs p0s | none | n/a | - | delete-safe | `git log origin/phase0-stack..worktree-agent-aa734d1baec1d8218` empty |
| `worktree-agent-aae1d4cd456e97655` | phase0-stack | +0/-79 vs p0s | none | n/a | - | delete-safe | `git log origin/phase0-stack..worktree-agent-aae1d4cd456e97655` empty |
| `worktree-agent-abb8b5e5e07239b59` | phase0-stack | +0/-79 vs p0s | none | n/a | - | delete-safe | `git log origin/phase0-stack..worktree-agent-abb8b5e5e07239b59` empty |
| `worktree-agent-acf6a571c1516be2b` | phase0-stack | +0/-79 vs p0s | none | n/a | - | delete-safe | `git log origin/phase0-stack..worktree-agent-acf6a571c1516be2b` empty |
| `worktree-agent-ad289386bd3cd8b68` | phase0-stack | +0/-79 vs p0s | none | n/a | - | delete-safe | `git log origin/phase0-stack..worktree-agent-ad289386bd3cd8b68` empty |
| `worktree-agent-ae440af5a9f8c13c2` | phase0-stack | +0/-287 vs p0s | none | n/a | - | delete-safe | `git log origin/phase0-stack..worktree-agent-ae440af5a9f8c13c2` empty |
| `worktree-agent-ae56d20a879fa8bc7` | phase0-stack | +0/-79 vs p0s | none | n/a | - | delete-safe | `git log origin/phase0-stack..worktree-agent-ae56d20a879fa8bc7` empty |
| `worktree-agent-aeebade14e07308c1` | phase0-stack | +0/-79 vs p0s | none | n/a | - | delete-safe | `git log origin/phase0-stack..worktree-agent-aeebade14e07308c1` empty |
| `worktree-wf_121e5ec4-470-1` | phase0-stack | +0/-302 vs p0s | none | n/a | - | delete-safe | `git log origin/phase0-stack..worktree-wf_121e5ec4-470-1` empty |
| `worktree-wf_121e5ec4-470-2` | phase0-stack | +0/-301 vs p0s | none | n/a | - | delete-safe | `git log origin/phase0-stack..worktree-wf_121e5ec4-470-2` empty |
| `worktree-wf_1794764e-415-1` | phase0-stack | +0/-198 vs p0s | none | n/a | - | delete-safe | `git log origin/phase0-stack..worktree-wf_1794764e-415-1` empty |
| `worktree-wf_1794764e-415-2` | phase0-stack | +0/-197 vs p0s | none | n/a | - | delete-safe | `git log origin/phase0-stack..worktree-wf_1794764e-415-2` empty |
| `worktree-wf_337a0268-ca2-1` | phase0-stack | +0/-79 vs p0s | none | n/a | - | delete-safe | `git log origin/phase0-stack..worktree-wf_337a0268-ca2-1` empty |
| `worktree-wf_337a0268-ca2-2` | phase0-stack | +0/-79 vs p0s | none | n/a | - | delete-safe | `git log origin/phase0-stack..worktree-wf_337a0268-ca2-2` empty |
| `worktree-wf_58845931-3ff-6` | phase0-stack | +0/-301 vs p0s | none | n/a | - | delete-safe | `git log origin/phase0-stack..worktree-wf_58845931-3ff-6` empty |
| `worktree-wf_58845931-3ff-7` | phase0-stack | +0/-301 vs p0s | none | n/a | - | delete-safe | `git log origin/phase0-stack..worktree-wf_58845931-3ff-7` empty |
| `worktree-wf_5a52b6ad-906-1` | phase0-stack | +0/-287 vs p0s | none | n/a | - | delete-safe | `git log origin/phase0-stack..worktree-wf_5a52b6ad-906-1` empty |
| `worktree-wf_5a52b6ad-906-2` | phase0-stack | +0/-287 vs p0s | none | n/a | - | delete-safe | `git log origin/phase0-stack..worktree-wf_5a52b6ad-906-2` empty |
| `worktree-wf_6d0cec9d-5ab-1` | phase0-stack | +0/-312 vs p0s | none | n/a | - | delete-safe | `git log origin/phase0-stack..worktree-wf_6d0cec9d-5ab-1` empty |
| `worktree-wf_6d0cec9d-5ab-2` | phase0-stack | +0/-312 vs p0s | none | n/a | - | delete-safe | `git log origin/phase0-stack..worktree-wf_6d0cec9d-5ab-2` empty |
| `worktree-wf_6d0cec9d-5ab-3` | phase0-stack | +0/-310 vs p0s | none | n/a | - | delete-safe | `git log origin/phase0-stack..worktree-wf_6d0cec9d-5ab-3` empty |
| `worktree-wf_6d0cec9d-5ab-4` | phase0-stack | +0/-310 vs p0s | none | n/a | - | delete-safe | `git log origin/phase0-stack..worktree-wf_6d0cec9d-5ab-4` empty |
| `worktree-wf_6d681674-391-6` | phase0-stack | +0/-246 vs p0s | none | n/a | - | delete-safe | `git log origin/phase0-stack..worktree-wf_6d681674-391-6` empty |
| `worktree-wf_6d681674-391-7` | phase0-stack | +0/-245 vs p0s | none | n/a | - | delete-safe | `git log origin/phase0-stack..worktree-wf_6d681674-391-7` empty |
| `worktree-wf_7f6317cf-1fc-1` | phase0-stack | +0/-287 vs p0s | none | n/a | - | delete-safe | `git log origin/phase0-stack..worktree-wf_7f6317cf-1fc-1` empty |
| `worktree-wf_7f6317cf-1fc-2` | phase0-stack | +0/-287 vs p0s | none | n/a | - | delete-safe | `git log origin/phase0-stack..worktree-wf_7f6317cf-1fc-2` empty |
| `worktree-wf_7f6317cf-1fc-3` | phase0-stack | +0/-287 vs p0s | none | n/a | - | delete-safe | `git log origin/phase0-stack..worktree-wf_7f6317cf-1fc-3` empty |
| `worktree-wf_7f6317cf-1fc-4` | phase0-stack | +0/-287 vs p0s | none | n/a | - | delete-safe | `git log origin/phase0-stack..worktree-wf_7f6317cf-1fc-4` empty |
| `worktree-wf_865cc9ed-d8b-2` | phase0-stack | +0/-287 vs p0s | none | n/a | - | delete-safe | `git log origin/phase0-stack..worktree-wf_865cc9ed-d8b-2` empty |
| `worktree-wf_865cc9ed-d8b-5` | phase0-stack | +0/-287 vs p0s | none | n/a | - | delete-safe | `git log origin/phase0-stack..worktree-wf_865cc9ed-d8b-5` empty |
| `worktree-wf_95559740-de2-1` | phase0-stack | +0/-79 vs p0s | none | n/a | - | delete-safe | `git log origin/phase0-stack..worktree-wf_95559740-de2-1` empty |
| `worktree-wf_95559740-de2-2` | phase0-stack | +0/-79 vs p0s | none | n/a | - | delete-safe | `git log origin/phase0-stack..worktree-wf_95559740-de2-2` empty |
| `worktree-wf_c3f75cad-25a-1` | phase0-stack | +0/-287 vs p0s | none | n/a | - | delete-safe | `git log origin/phase0-stack..worktree-wf_c3f75cad-25a-1` empty |
| `worktree-wf_c3f75cad-25a-2` | phase0-stack | +0/-287 vs p0s | none | n/a | - | delete-safe | `git log origin/phase0-stack..worktree-wf_c3f75cad-25a-2` empty |
| `worktree-wf_c3f75cad-25a-4` | phase0-stack | +0/-287 vs p0s | none | n/a | - | delete-safe | `git log origin/phase0-stack..worktree-wf_c3f75cad-25a-4` empty |
| `worktree-wf_e0b63e16-e8e-1` | phase0-stack | +0/-287 vs p0s | none | n/a | - | delete-safe | `git log origin/phase0-stack..worktree-wf_e0b63e16-e8e-1` empty |
| `worktree-wf_e0b63e16-e8e-2` | phase0-stack | +0/-287 vs p0s | none | n/a | - | delete-safe | `git log origin/phase0-stack..worktree-wf_e0b63e16-e8e-2` empty |

## Decisions and actions log

1. **Inventory** (read-only): this file, b06cab4.
2. **Loose files**: none besides this ledger. The stranded security-reviewer note in worktree `agent-a3d4197de3c2bba0b` (newer than origin's copy) was carried to phase0-stack in 32d15ad. The worktree copy was then discarded after a byte-identity check against `origin/phase0-stack`.
3. **meet-bot baseline**: `chore/meet-bot-baseline` = 000b424 (end-of-file-fixer excludes `meet-bot/tests/fixtures/`, following the read-only-data precedent of the top-level `exclude`; secret scans still run) + 70e8200 (68 files, `Req: VA-00`, fixture bytes unchanged), pushed. It was merged into phase0-stack (36703e6), then **reverted** (32af67b) for two reasons:
   - `meet-bot/` holds Gemini model ids, so `scripts/lint_model_ids.py` (PL-01, part of `just lint`) fails.
   - Its tests need their own rootdir, so root pytest fails to collect them.

   Fixing either needs a meet-bot code change or a PL-01 rule change, and both are the user's call. The working copy stays on disk untracked, byte-identical to 70e8200. To land it later, run `git revert 32af67b` on phase0-stack once the ids live in `config/` or an ADR scopes meet-bot out of PL-01 and root pytest. Git reports the branch as merged because of the revert, so it is kept deliberately.
   - The ignore line `C:/` never matched the stray folder: Git Bash stores it as `C` + U+F03A. `/C/` was added to `meet-bot/.gitignore`.
   - Deleting the stray folder was denied by the auto-mode classifier (see Needs the user).
4. **Origin sync**: phase0-stack merged `origin/phase0-stack` (a645ddf; qa-breaker MEMORY.md union). Gate steps green: 2059 passed. `--ignore=meet-bot` was passed on the command line only, because the untracked `meet-bot/` in this checkout is otherwise collected. Pushed 32af67b.
5. **PRs** (lowest risk first). The base was merged in, ticket tests were run locally, CI (`just check`) ran on the final head, and one code-reviewer round ran on the final head:

   | PR | final head | fix pass | review on final head | CI | result |
   | --- | --- | --- | --- | --- | --- |
   | #53 FR-HIL-07 idempotent append | cafaf22 | none | code PASS | pass | merged 0a1fb7b |
   | #62 P0-08b camera | 5a8c2f3 | vitest ^2.1.5 -> ^3.2.7 (SEC-13, GHSA-5xrq-8626-4rwp) | code PASS | pass | merged 13d82e0 |
   | #66 P0-08b player | c775d01 | merged camera + base; retargeted to phase0-stack | code PASS | pass | merged ead0bd7 |
   | #54 FR-HIL-09/SEC-07 redaction | 3e0748b | concluded the paused conflict merge + base | code PASS, security re-check PASS | pass | merged ccafdc5 |
   | #52 P8-06b eval checks | 70dcd2b | r1 FAIL (repeated check reused first args; ground-truth check passed with no ground truth) fixed in 70dcd2b | code PASS | pass | merged 3e0d4ad |
   | #60 FR-AGT-01/02/03 executor | 52283eb | r1 FAIL (runner self-cancel hung the run; writer-rejected handoff aborted it) fixed in e58a815; 52283eb re-wraps harness CLAUDE.md to the 40-line cap | code PASS (incl. 52283eb) | pass | merged c4ac3f7 |
   | #24 FR-AGT-04 skills | 586aad1 (backup push) | none | n/a | - | **parked**: 5 rounds + re-scope r3 all FAIL; Phase B per ADR-0008; redo in #70 |

   Follow-up issues filed: #69 (vite >= 6.4.3), #70 (#24 redo), #71 (services/api, including `/intake` taking no principal), #72 (eval checks), #73 (executor).
6. **Sweep**
   - Backup pushes under their own names (non-force), for commits on no remote: `feat/FR-HIL-07-kill-switches` (WIP committed as 42d4789), `feat/P0-09-harness-skeleton`, `feat/P8-06a-eval-cases`, `sh/base`, `tests/FR-HIL-07`, `tests/FR-HIL-07-r2`, `tests/P8-01`. `feat/FR-AGT-04-v0-skills` was fast-forwarded as part of #24.
   - Local branches: 97 deleted with `git branch -d`. Proof for each: `git rev-list --count origin/phase0-stack..<b>` = 0. `tests/P0-08b-camera` and `tests/P0-08b-player` needed `--unset-upstream` first (stale upstream `int/p0-08b-base`).
   - Remote branches: 7 merged PR heads deleted: #60, #53, #54, #62, #66, #44 and #52.
   - Worktrees removed without `--force`: `agent-a3d4…`, `agent-a6ae…` and its nested `nested-tests-P8-06b`, `agent-abb8…`, `lucid-kilby-06f5a8`, `sw-player`, `cleanup-cam`, `cleanup-p806b`. On Windows, git deregistered them but could not delete every directory (locked `node_modules`/`.venv` files). Those leftovers are in Needs the user.
   - The interrupted vitest bump in `sw-player` was saved as a diff in the session scratchpad and discarded, per the SW pause note; the bump was redone on camera.
7. **phase0-stack -> main**: PR #74 merged as 8f89fe2 (`gh pr merge --merge`). All gate conditions held:
   - Every step of `just check` green locally on b449964: contracts, format, lint, model ids, mypy, tsc, 2188 Python tests and 50 web tests (`--ignore=meet-bot`, as in step 4). CI `just check` green on #74.
   - Every PR merged here passed review on its final commit, and #24 is untouched.
   - No open security flag, and no blocking row in docs/open-questions.md.

   `origin/main` contains b449964, and `git diff b449964 origin/main` is empty. This ledger commit lands on phase0-stack after that, so main is one docs commit behind until the next promotion.
8. **Final check**: `git fetch --prune` done. Both remaining worktrees are clean apart from the untracked `meet-bot/` in the main checkout. The only open PR is #24, which matches the list below.

## Final state

### Open PRs
- None. #24 was merged from the user's account at 19:26 UTC (d4ac3b5), after this cleanup. With the user's OK it was reverted on phase0-stack on 2026-10-01 (3d37770; the tree is identical to bc66670). The FR-AGT-04 redo stays in #70.

### Worktrees
- The main checkout on `phase0-stack`. Its only untracked item is `meet-bot/`, which stays uncommitted until the PL-01 decision.
- `.claude/worktrees/agent-aae1d4cd456e97655` on `feat/FR-HIL-07-kill-switches` @ 42d4789: clean, pushed, parked for the ST kill-switch redo.
- `.claude/worktrees/meet-bot` on `chore/meet-bot-baseline`: the meet-bot build worktree (added 2026-10-01). meet-bot work branches from here and merges back here, not into phase0-stack, until an integration ticket moves its model calls into `packages/providers` and its model ids into `config/`.

### Local branches (32)
"+N" = commits not in `origin/phase0-stack`. Every branch is on origin under its own name, or reachable from another origin ref.

| name | head | unmerged | on origin |
| --- | --- | --- | --- |
| `chore/meet-bot-baseline` | 70e8200 | +0 | origin/chore/meet-bot-baseline |
| `feat/CC-SP-47-safety-provider` | 4b01dd0 | +2 | origin/feat/CC-SP-47-safety-provider |
| `feat/CC-SP-64-grant-budget-tier` | e96094a | +1 | reachable from other origin refs |
| `feat/FR-AGT-04-v0-skills` | 586aad1 | +11 | origin/feat/FR-AGT-04-v0-skills |
| `feat/FR-HIL-01-cards` | ea775d2 | +3 | origin/feat/FR-HIL-01-cards |
| `feat/FR-HIL-07-kill-switch-redaction` | 87d0d5d | +38 | origin/feat/FR-HIL-07-kill-switch-redaction |
| `feat/FR-HIL-07-kill-switches` | 42d4789 | +2 | origin/feat/FR-HIL-07-kill-switches |
| `feat/FR-INT-06-approaches` | 75960dd | +3 | origin/feat/FR-INT-06-approaches |
| `feat/FR-INT-09-plangraph` | 81b44c8 | +3 | origin/feat/FR-INT-09-plangraph |
| `feat/P0-09-harness-skeleton` | 23ab975 | +1 | origin/feat/P0-09-harness-skeleton |
| `feat/P8-06-eval-harness` | f4b7713 | +10 | origin/feat/P8-06-eval-harness |
| `feat/P8-06a-eval-cases` | 7123012 | +1 | origin/feat/P8-06a-eval-cases |
| `main` | 3a94287 | +0 | origin/main |
| `phase0-stack` | b449964 | +0 | origin/phase0-stack |
| `sh/base` | ea69dfa | +1 | origin/sh/base |
| `tests/CC-SP-47` | c4a94ac | +1 | origin/tests/CC-SP-47 |
| `tests/CC-SP-64` | e96094a | +1 | origin/tests/CC-SP-64 |
| `tests/FR-AGT-04` | 2d9781a | +2 | reachable from other origin refs |
| `tests/FR-HIL-01` | faba0b6 | +1 | reachable from other origin refs |
| `tests/FR-HIL-07` | 18add1a | +4 | origin/tests/FR-HIL-07 |
| `tests/FR-HIL-07-r2` | 04c2a75 | +6 | origin/tests/FR-HIL-07-r2 |
| `tests/FR-HIL-07-r3` | 6db698e | +6 | reachable from other origin refs |
| `tests/FR-HIL-07-r4` | 3e355ae | +8 | reachable from other origin refs |
| `tests/FR-HIL-07-r5` | 34036a7 | +10 | reachable from other origin refs |
| `tests/FR-HIL-07-r6` | cfab7dc | +13 | reachable from other origin refs |
| `tests/FR-HIL-07-r7` | b8064b4 | +15 | reachable from other origin refs |
| `tests/FR-HIL-07-r8` | d8a191d | +39 | origin/tests/FR-HIL-07-r8 |
| `tests/FR-INT-06` | 1a5fcb7 | +1 | origin/tests/FR-INT-06 |
| `tests/FR-INT-09` | 0522a9a | +1 | origin/tests/FR-INT-09 |
| `tests/P8-01` | acfe876 | +1 | origin/tests/P8-01 |
| `tests/P8-06` | 1439637 | +2 | reachable from other origin refs |
| `work/FR-HIL-07-a46f` | 87d0d5d | +38 | reachable from other origin refs |

### Needs the user
- Delete the stray `meet-bot/C:` folder: the auto-mode classifier denied it. It is gitignored now.
- The leftover worktree directories were deleted on 2026-10-01, with the user's OK. Before deletion, every one of their 1,748 non-dependency files was matched to an existing git blob.
- meet-bot and PL-01: decided on the default. meet-bot lives on its own branch line (`chore/meet-bot-baseline`, worktree `.claude/worktrees/meet-bot`). It lands in phase0-stack through an integration ticket (VA-INT: model ids to `config/`, calls through `packages/providers`), after which `git revert 32af67b` is replaced by that ticket's merge.
