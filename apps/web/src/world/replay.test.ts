// FR-WLD-08 (PRD 9.4 HR-4, 9.6, 9.7): replay and scrub of a finished run. Acceptance: "scrub to any
// point in <= 500 ms for runs <= 5,000 events". The pure side of the scrubber: stops, labels, the
// replay banner and the per-world replay point; plus the timing of stateAt over 5,000 events.
import type { Event, Layout } from "@tilo/contracts";
import { expect, test } from "vitest";
import {
  VILLAGE_BASIC_STREAM_PATH,
  readJsonl,
  villageBasicLayout,
} from "../../test-support/worldFixtures";
import { reduce } from "./reducer";
import {
  eventsUpTo,
  getReplayPoint,
  indexToPoint,
  pointToIndex,
  replayBanner,
  scrubText,
  setReplayPoint,
  subscribeReplay,
} from "./replay";
import { createWorldStore } from "./store";

const layout = villageBasicLayout() as unknown as Layout;
const village = readJsonl(VILLAGE_BASIC_STREAM_PATH) as unknown as Event[];
const AGENTS = ["A_dir", "A_l1", "A_s1", "A_s2", "A_v1"];
const BUILDINGS = ["B1", "B2", "B3", "B4", "B5"];

function synthetic(count: number): Event[] {
  return Array.from({ length: count }, (_, i) => {
    const base = village[0] as Event;
    return {
      ...base,
      id: `01JB5VQ${String(i + 1).padStart(19, "0")}`,
      seq: i + 1,
      ts: new Date(Date.UTC(2026, 8, 29, 9, 30, 0) + i * 1000).toISOString(),
      type: i % 2 === 0 ? "agent.working" : "agent.moved",
      actor: AGENTS[i % AGENTS.length],
      target: BUILDINGS[i % BUILDINGS.length],
    } as Event;
  });
}

test("FR-WLD-08 stops: index 0 is before the first event, index i is after the i-th event", () => {
  expect(indexToPoint(village, 0)).toBe(0);
  expect(indexToPoint(village, 1)).toBe(1);
  expect(indexToPoint(village, village.length)).toBe(44);
  for (let i = 0; i <= village.length; i++) {
    expect(pointToIndex(village, indexToPoint(village, i))).toBe(i);
  }
  expect(pointToIndex(village, null), "no point means the latest stop").toBe(village.length);
  expect(pointToIndex(village, 9_999), "a point past the end clamps").toBe(village.length);
});

test("FR-WLD-08 eventsUpTo: null is the whole run, a point keeps only events at or before it", () => {
  expect(eventsUpTo(village, null)).toBe(village);
  expect(eventsUpTo(village, 0)).toEqual([]);
  expect(eventsUpTo(village, 10).map((e) => e.seq)).toEqual([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]);
});

test("FR-WLD-08 banner (HR-4): 'Replay of run #<run> recorded <date>', fixtures say so too", () => {
  expect(replayBanner(village, false)).toBe(
    "Replay of run #r_village_basic_1 recorded 29 Sep 2026",
  );
  expect(replayBanner(village, true)).toBe(
    "Replay of run #r_village_basic_1 recorded 29 Sep 2026 · dev fixture, not a real run",
  );
  expect(replayBanner([], false)).toBeNull();
});

test("FR-WLD-08 label: names the event, its seq and its recorded time (screen readers get the same)", () => {
  expect(scrubText(village, 0)).toBe("Start of the run, before the first event");
  const text = scrubText(village, 3);
  expect(text).toContain("Event 3 of 44");
  expect(text).toContain("seq 3");
  expect(text).toContain("0:22"); // 09:30:24 against the first event at 09:30:02
  expect(text).toContain((village[2] as Event).type);
});

test("FR-WLD-08 replay point: held per world, null by default, listeners hear a change once", () => {
  let heard = 0;
  const off = subscribeReplay(() => heard++);
  expect(getReplayPoint("w_a")).toBeNull();
  setReplayPoint("w_a", 7);
  setReplayPoint("w_a", 7); // same again: nothing changes
  expect(getReplayPoint("w_a")).toBe(7);
  expect(getReplayPoint("w_b"), "another world's point is its own").toBeNull();
  setReplayPoint("w_a", null);
  expect(getReplayPoint("w_a")).toBeNull();
  off();
  expect(heard).toBe(2);
});

test("FR-WLD-08 perf: scrubbing a 5,000-event run lands on every stop in <= 500 ms", () => {
  const events = synthetic(5_000);
  const store = createWorldStore(layout);
  for (const event of events) store.apply(event);
  let worst = 0;
  for (let i = 0; i <= events.length; i += i < 300 ? 1 : 7) {
    const t0 = performance.now();
    const state = store.stateAt(indexToPoint(events, i));
    worst = Math.max(worst, performance.now() - t0);
    expect(state.seq).toBe(indexToPoint(events, i));
  }
  expect(worst, `slowest scrub took ${worst.toFixed(1)} ms`).toBeLessThanOrEqual(500);
}, 30_000);

test("FR-WLD-08 determinism: the scrubbed state is the from-scratch replay, at any point", () => {
  const events = synthetic(5_000);
  const store = createWorldStore(layout);
  for (const event of events) store.apply(event);
  for (const seq of [0, 1, 249, 250, 251, 2_500, 4_999, 5_000]) {
    expect(store.stateAt(seq), `stateAt(${seq})`).toEqual(reduce(layout, events.slice(0, seq)));
  }
});
