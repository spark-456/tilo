# Tilo · World page (Tilo W) — build prompt

You are building the live **World** page of Tilo in the Tilo T design language. The design lives in:

- `Tilo W Canvas.dc.html` — every state at 1440×900 and 390×844, light and dark, plus interactions, the component sheet, tokens and motion.
- `Tilo W World.dc.html` — the page itself. Props: `theme` (studio | studioDark), `device` (desktop | phone), `state` (planning | working | needs | done | failed), `overlay` (none | hover | agent | chat | convene | meeting | more), `tab`, `agent`, `filter`, `reduced`.
- `Tilo W Parts.dc.html` — rail tabs and cards (`part` = story, trace, steps, chat, hover, panel, convene, approval, failure, result, rMain, rSheet, rSlides, rWeb, rText, files, made, more).
- `Tilo W Sprite.dc.html` — the agent sprite and its walk cycle.
- `tilo-w.css` — the only new tokens and keyframes. `tilo-w.js` — fixture data in the shape of the real API.
- Reused from Tilo T: `tilo-daylight.css` (theme variables), `tilo-studio.css`, `tilo-t.css`, `tilo-t.js` (icons), `tilo-city.js` + `tilo-daylight.js` (isometric buildings).

## The one rule
Nothing moves unless something really happened. Each animation starts on an event from the run's event stream and stops when the matching end event arrives. Ambient loops are not allowed. The only exceptions are the live dot and the planning shimmer, and both stop once planning ends.

## Layout
- **Desktop 1440×900**: a slim 60 px header, the stage on the left (940 px, about 65%), and one right rail (500 px) with tabs for Story, Chat, Result and Steps. The stage always comes first and is never pushed down. Panels open over the rail, never over the stage. The only exceptions are the chat pop-up and the Convene dialog.
- **Phone 390×844**: the stage fills the screen and sits under a compact header. The rail becomes a bottom sheet with the same four tabs: 372 px when peeking, 600 px when tall (Result, Chat, Agent, Convene, More). Every touch target is at least 44 px.
- **Trace** is a toggle inside Story (Plain | Trace), not a tab.
- **More** (skill proposals, team work items, add a work item) opens from the header into the rail area and stays out of the stage.

## Data → UI
| Source | Where it shows |
|---|---|
| `world.title, size, status, started_at, agents.length` | Header: the title, the size chip (village / town / city), the status chip, "Started 3:54 pm · 7 agents" |
| `steps[].status` count | Header: "4 of 7 steps done" with its bar, and the Steps tab badge |
| `credits.used / credits.cap` | Header credits bar, Trace total, failure card |
| `steps[]` | One building each. Status maps to: planned or waiting = dashed plot, working = scaffold, done = finished with a check, needs = amber, failed = scaffold with a red chip |
| `places` | Meeting Hall and Delivery Dock always exist once the world is planned |
| `connectors[]` | Islands at the edge of the map, joined by a dashed line to the step that uses them. The line is darker while that step is working. The 32 px tile is a **logo slot**: drop in the official Gmail, Drive, Canva and Lovable marks under your licence. |
| `agents[]` | Sprites. `agents[].color` comes from `--ag1…--ag7` in join order and is never reused within a run. The same colour is used on the sprite, avatar, chat bubble tint, file dot and card swatch. |
| `events[]` (plain text) | Story, in order with the newest at the bottom. The latest line is also the "now" line at the top left of the stage. |
| `events[]` (raw) | Trace: time, event name, detail, credits |
| `messages[]` | Chat: agent↔agent, you↔agent 1:1, and team-meeting messages in one thread. Filters are All, a pair, an agent, You and Team meeting. Hand-overs render as a note card with the file name. |
| `approvals[]` | The approval card at the top of Story. It shows the exact action, the risk in plain words and the cost, with Approve / Edit / Decline. |
| `artifacts[]` | Result: the main deliverable first (rich card with preview), then sheet, slides, website and text. Working files are grouped and folded under their real names. "Where it was made" shows Tilo, Canva and Lovable. |

## Event → motion (all transform/opacity)
| Event | Motion | Timing |
|---|---|---|
| `world.planning` | Director in think pose at the Plan plot; the drafting card streams plan lines | lines 350 ms apart; shimmer 1.4 s |
| `building.planned` | Dashed plot fades and scales .85→1 | 400 ms, 120 ms stagger, ease-out |
| `building.constructing` | Scaffold rises from the base (scaleY .08→1) | 2.4 s, cubic-bezier(.2,.8,.2,1) |
| `tool.called` → `tool.returned` | Tool icon bobs above the head; arms swing | 1.6 s loop / 500 ms |
| `agent.moved` | Walk: translate along the path; legs ±26°, arms ∓22°, bob −3 px, squash 1.04/.95 on contact | stride 560 ms; travel = distance ÷ 130 px/s, clamped to 0.6–3.4 s; path easing (.4,0,.6,1) |
| `agent.handoff`, `question.routed` | Both agents face each other; 3 dots appear between their heads. No text on the map. | dots 1.2 s loop, 160 ms apart; hidden while either agent walks |
| `approval.requested` → `approval.resolved` | Hand up, amber "Needs you" chip with a ping ring; the now line turns amber with a Review button | ping 1.6 s loop |
| `building.completed` | Building settles 1.035→1; check pin | 300 ms |
| `meeting.called` | The picked agents walk to the Meeting Hall slots; the hall chip says In session; Chat opens the meeting thread | walk timing |
| `artifact.delivered` | Parcel arcs from the Hall to the Dock on a motion path; Result tab opens; cards slide in | 1.6 s (.45,0,.2,1); cards 420 ms, 40 ms stagger |
| `world.completed` | Agents gather at the Dock and hop 3 times; buildings regain full colour; confetti once | confetti 1.8 s after 1.5 s; never loops |
| `agent.blocked`, `world.failed` | Agent in sad pose; red Failed chip; failure card on top of Story; now line turns red | 300 ms fade |

Interaction motion: hover light-up (ring .6→1, other agents fade to .45 opacity) takes 180 ms. The agent panel slides 32 px in 260 ms. The chat pop-up opens in 220 ms and closes in 160 ms. The camera (Fit, Follow, zoom) moves in 900 ms. The phone sheet takes 250–320 ms.

## Spacing rule
Each building has three standing slots in front of it, 0.75 cells apart. The Dock and the Meeting Hall have a row. An agent always walks to a free slot, so agents never pile up.

## Performance
- Animate transform and opacity only, with no filter or blur animation. Shadows appear only on floating cards.
- Never animate SVG strokes on the ground layer, because it repaints the whole city. Connector lines change opacity as a state, not as a loop.
- An IntersectionObserver plus `visibilitychange` sets `data-paused="true"` on the root, which pauses every animation underneath. The replay timer stops too.
- With reduced motion (system setting or the `reduced` prop), every move becomes a 200 ms fade. Agents appear in place, loops show a still frame, and the parcel and confetti are skipped.
- Camera, labels and cards counter-scale (`scale(1/zoom)`) so text stays the same size at any zoom.

## Replay controls
Pause/Play, 1×, 2×, Catch up (jump to the latest event and resume live), Whole run (play the recorded events from the start), and a scrubber that reads "event N of T · event.name". The header button "Pause run" is different: it pauses the real agents.

## Copy rules
Use plain sentences with the agent's name first: "Juno handed 12 flights to Kai." Write risk in plain words: "People will see it and it can't be unsent." Failure always says what was done, what was not, and what was safe: "Nothing was sent or paid."
