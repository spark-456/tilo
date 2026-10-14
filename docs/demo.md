# Three-minute judges' walkthrough

This walkthrough targets the OLD-UI cutover. **Publication through GATE-OLDUI is
held until INDEXES READY and publication is confirmed.** Use the steps below only when the hosted build actually
exposes them; a merged PR, local test, or screenshot does not prove deployment.
Check the Home build stamp against the published gate head before presenting.

Use an authorised test account with an existing run and a pending approval for
the timed demonstration. Run completion can take longer than three minutes.
Starting a new task or approving an external action requires the account owner's
permission; this document does not grant it.

| Time | Page and action | What proves the step happened |
| --- | --- | --- |
| 0:00–0:40 | **Home** (`/`): enter one task, for example “Draft a one-page plan for a community garden”. Review the single scope/cost confirmation card, then choose **Start** if authorised. | Keep the returned world ID. The confirmation card is a proposal; the run is working only when its event stream records `world.started`. An error or “Getting ready” is not success. |
| 0:40–1:30 | **World** (`/world/<id>`), then its **World** lens (`/world/<id>/stage`): point out the recorded progress, open **Story** and **Trace**, and return to World. At a 1920px presenter viewport, enable **Stage mode** if the published build offers it. | Use the same world ID throughout. Trace shows event sequence and timestamps; the stage and lenses consume that run's recorded events. `building.planned`, `agent.spawned`, and `building.completed` substantiate the corresponding visible activity. Stage mode changes presentation, not run state. Read the source/lifecycle label aloud: recorded replay, live run, paused, completed, failed, or no run yet. |
| 1:30–2:20 | **Needs you** (`/needs-you?world=<id>`): open a waiting approval and inspect the exact action, recipient, and consequences. Resolve it only if authorised. If no approval is waiting, show the empty state. | A real waiting card comes from `approval.requested` for this run. After resolution, show the matching `approval.resolved`; an approval click or toast alone does not prove work resumed or an action was delivered. Never invent an approval for the demonstration. |
| 2:20–3:00 | **World result** (`/world/<id>`): inspect the recorded completion and open the result if a file is available; otherwise show the stated limitation. | `world.completed` establishes run completion. The actual returned/downloaded artifact establishes the result's contents. A missing file, failed download, or pending run must be described as such. Completion or approval alone does not prove an email/message was sent. |

If the hosted build lacks a lens or Stage mode, state that it is unavailable and
stay on the page that is deployed. Do not describe the pending cutover as live.
If the signed-in API or runner cannot start work, show its error and continue
with an explicitly labelled recording instead of claiming a completed task.

**Recorded fallback:** choose **Explore a demo session** from sign-in, then the
Home recording link if present. The bundled reference address is
`/world/w_village_basic/stage?fixture=village-basic`. Follow the same lenses and
point to the recording's sequence/timestamps. Say “recorded replay” throughout:
this does not start the entered task, resolve a real approval, make a provider
call, spend credits, or send anything. A sample result without a linked file is
not a downloadable deliverable.

For the presentation record, retain the hosted build stamp, world ID, relevant
Trace sequence numbers/timestamps, and the actual artifact when available.
Report each step as live evidence, recorded evidence, or unavailable according
to what was observed. This document records no hosted acceptance result.
