// Wires reducer + store + frame + choreographer + renderer into the Pixi world container Stage
// hands over. With `seqParam` set this jumps straight there, no animation (P8/HR-6); otherwise it
// plays events in real time. `runWorld` plays a loaded fixture, following the recorded `ts` gaps
// divided by `speed`; `runClientWorld` draws what a TiloClient delivers, as it arrives. Either way
// an `agent.moved` on an actor already on screen is a walk the choreographer times (HR-3) and this
// module lerps every frame; other location changes queue behind it and snap when their turn comes.
import type { Event, Layout } from "@tilo/contracts";
import type { Container } from "pixi.js";
import { MAX_DURATION_MS, createChoreographer } from "./choreographer";
import { type Frame, frameOf } from "./frame";
import { type WorldState, applyEvent, createInitialState } from "./reducer";
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
import { createWorldStore } from "./store";

const MOVE_DURATION_MS = 600; // a plausible walk; HR-3 caps it at MAX_DURATION_MS regardless
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

/** The state at one seq, drawn at once with nothing walking (P8/HR-6, FR-WLD-08): a jump to a
 * recorded moment is a replay, never an event, so there is no motion to time. */
function staticView(layer: WorldLayer, o: WorldOptions, events: readonly Event[]) {
  const store = createWorldStore(o.layout);
  for (const event of events) store.apply(event);
  let frame: Frame | undefined;
  let places = new Map<string, Vec>();
  const ring = () => {
    if (!frame) return;
    renderSelection(layer, frame, places, getSelection(o.layout.world_id));
    o.requestRender();
  };
  const off = subscribeSelection(ring);
  return {
    show(seq: number) {
      const state = store.stateAt(seq);
      frame = frameOf(o.layout, state);
      renderStatic(layer, frame);
      places = new Map(frame.agents.map((a) => [a.id, { x: a.cx, y: a.cy }]));
      renderAgents(layer, frame, places);
      ring();
      o.onSeq(state.seq);
      o.onTrace(state.trace);
      o.onStatus?.(state.status); // FR-WLD-07: the veil follows the recorded status at this point
      return state.seq;
    },
    off,
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
  // FR-WLD-06: the ring follows the run's one selection; choosing redraws one frame, nothing more.
  const selected = () => getSelection(layout.world_id);
  const agentIds = layout.semantic.agents.map((a) => a.id);
  let state = createInitialState(layout); // live playback folds events in one at a time
  const choreo = createChoreographer({ reducedMotion });
  const agentPos = new Map<string, Vec>(); // settled: where each actor's last completed move left it
  const pendingTo = new Map<number, Vec>(); // by seq: where a queued move lands once it finishes
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
        const to = pendingTo.get(done[done.length - 1] as number);
        if (to) agentPos.set(id, to);
      }
      if (done.length < (queued.get(id) ?? 0)) busy = true;
    }
    const display = new Map(agentPos);
    for (const id of agentIds) {
      const act = choreo.active(id);
      const to = act && pendingTo.get(act.seq);
      const settled = agentPos.get(id);
      if (!act || !to || !settled) continue;
      let walk = walkFrom.get(id);
      if (!walk || walk.seq !== act.seq) {
        walk = { seq: act.seq, from: settled };
        walkFrom.set(id, walk);
      }
      const span = act.finish - act.start;
      const t =
        span > 0 && !reducedMotion() ? Math.min(1, Math.max(0, (now - act.start) / span)) : 1;
      display.set(id, {
        x: walk.from.x + (to.x - walk.from.x) * t,
        y: walk.from.y + (to.y - walk.from.y) * t,
      });
    }
    lastDisplay = display;
    renderAgents(layer, lastFrame, display);
    renderSelection(layer, lastFrame, display, selected());
    requestRender();
    return busy;
  }

  function tickAnim() {
    raf = 0;
    if (stopped || paused || scrubbed) return;
    if (drawAgents(performance.now())) raf = requestAnimationFrame(tickAnim);
  }

  const unselect = subscribeSelection(() => {
    if (stopped || scrubbed) return; // a scrubbed run draws through its own static view
    // A ring redraw is a frame, not an animation; paused, the agents stay where they were drawn.
    if (paused) {
      renderSelection(layer, lastFrame, lastDisplay, selected());
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
        if (event.actor !== a.id) continue; // this event doesn't relocate this actor
        // HR-3: every location change for an already-visible actor goes through that actor's
        // choreographer queue in seq order (chained by finish time), never straight into
        // agentPos, so a later event can never race an earlier walk still in flight.
        pendingTo.set(event.seq, { x: a.cx, y: a.cy });
        queued.set(a.id, (queued.get(a.id) ?? 0) + 1);
        choreo.enqueue({
          actor: a.id,
          seq: event.seq,
          receivedAtMs,
          durationMs:
            event.type === "agent.moved" ? Math.min(MOVE_DURATION_MS, MAX_DURATION_MS) : 0,
        });
      }
      if (drawAgents(receivedAtMs) && !raf) raf = requestAnimationFrame(tickAnim);
      onSeq(state.seq);
      onTrace(state.trace);
    },
    replay,
    stop() {
      stopped = true;
      unselect();
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
