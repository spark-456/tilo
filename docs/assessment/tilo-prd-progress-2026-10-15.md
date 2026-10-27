# Tilo: PRD and progress assessment

**Evidence snapshot:** 15 October 2026, about 02:40 IST. This assessment separates the checked-in PRD, current repository artifacts, and bridge-reported release evidence. It does not treat a passing component test as proof of a successful live user task.

## Verdict

Tilo has a compelling, technically ambitious thesis: make delegated agent work visible and steerable through a world view, while keeping the underlying events, approvals, costs, and outputs auditable. That is a stronger identity than “another agent builder.” The event-driven World plus Story/Trace, human gates, and domain experts could make a convincing product if the interface helps people notice and resolve problems faster.

Today, the project is **not yet proven as a dependable product or a submission-ready demo**. The published baseline is LIVE3 (`9bccc12c`). The attempted LIVE5 gate failed a route audit; the team combined the repairs and subsequent work into a LIVE6 candidate, but the latest status does not yet show an exact ready SHA, its release gate, a deployment, or the required real-AI trip-prompt run. A separate judge-first-run branch is ready, with two reported gaps. The UX audit of the published site found that a new judge could not reach or complete real work. I also found no `docs/evidence.md`, `evals/results.md`, or `docs/genai-map.md` in the inspected workspace, so the PRD's measured impact and model-quality claims remain unsubstantiated here.

That is a recoverable position, but the final days should go to one complete, observed user journey and an honest submission package—not more platform breadth.

## Status chart

| Area | Where Tilo is now | Where the PRD says it must be | Readiness |
|---|---|---|---|
| Product idea and differentiation | The thesis is clear: real execution events drive the World, with human control and Trace. It directly addresses invisible, hard-to-trust agent work. The PRD itself still marks several problem claims as needing sources. | Demonstrate that the World makes a real run easier to understand and steer than a raw log, and that the chosen workflow solves a frequent user problem. | **Strong thesis; impact hypothesis unproven.** |
| Core task execution | LIVE3 is the published baseline. The LIVE5 candidate (`17154fca`) failed its cloud gate on a route-audit test (673 passed, 1 failed). A combined LIVE6 branch now gathers execution, search, recovery, budget, World, and answer-handling fixes. No exact LIVE6 ready head, gate/release result, or successful live trip-prompt result appears in the latest status. | One or more useful, real-Gemini scenarios complete end to end; the selected scenarios pass three consecutive runs. The PRD's first-user task should deliver a useful result, not just a plan or animation. | **Red: main release and outcome proof are pending.** |
| First-use and judge onboarding | The 15 Oct audit of LIVE3 found a judge saw sample content, could not open the recorded world, lacked access to Team/Agenda/People, could not see built-in skills, and had no clear first task. `JUDGE-FIRST-RUN` (`4e3964b9`) is reported ready with F1–F7 fixes; INR currency display remains unfinished, and the org must already be founded by its owner. It is not yet shown as deployed. | A fresh judge can reach a real or safely seeded task on desktop and phone without a private founder intervention; the sample world opens; the call to action is clear. | **Red on LIVE3; yellow on an unreleased fix branch.** |
| World, Story, and Trace | A substantial event/renderer architecture exists. `WORLD-USEFUL` (`ecd68503`) adds live step/status, assumption chips, an inline result and recovery information; the combined LIVE6 status lists it, but no release or completed end-to-end check is recorded. The PRD defines a 55 fps p95 guardrail and a 20-agent glanceability study. | Make the World a control surface: the user spots the stalled branch, understands why it stopped, intervenes, and sees the real event and final output reflected in Story/Trace. Complete the comparison against raw logs. | **Differentiator is promising; user benefit and live integration need proof.** |
| Trust, safety, and quality | Contracts, policy rules, security architecture, test suites, and many targeted test results are substantial. The PRD has explicit authorization, budget, injection, provenance, and recovery requirements. However, the real run failed before research in the earlier release, and no current full evaluation result is published. | Show the gates, sources, cost, and actual side effects in a real run; meet the task-success, groundedness, injection-resistance, recovery, and handoff thresholds on a named build. | **Good engineering foundation; production behavior not yet established.** |
| User and impact evidence | The PRD plans EV-G1 usability, EV-G2 manual baselines, and a 6–10 person pilot (EV-G3). The repository contains evaluation cases and harness code, but I found no published results or evidence report. | Publish methods and results: task success, time saved, trust, groundedness, costs, and what users did with saved time. State failures and sample size. | **Red: no evidence artifact found.** |
| Submission and communication | The checked-in root README still calls itself a skeleton. The inspected workspace has no `docs/genai-map.md`, `evals/results.md`, `docs/evidence.md`, or deck PDF at the PRD's expected paths. A deployed URL exists, but the live audit shows the first-use gap. | Stable public URL, accurate public README, architecture/GenAI map, eval and security notes, short public video, PDF deck, and an honest limitations section. | **Red: package is incomplete in this checkout.** |
| Product/business success | The PRD defines plausible personas and weekly-use goals, but its source placeholders and absent pilot results mean customer pull is unknown. | A narrow user group repeats the workflow, accepts outputs without redoing them, saves measurable time, trusts the controls, and has a reason to pay or expand use. | **Not validated; feature completion alone cannot establish this.** |

The PRD's own hackathon score map weights Technical Merit at 40%, Problem Alignment at 25%, Innovation at 25%, and UX at 10%. Tilo's strongest potential is innovation and technical depth. Its largest score risks are problem-impact evidence and the usability of the actual deployed build. UX's 10% judging weight understates its practical importance: a judge who cannot start a task never sees the other 90%.

## What “successful if the PRD is achieved” really means

If “achieved” includes the **measured outcomes** in the PRD—not only the feature list—then Tilo would be a credible and potentially award-competitive prototype: real tasks complete, the World improves human understanding, the safety and cost limits hold, the pilot reports meaningful time saved, and the submission shows the evidence. Those are strong signals of a useful project.

If “achieved” means that all eight pillars and integrations have been coded, success is not guaranteed. A broad platform can still fail if users do not return, outputs need extensive rework, the product costs too much to run, onboarding is confusing, or the World is decorative rather than useful. The PRD itself calls for adoption, trust, time saved, groundedness, recovery, and repeat use; these are outcomes to measure, not consequences of shipping features. Even a very strong hackathon demo would validate a prototype, not prove product-market fit.

There is also a scope risk. The PRD estimates roughly 350 hours for the Must build after an assumed coding-efficiency discount and places all eight pillars, three scenarios, evaluations, pilot work, and submission between late September and mid-October. The live release evidence still shows the core run and first-use path being repaired. For the submission, “one complete workflow with honest evidence” is a better target than “all pillars appear complete.”

## Highest-value improvements, in order

1. **Prove the core loop on the exact release candidate.** Let the authorized release owner finish the single LIVE6 gate and deploy. Then run the required trip prompt in a real browser with the real model. Record the exact commit, prompt, completion/failure, elapsed time, cost, sources, output, and any human intervention. If it fails, fix the first blocking cause and repeat only the required end-to-end check. Do not claim completion from a green unit-test count.

2. **Make a judge's first five minutes work.** Use the judge-first-run fix, then verify the deployed experience from a fresh account on desktop and a 375 px phone. Handle first-organization creation through a deliberate, audited onboarding flow; do not simply broaden permissions. Resolve the INR display decision for an India-based user, expose one clear “Start a task” path, make a sample world clickable, and keep developer/sample copy out of the primary journey.

3. **Choose one memorable user outcome.** Make the demo about a concrete task that produces a usable artifact—for example, a source-backed comparison or briefing—not a tour of eight pillars. Show the user approving a priced plan, watching meaningful execution, finding a source or assumption, steering or recovering from a stop, and opening the final result. Keep the mandated trip prompt first if it is the acceptance run.

4. **Prove the World earns its place.** Run the PRD's glanceability test: have 5–8 people find and explain the blocked branch using the World and then raw logs; measure time and errors. If the World does not improve comprehension or steering, make Story and Trace the dependable primary view and keep the animation secondary until the evidence improves.

5. **Turn the evaluation suite into a decision tool.** Publish results tied to an exact build and model profile: counts, denominators, failures, cost, latency, and repeat spread. Prioritize real-task success, source correctness, safe stopping, and recovery. Keep the small known LIVE5 gate failure and unrelated baseline reds visible in the release notes; do not turn “many tests passed” into a quality claim.

6. **Finish the evidence and submission package.** Replace the skeleton README with the real URL, setup steps, architecture, Gemini/Google Cloud map, measured evals, security notes, and known limits. Produce the short demo and deck only from claims backed by the live build or a published method. If there is no time for the full 6–10 person, three-day pilot, say so and publish the smaller test that actually happened; never imply the planned study was completed.

7. **After the deadline, narrow the product wedge before expanding.** Start with one recurring workflow for operations managers, such as supplier or competitor research that ends in a decision-ready report. Measure whether users repeat it and accept the output. Add channels, more connectors, and broader enterprise collaboration only when that workflow has repeat use and acceptable cost.

## Practical definition of “ready”

Tilo is ready to be shown as a credible product when a new user can start a task, see a transparent plan and cost, get a good real result with sources, understand and steer the run, recover safely from a failure, and repeat it without an engineer. It is ready to be claimed as valuable when independent users do this repeatedly, with measurable time saved and acceptable correction rates. It is ready to be claimed as a business when retention, willingness to pay, operating costs, and a defensible target market also hold.

## Evidence reviewed

- [PRD v2](../prd/tilo-prd-v2.md): goals, metrics, scope, evaluation, and submission package.
- [15 Oct live UX audit](../../agy-bridge/reports/UX-AUDIT-15OCT.md): first-use findings and recommended repairs.
- [Latest bridge status](../../agy-bridge/STATUS.md): published baseline, combined LIVE6 contents, and pending release sequence.
- [LIVE5 gate report](../../agy-bridge/reports/CX-MERGE-A-46-GATE-LIVE5.txt) and [red details](../../agy-bridge/reports/CX-MERGE-A-46-GATE-LIVE5-red.txt): prior gate outcome.
- [Current root README](../../README.md): submission-facing documentation state in this checkout.

