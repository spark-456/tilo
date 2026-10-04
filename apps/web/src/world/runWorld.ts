import type { Event, Layout } from "@tilo/contracts";
// Wires reducer + store + frame + choreographer + renderer into the Pixi world container Stage
// hands over. With `seqParam` set this jumps straight there, no animation (P8/HR-6); otherwise it
// plays `events` in real time, following their recorded `ts` gaps divided by `speed`. An
// `agent.moved` on an actor already on screen is a walk the choreographer times (HR-3) and this
// module lerps every frame; other location changes queue behind it and snap when their turn comes.
import type { Container } from "pixi.js";
import { MAX_DURATION_MS, createChoreographer } from "./choreographer";
import { type Frame, frameOf } from "./frame";
import { applyEvent, createInitialState } from "./reducer";
import { createLayer, renderAgents, renderSelection, renderStatic } from "./renderer";
import { getReplayPoint, setReplayPoint, subscribeReplay } from "./replayPoint";
import { getSelection, subscribeSelection } from "./selection";
import { createWorldStore } from "./store";

const MOVE_DURATION_MS = 600; // a plausible walk; HR-3 caps it at MAX_DURATION_MS regardless
const LEAD_IN_MS = 1000; // hold at seq 0 after load before the first event (see startPlayback)

export interface RunWorldOptions {
  readonly world: Container;
  readonly requestRender: () => void;
  readonly layout: Layout;
  readonly events: readonly Event[];
  readonly seqParam: number | null;
  readonly speed: number;
  /** Read live (not captured once): a prefers-reduced-motion change applies mid-playback. */
  readonly reducedMotion: () => boolean;
  readonly onSeq: (seq: number) => void;
  readonly onTrace: (trace: ReadonlyArray<{ seq: number; type: string }>) => void;
  /** The reducer's run status after each applied event (FR-WLD-07: the veil follows "paused"). */
  readonly onStatus?: (status: Frame["status"]) => void;
}

type Vec = { x: number; y: number };

export function runWorld(opts: RunWorldOptions): () => void {
  const { world, requestRender, layout, events, seqParam, speed, reducedMotion, onSeq, onTrace } =
    opts;
  const onStatus = opts.onStatus ?? (() => undefined);
  const layer = createLayer(world);
  // FR-WLD-06: the ring follows the run's one selection; choosing redraws one frame, nothing more.
  const selected = () => getSelection(layout.world_id);
  const agentIds = layout.semantic.agents.map((a) => a.id);

  // The state at one seq, drawn at once with nothing walking (P8/HR-6, FR-WLD-08): a jump to a
  // recorded moment is a replay, never an event, so there is no motion to time. Built on first use.
  function staticView() {
    const store = createWorldStore(layout);
    for (const event of events) store.apply(event);
    let frame: Frame | undefined;
    let places = new Map<string, Vec>();
    const ring = () => {
      if (!frame) return;
      renderSelection(layer, frame, places, selected());
      requestRender();
    };
    const off = subscribeSelection(ring);
    return {
      show(seq: number) {
        const state = store.stateAt(seq);
        frame = frameOf(layout, state);
        renderStatic(layer, frame);
        places = new Map(frame.agents.map((a) => [a.id, { x: a.cx, y: a.cy }]));
        renderAgents(layer, frame, places);
        ring();
        onSeq(state.seq);
        onTrace(state.trace);
        onStatus(state.status); // FR-WLD-07: the veil follows the recorded status at this point
        return state.seq;
      },
      off,
    };
  }

  if (seqParam !== null) {
    const view = staticView();
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
  let timer: ReturnType<typeof setTimeout> | undefined;
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

  function applyOne(event: Event, receivedAtMs: number) {
    if (event.seq <= state.seq) return; // duplicate or out of order: the reducer ignores it
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
        durationMs: event.type === "agent.moved" ? Math.min(MOVE_DURATION_MS, MAX_DURATION_MS) : 0,
      });
    }
    if (drawAgents(receivedAtMs) && !raf) raf = requestAnimationFrame(tickAnim);
    onSeq(state.seq);
    onTrace(state.trace);
  }

  function scheduleNext(index: number) {
    if (stopped || index >= events.length) return;
    const event = events[index];
    if (!event) return;
    const prevTs = index === 0 ? event.ts : (events[index - 1] as Event).ts;
    const gapMs = index === 0 ? 0 : (Date.parse(event.ts) - Date.parse(prevTs)) / speed;
    timer = setTimeout(
      () => {
        applyOne(event, performance.now());
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

  const unselect = subscribeSelection(() => {
    if (stopped || scrubbed) return; // a scrubbed run draws through its own static view
    // A ring redraw is a frame, not an animation; paused, the agents stay where they were drawn.
    if (paused) {
      renderSelection(layer, lastFrame, lastDisplay, selected());
      requestRender();
    } else drawAgents(performance.now());
  });
  // FR-WLD-08: a finished run (every event applied) can be scrubbed; the scrubber is disabled
  // until then, so a live run is never jumped around. From the first scrub the world shows
  // stateAt(point) at once and nothing is left to play or walk (also when it ended paused).
  const lastSeq = events[events.length - 1]?.seq ?? 0;
  const unreplay = subscribeReplay(() => {
    const point = getReplayPoint(layout.world_id);
    if (stopped || point === null || state.seq < lastSeq) return;
    if (timer) clearTimeout(timer);
    if (raf) cancelAnimationFrame(raf);
    raf = 0;
    scrubbed ??= staticView();
    scrubbed.show(point);
  });
  return () => {
    stopped = true;
    unselect();
    unreplay();
    scrubbed?.off();
    window.removeEventListener("load", startPlayback);
    if (timer) clearTimeout(timer);
    if (raf) cancelAnimationFrame(raf);
  };
}
