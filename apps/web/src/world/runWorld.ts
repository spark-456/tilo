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
import { applyEvent, createInitialState } from "./reducer";
import { createLayer, renderAgents, renderSelection, renderStatic } from "./renderer";
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
}

export interface RunWorldOptions extends WorldOptions {
  readonly events: readonly Event[];
  readonly seqParam: number | null;
  readonly speed: number;
}

export interface ClientWorldOptions extends Omit<WorldOptions, "onTrace"> {
  readonly seqParam: number | null;
  /** Delivers every event the run has so far, then each new one, in seq order; returns stop. */
  readonly watch: (onEvent: (event: Event) => void) => () => void;
  readonly onTrace?: (trace: Trace) => void;
}

type Vec = { x: number; y: number };
interface Live {
  /** Folds one event in: the reducer decides what it changes, the choreographer when it moves. */
  apply(event: Event, receivedAtMs: number): void;
  stop(): void;
}

/** FR-WLD-06: the ring follows the run's one selection; choosing redraws one frame, nothing more. */
function createLive(opts: WorldOptions): Live {
  const { world, requestRender, layout, reducedMotion, onSeq, onTrace } = opts;
  const layer = createLayer(world, opts.size);
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
    renderAgents(layer, lastFrame, display);
    renderSelection(layer, lastFrame, display, selected());
    requestRender();
    return busy;
  }

  function tickAnim() {
    raf = 0;
    if (stopped) return;
    if (drawAgents(performance.now())) raf = requestAnimationFrame(tickAnim);
  }

  // Nothing is drawn until the first event lands (HR-2): the stage stays as it was while the
  // layout and the run load, then the first event draws the plan and what that event says.
  const unselect = subscribeSelection(() => {
    if (!stopped) drawAgents(performance.now()); // a ring redraw: a frame, not an animation
  });
  return {
    apply(event, receivedAtMs) {
      if (stopped || event.seq <= state.seq) return; // duplicate or out of order: ignored
      state = applyEvent(state, event, layout);
      const frame = frameOf(layout, state);
      lastFrame = frame;
      renderStatic(layer, frame);

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
    stop() {
      stopped = true;
      unselect();
      if (raf) cancelAnimationFrame(raf);
    },
  };
}

/** The world at one seq, drawn once, with no animation (?seq=N). */
function showAt(opts: WorldOptions, events: readonly Event[], seq: number): () => void {
  const { world, requestRender, layout, onSeq, onTrace } = opts;
  const layer = createLayer(world, opts.size);
  const store = createWorldStore(layout);
  for (const event of events) store.apply(event);
  const state = store.stateAt(seq);
  const frame = frameOf(layout, state);
  renderStatic(layer, frame);
  const places = new Map(frame.agents.map((a) => [a.id, { x: a.cx, y: a.cy }]));
  renderAgents(layer, frame, places);
  const ring = () => {
    renderSelection(layer, frame, places, getSelection(layout.world_id));
    requestRender();
  };
  ring();
  onSeq(state.seq);
  onTrace(state.trace);
  return subscribeSelection(ring);
}

export function runWorld(opts: RunWorldOptions): () => void {
  const { events, seqParam, speed } = opts;
  if (seqParam !== null) return showAt(opts, events, seqParam);

  const live = createLive(opts);
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
 * they arrive. With `seqParam` the picture is the run as it stood at that seq, and stays there. */
export function runClientWorld(opts: ClientWorldOptions): () => void {
  const { seqParam, watch } = opts;
  let catchingUp = true;
  const live = createLive({
    ...opts,
    reducedMotion: () => catchingUp || seqParam !== null || opts.reducedMotion(),
    onTrace: opts.onTrace ?? (() => undefined),
  });
  const unwatch = watch((event) => {
    if (seqParam === null || event.seq <= seqParam) live.apply(event, performance.now());
  });
  catchingUp = false;
  return () => {
    unwatch();
    live.stop();
  };
}
