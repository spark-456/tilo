# ADR-0008: Prototype first, harden second

- Status: Accepted (2026-09-26, user decision, recorded by the orchestrator)
- Deciders: user
- Requirement: PRD 5.4 CP2 "Thin slice" (3 Oct), PRD 20.2 week plan

## Context
By 26 Sep about 10 M agent tokens had gone into roughly 8 merged tickets. Most of that was spent on
repeated review rounds: reviewers reported one problem per round, and up to five reviewers checked
every ticket across five parallel sessions. Nothing was yet visible end to end. The weekly plan was
at 76%. CP2 (3 Oct) needs one flow working end to end: intake, plan, world, and a gated action.

## Decision
1. **Phase A, prototype (now to CP2, 3 Oct).** All building goes to one flow: a person types a
   task, answers the clarifying questions, picks an approach and budget, watches the world play,
   gets a "Needs you" card, approves, and the result is delivered. It runs on fakes and recordings
   and sends nothing real.
2. **Two tracks.**
   - Backend: agent runtime (SH), intake and planning (SP), and the approval step and outbox (ST).
   - Frontend (SW): merge the world view first, then build the screens along the flow.

   These sessions keep the paths they own in `docs/parallel-sessions.md`, so there is no
   re-ownership churn.
3. **Paused until the flow works:** evals and metering (SE, after it parks its in-flight work
   cleanly), connectors, channels, browser workers and render (ST tickets 4 to 6), and contract
   work that only serves paused tickets.
4. **Reviews follow speed mode:** every blocking problem in one round (root `CLAUDE.md`), reviewers
   only where the diff needs them, and a redo or split after 3 failed rounds
   (`docs/parallel-sessions.md`). security-reviewer still runs whenever a diff touches its paths.
   It is not deferred.
5. **Phase B, harden (about 4 to 12 Oct).** The paused tracks resume. The full reviewer set
   reviews the finished flow once, and the follow-up issues are cleared. Then breadth goes in:
   Gmail, WhatsApp, Email Autopilot and the 170 eval cases. Everything must be cleared before any
   real email or WhatsApp message is sent.

## Stays strict throughout
Frozen contracts, acceptance tests named after requirement IDs, no paid calls without the user's
`LIVE=1`, T3 always needs a person, every side effect goes through the outbox and the policy
engine, and the guard hook.

## Consequences
- Some prototype code will be rewritten in Phase B.
- The follow-up list grows during Phase A and must be cleared before real sends.
- PRD 20.2's 9 Oct date for every Must test gets tighter, because evals and channels start later.
- Builder models are unchanged; this ADR does not move builders to cheaper models.
