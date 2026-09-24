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
| P0-01 Scaffold | PRD 20.3, 20.4, 17.6; SEC-13 (CI scan skeleton) | reach-builder | Queued | | | | | | n/a |
| P0-02 Core contracts + codegen + drift CI | FR-WLD-02; PRD 15.2 (brief, plan, layout, card, policy, handoff, envelope, skill, connector, providers) | architect | Queued | | | | n/a | n/a | n/a |
| P0-03 Event contract + registry | FR-WLD-03 (registry, data schemas, fixtures); PRD 9.3, 9.5 | architect | Queued | | | | n/a | n/a | n/a |
| P0-04 Provider layer A: interfaces, config loaders, denylist, model-id lint | PL-01, PL-04 (skeleton), PL-06, PL-07, NFR-25 | architect + intelligence-builder | Queued | | | | | | n/a |
| P0-05 Provider layer B: google, OpenAI-compatible (mock), record-and-replay | PL-02, EFF-01 | intelligence-builder | Queued | | | | | | n/a |
| P0-06 Provider layer C: role router, fallback, cascades, token caps, conformance | PL-03, PL-05, EFF-02, EFF-03 | intelligence-builder | Queued | | | | | | n/a |
| P0-07 Infrastructure plan for tilo-dev | PRD 6.2, 6.3, 6.5; SEC-02, SEC-12; 16.1 rule 5 | reach-builder | Queued | | | | | | n/a |
| P0-08 Web shell, tokens, fixture player (Village world) | FR-WLD-04 (partial), FR-WLD-10 (partial), PRD 18.2 tokens | world-builder | Queued | | | | | | |
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
