# Three-minute judges' walkthrough

This script describes the GATE-OLDUI+LIVE2 candidate
`182beac2a481d28982e145092e471939f59adc91`. It records no deployment or hosted
acceptance result. Before presenting, match the hosted Home build stamp to the
published gate head and check which steps are available. Present only what that
build exposes; retain any index, provider, activation and security holds.

Use an authorised test account and an existing run for the timed demonstration.
A new run can take longer than three minutes. Starting work or resolving an
external-action approval requires the account owner's permission; this script
does not grant it.

| Time | Page and action | Recorded evidence and limits |
| --- | --- | --- |
| Before timing | **Sign-in, then Team** (`/team`): sign in and inspect People. The configured founder can be bootstrapped once at app start. Until setup succeeds, show “Set up your organisation to see your team and agenda.” Home's agenda also shows this setup state. | Setup has **no world event**: the missing-person/organisation read establishes the setup state; a successful `/v1/people/first` response and subsequent People/Plate reads establish founding. Do not invent `person.created` or claim sign-in alone founded an organisation. A refusal or unconfigured bootstrap remains setup required. |
| 0:00–0:40 | **Home** (`/`): enter “Draft a one-page plan for a community garden”, choose **Start**, review the single scope/assumptions/cost card, then choose its **Start** if authorised. No old understanding/approach screens are needed. | The returned world ID identifies the run; its recorded `world.started` proves work began. The confirmation card, navigation, or “Getting ready” alone does not. |
| 0:40–1:25 | **World** (`/world/<id>`): show the live recorded map for a Village, Town or City run. Open the available **Story** and **Trace** lenses for the same world. | `district.created`, `building.planned` and `agent.spawned` establish the corresponding visible entities; `building.completed` establishes completed building work. All sizes use the live event view. With no entity events, show “Waiting for recorded districts and agents”; never substitute a sample map as live progress. Preserve sequence numbers and timestamps. |
| 1:25–2:05 | **Needs you** (`/needs-you?world=<id>`): inspect an actual waiting card's action, recipient and consequences; resolve it only if authorised. Otherwise show the empty state. | `approval.requested` establishes the waiting request; the matching `approval.resolved` establishes its resolution. A click or toast does not prove resumption, delivery or sending. No pending approval means there is nothing to demonstrate. |
| 2:05–2:35 | **World result** (`/world/<id>`): inspect completion and open the result only if a file is available. | `world.completed` establishes completion; `artifact.created` identifies an artifact when recorded. The actual returned/downloaded file establishes its contents. A pending run, missing file or failed download remains a stated limitation. |
| 2:35–3:00 | **Start it again — Home** (`/`): return to Home, enter the task again, review the new confirmation card and start only if authorised. | This candidate has no control labelled **Start it again**. Demonstrate a fresh Home start, not an automatic restart or reuse of the old run. A new world ID with its own `world.started` proves the second run; the old completion event proves nothing about it. If a published successor adds the control, verify its behavior before presenting it. |

Read the source/lifecycle label aloud: live run, recorded replay, paused,
completed, failed, or no run yet. Lenses and Stage mode are presentation only;
use them only if available in the hosted build. No completion or approval event
alone proves an email/message was sent or a connector is activated.

**Recorded fallback:** choose **Explore a demo session** from sign-in, then the
Home recording link if present. The bundled reference is
`/world/w_village_basic/stage?fixture=village-basic`. Point to its recorded
sequence/timestamps and say “recorded replay” throughout. This does not start
the entered task, resolve a real approval, call a provider, spend credits or send
anything. A sample result without a linked file is not downloadable.

Retain the hosted build stamp, world IDs, relevant Trace sequence/timestamps,
setup read responses and actual artifacts. Report each step as observed live
evidence, recorded evidence or unavailable; local tests and merged commits do
not establish deployment.
