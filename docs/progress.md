# Tilo build progress

Updated: 2026-09-25 night · Phase 0 (Foundations) · next gate **CP0 on 29 Sep**

## Checkpoints

| Checkpoint | Date | Status | Notes |
| --- | --- | --- | --- |
| CP0 Foundations | 29 Sep | In progress | Deploy and one real call need the user (BQ-05) |
| CP1 Skeletons | 2 Oct | Not started | |
| CP2 Thin slice | 3 Oct | Not started | |
| CP3 Pillars | 9 Oct | Not started | |
| CP4 Design and stretch gate | 12 Oct | Not started | |
| CP5 Scenarios | 14 Oct | Not started | |

## Phase 0 tickets

| Ticket | Requirement IDs | Builder | Status | Test-writer | code | security | cost | qa | design |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| P0-01 Scaffold | PRD 20.3, 20.4, 17.6; SEC-13 (CI scan skeleton) | reach-builder → opus (escalated) | Merged to `phase0-stack`; awaiting user OK for `main` (security flagged CI items, fixed) | 32 tests | PASS r2 | PASS r4 (FAIL r1–r3) | PASS r1 | n/a | n/a |
| P0-02 Core contracts + codegen + drift CI | FR-WLD-02; PRD 15.2 (brief, plan, layout, card, policy, handoff, envelope, skill, connector, providers) | architect | In progress | | | | n/a | n/a | n/a |
| P0-03 Event contract + registry | FR-WLD-03 (registry, data schemas, fixtures); PRD 9.3, 9.5 | architect | Queued | | | | n/a | n/a | n/a |
| P0-04 Provider layer A: interfaces, config loaders, denylist, model-id lint | PL-01, PL-04 (skeleton), PL-06, PL-07, NFR-25 | architect + intelligence-builder | Queued | | | | | | n/a |
| P0-05 Provider layer B: google, OpenAI-compatible (mock), record-and-replay | PL-02, EFF-01 | intelligence-builder | Queued | | | | | | n/a |
| P0-06 Provider layer C: role router, fallback, cascades, token caps, conformance | PL-03, PL-05, EFF-02, EFF-03 | intelligence-builder | Queued | | | | | | n/a |
| P0-07 Infrastructure plan for tilo-dev | PRD 6.2, 6.3, 6.5; SEC-02, SEC-12; 16.1 rule 5 | reach-builder → opus (escalated) | Stuck after 5 rounds, then resumed with 3 fixes (first-apply ordering, WIF main-only, VPC egress) | 19 tests | FAIL r1–r5 (new apply-time issue each round) | PASS r4, FLAGGED (WIF accepted git tags) | PASS r1 | n/a | n/a |
| P0-08a Web shell, tokens, layout frame, iso stage | PRD 18.2, 18.3 frame, 9.7 fallback | world-builder | Queued after P0-07 fix | | | | n/a | | |
| P0-08b Fixture player (Village world from contracts fixture) | FR-WLD-04 (partial), FR-WLD-10 (partial) | world-builder | Needs P0-03 | | | | | | |
| P0-09 Harness skeleton: ADK 3-agent fixture plan, single writer to Firestore emulator | FR-AGT-01 (partial), D-11, PRD 15.3 | intelligence-builder | Queued | | | | | | n/a |
| P0-10 First deploy to tilo-dev (tilo-api hello, web shell) | CP0 | reach-builder | Blocked on user applying infra | | | | | | |

## Done by pillar

| Pillar | Done IDs |
| --- | --- |
| Foundations | — |
| P1 Intake | — |
| P2 Harness | — |
| P3 World | — |
| P4 Human in the loop | — |
| P5 Channels | — |
| P6 Connectors | — |
| P7 Memory | — |
| P8 Metering | — |

## Blockers and open questions
- Build questions with defaults: [docs/open-questions.md](open-questions.md) (BQ-01 to BQ-09).
- Needs the user: Google Cloud projects and billing, `gcloud auth login`, applying the tilo-dev Terraform plan, one `LIVE=1` call for CP0, the public-repo decision before the first push, model profile choices (everything runs on record-and-replay until then).

## Usage and cost notes
- No paid model calls made. Dev and CI run on record-and-replay only.
- **Budget mode ON** since 2026-09-25 night (user: "don't burn away too many credits"): reviewers other than security-reviewer at medium effort, at most 2 builders in parallel, reviewers only where the diff touches their area, a ticket stops and is flagged after 5 failed review rounds.
- Custom agents in `.claude/agents/` load after a session restart. Until then the orchestrator runs the same roles through workflow agents with the same model, effort and worktree isolation.

## Agent tuning log

| Date | Agent | Change | Reason |
| --- | --- | --- | --- |
| 2026-09-25 | code-reviewer, design-critic, qa-breaker, checkpoint-auditor | effort high → medium | Budget mode (user asked to save credits). Revert to high when the user says so. |
| 2026-09-25 | cost-reviewer | added `memory: project` | Brief: reviewers keep recurring defects in project memory |
| 2026-09-26 | reach-builder (P0-01, P0-07 only) | sonnet → opus for the ticket | Each ticket failed review twice for reasoning or logic errors (self-tuning rule) |

## Integration branch
Tickets that security-reviewer flagged cannot reach `main` without the user. Approved work stacks on `phase0-stack`; new tickets branch from it. When the user approves the flags, `main` fast-forwards to `phase0-stack`.

## Usage log
- Workflow 1 (P0-01, P0-07): 28 agents, about 2.5 M subagent tokens, 45 min. Most spend went to repeated review rounds (security at xhigh on P0-01, code review on P0-07).
