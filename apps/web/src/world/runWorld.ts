import type { Event, Layout } from "@tilo/contracts";
// Wires reducer + store + frame + choreographer + renderer into the Pixi world container Stage
// hands over. With `seqParam` set this jumps straight there, no animation (P8/HR-6); otherwise it
// plays `events` in real time, following their recorded `ts` gaps divided by `speed`. Only
// `agent.moved` on an actor already on screen is choreographed (an actual walk, HR-3); every
// other location-bearing event snaps straight to the resolved position.
import type { Container } from "pixi.js";
import { MAX_DURATION_MS, createChoreographer } from "./choreographer";
import { type Frame, frameOf } from "./frame";
import { createLayer, renderAgents, renderStatic } from "./renderer";
import { createWorldStore } from "./store";

const MOVE_DURATION_MS = 600; // a plausible walk; HR-3 caps it at MAX_DURATION_MS regardless

export interface RunWorldOptions {
  readonly world: Container;
  readonly requestRender: () => void;
  readonly layout: Layout;
  readonly events: readonly Event[];
  readonly seqParam: number | null;
  readonly speed: number;
  readonly reducedMotion: boolean;
  readonly onSeq: (seq: number) => void;
  readonly onTrace: (trace: ReadonlyArray<{ seq: number; type: string }>) => void;
}

type Vec = { x: number; y: number };

export function runWorld(opts: RunWorldOptions): () => void {
  const { world, requestRender, layout, events, seqParam, speed, reducedMotion, onSeq, onTrace } =
    opts;
  const layer = createLayer(world);
  const agentIds = layout.semantic.agents.map((a) => a.id);

  if (seqParam !== null) {
    const store = createWorldStore(layout);
    for (const event of events) store.apply(event);
    const state = store.stateAt(seqParam);
    const frame = frameOf(layout, state);
    renderStatic(layer, frame);
    renderAgents(layer, frame, new Map(frame.agents.map((a) => [a.id, { x: a.cx, y: a.cy }])));
    onSeq(state.seq);
    onTrace(state.trace);
    requestRender();
    return () => {};
  }

  const store = createWorldStore(layout);
  const choreo = createChoreographer({ reducedMotion });
  const agentPos = new Map<string, Vec>();
  const pendingTo = new Map<number, Vec>(); // by seq: where a queued move lands once it finishes
  const completedCount = new Map<string, number>();
  let lastFrame: Frame = frameOf(layout, store.stateAt(0));
  let stopped = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let raf = 0;

  const ensureAnimating = () => {
    if (!raf) raf = requestAnimationFrame(tickAnim);
  };

  function tickAnim() {
    raf = 0;
    choreo.advance(performance.now());
    let anyActive = false;
    let changed = false;
    for (const id of agentIds) {
      if (choreo.isAnimating(id)) anyActive = true;
      const done = choreo.completed(id);
      const prevDone = completedCount.get(id) ?? 0;
      if (done.length > prevDone) {
        completedCount.set(id, done.length);
        const to = pendingTo.get(done[done.length - 1] as number);
        if (to) {
          agentPos.set(id, to);
          changed = true;
        }
      }
    }
    if (changed) {
      renderAgents(layer, lastFrame, agentPos);
      requestRender();
    }
    if (anyActive && !stopped) raf = requestAnimationFrame(tickAnim);
  }

  function applyOne(event: Event, receivedAtMs: number) {
    store.apply(event);
    const state = store.stateAt(event.seq);
    const frame = frameOf(layout, state);
    lastFrame = frame;
    renderStatic(layer, frame);

    for (const a of frame.agents) {
      const already = agentPos.has(a.id);
      if (!already) {
        agentPos.set(a.id, { x: a.cx, y: a.cy }); // first reveal: appear instantly, no walk
        continue;
      }
      if (event.actor !== a.id) continue; // this event doesn't relocate this actor
      // HR-3: every location change for an already-visible actor — a walk (`agent.moved`) or
      // any other event that resolves to a new position — goes through that actor's
      // choreographer queue in seq order, never straight into agentPos. The choreographer
      // chains each actor's entries by finish time, so an event applied here while an earlier
      // move for the same actor is still in flight lands *after* it completes instead of racing
      // it: tickAnim only ever advances agentPos to the *latest* completed entry's pendingTo, in
      // seq order, so the settled canvas can never regress to a stale, already-superseded spot.
      pendingTo.set(event.seq, { x: a.cx, y: a.cy });
      choreo.enqueue({
        actor: a.id,
        seq: event.seq,
        receivedAtMs,
        durationMs: event.type === "agent.moved" ? Math.min(MOVE_DURATION_MS, MAX_DURATION_MS) : 0,
      });
      ensureAnimating();
    }
    renderAgents(layer, frame, agentPos);
    onSeq(state.seq);
    onTrace(state.trace);
    requestRender();
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
  scheduleNext(0);

  return () => {
    stopped = true;
    if (timer) clearTimeout(timer);
    if (raf) cancelAnimationFrame(raf);
  };
}
