/**
 * P0-08b-player: FR-WLD-04 / HR-5 unit tests for apps/web/src/world/reducer.ts.
 *
 * Interface under test (module does not exist yet — every import below fails on
 * "Cannot find module" until the builder adds it):
 *
 *   export interface WorldState {
 *     readonly seq: number;                                   // highest seq applied
 *     readonly trace: ReadonlyArray<{ seq: number; type: string }>; // one row per applied event,
 *                                                               // known or unknown (HR-5)
 *     // any other field is implementation-defined and opaque to these tests; frame.ts (not
 *     // this file) is the only thing allowed to turn WorldState into what the renderer draws.
 *   }
 *   export function createInitialState(layout: Layout): WorldState;
 *   export function applyEvent(state: WorldState, event: Event, layout: Layout): WorldState;
 *   export function reduce(layout: Layout, events: readonly Event[]): WorldState;
 *
 * `reduce` and `applyEvent` are pure: no clock, no randomness, no I/O (PRD 9.6 "the reducer is
 * deterministic"; FR-WLD-04). `reduce(layout, events)` is equivalent to folding `applyEvent`
 * over `events` from `createInitialState(layout)`.
 */
import type { Event, Layout } from "@tilo/contracts";
import { expect, test } from "vitest";
import { villageBasicEvents, villageBasicLayout } from "../../test-support/worldFixtures";
import { applyEvent, createInitialState, reduce } from "./reducer";

const layout = villageBasicLayout() as unknown as Layout;
const events = villageBasicEvents() as unknown as Event[];

function foldFromScratch(): unknown {
  let state = createInitialState(layout);
  for (const event of events) state = applyEvent(state, event, layout);
  return state;
}

test("FR-WLD-04 reducer: reduce(layout, events) called twice gives a deep-equal state (two separate instances)", () => {
  const a = reduce(layout, events);
  const b = reduce(layout, events);
  expect(a).toEqual(b);
});

test("FR-WLD-04 reducer: reduce(layout, events) equals folding applyEvent from createInitialState (from scratch)", () => {
  expect(reduce(layout, events)).toEqual(foldFromScratch());
});

test("FR-WLD-04 reducer: final state.seq is the last applied event's seq; the empty stream is seq 0", () => {
  const finalState = reduce(layout, events) as { seq: number };
  const lastEvent = events[events.length - 1] as unknown as { seq: number };
  expect(finalState.seq).toBe(lastEvent.seq);
  expect((createInitialState(layout) as { seq: number }).seq).toBe(0);
});

test("FR-WLD-04 reducer purity: applyEvent does not mutate the state object it is given", () => {
  const before = createInitialState(layout);
  Object.freeze(before);
  expect(() => applyEvent(before, events[0] as Event, layout)).not.toThrow();
});

test("FR-WLD-04 reducer purity: reduce never reads the clock or Math.random (no I/O, no randomness)", () => {
  const originalNow = Date.now;
  const originalRandom = Math.random;
  const originalPerfNow = performance.now;
  Date.now = () => {
    throw new Error("reduce must not call Date.now()");
  };
  Math.random = () => {
    throw new Error("reduce must not call Math.random()");
  };
  performance.now = () => {
    throw new Error("reduce must not call performance.now()");
  };
  try {
    expect(() => reduce(layout, events)).not.toThrow();
  } finally {
    Date.now = originalNow;
    Math.random = originalRandom;
    performance.now = originalPerfNow;
  }
});

// HR-5: an unregistered event type is applied (it lands in the Trace lens, per registry.test.ts
// and the e2e apps/web/e2e/world-trace-unknown.spec.ts) but must leave every other part of
// WorldState exactly as it was before that one event.
const UNKNOWN_EVENT = {
  v: "1.0",
  id: "01JB5VQ0000000000000000045",
  seq: 45,
  ts: "2026-09-29T09:32:25.500Z",
  world_id: "w_village_basic",
  run_id: "r_village_basic_1",
  type: "alert.batched",
  actor: "system",
  target: "w_village_basic",
  level: null,
  district: null,
  item: null,
  severity: "fyi",
  credits: 0,
  summary: "3 low-priority alerts were batched.",
  cause: null,
  vis: "all",
  authz: null,
  data: { count: 3 },
  trace: {
    model_role: null,
    profile: null,
    tokens_in: null,
    tokens_out: null,
    tool: null,
    latency_ms: null,
    archive_ref: null,
  },
} as unknown as Event;

function omitSeqAndTrace(state: unknown): unknown {
  const {
    seq: _seq,
    trace: _trace,
    ...rest
  } = state as { seq: unknown; trace: unknown } & Record<string, unknown>;
  return rest;
}

test("HR-5 reducer: an unknown event type (BQ-07 alert.batched) changes only seq and trace, nothing else", () => {
  const before = reduce(layout, events);
  const after = applyEvent(before, UNKNOWN_EVENT, layout);

  expect(omitSeqAndTrace(after)).toEqual(omitSeqAndTrace(before));
  expect((after as { seq: number }).seq).toBe(45);
  expect((after as { trace: Array<{ seq: number; type: string }> }).trace.at(-1)).toEqual({
    seq: 45,
    type: "alert.batched",
  });
});
