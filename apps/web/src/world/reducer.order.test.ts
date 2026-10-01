// P0-08b-player / FR-WLD-04: a duplicate or out-of-order event (seq <= the highest applied) is
// ignored, so seq never goes down and the Trace list holds at most one row per seq.
import type { Event, Layout } from "@tilo/contracts";
import { expect, test } from "vitest";
import { villageBasicEvents, villageBasicLayout } from "../../test-support/worldFixtures";
import { reduce } from "./reducer";
import { createWorldStore } from "./store";

const layout = villageBasicLayout() as unknown as Layout;
const events = villageBasicEvents() as unknown as Event[];

function seqs(trace: ReadonlyArray<{ seq: number }>): number[] {
  return trace.map((r) => r.seq);
}

test("FR-WLD-04 reducer: a duplicated event is ignored, one Trace row per seq", () => {
  const dup = [...events.slice(0, 6), events[5] as Event, ...events.slice(6)];
  const state = reduce(layout, dup);
  expect(state).toEqual(reduce(layout, events));
  expect(new Set(seqs(state.trace)).size).toBe(state.trace.length);
});

test("FR-WLD-04 reducer: a swapped pair never lowers seq; the late event is ignored", () => {
  const swapped = [...events];
  [swapped[10], swapped[11]] = [swapped[11] as Event, swapped[10] as Event];
  let highest = 0;
  for (let n = 1; n <= swapped.length; n++) {
    const state = reduce(layout, swapped.slice(0, n));
    expect(state.seq).toBeGreaterThanOrEqual(highest);
    highest = state.seq;
  }
  const trace = seqs(reduce(layout, swapped).trace);
  expect(trace).not.toContain((events[10] as Event).seq);
  expect([...trace].sort((a, b) => a - b)).toEqual(trace);
});

test("FR-WLD-04 store: duplicates and a swapped pair keep currentSeq monotonic and stateAt consistent", () => {
  const store = createWorldStore(layout);
  const stream = [
    ...events.slice(0, 6),
    events[5] as Event,
    events[11] as Event,
    events[10] as Event,
  ];
  let highest = 0;
  for (const event of stream) {
    store.apply(event);
    expect(store.currentSeq()).toBeGreaterThanOrEqual(highest);
    highest = store.currentSeq();
  }
  expect(store.stateAt(highest)).toEqual(reduce(layout, stream));
});
