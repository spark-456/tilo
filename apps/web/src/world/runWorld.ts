// Wires reducer + store + frame + choreographer + renderer into the Pixi world container Stage
// hands over. With `seqParam` set this jumps straight there, no animation (P8/HR-6); otherwise it
// plays events in real time. `runWorld` plays a loaded fixture, following the recorded `ts` gaps
// divided by `speed`; `runClientWorld` draws what a TiloClient delivers, as it arrives. Either way
// an `agent.moved` on an actor already on screen is a walk the choreographer times (HR-3) and this
// module lerps every frame; other location changes queue behind it and snap when their turn comes.
// The display density (FR-WLD-14) is read at draw time: a switch redraws the frame in place, replays
// and emits nothing, and Professional draws no walks (the same jump a reduced-motion setting gives).
import type { Event, Layout } from "@tilo/contracts";
import type { Container } from "pixi.js";
import { subscribeDensity } from "../display/density";
import { MAX_DURATION_MS, createChoreographer } from "./choreographer";
import { type Frame, type FrameAgent, type FrameSay, frameOf } from "./frame";
import { createMobileQuality } from "./mobileQuality";
import { type WorldState, applyEvent, createInitialState, standingAt } from "./reducer";
import {
  type WorldLayer,
  createLayer,
  renderAgents,
  renderSelection,
  renderStatic,
} from "./renderer";
import { getReplayPoint, setReplayPoint, subscribeReplay } from "./replayPoint";
import { runEnded } from "./runSummary";
import { getSelection, subscribeSelection } from "./selection";
import { type Probe, getSpotlight, registerProbe, subscribeSpotlight } from "./spotlight";
import { createWorldStore } from "./store";

const MOVE_DURATION_MS = 600; // a plausible walk; HR-3 caps it at MAX_DURATION_MS regardless
/** How long a handoff note's speech bubble is held, so it can be read before the speaker's next event (WORLD-LIVE). */
const SAY_DURATION_MS = MAX_DURATION_MS;
/** Events whose relocation is a walk; every other relocation is a plain placement (no motion). */
const WALKS: ReadonlySet<string> = new Set([
  "agent.moved",
  "meeting.convened",
  "meeting.adjourned",
]);
/** The longest meeting-room turn drawn in a bubble; the Meeting Hall panel keeps all of it. */
const SAY_MAX = 160;
/** The events whose line is spoken in a bubble over their actor (triggeredBy each: the recorded event itself). */
const SPEAKS: ReadonlySet<string> = new Set([
  "agent.handoff",
  "agent.assigned",
  "agent.help_requested",
  "question.routed",
]);
const LEAD_IN_MS = 1000; // hold at seq 0 after load before the first event (see startPlayback)

type Trace = ReadonlyArray<{ seq: number; type: string }>;

interface WorldOptions {
  readonly world: Container;
  readonly requestRender: () => void;
  readonly size: () => { width: number; height: number };
  readonly layout: Layout;
  /** Read live (not captured once): a prefers-reduced-motion change applies mid-playback. */
  readonly reducedMotion: () => boolean;
  readonly onSeq: (seq: number) => void;
  readonly onTrace: (trace: Trace) => void;
  /** The reducer's run status after each applied event (FR-WLD-07: the veil follows "paused"). */
  readonly onStatus?: (status: Frame["status"]) => void;
  /** True while events the run already held are folded in: nothing is spoken for a past moment (WORLD-LIVE). */
  readonly catchingUp?: () => boolean;
  /** The words of a meeting-room turn (they are not in the event), or null; called when the turn is recorded. */
  readonly words?: (
    roomId: string,
    turn: number,
    kind: "asked" | "replied",
  ) => Promise<string | null>;
}

export interface RunWorldOptions extends WorldOptions {
  readonly events: readonly Event[];
  readonly seqParam: number | null;
  readonly speed: number;
}

export interface ClientWorldOptions extends Omit<WorldOptions, "onTrace"> {
  /** Delivers every event the run has so far, then each new one, in seq order; returns stop. */
  readonly watch: (onEvent: (event: Event) => void) => () => void;
  readonly onTrace?: (trace: Trace) => void;
}

type Vec = { x: number; y: number };

/** The agents drawn lit: the one under the pointer, and the ones a clicked message names (display state). */
function litOf(worldId: string): string[] {
  const { hover, lit } = getSpotlight(worldId);
  return hover === null || lit.includes(hover) ? [...lit] : [...lit, hover];
}

/** What the page may ask the drawn stage (TILO-T-WORLD): which agent is under a point and where an id stands, in px
 * from the stage's corner. Read from the current frame and the Pixi transforms, so it follows the camera. */
function probeOf(
  layer: WorldLayer,
  frame: () => Frame | undefined,
  places: () => ReadonlyMap<string, Vec>,
): Probe {
  return {
    agentAt(x, y) {
      let best: { id: string; d: number } | null = null;
      for (const [id, fig] of layer.figures) {
        if (!fig.g.visible) continue;
        try {
          const b = fig.g.getBounds();
          const pad = 6;
          if (x < b.x - pad || x > b.x + b.width + pad || y < b.y - pad || y > b.y + b.height + pad)
            continue;
          const d = Math.hypot(x - (b.x + b.width / 2), y - (b.y + b.height / 2));
          if (!best || d < best.d) best = { id, d };
        } catch {
          // a figure not yet on the stage has no bounds: it cannot be hovered
        }
      }
      return best?.id ?? null;
    },
    locate(id) {
      try {
        const at = places().get(id);
        if (at) return layer.content.toGlobal(at);
        const f = frame();
        const spot = [...(f?.buildings ?? []), ...(f?.districts ?? []), ...(f?.islands ?? [])].find(
          (r) => r.id === id,
        );
        return spot ? layer.content.toGlobal({ x: spot.cx, y: spot.cy }) : null;
      } catch {
        return null;
      }
    },
  };
}

/** The state at one seq, drawn at once with nothing walking (P8/HR-6, FR-WLD-08): a jump to a
 * recorded moment is a replay, never an event, so there is no motion to time. */
function staticView(layer: WorldLayer, o: WorldOptions, events: readonly Event[]) {
  const store = createWorldStore(o.layout);
  for (const event of events) store.apply(event);
  let frame: Frame | undefined;
  let places = new Map<string, Vec>();
  const ring = () => {
    if (!frame) return;
    renderSelection(
      layer,
      frame,
      places,
      getSelection(o.layout.world_id),
      litOf(o.layout.world_id),
    );
    o.requestRender();
  };
  const offSelection = subscribeSelection(ring);
  const offSpotlight = subscribeSpotlight(ring);
  const offProbe = registerProbe(
    o.layout.world_id,
    probeOf(
      layer,
      () => frame,
      () => places,
    ),
  );
  // A density switch redraws what is shown, in place: no callback, no event, no replay.
  const offDensity = subscribeDensity(() => {
    if (!frame) return;
    renderStatic(layer, frame);
    renderAgents(layer, frame, places);
    ring();
  });
  return {
    show(seq: number) {
      const state = store.stateAt(seq);
      // WORLD-LIVE: at a recorded moment only the agent that spoke in its last event has a bubble (a note is an
      // event's, never a lasting state of the world), so a scrub does not pile every earlier note on the stage.
      const spoke = events.find((e) => e.seq === state.seq)?.actor;
      const whole = frameOf(o.layout, state);
      frame = {
        ...whole,
        agents: whole.agents.map((a) => (a.id === spoke ? a : { ...a, say: null })),
      };
      renderStatic(layer, frame);
      places = new Map(frame.agents.map((a) => [a.id, { x: a.cx, y: a.cy }]));
      renderAgents(layer, frame, places);
      ring();
      o.onSeq(state.seq);
      o.onTrace(state.trace);
      o.onStatus?.(state.status); // FR-WLD-07: the veil follows the recorded status at this point
      return state.seq;
    },
    off() {
      offSelection();
      offSpotlight();
      offProbe();
      offDensity();
    },
  };
}

interface Live {
  /** Folds one event in: the reducer decides what it changes, the choreographer when it moves. */
  apply(event: Event, receivedAtMs: number): void;
  /** Shows the replay point if one is set and the run can be scrubbed (FR-WLD-08). */
  replay(): void;
  stop(): void;
}

function createLive(
  o: WorldOptions,
  source: { events: () => readonly Event[]; canScrub: (state: WorldState) => boolean },
): Live {
  const { world, requestRender, layout, reducedMotion, onSeq, onTrace } = o;
  const onStatus = o.onStatus ?? (() => undefined);
  const layer = createLayer(world, o.size);
  const mobileQuality = createMobileQuality();
  // FR-WLD-06: the ring follows the run's one selection; choosing redraws one frame, nothing more.
  const selected = () => getSelection(layout.world_id);
  const agentIds = layout.semantic.agents.map((a) => a.id);
  let state = createInitialState(layout); // live playback folds events in one at a time
  // Professional density has no decorative motion: a walk is drawn as a jump, as under reduced motion.
  const calm = () => reducedMotion() || layer.density() === "professional";
  const choreo = createChoreographer({ reducedMotion: calm });
  // WORLD-LIVE: a handoff note is held for a readable time by a queue of its own (a bubble is not a walk, so reduced
  // motion does not cut it), one hold per speaker, in seq order, each starting no earlier than its event was received.
  const talk = createChoreographer({ reducedMotion: false });
  // A room's bubbles stay while the room is open (it is a conversation, not a moment); meeting.adjourned ends them.
  const roomSay = new Map<string, FrameSay>();
  const spoken = new Map<
    string,
    Array<{ seq: number; say: NonNullable<FrameAgent["say"]>; armed: boolean }>
  >();
  const agentPos = new Map<string, Vec>(); // settled: where each actor's last completed move left it
  const pendingTo = new Map<string, Vec>(); // by "actor:seq": where a queued move lands once it finishes
  const queued = new Map<string, number>(); // moves enqueued per actor
  const completedCount = new Map<string, number>();
  const walkFrom = new Map<string, { seq: number; from: Vec }>(); // the in-flight move's start
  let lastFrame: Frame = frameOf(layout, state);
  let stopped = false;
  let scrubbed: ReturnType<typeof staticView> | null = null; // FR-WLD-08: set once scrubbed
  // FR-WLD-07: while the recorded status is "paused" the world holds still: nothing is drawn or
  // walked, and events that still arrive are only counted and traced (HR-1, HR-3).
  let paused = false;
  let lastDisplay = new Map<string, Vec>(); // what the agents were last drawn at
  let raf = 0;

  // Draws every agent where the choreographer says it is at `now`: settled actors at their last
  // completed destination, an actor mid-walk lerped from its settled position to the walk's
  // destination over the entry's start..finish. Returns whether any actor still has queued or
  // in-flight moves (so the rAF loop keeps rendering every frame while, and only while, one does).
  function drawAgents(now: number): boolean {
    choreo.advance(now);
    let busy = false;
    for (const id of agentIds) {
      const done = choreo.completed(id);
      if (done.length > (completedCount.get(id) ?? 0)) {
        completedCount.set(id, done.length);
        const to = pendingTo.get(`${id}:${done[done.length - 1]}`);
        if (to) agentPos.set(id, to);
      }
      if (done.length < (queued.get(id) ?? 0)) busy = true;
    }
    const display = new Map(agentPos);
    for (const id of agentIds) {
      const act = choreo.active(id);
      const to = act && pendingTo.get(`${id}:${act.seq}`);
      const settled = agentPos.get(id);
      if (!act || !to || !settled) continue;
      let walk = walkFrom.get(id);
      if (!walk || walk.seq !== act.seq) {
        walk = { seq: act.seq, from: settled };
        walkFrom.set(id, walk);
      }
      const span = act.finish - act.start;
      const t = span > 0 && !calm() ? Math.min(1, Math.max(0, (now - act.start) / span)) : 1;
      display.set(id, {
        x: walk.from.x + (to.x - walk.from.x) * t,
        y: walk.from.y + (to.y - walk.from.y) * t,
      });
    }
    lastDisplay = display;
    // WORLD-LIVE: a note is spoken, and a tool is shown, only once the agent has arrived (its recorded walks are done).
    const arrived = (id: string) => choreo.completed(id).length >= (queued.get(id) ?? 0);
    for (const [id, list] of spoken) {
      for (const hold of list) {
        if (hold.armed || !arrived(id)) continue;
        hold.armed = true;
        talk.enqueue({ actor: id, seq: hold.seq, receivedAtMs: now, durationMs: SAY_DURATION_MS });
      }
    }
    talk.advance(now);
    const speaking = new Map<string, FrameAgent["say"]>();
    for (const [id, list] of spoken) {
      const done = new Set(talk.completed(id));
      const left = list.filter((hold) => !done.has(hold.seq));
      spoken.set(id, left);
      const act = talk.active(id);
      const current = act ? left.find((hold) => hold.seq === act.seq) : undefined;
      if (current) speaking.set(id, current.say);
      if (left.length > 0) busy = true; // a note still waiting for its turn or being read keeps the frames coming
    }
    const shown: Frame = {
      ...lastFrame,
      agents: lastFrame.agents.map((a) => ({
        ...a,
        working: a.working && arrived(a.id),
        say: speaking.get(a.id) ?? (arrived(a.id) ? (roomSay.get(a.id) ?? null) : null),
      })),
    };
    renderAgents(layer, shown, display);
    renderSelection(layer, lastFrame, display, selected(), litOf(layout.world_id));
    requestRender();
    return busy;
  }

  function tickAnim() {
    raf = 0;
    if (stopped || paused || scrubbed) {
      mobileQuality.idle();
      return;
    }
    const now = performance.now();
    mobileQuality.sample(now, o.size().width);
    layer.shadows = mobileQuality.shadows;
    if (drawAgents(now)) raf = requestAnimationFrame(tickAnim);
    else mobileQuality.idle();
  }

  const probe = registerProbe(
    layout.world_id,
    probeOf(
      layer,
      () => lastFrame,
      () => lastDisplay,
    ),
  );
  const spotlit = () => {
    if (stopped || scrubbed) return; // a scrubbed run lights through its own static view
    if (paused) {
      renderSelection(layer, lastFrame, lastDisplay, selected(), litOf(layout.world_id));
      requestRender();
    } else drawAgents(performance.now());
  };
  const unspot = subscribeSpotlight(spotlit);
  const unselect = subscribeSelection(() => {
    if (stopped || scrubbed) return; // a scrubbed run draws through its own static view
    // A ring redraw is a frame, not an animation; paused, the agents stay where they were drawn.
    if (paused) {
      renderSelection(layer, lastFrame, lastDisplay, selected(), litOf(layout.world_id));
      requestRender();
    } else drawAgents(performance.now());
  });
  // FR-WLD-14: a density switch redraws the frame in place (a scrubbed run through its own view).
  const undensity = subscribeDensity(() => {
    if (stopped || scrubbed) return;
    renderStatic(layer, lastFrame);
    if (paused) {
      renderAgents(layer, lastFrame, lastDisplay);
      renderSelection(layer, lastFrame, lastDisplay, selected(), litOf(layout.world_id));
      requestRender();
    } else drawAgents(performance.now());
  });
  // FR-WLD-08: a finished run can be scrubbed; the scrubber is disabled until then, so a live run
  // is never jumped around. From the first scrub the world shows stateAt(point) at once and
  // nothing is left to play or walk (also when it ended paused).
  const replay = () => {
    const point = getReplayPoint(layout.world_id);
    if (stopped || point === null || !source.canScrub(state)) return;
    if (raf) cancelAnimationFrame(raf);
    raf = 0;
    scrubbed ??= staticView(layer, o, source.events());
    scrubbed.show(point);
  };
  const unreplay = subscribeReplay(replay);

  return {
    apply(event, receivedAtMs) {
      if (stopped || event.seq <= state.seq) return; // duplicate or out of order: ignored
      const wasPaused = paused;
      const before = state;
      state = applyEvent(state, event, layout);
      paused = state.status === "paused";
      onStatus(state.status);
      if (paused) {
        onSeq(state.seq);
        onTrace(state.trace);
        return;
      }
      const frame = frameOf(layout, state);
      lastFrame = frame;
      renderStatic(layer, frame);
      if (wasPaused) {
        // Resumed: every agent goes straight to where the record says it is, no walk (HR-3).
        choreo.advance(Number.POSITIVE_INFINITY);
        for (const id of agentIds) completedCount.set(id, choreo.completed(id).length);
        for (const a of frame.agents) agentPos.set(a.id, { x: a.cx, y: a.cy });
      }

      for (const a of frame.agents) {
        if (!agentPos.has(a.id)) {
          agentPos.set(a.id, { x: a.cx, y: a.cy }); // first reveal: appear instantly, no walk
          continue;
        }
        // This event relocates its actor, and, for a meeting room (WORLD-LIVE), every agent it called or sent back.
        // TILO-T-WORLD: where it stands (its post once its handoff is old), not only where its last event sent it.
        const was = before.agents[a.id];
        const stood = was && standingAt(before, was);
        const stands = standingAt(state, state.agents[a.id] as never);
        if (event.actor !== a.id && stood === stands) continue;
        // HR-3: every location change for an already-visible actor goes through that actor's
        // choreographer queue in seq order (chained by finish time), never straight into
        // agentPos, so a later event can never race an earlier walk still in flight.
        pendingTo.set(`${a.id}:${event.seq}`, { x: a.cx, y: a.cy });
        queued.set(a.id, (queued.get(a.id) ?? 0) + 1);
        choreo.enqueue({
          actor: a.id,
          seq: event.seq,
          receivedAtMs,
          // A settle (a finished agent going to its post once the talk window has passed) is a walk too: the event
          // that closed the window is its recorded cause (TILO-T-WORLD).
          durationMs:
            WALKS.has(event.type) || (event.actor !== a.id && stood !== stands)
              ? Math.min(MOVE_DURATION_MS, MAX_DURATION_MS)
              : 0,
        });
      }
      if (event.type === "meeting.adjourned") roomSay.clear(); // the room is over: its bubbles go with it
      const asked = event.type === "meeting.asked";
      if ((asked || event.type === "meeting.replied") && o.words && !o.catchingUp?.()) {
        // The words of a room turn are not in the event (MR-12); they are read from the room when it is recorded.
        const d = (event.data ?? {}) as { room_id?: unknown; turn?: unknown; to?: unknown };
        const who = asked ? d.to : event.actor;
        if (
          typeof d.room_id === "string" &&
          typeof d.turn === "number" &&
          typeof who === "string"
        ) {
          o.words(d.room_id, d.turn, asked ? "asked" : "replied").then(
            (text) => {
              if (!text || stopped || scrubbed) return;
              const cut = text.length > SAY_MAX ? `${text.slice(0, SAY_MAX - 1).trimEnd()}…` : text;
              roomSay.set(who, { text: cut, to: "", head: asked ? "You asked" : "Replied to you" });
              if (!paused) drawAgents(performance.now());
            },
            () => undefined, // no words, no bubble: nothing is made up
          );
        }
      }
      const say =
        SPEAKS.has(event.type) && !o.catchingUp?.()
          ? frame.agents.find((a) => a.id === event.actor)?.say
          : null;
      if (say) {
        const list = spoken.get(event.actor) ?? [];
        spoken.set(event.actor, [...list, { seq: event.seq, say, armed: false }]);
      }
      if (drawAgents(receivedAtMs) && !raf) raf = requestAnimationFrame(tickAnim);
      onSeq(state.seq);
      onTrace(state.trace);
    },
    replay,
    stop() {
      stopped = true;
      unselect();
      unspot();
      probe();
      undensity();
      unreplay();
      scrubbed?.off();
      if (raf) cancelAnimationFrame(raf);
    },
  };
}

export function runWorld(opts: RunWorldOptions): () => void {
  const { events, seqParam, speed, layout } = opts;
  if (seqParam !== null) {
    const view = staticView(createLayer(opts.world, opts.size), opts, events);
    // The point is the stop the state landed on (a seq with no event rounds down), so the
    // scrubber and the stage agree; later scrubs redraw through the same view.
    setReplayPoint(layout.world_id, view.show(seqParam));
    const unreplay = subscribeReplay(() => {
      const point = getReplayPoint(layout.world_id);
      if (point !== null) view.show(point);
    });
    return () => {
      unreplay();
      view.off();
    };
  }

  const lastSeq = events[events.length - 1]?.seq ?? 0;
  const live = createLive(opts, { events: () => events, canScrub: (s) => s.seq >= lastSeq });
  let stopped = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  function scheduleNext(index: number) {
    if (stopped || index >= events.length) return;
    const event = events[index];
    if (!event) return;
    const prevTs = index === 0 ? event.ts : (events[index - 1] as Event).ts;
    const gapMs = index === 0 ? 0 : (Date.parse(event.ts) - Date.parse(prevTs)) / speed;
    timer = setTimeout(
      () => {
        live.apply(event, performance.now());
        scheduleNext(index + 1);
      },
      Math.max(0, gapMs),
    );
  }
  // The page is observable at seq 0 before anything plays: the first event is applied only
  // LEAD_IN_MS (wall time, not divided by `speed`) after the window's load event, so the
  // pre-playback state is a real, visible frame (HR-2) even when ?speed compresses the whole
  // stream into a few milliseconds. Recorded gaps between events are unaffected (HR-6).
  const startPlayback = () => {
    if (!stopped) timer = setTimeout(() => scheduleNext(0), LEAD_IN_MS);
  };
  if (document.readyState === "complete") startPlayback();
  else window.addEventListener("load", startPlayback, { once: true });
  return () => {
    stopped = true;
    window.removeEventListener("load", startPlayback);
    if (timer) clearTimeout(timer);
    live.stop();
  };
}

/** Draws what a client delivers. Events the run already holds when the stage opens (after a trip
 * to another lens, say) are folded in at once, as a jump and not a replay; later ones animate as
 * they arrive. Pause and scrub behave as in a fixture replay: a recorded pause holds the world
 * still, and a finished run opened at a replay point shows that moment. */
export function runClientWorld(opts: ClientWorldOptions): () => void {
  let catchingUp = true;
  const seen: Event[] = [];
  const live = createLive(
    {
      ...opts,
      reducedMotion: () => catchingUp || opts.reducedMotion(),
      catchingUp: () => catchingUp,
      onTrace: opts.onTrace ?? (() => undefined),
    },
    { events: () => seen, canScrub: (s) => runEnded(s.status) },
  );
  const unwatch = opts.watch((event) => {
    seen.push(event);
    live.apply(event, performance.now());
  });
  catchingUp = false;
  live.replay(); // the run was already scrubbed when the stage opened
  return () => {
    unwatch();
    live.stop();
  };
}
