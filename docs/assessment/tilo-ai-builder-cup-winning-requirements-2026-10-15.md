# Tilo requirements for a competitive AI Builder Cup entry

Prepared on 15 October 2026. Project status below comes from release records through about 02:40 IST, the recorded live-site audit, and the named source versions. It is not a new live test. Official competition pages were checked on 15 October.

**Tilo has a strong idea, but the available evidence does not yet establish a dependable competition entry. The biggest problem is the gap between features being built and a new user getting useful work finished.**

The strongest pitch is simple: **Tilo helps an operations manager delegate research, see what the AI is doing, step in when needed, and receive a useful result with sources and a clear cost.** The animated World can make this memorable if it makes the work easier to understand and control.

This report separates official entry rules, Tilo's own targets, and recommended priorities. Meeting them can strengthen the entry; no checklist guarantees a win.

## 1 Official requirements we must meet

| Requirement | What Tilo needs to provide |
| --- | --- |
| A working prototype | A deployed journey that actually completes a task. The official FAQ says a prototype is enough. |
| Google technology | Build primarily on Google Cloud. Use the required Google AI models or qualifying agentic platforms and deploy through Cloud Run or Firebase. |
| Submission materials | A live URL, public GitHub source repository, video strictly under three minutes, and a deck covering architecture and the business case. |
| Format | Submit the deck as PDF and use English for submission materials. |
| Original work | Fresh code and original assets created within the official hackathon period. Keep dated development and asset records. |
| Eligible team | Two to four eligible JAPAC-based members, aged 21 or older; students are excluded. Check the registered roster. |

Sources: [official terms](https://docs.google.com/document/d/e/2PACX-1vRm7ChZ6Ij9fG7uFDkxzUMpwgVeBmnQ6cMDnAIEEX84AiLBOOQ9cYbl3S5OzFBbcVb8TF55s-eVpiXb/pub), [official FAQ](https://aibuildercup.com/Faqs.html), and [technical and submission requirements](https://aibuildercup.com/themes.html).

The public timeline lists **18 October 2026** as the prototype deadline. Keep Tilo's internal submission date of **17 October**. The exact cutoff time and time zone remain unverified; check the submission dashboard before the final day. Registration and team formation are already closed according to the current public timeline. [Official timeline](https://aibuildercup.com/)

Tilo fits **Future of Work & Enterprise Productivity**. The themes page also contains a conflicting category list further down. Use the actual form and organiser clarification for that field; do not change the product story to match the stray list. [Official themes](https://aibuildercup.com/themes.html)

The source repository must be public for submission. Tilo's project rules currently keep it private until the owner approves publication. Prepare the exact version, remove private material, and obtain that approval before changing visibility. This report does not change it. Team eligibility, the dashboard state, and current repository visibility have not been verified here.

## 2 What will make Tilo competitive

The official weights are 40% technical merit and GenAI implementation, 25% problem alignment and impact, 25% innovation and creativity, and 10% user experience and solution design. [Official judging rubric](https://aibuildercup.com/Faqs.html)

The following are practical recommendations for Tilo under those categories, not extra competition rules.

| Judging area | What we should prove | Evidence to show |
| --- | --- | --- |
| Technical merit, 40% | Real AI completes useful work reliably. Google Cloud services have clear jobs. Failures, approvals and costs are handled correctly. | A real completed run, its output, model and service map, test results, cost and elapsed time. |
| Problem and impact, 25% | A specific kind of user saves effort on a recurring problem and accepts the result. | A timed comparison with the same task done manually, user observations and correction effort. |
| Innovation, 25% | Seeing and steering work through the World provides a practical benefit. | A person notices a blocked task, understands it and resolves it; compare this with reading an ordinary activity log. |
| User experience, 10% | A first-time user can start, follow and finish work without coaching. | A fresh-account test on desktop and phone, including opening the final result. |

Although UX has the smallest formal weight, a broken first visit prevents judges from seeing the technical work and innovation.

## 3 The product we should demonstrate

Choose **one primary user and one main task** for the submission story. The existing PRD already names operations managers as the primary audience. A suitable task is a source-backed supplier comparison that ends in a decision brief.

For example: “Compare these three suppliers for our small team. Use the budget and requirements I provide. Show your sources, explain missing information, and give me a one-page recommendation.” This is a proposed demo task, not a claim that it currently works.

The user should see this complete journey:

1. Enter the task and any useful constraints.
2. Review what Tilo will do, its assumptions, and the estimated cost.
3. Start the work and see understandable progress.
4. Inspect a source or a decision that needs attention.
5. Change a requirement or resolve a genuine question.
6. Receive and open the final comparison and recommendation.
7. See the actual cost, remaining uncertainty, and a record of what happened.

Keep the already-requested trip-planning task as the release acceptance check. Use the business task for the competition narrative only after it works. Both should use the same general system; do not add code that recognises a demo prompt and returns a prepared answer.

The audience should understand the task before hearing about agents, districts, model routing, or service architecture.

## 4 Requirements and clear completion checks

These are proposed submission priorities. They do not silently replace the frozen PRD. The PRD includes a broader two-scenario goal and further platform requirements.

| Priority | Requirement | Done when |
| --- | --- | --- |
| Essential | A judge can enter | A fresh authorised account reaches a usable workspace without an engineer fixing data or permissions during the session. A clearly labelled recording is also accessible. |
| Essential | One task works repeatedly | The same deployed version completes the primary task three consecutive times using the real AI. Save every attempt and failure. This is a demo reliability check, not a broad success-rate claim. |
| Essential | The result is useful | A person checks it against the requested task, opens the actual deliverable, and records any correction needed. A completion badge alone is insufficient. |
| Essential | Sources support the answer | Check the factual claims against their citations. The PRD target is at least 90% supported claims; publish the number checked and the result. Unknown facts remain visibly unknown. |
| Essential | Human control works | A controlled test shows that a consequential action waits for approval, rejection prevents it, and retrying does not duplicate it. Use test destinations or a safe simulator for demonstrations. |
| Essential | Failures are understandable | A failed step gives a useful explanation and a safe next action. The interface does not remain stuck or imply success. |
| Essential | Cost is understandable | Show the estimate, actual spend and units. A budget stop explains what happened and how to continue. Do not imply an unimplemented currency conversion. |
| Essential | The first visit is simple | A new tester finds one clear starting action, understands the options, and opens the final result on desktop and phone. Record any help given. |
| High | The World helps a person | Test whether people find a blocked branch faster or with fewer mistakes using the World than an activity log. Keep text status and Story usable too. |
| High | Impact is measured | Several intended users try comparable tasks manually and with Tilo. Record time, review effort, errors and whether they would use the result. |
| Essential | Claims match the release | The website, README, video, deck and evidence refer to the same released version and accurately label live work, recordings and unavailable features. |
| Essential | The package is accessible | A separate browser session can open every required submission link. The video is under three minutes and the PDF is readable. Judge access instructions work. |

The PRD also targets at least 85% task success on prepared cases and 60% on open tasks. Those are internal targets, not official Cup thresholds and not current results. Three successful demonstrations cannot establish either rate. [PRD sections 3.3 and 3.5](../prd/tilo-prd-v2.md)

## 5 What we are doing wrong

### We have prioritised platform breadth before proving the whole task

The PRD covers eight major areas and seven personas. Its judging section says the pillars earn the score while scenarios showcase them. That framing risks encouraging component completion before user outcomes. The 15 October audit still recorded a failed task-to-result journey.

**Change:** make a complete, useful task the unit of progress. A feature earns a place in the final push when it removes a blocker from that journey or supplies necessary submission evidence. Keep the broader product plan for later. [PRD sections 2.3, 3 and 4](../prd/tilo-prd-v2.md); [live audit](../../agy-bridge/reports/UX-AUDIT-15OCT.md)

### We have allowed passing tests to coexist with broken real behaviour

The release records contain many passing component tests. Yet the handoff reports that the real provider rejected the tool definitions, causing tool steps to fail silently. This is a gap between testing pieces and testing the actual deployed combination.

**Change:** keep component checks, but require one observed task on the exact deployed version before calling a release done. Record the prompt, output, elapsed time, cost, errors and human help. The supervisor's 15 October release rule already makes this correction. [Release handoff](../../agy-bridge/handoffs/SUPERVISOR-06-PROMPT.md); [status record](../../agy-bridge/STATUS.md)

### We have made the first visit depend on insider knowledge

The recorded judge visit found sample worlds that could not open, organisation setup errors, unavailable real skills and unexplained task options. A judge should not need to know which account founded the organisation or which branch has a fix.

**Change:** verify the actual judge route from a fresh account. The first-run repair is reported ready, but still requires the owner to have founded the organisation; its deployment is not established by the inspected records. Fixing a branch is only part of fixing the user experience. [Live audit](../../agy-bridge/reports/UX-AUDIT-15OCT.md); [02:40 handoff](../../agy-bridge/handoffs/CX-ORCH-110.md)

### We have evaluation cases without usable quality evidence

The release README reports a preserved replay result of **0/0 passed, 160 not runnable**. The local result file also reports no executed cases. This is not a 100% pass rate, and it does not mean that 160 tasks failed. It means the evaluation supplied no runnable coverage.

**Change:** make a small representative set runnable first. Cover task completion, factual support, approval behaviour and recovery. Publish successes, failures and cases that could not run separately. Keep replay results separate from real-provider results. [Release README at 9bccc12c](https://github.com/spark-456/tilo/blob/9bccc12c/README.md); [local replay result](../../evals/results.local.md)

### We have not yet demonstrated why the World improves work

The World is distinctive, but attractive animation alone does not establish usefulness. The PRD sensibly planned a comparison with raw logs; the inspected release tree contains no published evidence report for that study.

**Change:** ask people to find and explain a blocked task using both views. Alternate which view they see first so practice does not favour the second view. Report time and errors. If the benefit is weak, improve clarity and keep Story prominent. [PRD evidence plan](../prd/tilo-prd-v2.md)

### Our release process has consumed scarce time without settling the user outcome

The status record shows repeated candidate changes, test-environment problems, false failure reports from health checks, a repeated missing-files packaging issue, and constrained machine and AI usage capacity. These are documented process problems, not a judgement about individual effort.

**Change:** keep one release candidate and a clear owner. Run the required release checks, fix failures, then observe the live task. Repeat checks when a change or failure warrants them. Stop unrelated additions during this sequence. The existing supervisor direction already supports this approach. [Status record](../../agy-bridge/STATUS.md)

### Our documentation describes different points in time

The local root README is a skeleton, but **the named released source version already has a substantial README, architecture explanation and walkthrough**. The earlier assessment was too broad in treating the skeleton as the submission state. However, that newer README still references earlier candidate and verification details, so documentation alignment remains unfinished.

**Change:** publish one current release summary and make the submission materials agree with it. Update stale status text; distinguish configured services from services observed working. Keep internal release troubleshooting out of the main judge instructions. [Earlier assessment](tilo-prd-progress-2026-10-15.md); [release README](https://github.com/spark-456/tilo/blob/9bccc12c/README.md)

## 6 Evidence we need before making strong claims

For each real task attempt, save the build version, model configuration, task, start and finish times, actual cost, output, sources, human interventions and outcome. Preserve failed attempts as well as successful ones.

Measure effort fairly. Compare manual work with **Tilo setup plus human monitoring, review and corrections**. Report waiting time separately from hands-on effort. AI run duration is not automatically time saved. Use comparable tasks and quality standards; identify team-member tests separately from outside-user tests.

The PRD planned 5–8 people for the World comparison and 6–10 people using Tilo over three days for the pilot. If that has not happened, a smaller honest study can still help. State its actual size and duration, and describe it as early feedback. Do not present a short usability session as the planned pilot.

The business case should answer four plain questions: Who repeats this task? How often? Why would they choose Tilo? What does one accepted result cost to produce? State willingness to pay as a hypothesis unless users have provided evidence. Avoid unsupported market-size or productivity claims.

## 7 Priorities for 15 to 17 October

The responsibilities below are suggested roles, not assignments to named people.

| Date | Focus | Required output | Suggested owner |
| --- | --- | --- | --- |
| 15 October | Resolve core execution and judge access; settle one release candidate. | Required checks pass and the trip acceptance task finishes on the deployed version. | Release owner |
| 16 October | Repeat the main business task, observe fresh users, check outputs and costs. | Attempt log, useful deliverables, small evidence report and a clear limitations list. | Product and evidence owner |
| 16 October | Prepare submission materials using the proven behaviour. | Current README, architecture and AI-use explanation, PDF deck and video draft. | Submission owner |
| 17 October | Freeze claims, verify access, publish approved materials and submit early. | Accessible links, exact submitted version and saved submission confirmation. | Team leader |

Until the core journey works, defer new connectors, additional meeting features, broader personas and decorative animation. Preserve the controls needed for safety and truthful status. If a feature cannot be made dependable in time, remove it from the demonstration and disclose the limitation.

If a full three-day pilot has not started, do not try to imply one was completed before the internal deadline. Deliver the smaller study that actually fits.

## 8 A focused demonstration and deck

Aim for a **2 minute 45 second** video so there is room under the strict limit:

| Time | Show |
| --- | --- |
| 0:00–0:20 | The user, recurring task and difficulty today. |
| 0:20–0:45 | Entering the task and reviewing scope and estimated cost. |
| 0:45–1:20 | Real progress, an important source, and a useful human intervention. |
| 1:20–1:55 | The finished deliverable and why it answers the request. |
| 1:55–2:20 | Measured results, including sample size, time and cost. |
| 2:20–2:45 | The Google Cloud architecture, the World benefit and honest limits. |

Record actual behaviour. Label any time compression, recording or replay. Do not invent an approval event to fill the script. If a task takes longer than the video, show a clearly edited recording of its real execution and state its actual duration.

The deck should cover the user problem, current alternative, Tilo's workflow, evidence of value, the World benefit, AI responsibilities, architecture, safety, operating cost, adoption plan and limitations. Tilo's PRD suggests about 14 slides; that is an internal format choice. Put detailed technical material after the main story.

## 9 Decision before submission

The critical questions are whether a new judge can get in, whether the demonstrated task finishes, whether its result is useful, whether every public claim has evidence, and whether all required materials are accessible.

**The strongest next step is to close the gap between Tilo's technical ambition and one person's successful experience.** Once that experience is dependable, the World, controls and architecture can support a convincing competition entry.
